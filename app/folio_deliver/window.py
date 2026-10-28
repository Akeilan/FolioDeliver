"""The presentation window: title bar with Quick Access and search, the ribbon, the slide
pane, the slide, the notes pane and the status bar, and every command they run."""
import datetime
import os
import subprocess
import tempfile

from gi.repository import Gdk, GLib, Gtk, Pango

from . import APP_NAME, VERSION, icons
from .backstage import Backstage
from .canvas import SlideCanvas
from .core import Presentation, surface_from
from .dialogs import Dialogs
from .more_ui import AnimationCommands, MoreCommands
from .master_ui import MasterCommands
from .review_ui import PictureCommands, ReviewCommands
from .show_ui import ShowCommands
from .chart_ui import ChartCommands
from .smartart_ui import SmartArtCommands
from .media_ui import MediaCommands
from .ink_ui import InkCommands
from .eq_ui import EquationCommands
from .ribbon import Ribbon
from .slidepane import SlidePane, Thumbs
from .statusbar import StatusBar

NATIVE = (".pptx", ".pptm", ".ppsx", ".ppsm", ".potx", ".potm")
IMPORT = (".ppt", ".pps", ".pot", ".odp", ".otp", ".fodp", ".key")
CT_MAIN = {
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml",
    "ppsx": "application/vnd.openxmlformats-officedocument.presentationml.slideshow.main+xml",
    "potx": "application/vnd.openxmlformats-officedocument.presentationml.template.main+xml",
}
# slide commands a master view doesn't offer (PowerPoint greys them out)
MASTER_BLOCKED = {"new-slide", "new-slide-layout", "duplicate-slides", "delete-slides", "hide-slide", "slide-up", "slide-down",
                  "reuse-slides", "slides-from-outline", "show-start", "show-current", "view-sorter", "view-reading",
                  "view-outline", "view-notes-page", "set-layout", "reset-slide", "add-section", "new-comment",
                  "transition", "anim", "anim-add", "setup-show", "toggle-presenter-view", "rehearse-timings"}
SIZES = [8, 9, 10, 10.5, 11, 12, 14, 16, 18, 20, 24, 28, 32, 36, 40, 44, 48, 54, 60, 66, 72, 80, 88, 96]


class DeliverWindow(EquationCommands, InkCommands, MediaCommands, SmartArtCommands, ChartCommands, ShowCommands, MasterCommands, PictureCommands, ReviewCommands, AnimationCommands, MoreCommands, Gtk.ApplicationWindow):
    def __init__(self, app, path=None, twin=None):
        Gtk.ApplicationWindow.__init__(self, application=app)
        self.app = app
        self.path = None
        self.untitled = None
        self.imported_from = None
        self.deck = None
        self.current = 0
        self.view = "normal"
        self._alt_alone = False
        self.clip = None
        self.painter_props = None
        self.last_colors = {"font-color": "C00000", "highlight": "FFFF00", "shape-fill": "scheme:accent1",
                            "shape-outline": "scheme:accent1"}
        self.missing_log = []
        geo = app.settings.get("window", {})
        self.set_default_size(geo.get("w", 1280), geo.get("h", 820))
        if geo.get("max", True):
            self.maximize()
        self.set_icon_name("folio-deliver")
        self.dialogs = Dialogs(self)
        self.thumbs = Thumbs(self)

        # ---- title bar
        self.header = Gtk.HeaderBar()
        self.header.set_show_close_button(True)
        self.header.get_style_context().add_class("folio-titlebar")
        self.title_label = Gtk.Label(label=APP_NAME)
        self.title_label.get_style_context().add_class("title")
        self.header.set_custom_title(self.title_label)
        self.qat = Gtk.Box(spacing=0)
        self.build_qat()
        self.header.pack_start(self.qat)
        self.search = Gtk.SearchEntry()
        self.search.set_placeholder_text("Search (Alt+Q)")
        self.search.get_style_context().add_class("folio-search")
        self.search.set_width_chars(28)
        self.search.connect("activate", self.on_search)
        self.header.pack_end(self.search)
        self.set_titlebar(self.header)

        # ---- layout
        self.overlay = Gtk.Overlay()
        self.add(self.overlay)
        self.outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.overlay.add(self.outer)
        self.ribbon = Ribbon(self.run, self.focus_document)
        self.ribbon.connect("file-clicked", lambda *_: self.show_backstage())
        self.anim_pick = None
        self.outer.pack_start(self.ribbon, False, False, 0)
        self.stack = Gtk.Stack()
        self.stack.set_transition_type(Gtk.StackTransitionType.NONE)
        # Normal view
        self.pane = SlidePane(self)
        self.canvas = SlideCanvas(self)
        self.notes = Gtk.TextView()
        self.notes.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self.notes.set_left_margin(12)
        self.notes.set_top_margin(6)
        self.notes.get_style_context().add_class("folio-notes")
        self.notes.get_buffer().connect("changed", self._notes_changed)
        self.notes.connect("focus-out-event", lambda *_: (self._save_notes(), False)[1])
        self._notes_quiet = False
        self._notes_timer = None
        self.notes_hint = Gtk.Label(label="Click to add notes", xalign=0)
        self.notes_hint.get_style_context().add_class("folio-notes-hint")
        self.notes_hint.set_margin_start(14)
        self.notes_hint.set_margin_top(6)
        self.notes_hint.set_valign(Gtk.Align.START)
        self.notes_hint.set_halign(Gtk.Align.START)
        nov = Gtk.Overlay()
        nsw = Gtk.ScrolledWindow()
        nsw.add(self.notes)
        nov.add(nsw)
        nov.add_overlay(self.notes_hint)
        nov.set_overlay_pass_through(self.notes_hint, True)
        self.notes_box = nov
        right = Gtk.Paned(orientation=Gtk.Orientation.VERTICAL)
        right.pack1(self.canvas, True, False)
        right.pack2(nov, False, True)
        self.vpaned = right
        normal = Gtk.Paned()
        self.normal_paned = normal
        normal.pack1(self.pane, False, False)
        normal.pack2(right, True, False)
        self.stack.add_named(normal, "normal")
        # Slide Sorter
        self.sorter = SlidePane(self, sorter=True)
        self.stack.add_named(self.sorter, "sorter")
        # Reading View
        self.reading = Gtk.DrawingArea()
        self.reading.set_can_focus(True)
        self.reading.add_events(Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.KEY_PRESS_MASK)
        self.reading.connect("draw", self._draw_reading)
        self.reading.connect("button-press-event", lambda *_: (self.go_slide(self.current + 1), True)[1])
        self.stack.add_named(self.reading, "reading")
        self.build_outline_view()
        self.build_notes_page()
        self.outer.pack_start(self.stack, True, True, 0)
        self.status = StatusBar(self)
        self.outer.pack_start(self.status, False, False, 0)

        from .ribbon_defs import build_ribbon
        build_ribbon(self)
        _select = self.ribbon.select

        def select_tab(tab):
            _select(tab)
            self.canvas.queue()
        self.ribbon.select = select_tab
        self.backstage = Backstage(self)
        self.overlay.add_overlay(self.backstage)
        from .keytips import KeyTips
        self.keytips = KeyTips(self)
        self.connect("key-press-event", self.on_key)
        self.connect("key-release-event", self.on_key_release)
        self.connect("delete-event", self.on_delete)
        self.connect("configure-event", self._remember_geometry)
        self.show_all()
        self.backstage.hide()
        if twin is not None:
            # New Window: a second window on the same presentation
            self.deck = twin.deck
            self.path, self.untitled, self.imported_from = twin.path, twin.untitled, twin.imported_from
            self._after_load()
            self.go_slide(twin.current or 0)
        elif path:
            self.load(path)
        else:
            self.new_deck()
        GLib.idle_add(lambda: (self.vpaned.set_position(max(200, self.vpaned.get_allocated_height() - 90)), False)[1])
        GLib.idle_add(self.focus_document)

    # ------------------------------------------------------------ QAT
    QAT_ALL = [("new", "qat-new", "New (Ctrl+N)", "New"), ("open", "r-browse", "Open (Ctrl+O)", "Open"),
               ("save", "qat-save", "Save (Ctrl+S)", "Save"), ("undo", "r-undo-sm", "Undo (Ctrl+Z)", "Undo"),
               ("redo", "r-redo-sm", "Redo (Ctrl+Y)", "Redo"), ("print", "qat-print", "Print (Ctrl+P)", "Print"),
               ("show-start", "presentation", "Start From Beginning (F5)", "Start From Beginning")]
    QAT_DEFAULT = ["save", "undo", "redo", "show-start"]

    @property
    def QAT(self):
        on = self.app.settings.get("qat", self.QAT_DEFAULT)
        return [(k, i, t) for k, i, t, _n in self.QAT_ALL if k in on]

    def build_qat(self):
        for c in self.qat.get_children():
            self.qat.remove(c)
        for key, icon, tip in self.QAT:
            b = Gtk.Button()
            b.add(icons.dark_image(icon, 16))
            b.set_tooltip_text(tip)
            b.set_focus_on_click(False)
            b.connect("clicked", lambda _b, k=key: self.run(k))
            self.qat.pack_start(b, False, False, 0)
        mb = Gtk.MenuButton()
        mb.set_relief(Gtk.ReliefStyle.NONE)
        mb.set_focus_on_click(False)
        mb.set_tooltip_text("Customize Quick Access Toolbar")
        mb.add(Gtk.Label(label="▾"))
        menu = Gtk.Menu()
        head = Gtk.MenuItem(label="Customize Quick Access Toolbar")
        head.set_sensitive(False)
        menu.append(head)
        on = self.app.settings.get("qat", self.QAT_DEFAULT)
        for k, _i, _t, name in self.QAT_ALL:
            mi = Gtk.CheckMenuItem(label=name)
            mi.set_active(k in on)
            mi.connect("toggled", lambda m, k=k: GLib.idle_add(lambda: (self.set_qat(k, m.get_active()), False)[1]))
            menu.append(mi)
        menu.show_all()
        mb.set_popup(menu)
        self.qat_menu_button = mb
        self.qat.pack_start(mb, False, False, 0)
        self.qat.show_all()

    def set_qat(self, key, on):
        cur = [k for k in self.app.settings.get("qat", self.QAT_DEFAULT) if k != key]
        if on:
            cur.append(key)
        self.app.settings["qat"] = [k for k, *_ in self.QAT_ALL if k in cur]
        try:
            self.app.save_settings()
        except OSError:
            pass
        for w in self.app.windows:
            w.build_qat()

    # ------------------------------------------------------------ documents
    def new_deck(self):
        tpl = self.app.blank_template()
        if tpl is None:
            raise RuntimeError("the blank presentation template is missing")
        self.deck = Presentation.open(tpl)
        self.deck.modified = False
        self.path = None
        self.untitled = self.app.next_untitled()
        self._after_load()

    def load(self, path):
        ext = os.path.splitext(path)[1].lower()
        try:
            if ext in IMPORT:
                deck = self._import_legacy(path)
                self.imported_from = os.path.abspath(path)
                self.path = None
                self.untitled = os.path.splitext(os.path.basename(path))[0]
            else:
                deck = Presentation.open(path)
                self.imported_from = None
                if ext in (".potx", ".potm"):
                    # a template opens as a new presentation made from it
                    self.path = None
                    self.untitled = self.app.next_untitled()
                else:
                    self.path = os.path.abspath(path)
        except Exception as e:
            self.dialogs.message("%s can't open '%s'.\n\n%s" % (APP_NAME, os.path.basename(path), e))
            if self.deck is None:
                self.new_deck()
            return
        self.deck = deck
        self.deck.modified = False
        self.app.add_recent(path)
        self._after_load()
        if ext in (".ppsx", ".ppsm", ".pps"):
            # a show file starts the show
            GLib.idle_add(lambda: (self.run("show-start"), False)[1])

    def _import_legacy(self, path):
        """Old formats go through LibreOffice as a converter only."""
        out = tempfile.mkdtemp(prefix="folio-deliver-")
        cmd = ["soffice", "--headless", "--norestore", "--convert-to", "pptx:Impress MS PowerPoint 2007 XML",
               "--outdir", out, path]
        try:
            subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=180)
        except (OSError, subprocess.TimeoutExpired):
            raise RuntimeError("Opening this older format needs the LibreOffice converter (package libreoffice-impress), "
                               "which isn't installed.")
        conv = os.path.join(out, os.path.splitext(os.path.basename(path))[0] + ".pptx")
        if not os.path.exists(conv):
            raise RuntimeError("the converter could not read this file")
        return Presentation.open(conv)

    def _after_load(self):
        self.current = 0
        self.thumbs.forget()
        self.pane.selected = [0]
        self.canvas.sel = []
        self.canvas.edit = None
        self.canvas.invalidate()
        self.pane.relayout()
        self.sorter.relayout()
        self._show_notes()
        self.sync_theme_palette()
        self.update_title()
        self.selection_changed()
        self._sync_transition()
        self.status.set_slide(self.current, self.deck.slide_count())

    def doc_name(self):
        return os.path.basename(self.path) if self.path else (self.untitled or "Presentation1")

    def title_text(self):
        name = self.doc_name()
        if self.path:
            name = os.path.splitext(name)[0]
        return name

    def update_title(self):
        name = self.title_text()
        tw = [w for w in getattr(self.app, "windows", []) if w.deck is self.deck] if getattr(self, "deck", None) else []
        if len(tw) > 1 and self in tw:
            name += ":%d" % (tw.index(self) + 1)
        if self.imported_from:
            name += "  [Compatibility Mode]"
        self.title_label.set_text("%s - %s" % (name, APP_NAME))
        self.set_title("%s - %s" % (name, APP_NAME))

    def master_name(self, part):
        return "Office Theme" if part.endswith("slideMaster1.xml") else os.path.splitext(os.path.basename(part))[0]

    def layout_picture(self, part, width):
        sw, sh = self.deck.size()
        scale = width / sw
        w, h, stride, data = self.deck.render_part(part, scale)
        surf = surface_from(w, h, stride, data)
        area = Gtk.DrawingArea()
        area.set_size_request(w + 2, h + 2)

        def draw(a, cr):
            cr.set_source_rgb(0.7, 0.7, 0.7)
            cr.rectangle(0, 0, w + 2, h + 2)
            cr.fill()
            cr.set_source_surface(surf, 1, 1)
            cr.paint()
        area.connect("draw", draw)
        return area

    # ------------------------------------------------------------ state
    def backstage_open(self):
        return self.backstage.get_visible()

    def show_backstage(self, page="home"):
        self.keytips.leave()
        self.canvas.leave_text()
        self._save_notes()
        self.backstage.open(page)

    def focus_document(self):
        if self.view == "sorter":
            self.sorter.area.grab_focus()
        elif self.view == "reading":
            self.reading.grab_focus()
        else:
            self.canvas.area.grab_focus()

    def go_slide(self, i, keep_selection=False):
        if self.master_mode is not None:
            return
        n = self.deck.slide_count()
        if n == 0:
            self.current = None
            self.canvas.invalidate()
            return
        i = max(0, min(n - 1, i))
        if i != self.current:
            self._save_notes()
            self.canvas.finish_crop()
            self.canvas.leave_text()
            self.canvas.sel = []
        self.current = i
        if not keep_selection:
            self.pane.selected = [i]
            self.sorter.selected = [i]
        self.canvas.invalidate()
        self.pane.queue()
        self.pane.ensure_visible(i)
        self.sorter.queue()
        self.reading.queue_draw()
        self._show_notes()
        self.status.set_slide(i, n)
        self.selection_changed()
        self._sync_transition()
        if getattr(self, "comments_pane", None) is not None:
            self.comments_pane.refresh()
        if getattr(self, "view", None) == "notespage":
            self.notes_page_pic.queue_draw()

    def changed(self, slide=False, structure=False, text=False, all_slides=False):
        """After an edit: redraw what it touched."""
        if structure or all_slides:
            if all_slides:
                self.thumbs.forget()
            n = self.deck.slide_count()
            if n and (self.current is None or self.current >= n):
                self.current = n - 1
            self.pane.relayout()
            self.sorter.relayout()
        if self.current is not None and self.current < self.deck.slide_count():
            self.thumbs.forget(self.deck.slide_parts()[self.current])
        if self.master_mode is not None:
            self.master_changed()
        self.canvas.invalidate()
        self.pane.queue()
        self.sorter.queue()
        self.update_title()
        self.status.set_slide(self.current or 0, self.deck.slide_count())
        for t in self.twins():
            t.twin_changed()
        if not text:
            self.selection_changed()
        else:
            self._sync_ribbon()

    def selection_changed(self):
        c = self.canvas
        shapes = [c.shape(s) for s in c.sel]
        shapes = [s for s in shapes if s]
        any_shape = bool(shapes)
        pics = shapes and all(s["kind"] == "pic" for s in shapes)
        tables = shapes and all(s["geom"] == "table" for s in shapes)
        self.ribbon.show_contextual("Shape Format", any_shape and not pics and not tables)
        self.ribbon.show_contextual("Picture Format", bool(pics))
        self.ribbon.show_contextual("Table Design", bool(tables))
        self.ribbon.show_contextual("Table Layout", bool(tables))
        self.ribbon.show_contextual("Chart Design", len(shapes) == 1 and shapes[0]["geom"] == "chart")
        self.ribbon.show_contextual("SmartArt Design", len(shapes) == 1 and shapes[0]["geom"] == "smartart")
        media = len(shapes) == 1 and shapes[0]["kind"] == "pic" and self.current is not None and \
            self.master_mode is None and self.deck.media_info(self.current, shapes[0]["id"]) is not None
        self.ribbon.show_contextual("Playback", bool(media))
        if tables and len(shapes) == 1:
            for key in ("firstRow", "lastRow", "bandRow", "firstCol", "lastCol", "bandCol"):
                self.ribbon.update("tbl-" + key, "true" if self.deck.table_option_value(self.current, shapes[0]["id"], key) else "false")
        if len(shapes) == 1:
            for sp in getattr(self, "size_spins", []):
                sp.show_value((shapes[0]["h"] if sp.which == "h" else shapes[0]["w"]) / 72.0)
        self._sync_ribbon()
        try:
            if self.anim_pick is not None:
                fx = self.deck.animations(self.current)
                if self.anim_pick >= len(fx) or (c.sel and fx[self.anim_pick]["spid"] not in c.sel):
                    self.anim_pick = None
            self.sync_animation()
        except Exception:
            pass
        if getattr(self, "anim_painter_fx", None) and len(c.sel) == 1 and c.edit is None:
            self.apply_anim_painter(c.sel[0])
        # the format painter applies to the next text selection or object
        if self.painter_props and (c.edit is not None and c.edit.has_selection() or (any_shape and c.edit is None)):
            props = self.painter_props
            self.painter_props = None
            for k, v in props.items():
                c.run_format(k, v)

    def _sync_ribbon(self):
        rp, pp = self.canvas.current_run()
        if rp:
            self.ribbon.update("bold", "true" if rp.get("b") else "false")
            self.ribbon.update("italic", "true" if rp.get("i") else "false")
            self.ribbon.update("underline", "true" if rp.get("u") else "false")
            self.ribbon.update("strike", "true" if rp.get("strike") else "false")
            self.ribbon.update("font-name", rp.get("font", ""))
            sz = rp.get("sz", 18)
            self.ribbon.update("font-size", ("%g" % sz))
        if pp:
            for a in ("l", "ctr", "r", "just"):
                self.ribbon.update("algn-" + a, "true" if pp.get("algn") == a else "false")

    # ------------------------------------------------------------ notes
    def _show_notes(self):
        self._notes_quiet = True
        has = self.current is not None and self.current < self.deck.slide_count() and self.master_mode is None
        txt = self.deck.notes(self.current) if has else ""
        # the notes belong to this slide, wherever it moves
        self._notes_part = self.deck.slide_parts()[self.current] if has else None
        self.notes.get_buffer().set_text(txt)
        self.notes_hint.set_visible(not txt)
        self._notes_quiet = False

    def _notes_changed(self, buf):
        if self._notes_quiet:
            return
        self.notes_hint.set_visible(buf.get_char_count() == 0)
        if self._notes_timer:
            GLib.source_remove(self._notes_timer)
        self._notes_timer = GLib.timeout_add(700, lambda: (self._save_notes(), False)[1])

    def _save_notes(self):
        if self._notes_timer:
            GLib.source_remove(self._notes_timer)
            self._notes_timer = None
        part = getattr(self, "_notes_part", None)
        if self.deck is None or part is None or part not in self.deck.slide_parts():
            return
        i = self.deck.slide_parts().index(part)
        buf = self.notes.get_buffer()
        txt = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False)
        if txt != self.deck.notes(i):
            self.deck.set_notes(i, txt)
            self.update_title()

    # ------------------------------------------------------------ commands
    def run(self, cmd, *args):
        """Run a command: 'name' or 'name:argument' → act_name(argument)."""
        if cmd is None:
            return None
        name, _, arg = cmd.partition(":")
        if self.master_mode is not None and name in MASTER_BLOCKED:
            self.dialogs.info("Close Master View to use this.")
            return None
        fn = getattr(self, "act_" + name.replace("-", "_"), None)
        if fn is None:
            return self.not_available(cmd)
        if self.keytips.active:
            self.keytips.leave()
        try:
            r = fn(arg) if arg or _ else fn()
        except Exception as e:
            import traceback
            traceback.print_exc()
            self.dialogs.message("Something went wrong running this command.\n\n%s" % e)
            return None
        return r

    def not_available(self, cmd):
        label = cmd.split(":", 1)[1] if cmd.startswith("not-available:") else cmd
        self.missing_log.append(cmd)
        self.dialogs.info("“%s” isn't available yet in %s." % (label, APP_NAME))

    def act_not_available(self, label):
        self.not_available("not-available:" + label)

    def act_out_of_scope(self, label):
        """Features Folio leaves out on purpose."""
        self.dialogs.info("“%s” isn't part of %s: it doesn't run macros or add-ins." % (label, APP_NAME) if label == "Macros" else "“%s” isn't part of %s." % (label, APP_NAME))

    # file
    def act_new(self):
        self.app.new_window()

    def choose_open_file(self):
        d = Gtk.FileChooserNative(title="Open", transient_for=self, action=Gtk.FileChooserAction.OPEN)
        f = Gtk.FileFilter()
        f.set_name("All PowerPoint Presentations")
        for pat in ("*.pptx", "*.pptm", "*.ppsx", "*.ppsm", "*.potx", "*.potm", "*.ppt", "*.pps", "*.pot", "*.odp"):
            f.add_pattern(pat)
            f.add_pattern(pat.upper())
        d.add_filter(f)
        a = Gtk.FileFilter()
        a.set_name("All Files")
        a.add_pattern("*")
        d.add_filter(a)
        if self.path:
            d.set_current_folder(os.path.dirname(self.path))
        r = d.run()
        p = d.get_filename() if r == Gtk.ResponseType.ACCEPT else None
        d.destroy()
        return p

    def act_open(self):
        p = self.choose_open_file()
        if p:
            self.app.open_path(p, self)

    def act_save(self):
        self._save_notes()
        if self.path is None or os.path.splitext(self.path)[1].lower() not in NATIVE:
            return self.act_save_as()
        return self.save_to(self.path)

    def save_to(self, path):
        self.canvas.leave_text()
        try:
            self.deck.save(path)
        except Exception as e:
            self.dialogs.message("%s couldn't save '%s'.\n\n%s" % (APP_NAME, os.path.basename(path), e))
            return False
        self.path = os.path.abspath(path)
        self.imported_from = None
        self.app.add_recent(self.path)
        self.update_title()
        for t in self.twins():
            t.path, t.imported_from = self.path, None
            t.update_title()
        return True

    def twins(self):
        """The other windows on this presentation (View > New Window)."""
        return [w for w in self.app.windows if w is not self and w.deck is self.deck]

    def twin_changed(self):
        """Another window on this presentation changed it."""
        n = self.deck.slide_count()
        self.thumbs.forget()
        if self.current is not None and self.current >= n:
            self.current = n - 1 if n else None
        self.canvas.invalidate()
        self.pane.relayout()
        self.sorter.relayout()
        self.update_title()
        if self.current is not None:
            self._show_notes()

    def act_save_as(self, kind="pptx"):
        self._save_notes()
        d = Gtk.FileChooserNative(title="Save As", transient_for=self, action=Gtk.FileChooserAction.SAVE)
        d.set_do_overwrite_confirmation(True)
        names = {"pptx": "PowerPoint Presentation (*.pptx)", "ppsx": "PowerPoint Show (*.ppsx)",
                 "potx": "PowerPoint Template (*.potx)", "pdf": "PDF (*.pdf)"}
        f = Gtk.FileFilter()
        f.set_name(names.get(kind, kind))
        f.add_pattern("*." + kind)
        d.add_filter(f)
        base = self.title_text()
        d.set_current_name(base + "." + kind)
        if self.path:
            d.set_current_folder(os.path.dirname(self.path))
        r = d.run()
        p = d.get_filename() if r == Gtk.ResponseType.ACCEPT else None
        d.destroy()
        if not p:
            return False
        if not p.lower().endswith("." + kind):
            p += "." + kind
        if kind == "pdf":
            self.deck.export_pdf(p)
            return True
        if kind in ("ppsx", "potx"):
            # the same package with the main part's content type changed
            data = bytes(self.deck.to_bytes())
            import io
            import zipfile
            src = zipfile.ZipFile(io.BytesIO(data))
            out = io.BytesIO()
            with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
                for it in src.infolist():
                    b = src.read(it.filename)
                    if it.filename == "[Content_Types].xml":
                        b = b.replace(CT_MAIN["pptx"].encode(), CT_MAIN[kind].encode())
                    z.writestr(it, b)
            with open(p, "wb") as fh:
                fh.write(out.getvalue())
            return True
        return self.save_to(p)

    def act_send_attachment(self, pdf=""):
        """File > Share > Email: a new message in the mail app with this presentation (or a PDF of it) attached."""
        import shutil
        import subprocess
        import tempfile
        name = os.path.splitext(os.path.basename(self.path or (self.untitled or "Presentation") + ".pptx"))[0]
        d = tempfile.mkdtemp(prefix="folio-share-")
        path = os.path.join(d, name + (".pdf" if pdf else ".pptx"))
        try:
            if pdf:
                self.deck.export_pdf(path)
            else:
                self.canvas.leave_text()
                was = self.deck.modified
                self.deck.save(path)
                self.deck.modified = was
        except Exception as e:
            self.dialogs.message("%s couldn't make the attachment.\n\n%s" % (APP_NAME, e))
            return None
        post = shutil.which("folio-post")
        if post:
            subprocess.Popen([post, "--attach", path])
        elif shutil.which("xdg-email"):
            subprocess.Popen(["xdg-email", "--subject", name, "--attach", path])
        else:
            self.dialogs.info("Sending needs a mail app: install Folio Post.")
            return None
        return path

    def act_send_pdf(self):
        return self.act_send_attachment("pdf")

    def act_export_pdf(self):
        return self.act_save_as("pdf")

    def act_export_png(self, all_slides=False):
        d = Gtk.FileChooserNative(title="Save as Picture", transient_for=self, action=Gtk.FileChooserAction.SAVE)
        d.set_current_name("%s%s.png" % (self.title_text(), "" if all_slides else " - Slide %d" % (self.current + 1)))
        d.set_do_overwrite_confirmation(True)
        r = d.run()
        p = d.get_filename() if r == Gtk.ResponseType.ACCEPT else None
        d.destroy()
        if not p:
            return
        if all_slides:
            folder = os.path.splitext(p)[0]
            os.makedirs(folder, exist_ok=True)
            for i in range(self.deck.slide_count()):
                self.deck.export_png(i, os.path.join(folder, "Slide%d.png" % (i + 1)), 1920)
            self.dialogs.info("Each slide was saved as a picture in\n%s" % folder)
        else:
            self.deck.export_png(self.current, p if p.lower().endswith(".png") else p + ".png", 1920)

    def act_export_png_all(self):
        self.act_export_png(True)

    def act_print(self):
        self.show_backstage("print")

    def act_close(self):
        if self.confirm_close():
            self._closing()
            self.app.window_closed(self)
            self.destroy()

    def act_options(self):
        self.dialogs.info("Options will be available in a later version.", "Options")

    def confirm_close(self):
        self._save_notes()
        if not self.deck.modified or self.twins():
            return True
        ans = self.dialogs.confirm_save(self.doc_name())
        if ans == "save":
            return bool(self.act_save())
        return ans == "discard"

    def _closing(self):
        pass

    def on_delete(self, *a):
        self.canvas.leave_text()
        if not self.confirm_close():
            return True
        self._closing()
        self.app.window_closed(self)
        return False

    def _remember_geometry(self, w, ev):
        if not self.is_maximized():
            self.app.settings["window"] = {"w": ev.width, "h": ev.height, "max": False}
        else:
            self.app.settings.setdefault("window", {})["max"] = True
        return False

    # undo
    def act_undo(self):
        self.canvas.leave_text()
        self._save_notes()
        if self.deck.undo() is None:
            return
        self.thumbs.forget()
        self.changed(structure=True)
        self._show_notes()

    def act_redo(self):
        self.canvas.leave_text()
        if self.deck.redo() is None:
            return
        self.thumbs.forget()
        self.changed(structure=True)
        self._show_notes()

    # slides
    def _layout_for_new(self):
        """The layout a new slide gets: after the title slide, Title and Content; else the current one."""
        names = {p: n for _m, ls in self.deck.layouts() for p, n in ls}
        cur = self.deck.slide_layout(self.current) if self.deck.slide_count() else None
        if cur is None or names.get(cur) == "Title Slide":
            for p, n in names.items():
                if n == "Title and Content":
                    return p
            for p in names:
                return p
        return cur

    def act_new_slide(self, layout=None):
        layout = layout or self._layout_for_new()
        after = self.current if self.deck.slide_count() else None
        i = self.deck.new_slide(after, layout)
        self.changed(structure=True)
        self.go_slide(i)

    def act_new_slide_layout(self, part):
        self.act_new_slide(part)

    def act_set_layout(self, part):
        idx = self._selected_slides()
        self.deck.set_layout(idx, part)
        for i in idx:
            self.thumbs.forget(self.deck.slide_parts()[i])
        self.changed(slide=True)

    def act_reset_slide(self):
        idx = self._selected_slides()
        lay = self.deck.slide_layout(self.current)
        if lay:
            self.deck.set_layout(idx, lay)
            for i in idx:
                self.thumbs.forget(self.deck.slide_parts()[i])
            self.changed(slide=True)

    def _selected_slides(self):
        sel = self.pane.selected if self.view == "normal" else self.sorter.selected
        sel = sorted(i for i in sel if 0 <= i < self.deck.slide_count())
        return sel or ([self.current] if self.current is not None else [])

    def act_duplicate_slides(self):
        idx = self._selected_slides()
        if not idx:
            return
        i = self.deck.duplicate_slides(idx)
        self.changed(structure=True)
        self.pane.selected = list(range(i, i + len(idx)))
        self.go_slide(i, keep_selection=True)

    def act_delete_slides(self):
        idx = self._selected_slides()
        if not idx:
            return
        self.canvas.leave_text()
        self.deck.delete_slides(idx)
        n = self.deck.slide_count()
        self.current = min(idx[0], n - 1) if n else None
        self.pane.selected = [self.current] if n else []
        self.changed(structure=True)
        if n:
            self.go_slide(self.current)
        else:
            self.canvas.invalidate()

    def act_hide_slide(self):
        idx = self._selected_slides()
        hide = not self.deck.is_hidden(idx[0])
        self.deck.set_hidden(idx, hide)
        self.changed(structure=True)

    def act_slide_up(self):
        idx = self._selected_slides()
        if idx and idx[0] > 0:
            at = self.deck.move_slides(idx, idx[0] - 1)
            self.pane.selected = list(range(at, at + len(idx)))
            self.changed(structure=True)
            self.go_slide(at, keep_selection=True)

    def act_slide_down(self):
        idx = self._selected_slides()
        if idx and idx[-1] + 1 < self.deck.slide_count():
            at = self.deck.move_slides(idx, idx[-1] + 2)
            self.pane.selected = list(range(at, at + len(idx)))
            self.changed(structure=True)
            self.go_slide(at, keep_selection=True)


    def act_slides_from_outline(self):
        """A text outline (one line a slide title, indented lines its bullets) as new slides."""
        d = Gtk.FileChooserNative(title="Insert Outline", transient_for=self, action=Gtk.FileChooserAction.OPEN)
        f = Gtk.FileFilter()
        f.set_name("Outlines (*.txt, *.docx)")
        for p in ("*.txt", "*.docx"):
            f.add_pattern(p)
        d.add_filter(f)
        r = d.run()
        p = d.get_filename() if r == Gtk.ResponseType.ACCEPT else None
        d.destroy()
        if not p:
            return
        from .outline import read_outline
        try:
            items = read_outline(p)
        except Exception as e:
            self.dialogs.message("This outline can't be read.\n\n%s" % e)
            return
        self.insert_outline(items)

    def insert_outline(self, items):
        """items: [(title, [(level, text)])] → slides after the current one."""
        layout = None
        for _m, ls in self.deck.layouts():
            for part, n in ls:
                if n == "Title and Content":
                    layout = part
        layout = layout or self._layout_for_new()
        at = self.current
        for title, bullets in items:
            at = self.deck.new_slide(at, layout)
            shapes = self.deck.shapes(at)
            for s in shapes:
                if s["ph"] in ("title", "ctrTitle"):
                    self.deck.set_text(at, s["id"], title)
                elif s["ph"] in ("body", "obj", None) and bullets and s["has_text"]:
                    self.deck.set_text(at, s["id"], "\n".join(t for _l, t in bullets))
                    for k, (lvl, _t) in enumerate(bullets):
                        if lvl:
                            self.deck.format_paras(at, s["id"], k, k, "lvl", str(min(8, lvl)))
                    bullets = []
        self.changed(structure=True)
        self.go_slide(at)


    # views
    def set_view(self, view):
        self._save_notes()
        self.canvas.leave_text()
        self.canvas.finish_crop()
        if getattr(self, "view", None) == "outline":
            self.outline.apply()
        self.view = view
        np = self.normal_paned
        left = np.get_child1()
        want = self.outline if view == "outline" else self.pane
        if view == "outline" and left is self.pane:
            self._pane_width = np.get_position()
        if left is not want:
            np.remove(left)
            np.pack1(want, False, False)
            want.show_all()
            np.set_position(int(self.get_allocated_width() * 0.32) if view == "outline" else self._pane_width)
        if view == "outline":
            self.outline.load()
        elif view == "notespage":
            self.notes_page_pic.queue_draw()
        self.stack.set_visible_child_name("normal" if view == "outline" else view)
        self.status.set_view(view)
        if view == "sorter":
            self.sorter.selected = list(self.pane.selected)
            self.sorter.relayout()
        elif view == "normal":
            self.pane.selected = list(self.sorter.selected) or [self.current]
            self.pane.relayout()
        if view == "outline":
            GLib.idle_add(lambda: (self.outline.view.grab_focus(), False)[1])
        else:
            GLib.idle_add(self.focus_document)

    def act_view_normal(self):
        self.set_view("normal")

    def act_view_sorter(self):
        self.set_view("sorter")

    def act_view_reading(self):
        self.set_view("reading")

    def _draw_reading(self, area, cr):
        from .show import draw_slide

        class _St:
            pass
        st = getattr(self, "_reading_state", None)
        if st is None:
            from .show import ShowState
            st = self._reading_state = ShowState(self, self.current or 0, hidden_too=True)
        st.deck = self.deck
        draw_slide(cr, st, self.current, area.get_allocated_width(), area.get_allocated_height(), ink=False)

    def act_toggle_notes(self):
        self.notes_box.set_visible(not self.notes_box.get_visible())

    def act_toggle_ruler(self):
        self.canvas.show_ruler = self.ruler_check.get_active()
        self.canvas.queue()

    def act_toggle_grid(self):
        self.canvas.show_grid = self.grid_check.get_active()
        self.canvas.queue()

    def act_toggle_guides(self):
        self.canvas.show_guides = self.guides_check.get_active()
        self.canvas.queue()

    def act_zoom_fit(self):
        self.canvas.set_zoom(fit=True)

    def act_zoom_dialog(self):
        d = Gtk.Dialog(title="Zoom", transient_for=self, modal=True)
        d.add_button("OK", Gtk.ResponseType.OK)
        d.add_button("Cancel", Gtk.ResponseType.CANCEL)
        box = d.get_content_area()
        box.set_border_width(10)
        group = None
        radios = {}
        for label in ("Fit", "400%", "200%", "100%", "66%", "50%", "33%"):
            rb = Gtk.RadioButton.new_with_label_from_widget(group, label)
            group = group or rb
            radios[label] = rb
            box.pack_start(rb, False, False, 0)
        spin = Gtk.SpinButton.new_with_range(10, 400, 1)
        spin.set_value(self.canvas.zoom_percent())
        row = Gtk.Box(spacing=6)
        row.pack_start(Gtk.Label(label="Percent:"), False, False, 0)
        row.pack_start(spin, False, False, 0)
        box.pack_start(row, False, False, 6)
        for label, rb in radios.items():
            if label != "Fit":
                rb.connect("toggled", lambda b, v=int(label[:-1]): b.get_active() and spin.set_value(v))
        if self.canvas.fit:
            radios["Fit"].set_active(True)
        d.show_all()
        r = d.run()
        if r == Gtk.ResponseType.OK:
            if radios["Fit"].get_active():
                self.canvas.set_zoom(fit=True)
            else:
                self.canvas.set_zoom(spin.get_value())
        d.destroy()

    def act_new_window(self):
        self._save_notes()
        w = DeliverWindow(self.app, twin=self)
        self.app.windows.append(w)
        for t in [self] + self.twins():
            t.update_title()
        w.present()
        return w

    def act_arrange_all(self):
        """Side by side, filling the screen."""
        ws = [w for w in self.app.windows]
        disp = Gdk.Display.get_default()
        mon = disp.get_monitor_at_window(self.get_window()) if self.get_window() else disp.get_monitor(0)
        g = mon.get_workarea()
        n = len(ws)
        for k, w in enumerate(ws):
            w.unmaximize()
            ww = g.width // n
            w.move(g.x + k * ww, g.y)
            w.resize(ww, g.height)

    def act_switch_windows(self):
        m = Gtk.Menu()
        for w in self.app.windows:
            mi = Gtk.MenuItem(label=w.title_text())
            mi.connect("activate", lambda _m, w=w: w.present())
            m.append(mi)
        m.show_all()
        m.popup_at_pointer(None)

    # slide show
    def act_show_start(self):
        self.start_show(0)

    def act_show_current(self):
        self.start_show(self.current or 0)

    def start_show(self, i, presenter=False):
        self._save_notes()
        self.canvas.leave_text()
        if self.deck.slide_count() == 0:
            return
        from . import show
        self.show_state = show.start(self, i, presenter)

    def presenter_view(self, st):
        from . import show
        sw = getattr(st, "show_window", None)
        if sw is not None:
            st.listeners.remove(sw.refresh)
            sw.destroy()
            st.show_window = None
        st.presenter_window = show.PresenterWindow(st, None)

    def show_ended(self, st):
        if st.index is not None and self.view == "normal" and not getattr(st, "custom", False):
            self.go_slide(st.index)
        self.present()
        def after():
            if getattr(st, "narration", None):
                self.keep_narration(st)
            if getattr(st, "rehearse", None) is not None:
                self.finish_rehearsal(st, keep=True if getattr(st, "narration", None) else None)
            if any(getattr(st, "ink", {}).values()):
                self.keep_show_ink(st)
            return False
        GLib.idle_add(after)

    def act_toggle_presenter_view(self):
        self.app.settings["presenter_view"] = self.presenter_check.get_active()
        try:
            self.app.save_settings()
        except OSError:
            pass


    # clipboard
    def act_copy(self):
        c = self.canvas
        if c.edit is not None:
            t = c.selected_text()
            if t:
                Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD).set_text(t.replace("\x0b", "\n"), -1)
                self.clip = {"kind": "text", "text": t}
                self.remember_clip(self.clip, t.replace("\x0b", " ").replace("\n", " ")[:60])
            return
        if c.sel:
            xml = self.deck.shapes_xml(self.current, c.sel)
            texts = []
            for sid in c.sel:
                texts += self.deck.paragraphs(self.current, sid)
            media = [(a, b, c_, bytes(d_), e, f) for a, b, c_, d_, e, f in self.deck.shape_media(self.current, xml)]
            self.clip = {"kind": "shapes", "xml": xml, "deck": id(self.deck), "slide": self.current, "media": media,
                         "text": "\n".join(texts)}
            self.app.clip = self.clip
            Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD).set_text("\n".join(texts), -1)
            self._clip_text = "\n".join(texts)
            names = [s["name"] for s in (c.shape(x) for x in c.sel) if s]
            self.remember_clip(self.clip, ", ".join(names)[:60] or "Objects")
        elif self.view == "sorter" or self.pane.area.has_focus():
            self.clip = {"kind": "slides", "idx": self._selected_slides(), "deck": id(self.deck)}
            self.app.clip = self.clip
            self.remember_clip(self.clip, "Slide " + ", ".join(str(i + 1) for i in self.clip["idx"]))

    def act_cut(self):
        c = self.canvas
        if c.edit is not None:
            if c.edit.has_selection():
                self.act_copy()
                c.delete(True)
            return
        if c.sel:
            self.act_copy()
            self.act_delete()
        elif self.pane.area.has_focus() or self.view == "sorter":
            self.act_copy()
            self.act_delete_slides()

    def act_paste(self, mode=None):
        c = self.canvas
        clip = getattr(self.app, "clip", None) or self.clip
        cb = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
        text = cb.wait_for_text()
        if c.edit is not None:
            if text:
                c.type_text(text.replace("\r\n", "\n").replace("\r", "\n"))
            return
        if clip and clip.get("kind") == "slides" and clip.get("deck") == id(self.deck) and \
                (self.pane.area.has_focus() or self.view == "sorter"):
            i = self.deck.duplicate_slides(clip["idx"])
            at = self.current + 1
            self.deck.move_slides(list(range(i, i + len(clip["idx"]))), at)
            self.changed(structure=True)
            self.go_slide(at)
            return
        if clip and clip.get("kind") == "shapes" and (text is None or text == getattr(self, "_clip_text", None)):
            same = clip.get("slide") == self.current and clip.get("deck") == id(self.deck)
            off = 12.0 if same else 0.0
            # pictures and links come along, from this presentation or another
            new = self.deck.paste_shapes_media(self.current, clip["xml"], clip.get("media", []), off, off)
            self.changed(slide=True)
            c.select(new)
            return
        img = cb.wait_for_image()
        if img is not None:
            ok, data = img.save_to_bufferv("png", [], [])
            if ok:
                self._insert_picture_bytes(bytes(data), "png", "Picture")
            return
        grid = table_from_text(text) if (text and mode != "text") else None
        if grid is not None:
            self.paste_table(grid)
            return
        if text:
            sw, sh = self.deck.size()
            sid = self.deck.add_textbox(self.current, sw * 0.1, sh * 0.4, sw * 0.8, 40, text.strip("\n"))
            self.deck.fit_text(self.current, sid, "Paste")
            self.changed(slide=True)
            c.select([sid])

    def paste_table(self, grid):
        """Cells copied from Folio Sheets (or any spreadsheet: tab-separated rows) become a table."""
        rows, cols = len(grid), max(len(r) for r in grid)
        sw, sh = self.deck.size()
        w = min(sw * 0.8, max(sw * 0.3, cols * sw * 0.12))
        tid = self.deck.add_table(self.current, rows, cols, (sw - w) / 2, sh * 0.25, w)
        for r, row in enumerate(grid):
            for c in range(cols):
                v = row[c] if c < len(row) else ""
                if v:
                    self.deck.set_text(self.current, Presentation.cell_id(tid, r * cols + c), v)
        self.changed(slide=True)
        self.canvas.select([tid])
        return tid

    def act_paste_text(self):
        self.act_paste("text")

    def act_paste_picture(self):
        self.act_paste("picture")

    def act_format_painter(self):
        rp, _pp = self.canvas.current_run()
        if not rp:
            return
        self.painter_props = {"b": "1" if rp.get("b") else "0", "i": "1" if rp.get("i") else "0",
                              "u": "sng" if rp.get("u") else "none", "sz": "%g" % rp.get("sz", 18),
                              "font": rp.get("font", "")}
        if rp.get("color"):
            self.painter_props["color"] = rp["color"]

    # objects
    def act_delete(self):
        c = self.canvas
        if c.edit is not None:
            c.delete(False)
            return
        if c.sel:
            # placeholders with text are emptied first (as PowerPoint does), empty ones go
            ids = list(c.sel)
            self.deck.delete_shapes(self.current, ids)
            c.sel = []
            self.changed(slide=True)
        elif self.pane.area.has_focus():
            self.act_delete_slides()

    def act_select_all(self):
        self.canvas.select_all()

    def act_select_objects(self):
        self.canvas.leave_text()

    def act_selection_pane(self):
        from .panes import selection_pane
        selection_pane(self)

    def act_pointer(self):
        self.canvas.insert_mode = None
        self.canvas.ink_tool = None

    def act_draw_shape(self, prst):
        self.canvas.leave_text()
        self.canvas.insert_mode = ("shape", prst)
        self.status.slide_label.set_text("Click and drag to draw the shape")

    def act_draw_textbox(self):
        self.canvas.leave_text()
        self.canvas.insert_mode = ("textbox",)
        self.status.slide_label.set_text("Click and drag to draw the text box")

    def insert_mode_done(self):
        self.status.set_slide(self.current or 0, self.deck.slide_count())

    def act_insert_picture(self):
        d = Gtk.FileChooserNative(title="Insert Picture", transient_for=self, action=Gtk.FileChooserAction.OPEN)
        f = Gtk.FileFilter()
        f.set_name("All Pictures")
        for p in ("*.png", "*.jpg", "*.jpeg", "*.gif", "*.bmp", "*.tif", "*.tiff", "*.webp"):
            f.add_pattern(p)
            f.add_pattern(p.upper())
        d.add_filter(f)
        r = d.run()
        p = d.get_filename() if r == Gtk.ResponseType.ACCEPT else None
        d.destroy()
        if not p:
            return
        with open(p, "rb") as fh:
            data = fh.read()
        ext = os.path.splitext(p)[1][1:].lower()
        if ext == "webp":
            from gi.repository import GdkPixbuf
            pb = GdkPixbuf.Pixbuf.new_from_file(p)
            ok, data = pb.save_to_bufferv("png", [], [])
            data, ext = bytes(data), "png"
        self._insert_picture_bytes(data, ext, os.path.basename(p))

    def _insert_picture_bytes(self, data, ext, name):
        size = Presentation.picture_size(data)
        if size is None:
            self.dialogs.message("This picture can't be read.")
            return
        sw, sh = self.deck.size()
        pw, ph = size[0] * 0.75, size[1] * 0.75        # 96 dpi
        k = min(1.0, sw * 0.8 / pw, sh * 0.8 / ph)
        w, h = pw * k, ph * k
        # into an empty picture/content placeholder when there is one
        target = None
        for s in self.canvas.shapes:
            if s["empty"] and s["ph"] in ("pic", "obj", "body") and s["ph"] != "body" or (s["empty"] and s["ph"] == "pic"):
                target = s
                break
        if target is not None:
            k2 = min(target["w"] / w, target["h"] / h)
            w2, h2 = w * k2, h * k2
            x, y = target["x"] + (target["w"] - w2) / 2, target["y"] + (target["h"] - h2) / 2
            self.deck.delete_shapes(self.current, [target["id"]])
            sid = self.deck.add_picture(self.current, data, ext, name, x, y, w2, h2)
        else:
            sid = self.deck.add_picture(self.current, data, ext, name, (sw - w) / 2, (sh - h) / 2, w, h)
        self.changed(slide=True)
        self.canvas.select([sid])


    def _insert_text_here(self, text):
        c = self.canvas
        if c.edit is not None:
            c.type_text(text)
            return
        sw, sh = self.deck.size()
        sid = self.deck.add_textbox(self.current, sw * 0.4, sh * 0.45, sw * 0.2, 30, text)
        self.deck.fit_text(self.current, sid, "Insert Text Box")
        self.changed(slide=True)
        c.select([sid])

    def act_insert_date(self):
        self._insert_text_here(datetime.date.today().strftime("%-m/%-d/%Y"))

    def act_insert_slide_number(self):
        self._insert_text_here(str((self.current or 0) + 1))

    def act_insert_symbol(self):
        from .panes import symbol_dialog
        ch = symbol_dialog(self)
        if ch:
            self._insert_text_here(ch)

    def act_wordart(self):
        sw, sh = self.deck.size()
        sid = self.deck.add_textbox(self.current, sw * 0.2, sh * 0.38, sw * 0.6, 80, "Your text here")
        n = len("Your text here")
        self.deck.format_runs(self.current, sid, (0, 0), (0, n), "sz", "54")
        self.deck.format_runs(self.current, sid, (0, 0), (0, n), "color", "scheme:accent1")
        self.deck.format_runs(self.current, sid, (0, 0), (0, n), "shadow", "1")
        self.deck.format_paras(self.current, sid, 0, 0, "algn", "ctr")
        self.deck.fit_text(self.current, sid, "WordArt")
        self.changed(slide=True)
        self.canvas.start_text(sid, (0, 0), select_all=True)
        self.canvas.edit.caret = (0, n)

    # text formatting
    def act_bold(self):
        rp, _ = self.canvas.current_run()
        self.canvas.run_format("b", "0" if rp and rp.get("b") else "1")

    def act_italic(self):
        rp, _ = self.canvas.current_run()
        self.canvas.run_format("i", "0" if rp and rp.get("i") else "1")

    def act_underline(self):
        rp, _ = self.canvas.current_run()
        self.canvas.run_format("u", "none" if rp and rp.get("u") else "sng")

    def act_strike(self):
        rp, _ = self.canvas.current_run()
        self.canvas.run_format("strike", "noStrike" if rp and rp.get("strike") else "sngStrike")

    def act_text_shadow(self):
        self.canvas.run_format("shadow", "1")

    def act_clear_formatting(self):
        self.canvas.run_format("clear", "")

    def act_font_name(self, name):
        if name:
            self.canvas.run_format("font", name)
            self.focus_document()

    def act_font_size(self, v):
        try:
            sz = float(v)
        except ValueError:
            return
        if 1 <= sz <= 4000:
            self.canvas.run_format("sz", "%g" % sz)
            self.focus_document()

    def _step_size(self, up):
        rp, _ = self.canvas.current_run()
        cur = rp.get("sz", 18) if rp else 18
        if up:
            nxt = next((s for s in SIZES if s > cur + 0.01), cur + 10)
        else:
            nxt = next((s for s in reversed(SIZES) if s < cur - 0.01), max(1, cur - 1))
        self.canvas.run_format("sz", "%g" % nxt)

    def act_font_grow(self):
        self._step_size(True)

    def act_font_shrink(self):
        self._step_size(False)

    def _color_cmd(self, which, v, apply):
        if v == "more":
            d = Gtk.ColorChooserDialog(title="Colors", transient_for=self)
            if d.run() == Gtk.ResponseType.OK:
                c = d.get_rgba()
                v = "%02X%02X%02X" % (int(c.red * 255), int(c.green * 255), int(c.blue * 255))
            else:
                v = None
            d.destroy()
            if v is None:
                return
        if v != "none":
            self.last_colors[which] = v
        apply(v)

    def act_font_color(self, v):
        self._color_cmd("font-color", v, lambda v: self.canvas.run_format("color", "" if v == "none" else v))

    def act_font_color_last(self):
        self.act_font_color(self.last_colors["font-color"])

    def act_highlight(self, v):
        self._color_cmd("highlight", v, lambda v: self.canvas.run_format("highlight", "" if v == "none" else v))

    def act_highlight_last(self):
        self.act_highlight(self.last_colors["highlight"])

    def act_spacing(self, v):
        self.canvas.run_format("spc", v)

    def act_case(self, how):
        c = self.canvas
        if c.edit is None or not c.edit.has_selection():
            return
        t = c.selected_text()
        if how == "upper":
            n = t.upper()
        elif how == "lower":
            n = t.lower()
        elif how == "title":
            n = " ".join(w[:1].upper() + w[1:].lower() for w in t.split(" "))
        elif how == "toggle":
            n = t.swapcase()
        else:
            n = t[:1].upper() + t[1:].lower()
        a, _b = c.edit.range()
        c.type_text(n)
        c.edit.anchor = a

    def act_bullets(self, v=None):
        if v is None:
            _, pp = self.canvas.current_run()
            v = "none" if pp and pp.get("bullet", "none").startswith("char") else "char:•"
        self.canvas.para_format("bullet", v, label="Bullets")

    def act_numbering(self, v=None):
        if v is None:
            _, pp = self.canvas.current_run()
            v = "none" if pp and pp.get("bullet", "none").startswith("auto") else "arabicPeriod"
        self.canvas.para_format("bullet", "none" if v == "none" else "auto:" + v, label="Numbering")

    def act_level_up(self):
        _, pp = self.canvas.current_run()
        self.canvas.para_format("lvl", str(min(8, (pp or {}).get("lvl", 0) + 1)), label="Increase List Level")

    def act_level_down(self):
        _, pp = self.canvas.current_run()
        self.canvas.para_format("lvl", str(max(0, (pp or {}).get("lvl", 0) - 1)), label="Decrease List Level")

    def act_line_spacing(self, v):
        self.canvas.para_format("lnSpc", v, label="Line Spacing")

    def act_align(self, a):
        self.canvas.para_format("algn", a, label="Align")

    def act_columns(self, n):
        self.canvas.para_format("numCol", "" if n == "1" else n, label="Columns")

    def act_text_direction(self, v):
        self.canvas.para_format("vert", "" if v == "horz" else v, label="Text Direction")

    def act_anchor(self, v):
        self.canvas.para_format("anchor", v, label="Align Text")

    def act_font_dialog(self):
        from .panes import font_dialog
        font_dialog(self)

    def act_paragraph_dialog(self):
        from .panes import paragraph_dialog
        paragraph_dialog(self)

    # shape formatting
    def _targets(self):
        return list(self.canvas.sel)

    def act_shape_fill(self, v):
        def apply(v):
            if self._targets():
                self.deck.set_shape_fill(self.current, self._targets(), v)
                self.changed(slide=True)
        self._color_cmd("shape-fill", v, apply)

    def act_shape_fill_last(self):
        self.act_shape_fill(self.last_colors["shape-fill"])

    def act_shape_outline(self, v):
        def apply(v):
            if self._targets():
                self.deck.set_shape_line(self.current, self._targets(), v, None, None)
                self.changed(slide=True)
        self._color_cmd("shape-outline", v, apply)

    def act_shape_outline_last(self):
        self.act_shape_outline(self.last_colors["shape-outline"])

    def act_shape_shadow(self, v):
        if self._targets():
            self.deck.set_shape_shadow(self.current, self._targets(), v == "on")
            self.changed(slide=True)

    def act_format_shape(self):
        from .panes import format_shape_dialog
        format_shape_dialog(self)

    def act_format_background(self):
        from .panes import background_dialog
        background_dialog(self)

    def act_order(self, how):
        if self._targets():
            self.deck.reorder(self.current, self._targets(), how)
            self.changed(slide=True)

    def act_group(self):
        if len(self._targets()) < 2:
            return
        gid = self.deck.group(self.current, self._targets())
        self.changed(slide=True)
        self.canvas.select([gid])

    def act_ungroup(self):
        out = []
        for sid in self._targets():
            s = self.canvas.shape(sid)
            if s and s["kind"] == "grpSp":
                out += self.deck.ungroup(self.current, sid)
        if out:
            self.changed(slide=True)
            self.canvas.select(out)

    def act_rotate(self, deg):
        boxes = []
        for sid in self._targets():
            s = self.canvas.shape(sid)
            if s:
                boxes.append((sid, s["x"], s["y"], s["w"], s["h"], (s["rot"] + float(deg)) % 360))
        if boxes:
            self.deck.set_boxes(self.current, boxes, "Rotate")
            self.changed(slide=True)

    def act_flip(self, axis):
        if self._targets():
            self.deck.flip(self.current, self._targets(), axis == "h")
            self.changed(slide=True)

    def act_align_to(self, how):
        self.app.settings["align_to"] = how

    def act_align_obj(self, how):
        shapes = [self.canvas.shape(s) for s in self._targets()]
        shapes = [s for s in shapes if s]
        if not shapes:
            return
        sw, sh = self.deck.size()
        to_slide = len(shapes) == 1 or self.app.settings.get("align_to") == "slide"
        if to_slide:
            x0, y0, x1, y1 = 0, 0, sw, sh
        else:
            x0 = min(s["x"] for s in shapes)
            y0 = min(s["y"] for s in shapes)
            x1 = max(s["x"] + s["w"] for s in shapes)
            y1 = max(s["y"] + s["h"] for s in shapes)
        boxes = []
        if how in ("dist-h", "dist-v"):
            key, size = ("x", "w") if how == "dist-h" else ("y", "h")
            order = sorted(shapes, key=lambda s: s[key])
            total = sum(s[size] for s in order)
            span = ((x1 - x0) if how == "dist-h" else (y1 - y0)) - total
            gap = span / max(1, len(order) - 1) if not to_slide else span / (len(order) + 1)
            pos = (x0 if how == "dist-h" else y0) + (gap if to_slide else 0)
            for s in order:
                nx, ny = (pos, s["y"]) if how == "dist-h" else (s["x"], pos)
                boxes.append((s["id"], nx, ny, s["w"], s["h"], None))
                pos += s[size] + gap
        else:
            for s in shapes:
                x, y = s["x"], s["y"]
                if how == "left":
                    x = x0
                elif how == "center":
                    x = (x0 + x1) / 2 - s["w"] / 2
                elif how == "right":
                    x = x1 - s["w"]
                elif how == "top":
                    y = y0
                elif how == "middle":
                    y = (y0 + y1) / 2 - s["h"] / 2
                elif how == "bottom":
                    y = y1 - s["h"]
                boxes.append((s["id"], x, y, s["w"], s["h"], None))
        self.deck.set_boxes(self.current, boxes, "Align")
        self.changed(slide=True)

    def _size(self, which, inches):
        boxes = []
        for sid in self._targets():
            s = self.canvas.shape(sid)
            if not s:
                continue
            v = float(inches) * 72
            w, h = (v, s["h"]) if which == "w" else (s["w"], v)
            if s["kind"] == "pic" and s["w"] and s["h"]:
                # pictures keep their proportions
                k = v / (s["w"] if which == "w" else s["h"])
                w, h = s["w"] * k, s["h"] * k
            boxes.append((sid, s["x"], s["y"], w, h, None))
        if boxes:
            self.deck.set_boxes(self.current, boxes, "Size")
            self.changed(slide=True)

    def act_size_w(self, v):
        self._size("w", v)

    def act_size_h(self, v):
        self._size("h", v)

    # review
    def act_spelling(self):
        from .panes import spelling_dialog
        spelling_dialog(self)

    def act_accessibility(self):
        from .panes import accessibility_report
        accessibility_report(self)

    def act_find(self):
        from .panes import find_dialog
        find_dialog(self, replace=False)

    def act_replace(self):
        from .panes import find_dialog
        find_dialog(self, replace=True)

    # help
    def act_help(self):
        self.act_shortcuts()

    def act_shortcuts(self):
        from .panes import shortcuts_dialog
        shortcuts_dialog(self)

    def act_about(self):
        d = Gtk.AboutDialog(transient_for=self, modal=True)
        d.set_program_name(APP_NAME)
        d.set_version(VERSION)
        d.set_comments("Presentations, made for a seamless move from PowerPoint.\n"
                       "Opens and saves .pptx with its own engine.")
        d.set_logo_icon_name("folio-deliver")
        d.run()
        d.destroy()

    def act_tab(self, name):
        t = self.ribbon.tab_by_name(name)
        if t is not None:
            self.ribbon.select(t)

    # ------------------------------------------------------------ menus
    def context_menu(self, ev, shape):
        c = self.canvas
        items = []
        link = self.current_link() if (c.edit is not None or shape is not None) else None
        link_items = ([("Edit Link...", "insert-link"), ("Open Link", "open-link"), ("Copy Link", "copy-link"),
                       ("Remove Link", "remove-link")] if link else [("Link...", "insert-link")])
        if c.edit is not None:
            items = [("Cut", "cut"), ("Copy", "copy"), ("Paste", "paste"), None, ("Font...", "font-dialog"),
                     ("Paragraph...", "paragraph-dialog"), ("Bullets", "bullets"), ("Numbering", "numbering"), None] + link_items + \
                    [None, ("New Comment", "new-comment")]
        elif shape is not None:
            items = [("Cut", "cut"), ("Copy", "copy"), ("Paste", "paste"), None,
                     ("Group", "group"), ("Ungroup", "ungroup"), None,
                     ("Bring to Front", "order:front"), ("Send to Back", "order:back"), None,
                     ("Edit Alt Text...", "alt-text"), ("Size and Position...", "format-shape"),
                     ("Format Shape...", "format-shape"), None] + link_items + [("New Comment", "new-comment")]
            if shape["kind"] == "pic":
                items[3:3] = [("Crop", "crop")]
        else:
            items = [("Paste", "paste"), None, ("Layout", [(n, "set-layout:" + p) for _m, ls in self.deck.layouts() for p, n in ls]),
                     ("Reset Slide", "reset-slide"), None, ("Ruler", "toggle-ruler-menu"), ("Grid and Guides...", "toggle-grid-menu"),
                     None, ("Format Background...", "format-background"), ("New Comment", "new-comment")]
        self._popup(ev, items)

    def slide_menu(self, ev, i):
        items = [("Cut", "cut"), ("Copy", "copy"), ("Paste", "paste-slides"), None,
                 ("New Slide", "new-slide"), ("Duplicate Slide", "duplicate-slides"), ("Delete Slide", "delete-slides"), None,
                 ("Add Section", "add-section"), None,
                 ("Layout", [(n, "set-layout:" + p) for _m, ls in self.deck.layouts() for p, n in ls]),
                 ("Reset Slide", "reset-slide"), ("Format Background...", "format-background"), None,
                 ("Hide Slide" if i is None or not self.deck.is_hidden(i) else "Unhide Slide", "hide-slide")]
        self._popup(ev, items)

    def act_paste_slides(self):
        self.pane.area.grab_focus()
        self.act_paste()

    def act_toggle_ruler_menu(self):
        self.ruler_check.set_active(not self.ruler_check.get_active())

    def act_toggle_grid_menu(self):
        self.grid_check.set_active(not self.grid_check.get_active())

    def act_alt_text(self):
        if len(self.canvas.sel) != 1:
            return
        s = self.canvas.shape(self.canvas.sel[0])
        t = self.dialogs.ask_text("Alt Text", "How would you describe this object to someone who is blind?", s.get("descr", ""))
        if t is not None:
            self.deck.set_alt_text(self.current, s["id"], t)
            self.changed(slide=True)

    def _popup(self, ev, items):
        m = Gtk.Menu()

        def fill(menu, items):
            for it in items:
                if it is None:
                    menu.append(Gtk.SeparatorMenuItem())
                    continue
                label, cmd = it
                mi = Gtk.MenuItem(label=label)
                if isinstance(cmd, list):
                    sub = Gtk.Menu()
                    fill(sub, cmd)
                    mi.set_submenu(sub)
                else:
                    mi.connect("activate", lambda _m, c=cmd: GLib.idle_add(lambda: (self.run(c), False)[1]))
                menu.append(mi)
        fill(m, items)
        m.show_all()
        m.attach_to_widget(self, None)
        m.popup_at_pointer(ev)

    # ------------------------------------------------------------ search
    def on_search(self, entry):
        text = entry.get_text().strip().lower()
        entry.set_text("")
        if not text:
            return
        for c in self.ribbon.all_controls():
            lab = (getattr(c, "label_text", "") or "").lower()
            if text in lab and getattr(c, "action", None):
                c.press()
                return
        self.status.slide_label.set_text("No command matches “%s”." % text)

    # ------------------------------------------------------------ keys
    def on_key_release(self, w, ev):
        name = (Gdk.keyval_name(ev.keyval) or "").lower()
        if name in ("alt_l", "alt_r") and self._alt_alone and not self.keytips.active \
                and not self.backstage_open():
            self._alt_alone = False
            self.keytips.start()
            return True
        return False

    def on_key(self, w, ev):
        kv = ev.keyval
        state = ev.state & Gtk.accelerator_get_default_mod_mask()
        ctrl = bool(state & Gdk.ModifierType.CONTROL_MASK)
        shift = bool(state & Gdk.ModifierType.SHIFT_MASK)
        alt = bool(state & Gdk.ModifierType.MOD1_MASK)
        name = (Gdk.keyval_name(kv) or "")
        low = name.lower()
        self._alt_alone = low in ("alt_l", "alt_r")
        if self.keytips.active:
            return self.keytips.key(ev)
        if self.backstage_open():
            if kv == Gdk.KEY_Escape:
                self.backstage.close()
                return True
            return False
        focus = self.get_focus()
        in_entry = isinstance(focus, (Gtk.Entry, Gtk.TextView)) and focus is not self.canvas.area
        if kv == Gdk.KEY_F10 and not shift:
            self.keytips.start()
            return True
        if alt and low == "q":
            self.search.grab_focus()
            return True
        if alt and not ctrl and kv < 0x10000 and chr(kv).isalnum() and not in_entry:
            if self.keytips.start_with(chr(Gdk.keyval_to_upper(kv)).upper()):
                return True
        if kv == Gdk.KEY_F5 and not ctrl:
            if alt:
                self.start_show(self.current or 0, presenter=True)
            else:
                self.start_show(self.current or 0 if shift else 0)
            return True
        if kv == Gdk.KEY_F7 and shift and not ctrl:
            self.run("thesaurus")
            return True
        if kv == Gdk.KEY_F7 and not ctrl:
            self.run("spelling")
            return True
        if kv == Gdk.KEY_F12 and not ctrl:
            self.run("save-as")
            return True
        if ctrl and not alt:
            k = low
            cmds = {"n": "new", "o": "open", "s": "save", "p": "print", "w": "close", "z": "undo", "y": "redo",
                    "m": "new-slide", "f": "find", "h": "replace", "k": "insert-link", "q": None}
            if shift:
                cmds = {"s": "save-as", "z": "redo", "f": "font-dialog", "p": "font-dialog", "g": "ungroup",
                        "greater": "font-grow", "less": "font-shrink", "period": "font-grow", "comma": "font-shrink"}
            if k == "f4" or (k == "w" and not shift):
                self.run("close")
                return True
            if k in cmds and cmds[k]:
                if in_entry and k in ("z", "y"):
                    return False
                self.run(cmds[k])
                return True
            if in_entry:
                return False
            edit = self.canvas.edit is not None
            onpane = self.pane.area.has_focus() or self.view == "sorter"
            simple = {"b": "bold", "i": "italic", "u": "underline", "bracketright": "font-grow",
                      "bracketleft": "font-shrink", "space": "clear-formatting", "c": "copy", "x": "cut", "v": "paste",
                      "a": "select-all", "g": "group", "l": "align:l", "e": "align:ctr", "r": "align:r", "j": "align:just",
                      "t": "font-dialog"}
            if k == "d" and not shift:
                if onpane or not self.canvas.sel:
                    self.run("duplicate-slides")
                else:
                    new = self.deck.duplicate_shapes(self.current, self.canvas.sel, 12, 12)
                    self.changed(slide=True)
                    self.canvas.select(new)
                return True
            if k == "a" and onpane:
                return False
            if k == "return" or k == "kp_enter":
                self._next_placeholder()
                return True
            if k in ("equal", "plus") and edit:
                # Ctrl+= subscript, Ctrl+Shift+= superscript
                rp, _ = self.canvas.current_run()
                want = "30" if (shift or k == "plus") else "-25"
                cur = "%g" % (rp or {}).get("baseline", 0) if rp else "0"
                self.canvas.run_format("baseline", "0" if cur == want else want)
                return True
            if k in simple and (edit or k not in ("l", "e", "r", "j") or self.canvas.sel):
                if k in ("c", "x", "v") and onpane and not edit:
                    self.run({"c": "copy", "x": "cut", "v": "paste"}[k])
                    return True
                self.run(simple[k])
                return True
            if k in ("home", "end", "up", "down") and onpane:
                return False
        if in_entry:
            return False
        if self.view == "reading":
            if kv in (Gdk.KEY_Right, Gdk.KEY_Down, Gdk.KEY_space, Gdk.KEY_Page_Down):
                self.go_slide(self.current + 1)
                return True
            if kv in (Gdk.KEY_Left, Gdk.KEY_Up, Gdk.KEY_BackSpace, Gdk.KEY_Page_Up):
                self.go_slide(self.current - 1)
                return True
            if kv == Gdk.KEY_Escape:
                self.set_view("normal")
                return True
            return True
        if focus is self.canvas.area:
            if self.canvas.on_key(ev):
                return True
            if self.canvas.edit is None and not ctrl and not alt:
                if kv in (Gdk.KEY_Page_Down,):
                    self.go_slide((self.current or 0) + 1)
                    return True
                if kv in (Gdk.KEY_Page_Up,):
                    self.go_slide((self.current or 0) - 1)
                    return True
                if not self.canvas.sel and kv in (Gdk.KEY_Down, Gdk.KEY_Right):
                    self.go_slide((self.current or 0) + 1)
                    return True
                if not self.canvas.sel and kv in (Gdk.KEY_Up, Gdk.KEY_Left):
                    self.go_slide((self.current or 0) - 1)
                    return True
                if kv == Gdk.KEY_Home and not self.canvas.sel:
                    self.go_slide(0)
                    return True
                if kv == Gdk.KEY_End and not self.canvas.sel:
                    self.go_slide(self.deck.slide_count() - 1)
                    return True
        return False

    def _next_placeholder(self):
        """Ctrl+Enter: the next text placeholder, else a new slide."""
        c = self.canvas
        textish = [s for s in c.shapes if s["has_text"] and s["ph"] not in (None, "dt", "ftr", "sldNum")]
        cur = c.edit.id if c.edit else (c.sel[0] if c.sel else None)
        ids = [s["id"] for s in textish]
        if cur in ids and ids.index(cur) + 1 < len(ids):
            c.leave_text()
            c.start_text(ids[ids.index(cur) + 1], select_all=True)
        elif cur is None and ids:
            c.start_text(ids[0], select_all=True)
        else:
            c.leave_text()
            self.act_new_slide()
            c._surface()
            t = [s for s in c.shapes if s["ph"] in ("title", "ctrTitle")]
            if t:
                c.start_text(t[0]["id"], (0, 0))



def table_from_text(text):
    """Tab-separated rows (as spreadsheets put on the clipboard) as a grid, or None for ordinary text."""
    t = text.replace("\r\n", "\n").replace("\r", "\n").rstrip("\n")
    lines = t.split("\n")
    if "\t" not in t or len(lines) > 200:
        return None
    grid = [ln.split("\t") for ln in lines]
    cols = max(len(r) for r in grid)
    if cols < 2 or cols > 40 or (len(grid) == 1 and cols < 2):
        return None
    # a quoted cell with line breaks inside stays one cell
    return [[c[1:-1].replace('""', '"') if len(c) > 1 and c[0] == c[-1] == '"' else c for c in r] for r in grid]

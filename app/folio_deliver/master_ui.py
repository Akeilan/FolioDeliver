"""Slide Master, Notes Master and Handout Master views: the masters and layouts pane, the
master tabs and their commands. While a master view is open, the canvas edits a design part
(its index is Presentation.design_base() + k)."""
import cairo
from gi.repository import Gdk, GLib, Gtk

from .core import surface_from

HANDOUT_LAYOUTS = {1: (1, 1), 2: (1, 2), 3: (1, 3), 4: (2, 2), 6: (2, 3), 9: (3, 3)}


class DesignPane(Gtk.Box):
    """The Slide Master view's left pane: each master, its layouts indented below it."""
    W_MASTER, W_LAYOUT = 176, 140

    def __init__(self, win):
        Gtk.Box.__init__(self, orientation=Gtk.Orientation.VERTICAL)
        self.win = win
        self.get_style_context().add_class("folio-slidepane")
        self.area = Gtk.DrawingArea()
        self.area.set_can_focus(True)
        self.area.add_events(Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.KEY_PRESS_MASK)
        self.area.connect("draw", self.on_draw)
        self.area.connect("button-press-event", self.on_press)
        self.area.connect("key-press-event", self.on_key)
        sw = Gtk.ScrolledWindow()
        sw.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        sw.add(self.area)
        self.scroller = sw
        self.pack_start(sw, True, True, 0)
        self.cache = {}
        self.items = []
        self.set_size_request(230, -1)

    def forget(self, part=None):
        if part is None:
            self.cache.clear()
        else:
            self.cache.pop(part, None)

    def relayout(self):
        deck = self.win.deck
        self.items = [d for d in deck.design_parts() if d[2] in ("master", "layout")]
        sw, sh = deck.size()
        y = 10
        self.rects = []
        for k, part, kind, name, uses in self.items:
            w = self.W_MASTER if kind == "master" else self.W_LAYOUT
            h = w * sh / sw
            x = 30 if kind == "master" else 54
            self.rects.append((x, y, w, h))
            y += h + 12
        self.area.set_size_request(-1, int(y + 10))
        self.area.queue_draw()

    def thumb(self, k, part, w):
        c = self.cache.get(part)
        if c is not None and c[0] == w:
            return c[1]
        deck = self.win.deck
        sw, _sh = deck.size()
        pw, ph, stride, data = deck.render_part(part, w / sw)
        surf = surface_from(pw, ph, stride, data)
        self.cache[part] = (w, surf)
        return surf

    def on_draw(self, area, cr):
        cr.set_source_rgb(0.953, 0.953, 0.953)
        cr.paint()
        base = self.win.deck.design_base()
        cur = (self.win.current or 0) - base
        n_master = 0
        for (k, part, kind, name, uses), (x, y, w, h) in zip(self.items, self.rects):
            surf = self.thumb(k, part, w)
            cr.set_source_surface(surf, x, y)
            cr.paint()
            sel = k == cur
            cr.set_line_width(3 if sel else 1)
            if sel:
                cr.set_source_rgb(0.937, 0.51, 0.0)
            else:
                cr.set_source_rgb(0.75, 0.75, 0.75)
            cr.rectangle(x - 0.5, y - 0.5, w + 1, h + 1)
            cr.stroke()
            cr.set_source_rgb(0.3, 0.3, 0.3)
            cr.select_font_face("Sans")
            cr.set_font_size(10)
            if kind == "master":
                n_master += 1
                cr.move_to(8, y + 14)
                cr.show_text(str(n_master))
            else:
                # the connector from the master
                cr.set_source_rgb(0.65, 0.65, 0.65)
                cr.set_line_width(1)
                cr.move_to(40.5, y - 12)
                cr.line_to(40.5, y + h / 2)
                cr.line_to(x - 2, y + h / 2)
                cr.stroke()
                if uses:
                    # the layout is used: a hint like PowerPoint's tooltip
                    pass

    def index_at(self, x, y):
        for (k, *_r), (rx, ry, w, h) in zip(self.items, self.rects):
            if rx <= x <= rx + w and ry <= y <= ry + h:
                return k
        return None

    def on_press(self, area, ev):
        area.grab_focus()
        k = self.index_at(ev.x, ev.y)
        if k is not None:
            self.win.design_go(k)
        if ev.button == 3 and k is not None:
            self.win._popup(ev, [("Insert Slide Master", "master-insert"), ("Insert Layout", "master-insert-layout"),
                                 ("Duplicate Layout", "master-duplicate"), ("Delete Layout", "master-delete"),
                                 ("Rename Layout", "master-rename"), None, ("Preserve Master", "master-preserve"),
                                 None, ("Format Background...", "format-background")])
        return True

    def on_key(self, area, ev):
        name = Gdk.keyval_name(ev.keyval)
        base = self.win.deck.design_base()
        ks = [it[0] for it in self.items]
        cur = (self.win.current or 0) - base
        if cur in ks:
            j = ks.index(cur)
            if name in ("Up", "Left") and j > 0:
                self.win.design_go(ks[j - 1])
                return True
            if name in ("Down", "Right") and j + 1 < len(ks):
                self.win.design_go(ks[j + 1])
                return True
            if name == "Delete":
                self.win.run("master-delete")
                return True
        return False

    def ensure_visible(self, k):
        for (kk, *_r), (x, y, w, h) in zip(self.items, self.rects):
            if kk == k:
                adj = self.scroller.get_vadjustment()
                if y < adj.get_value() or y + h > adj.get_value() + adj.get_page_size():
                    adj.set_value(max(0, y - 20))


class MasterCommands:
    """Commands of the master views."""
    master_mode = None            # None | "slide" | "notes" | "handout"

    def design_index(self):
        return (self.current or 0) - self.deck.design_base()

    def design_part(self):
        if self.master_mode is None:
            return None
        ds = self.deck.design_parts()
        k = self.design_index()
        return ds[k][1] if 0 <= k < len(ds) else None

    def _enter_master(self, mode, k):
        self._save_notes()
        self.canvas.leave_text()
        self.canvas.finish_crop()
        if self.master_mode is None:
            self._master_return = (self.current, getattr(self, "view", "normal"))
            if getattr(self, "view", "normal") != "normal":
                self.set_view("normal")
        self.master_mode = mode
        np = self.normal_paned
        left = np.get_child1()
        if mode == "slide":
            if not hasattr(self, "design_pane"):
                self.design_pane = DesignPane(self)
            if left is not self.design_pane:
                np.remove(left)
                np.pack1(self.design_pane, False, False)
                self.design_pane.show_all()
            self.design_pane.forget()
            self.design_pane.relayout()
            left = self.design_pane
        else:
            left.hide()
        self.notes_box.hide()
        for tab in ("Slide Master", "Notes Master", "Handout Master"):
            self.ribbon.show_contextual(tab, False)
        tab = {"slide": "Slide Master", "notes": "Notes Master", "handout": "Handout Master"}[mode]
        self.ribbon.show_contextual(tab, True)
        self.ribbon.select(self.ribbon.tab_by_name(tab))
        self.design_go(k)
        self.status.set_mode_text(tab)

    def design_go(self, k):
        self.canvas.leave_text()
        self.canvas.sel = []
        self.current = self.deck.design_base() + k
        self.canvas.invalidate()
        self.canvas.set_zoom(fit=True)
        if hasattr(self, "design_pane") and self.master_mode == "slide":
            self.design_pane.area.queue_draw()
            self.design_pane.ensure_visible(k)
        self.sync_master_tab()
        self.selection_changed()

    def sync_master_tab(self):
        part = self.design_part()
        if part is None:
            return
        phs = self.deck.design_placeholders(part)
        self.ribbon.update("master-title", "true" if "title" in phs else "false")
        self.ribbon.update("master-footers", "true" if any(k in phs for k in ("dt", "ftr", "sldNum")) else "false")
        self.ribbon.update("master-hide-bg", "true" if not self.deck.shows_master_shapes(part) else "false")
        is_layout = "slideLayouts/" in part
        self.ribbon.update("master-layout-only", "enabled" if is_layout else "disabled")
        for k in ("hdr", "sldImg", "body", "ftr", "dt", "sldNum"):
            self.ribbon.update("nm-" + k, "true" if k in phs else "false")

    def act_view_slide_master(self):
        """Open Slide Master view at the current slide's layout."""
        ds = self.deck.design_parts()
        k = 0
        if self.master_mode is None and self.current is not None and self.current < self.deck.slide_count():
            lay = self.deck.slide_layout(self.current)
            for d in ds:
                if d[1] == lay:
                    k = d[0]
        self._enter_master("slide", k)

    def act_view_notes_master(self):
        part = self.deck.notes_master_part()
        k = [d[0] for d in self.deck.design_parts() if d[1] == part][0]
        self._enter_master("notes", k)

    def act_view_handout_master(self):
        part = self.deck.ensure_handout_master()
        k = [d[0] for d in self.deck.design_parts() if d[1] == part][0]
        self._enter_master("handout", k)

    def act_close_master(self):
        if self.master_mode is None:
            return
        self.canvas.leave_text()
        mode = self.master_mode
        self.master_mode = None
        np = self.normal_paned
        left = np.get_child1()
        if left is not self.pane:
            np.remove(left)
            np.pack1(self.pane, False, False)
        self.pane.show_all()
        self.notes_box.show()
        for tab in ("Slide Master", "Notes Master", "Handout Master"):
            self.ribbon.show_contextual(tab, False)
        self.ribbon.select(self.ribbon.tab_by_name("View"))
        cur, view = getattr(self, "_master_return", (0, "normal"))
        n = self.deck.slide_count()
        self.current = None
        self.thumbs.forget()
        self.status.set_mode_text(None)
        self.changed(structure=True, all_slides=True)
        if n:
            self.go_slide(min(cur or 0, n - 1))
        self.canvas.set_zoom(fit=True)
        if view not in ("normal", None):
            self.set_view(view)
        return mode

    def master_changed(self):
        """After an edit in a master view."""
        part = self.design_part()
        if hasattr(self, "design_pane"):
            if part is not None:
                self.design_pane.forget(part)
            if part and "slideMasters/" in part:
                self.design_pane.forget()
            self.design_pane.relayout()
        self.sync_master_tab()

    # ------------------------------------------------------------ Edit Master
    def _master_of_current(self):
        part = self.design_part()
        ds = self.deck.design_parts()
        k = self.design_index()
        while k >= 0 and ds[k][2] != "master":
            k -= 1
        return ds[k][1] if k >= 0 else part

    def act_master_insert(self):
        if self.master_mode is None:
            return
        m = self.deck.duplicate_design(self._master_of_current())
        self.master_changed()
        self.design_go([d[0] for d in self.deck.design_parts() if d[1] == m][0])

    def act_master_insert_layout(self):
        if self.master_mode is None:
            return
        part = self.design_part()
        after = part if part and "slideLayouts/" in part else None
        if after is None:
            ls = [d[1] for d in self.deck.design_parts() if d[2] == "layout"]
            mine = self.deck.layouts_of(self._master_of_current()) if hasattr(self.deck, "layouts_of") else []
            after = mine[-1] if mine else (ls[-1] if ls else None)
        new = self.deck.add_layout(self._master_of_current(), after, "Custom Layout")
        self.master_changed()
        self.design_go([d[0] for d in self.deck.design_parts() if d[1] == new][0])

    def act_master_duplicate(self):
        if self.master_mode is None:
            return
        part = self.design_part()
        if part is None:
            return
        new = self.deck.duplicate_design(part)
        self.master_changed()
        self.design_go([d[0] for d in self.deck.design_parts() if d[1] == new][0])

    def act_master_delete(self):
        if self.master_mode is None:
            return
        part = self.design_part()
        if part is None:
            return
        info = [d for d in self.deck.design_parts() if d[1] == part][0]
        if info[4]:
            self.dialogs.info("This %s is used by %d slide%s and can't be deleted." %
                              ("master" if info[2] == "master" else "layout", info[4], "" if info[4] == 1 else "s"))
            return
        try:
            self.deck.delete_design(part)
        except Exception as e:
            self.dialogs.info("This can't be deleted: %s." % e)
            return
        k = max(0, info[0] - 1)
        self.master_changed()
        self.design_go(min(k, len([d for d in self.deck.design_parts() if d[2] in ("master", "layout")]) - 1))

    def act_master_rename(self):
        if self.master_mode is None:
            return
        part = self.design_part()
        if part is None:
            return
        info = [d for d in self.deck.design_parts() if d[1] == part][0]
        t = self.dialogs.ask_text("Rename Layout" if info[2] == "layout" else "Rename Master", "Name:", info[3])
        if t:
            self.deck.rename_design(part, t)
            self.master_changed()

    def act_master_preserve(self):
        if self.master_mode is None:
            return
        m = self._master_of_current()
        self.deck.set_preserved(m, not self.deck.preserved(m))
        self.master_changed()

    # ------------------------------------------------------------ Master Layout
    def act_master_title(self):
        if self.master_mode is None:
            return
        part = self.design_part()
        on = self.master_check("master-title")
        if part and "slideLayouts/" in part:
            self.deck.design_toggle(part, "title", on)
            self.changed(slide=True)
            self.master_changed()

    def act_master_footers(self):
        if self.master_mode is None:
            return
        part = self.design_part()
        on = self.master_check("master-footers")
        if part and "slideLayouts/" in part:
            self.deck.design_toggle(part, "footers", on)
            self.changed(slide=True)
            self.master_changed()

    def master_check(self, key):
        for c in self.ribbon.controls:
            if c.state_key == key and isinstance(c, Gtk.CheckButton):
                return c.get_active()
        return True

    def act_master_hide_bg(self):
        if self.master_mode is None:
            return
        part = self.design_part()
        if part:
            self.deck.set_show_master_shapes(part, not self.master_check("master-hide-bg"))
            self.changed(slide=True)
            self.master_changed()

    def act_master_layout_dialog(self):
        """Master Layout: which placeholders the slide master has."""
        if self.master_mode is None:
            return
        part = self._master_of_current()
        phs = self.deck.design_placeholders(part)
        d = Gtk.Dialog(title="Master Layout", transient_for=self, modal=True)
        d.get_style_context().add_class("folio-dialog")
        d.add_button("Cancel", Gtk.ResponseType.CANCEL)
        d.add_button("OK", Gtk.ResponseType.OK)
        box = d.get_content_area()
        box.set_border_width(12)
        box.set_spacing(4)
        box.pack_start(Gtk.Label(label="Placeholders", xalign=0), False, False, 0)
        checks = {}
        for k, label in (("title", "Title"), ("body", "Text"), ("dt", "Date"), ("sldNum", "Slide number"), ("ftr", "Footer")):
            c = Gtk.CheckButton(label=label, active=k in phs)
            c.set_sensitive(k not in phs)          # PowerPoint only puts missing ones back
            checks[k] = c
            box.pack_start(c, False, False, 0)
        d.show_all()
        r = d.run()
        want = {k: c.get_active() for k, c in checks.items()}
        d.destroy()
        if r == Gtk.ResponseType.OK:
            self.apply_master_layout(want)

    def apply_master_layout(self, want):
        part = self._master_of_current()
        phs = self.deck.design_placeholders(part)
        for k, on in want.items():
            if on and k not in phs:
                self.deck.design_toggle(part, k, True)
        self.changed(slide=True)
        self.master_changed()

    def act_master_placeholder(self, kind):
        part = self.design_part()
        if not part or "slideLayouts/" not in part:
            self.dialogs.info("Placeholders are drawn on a layout. Pick a layout under the master first.")
            return
        self.canvas.insert_mode = ("placeholder", kind)
        win = self.canvas.area.get_window()
        if win is not None:
            win.set_cursor(Gdk.Cursor.new_from_name(win.get_display(), "crosshair"))

    def add_placeholder_at(self, kind, x, y, w, h):
        part = self.design_part()
        sid = self.deck.add_layout_placeholder(part, kind, x, y, w, h)
        self.changed(slide=True)
        self.master_changed()
        self.canvas.select([sid])
        return sid

    # ------------------------------------------------------------ notes and handout masters
    def act_nm_toggle(self, kind):
        if self.master_mode is None:
            return
        part = self.design_part()
        if part:
            on = self.master_check("nm-" + kind)
            self.deck.design_toggle(part, kind, on)
            self.changed(slide=True)
            self.sync_master_tab()

    def act_handout_per_page(self, n):
        if self.master_mode is None:
            return
        self.handout_per_page = int(n)
        self.canvas.queue()

    def draw_handout_frames(self, cr):
        """The handout master shows where the slides go."""
        if self.master_mode != "handout":
            return
        n = getattr(self, "handout_per_page", 6)
        cols, rows = HANDOUT_LAYOUTS.get(n, (2, 3))
        part = self.design_part()
        pw, ph = self.deck.page_size(part)
        sw, sh = self.deck.size()
        mx, top, bottom = 36.0, 54.0, 54.0
        cw, chh = (pw - 2 * mx) / cols, (ph - top - bottom) / rows
        k = min((cw - 18) / sw, (chh - 18) / sh)
        c = self.canvas
        cr.save()
        cr.set_source_rgb(0.45, 0.45, 0.45)
        cr.set_line_width(1)
        cr.set_dash([4, 3])
        for r in range(rows):
            for q in range(cols):
                x = mx + q * cw + (cw - sw * k) / 2
                y = top + r * chh + (chh - sh * k) / 2
                X, Y = c.to_px(x, y)
                cr.rectangle(X + 0.5, Y + 0.5, sw * k * c.scale, sh * k * c.scale)
        cr.stroke()
        cr.restore()

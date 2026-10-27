"""Commands for tables, Header & Footer, slide size, sections, transitions and themes (a mixin
of the window)."""
from gi.repository import Gdk, GLib, Gtk

from .core import Presentation

TRANSITIONS = [
    # (kind, label, effect options [(label, value)])
    ("none", "None", []),
    ("cut", "Cut", [("Smoothly", ""), ("Through Black", "thruBlk")]),
    ("fade", "Fade", [("Smoothly", ""), ("Through Black", "thruBlk")]),
    ("push", "Push", [("From Bottom", "u"), ("From Left", "r"), ("From Right", "l"), ("From Top", "d")]),
    ("wipe", "Wipe", [("From Right", "l"), ("From Top", "d"), ("From Left", "r"), ("From Bottom", "u")]),
    ("split", "Split", [("Vertical Out", "vert"), ("Horizontal Out", "horz")]),
    ("pull", "Reveal", [("From Right", "l"), ("From Left", "r"), ("From Top", "d"), ("From Bottom", "u")]),
    ("cover", "Cover", [("From Right", "l"), ("From Left", "r"), ("From Top", "d"), ("From Bottom", "u")]),
    ("randomBar", "Random Bars", [("Vertical", "vert"), ("Horizontal", "horz")]),
    ("circle", "Shape", []),
    ("dissolve", "Dissolve", []),
    ("zoom", "Zoom", []),
]

# theme colour sets (dk1 lt1 dk2 lt2 accent1-6 hlink folHlink) — the first two as Office has them
COLOR_SETS = [
    ("Office", [0x000000, 0xFFFFFF, 0x44546A, 0xE7E6E6, 0x4472C4, 0xED7D31, 0xA5A5A5, 0xFFC000, 0x5B9BD5, 0x70AD47, 0x0563C1, 0x954F72]),
    ("Office 2007 - 2010", [0x000000, 0xFFFFFF, 0x1F497D, 0xEEECE1, 0x4F81BD, 0xC0504D, 0x9BBB59, 0x8064A2, 0x4BACC6, 0xF79646, 0x0000FF, 0x800080]),
    ("Grayscale", [0x000000, 0xFFFFFF, 0x000000, 0xF8F8F8, 0xDDDDDD, 0xB2B2B2, 0x969696, 0x808080, 0x5F5F5F, 0x4D4D4D, 0x5F5F5F, 0x919191]),
    ("Volunteer", [0x000000, 0xFFFFFF, 0x4B4B4B, 0xF1F1F1, 0xFF8200, 0x58595B, 0x006C93, 0xFED535, 0x8D2048, 0x517C96, 0x0563C1, 0x954F72]),
    ("Harbor", [0x000000, 0xFFFFFF, 0x17406D, 0xDBEFF9, 0x0F6FC6, 0x009DD9, 0x0BD0D9, 0x10CF9B, 0x7CCA62, 0xA5C249, 0xF49100, 0x85DFD0]),
    ("Forest", [0x000000, 0xFFFFFF, 0x2C3C1F, 0xEBF0E1, 0x549E39, 0x8AB833, 0xC0CF3A, 0x029676, 0x4AB5C4, 0x0989B1, 0x6B9F25, 0xB26B02]),
    ("Plum", [0x000000, 0xFFFFFF, 0x452C40, 0xEFE7EE, 0x7E3E7A, 0xA35D9C, 0xD08EB3, 0x5B6CA6, 0x8B8EC7, 0xC4A35A, 0x5B6CA6, 0x8B8EC7]),
    ("Slate", [0x000000, 0xFFFFFF, 0x212745, 0xECEFF5, 0x4E67C8, 0x5ECCF3, 0xA7EA52, 0x5DCEAF, 0xFF8021, 0xF14124, 0x56C7AA, 0x59A8D1]),
    ("Ember", [0x000000, 0xFFFFFF, 0x4E3B30, 0xFBEEC9, 0xF0A22E, 0xA5644E, 0xB58B80, 0xC3986D, 0xA19574, 0xC17529, 0xAD1F1F, 0xFFC42F]),
]
FONT_SETS = [("Office", "Calibri Light", "Calibri"), ("Office 2007 - 2010", "Cambria", "Calibri"),
             ("Arial", "Arial", "Arial"), ("Times New Roman", "Times New Roman", "Times New Roman"),
             ("Georgia / Calibri", "Georgia", "Calibri"), ("Liberation Sans", "Liberation Sans", "Liberation Sans"),
             ("DejaVu", "DejaVu Serif", "DejaVu Sans")]
THEMES = [("Office Theme", "Office", "Office"), ("Volunteer", "Volunteer", "Arial"),
          ("Harbor", "Harbor", "Office"), ("Forest", "Forest", "Georgia / Calibri"),
          ("Plum", "Plum", "Office 2007 - 2010"), ("Slate", "Slate", "Liberation Sans"),
          ("Ember", "Ember", "Times New Roman"), ("Grayscale", "Grayscale", "Arial")]

SIZES = [("Widescreen (16:9)", 960.0, 540.0), ("Standard (4:3)", 720.0, 540.0), ("Letter Paper (8.5x11 in)", 720.0, 540.0),
         ("A4 Paper (210x297 mm)", 780.0, 540.0), ("On-screen Show (16:10)", 720.0, 450.0), ("Banner", 576.0, 72.0)]


class MoreCommands:
    # ------------------------------------------------------------ tables
    def _table_target(self):
        """The table being worked on: (table id, cell index or None)."""
        c = self.canvas
        if c.edit is not None and c.edit.cell is not None:
            return c.edit.base, c.edit.cell
        for sid in c.sel:
            s = c.shape(sid)
            if s and s["geom"] == "table":
                return sid, None
        return None, None

    def table_menu(self):
        """Insert > Table: a grid to pick rows and columns, then Insert Table..."""
        pop = Gtk.Popover()
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        box.set_border_width(6)
        title = Gtk.Label(label="Insert Table", xalign=0)
        box.pack_start(title, False, False, 0)
        area = Gtk.DrawingArea()
        area.set_size_request(10 * 18 + 2, 8 * 18 + 2)
        area.add_events(Gdk.EventMask.POINTER_MOTION_MASK | Gdk.EventMask.BUTTON_PRESS_MASK)
        st = {"r": 0, "c": 0}

        def draw(a, cr):
            for r in range(8):
                for c in range(10):
                    on = r < st["r"] and c < st["c"]
                    cr.set_source_rgb(1.0, 0.85, 0.7) if on else cr.set_source_rgb(1, 1, 1)
                    cr.rectangle(1 + c * 18, 1 + r * 18, 16, 16)
                    cr.fill_preserve()
                    cr.set_source_rgb(0.6, 0.6, 0.6) if not on else cr.set_source_rgb(1.0, 0.51, 0.0)
                    cr.set_line_width(1)
                    cr.stroke()

        def motion(a, ev):
            st["c"] = min(10, int(ev.x // 18) + 1)
            st["r"] = min(8, int(ev.y // 18) + 1)
            title.set_text("%dx%d Table" % (st["c"], st["r"]))
            a.queue_draw()

        def press(a, ev):
            pop.popdown()
            GLib.idle_add(lambda: (self.insert_table(st["r"], st["c"]), False)[1])
        area.connect("draw", draw)
        area.connect("motion-notify-event", motion)
        area.connect("button-press-event", press)
        box.pack_start(area, False, False, 0)
        b = Gtk.ModelButton(text="Insert Table...")
        b.connect("clicked", lambda *_: (pop.popdown(), self.run("insert-table-dialog")))
        box.pack_start(b, False, False, 0)
        box.show_all()
        pop.add(box)
        return pop

    def act_insert_table(self):
        self.act_insert_table_dialog()

    def act_insert_table_dialog(self):
        d = Gtk.Dialog(title="Insert Table", transient_for=self, modal=True)
        d.add_button("Cancel", Gtk.ResponseType.CANCEL)
        d.add_button("OK", Gtk.ResponseType.OK)
        d.set_default_response(Gtk.ResponseType.OK)
        g = Gtk.Grid(column_spacing=10, row_spacing=8, margin=12)
        cols = Gtk.SpinButton.new_with_range(1, 75, 1)
        cols.set_value(5)
        rows = Gtk.SpinButton.new_with_range(1, 75, 1)
        rows.set_value(2)
        g.attach(Gtk.Label(label="Number of columns:", xalign=0), 0, 0, 1, 1)
        g.attach(cols, 1, 0, 1, 1)
        g.attach(Gtk.Label(label="Number of rows:", xalign=0), 0, 1, 1, 1)
        g.attach(rows, 1, 1, 1, 1)
        d.get_content_area().add(g)
        d.show_all()
        if d.run() == Gtk.ResponseType.OK:
            self.insert_table(int(rows.get_value()), int(cols.get_value()))
        d.destroy()

    def insert_table(self, rows, cols):
        if rows < 1 or cols < 1 or self.current is None:
            return
        sw, sh = self.deck.size()
        target = None
        for s in self.canvas.shapes:
            if s["empty"] and s["ph"] in ("obj", "tbl", "body") and s["w"] > sw * 0.3:
                target = s
                break
        if target is not None and target["ph"] != "body" or (target is not None and target["empty"]):
            x, y, w = target["x"], target["y"], target["w"]
            self.deck.delete_shapes(self.current, [target["id"]])
        else:
            w = sw * 0.8
            x, y = sw * 0.1, sh * 0.25
        tid = self.deck.add_table(self.current, rows, cols, x, y, w)
        self.changed(slide=True)
        self.canvas.start_text(Presentation.cell_id(tid, 0), (0, 0))

    def act_table_insert(self, where):
        tid, cell = self._table_target()
        if tid is None:
            return
        rows, cols = self.deck.table_size(self.current, tid)
        r, c = (cell // cols, cell % cols) if cell is not None else (rows - 1, cols - 1)
        self.canvas.leave_text()
        if where == "above":
            self.deck.table_insert_row(self.current, tid, r)
        elif where == "below":
            self.deck.table_insert_row(self.current, tid, r + 1)
        elif where == "left":
            self.deck.table_insert_col(self.current, tid, c)
        else:
            self.deck.table_insert_col(self.current, tid, c + 1)
        self.changed(slide=True)
        self.canvas.select([tid])

    def act_table_delete(self, what):
        tid, cell = self._table_target()
        if tid is None:
            return
        rows, cols = self.deck.table_size(self.current, tid)
        r, c = (cell // cols, cell % cols) if cell is not None else (0, 0)
        self.canvas.leave_text()
        if what == "table":
            self.deck.delete_shapes(self.current, [tid])
        elif what == "rows":
            self.deck.table_delete_row(self.current, tid, r)
        else:
            self.deck.table_delete_col(self.current, tid, c)
        self.changed(slide=True)

    def act_table_option(self, key):
        tid, _cell = self._table_target()
        if tid is None:
            return
        on = not self.deck.table_option_value(self.current, tid, key)
        self.deck.table_option(self.current, tid, key, on)
        self.changed(slide=True)

    def act_table_shading(self, v):
        tid, cell = self._table_target()
        if tid is None:
            return

        def apply(v):
            cells = [cell] if cell is not None else [c[0] for c in self.deck.table_cells(self.current, tid)]
            self.deck.table_shade(self.current, tid, cells, "none" if v == "none" else v)
            self.changed(slide=True)
        self._color_cmd("shape-fill", v, apply)

    def act_select_table(self):
        tid, _ = self._table_target()
        if tid is not None:
            self.canvas.leave_text()
            self.canvas.select([tid])

    # ------------------------------------------------------------ header and footer
    def act_header_footer(self):
        n = self.deck.slide_count()
        if not n:
            return
        has, fixed, num, ftr, ftext = self.deck.header_footer(self.current)
        d = Gtk.Dialog(title="Header and Footer", transient_for=self, modal=True)
        d.add_button("Cancel", Gtk.ResponseType.CANCEL)
        d.add_button("Apply to All", 2)
        d.add_button("Apply", Gtk.ResponseType.OK)
        box = d.get_content_area()
        box.set_border_width(12)
        box.set_spacing(6)
        box.pack_start(Gtk.Label(label="Include on slide", xalign=0), False, False, 0)
        date = Gtk.CheckButton(label="Date and time")
        date.set_active(has)
        auto = Gtk.RadioButton.new_with_label(None, "Update automatically")
        fix = Gtk.RadioButton.new_with_label_from_widget(auto, "Fixed")
        fixed_e = Gtk.Entry()
        import datetime
        fixed_e.set_text(fixed or datetime.date.today().strftime("%-m/%-d/%Y"))
        (fix if fixed else auto).set_active(True)
        num_c = Gtk.CheckButton(label="Slide number")
        num_c.set_active(num)
        ftr_c = Gtk.CheckButton(label="Footer")
        ftr_c.set_active(ftr)
        ftr_e = Gtk.Entry()
        ftr_e.set_text(ftext)
        skip = Gtk.CheckButton(label="Don't show on title slide")
        skip.set_active(True)
        for w, indent in ((date, 0), (auto, 24), (fix, 24), (fixed_e, 44), (num_c, 0), (ftr_c, 0), (ftr_e, 24), (skip, 0)):
            w.set_margin_start(indent)
            box.pack_start(w, False, False, 0)
        d.show_all()
        r = d.run()
        if r in (Gtk.ResponseType.OK, 2):
            idx = list(range(n)) if r == 2 else self._selected_slides()
            dv = None if not date.get_active() else ("" if auto.get_active() else fixed_e.get_text())
            fv = ftr_e.get_text() if ftr_c.get_active() else None
            self.deck.set_header_footer(idx, dv, num_c.get_active(), fv, skip.get_active())
            for i in idx:
                self.thumbs.forget(self.deck.slide_parts()[i])
            self.changed(slide=True)
        d.destroy()

    # ------------------------------------------------------------ slide size
    def act_slide_size(self, v):
        if v == "custom":
            return self._custom_size()
        w, h = (960.0, 540.0) if v == "16:9" else (720.0, 540.0)
        self._resize(w, h)

    def _resize(self, w, h):
        cw, ch = self.deck.size()
        if abs(cw - w) < 0.01 and abs(ch - h) < 0.01:
            return
        mode = "fit"
        if w * ch < h * cw or w < cw or h < ch:
            # smaller: PowerPoint asks how to scale the content
            d = Gtk.MessageDialog(transient_for=self, modal=True, message_type=Gtk.MessageType.QUESTION,
                                  text="You are scaling to a new slide size. Do you want to maximize the size of your "
                                       "content, or scale it down to make sure it will fit on the new slide?")
            d.add_button("Maximize", 1)
            d.add_button("Ensure Fit", 2)
            d.add_button("Cancel", 3)
            r = d.run()
            d.destroy()
            if r not in (1, 2):
                return
            mode = "max" if r == 1 else "fit"
        self.deck.set_slide_size(w, h, mode)
        self.thumbs.forget()
        self.changed(all_slides=True)

    def _custom_size(self):
        d = Gtk.Dialog(title="Slide Size", transient_for=self, modal=True)
        d.add_button("Cancel", Gtk.ResponseType.CANCEL)
        d.add_button("OK", Gtk.ResponseType.OK)
        g = Gtk.Grid(column_spacing=10, row_spacing=8, margin=12)
        combo = Gtk.ComboBoxText()
        for name, _w, _h in SIZES:
            combo.append_text(name)
        combo.append_text("Custom")
        cw, ch = self.deck.size()
        wsp = Gtk.SpinButton.new_with_range(1, 56, 0.01)
        wsp.set_digits(2)
        wsp.set_value(cw / 72)
        hsp = Gtk.SpinButton.new_with_range(1, 56, 0.01)
        hsp.set_digits(2)
        hsp.set_value(ch / 72)
        k = next((i for i, (_n, w, h) in enumerate(SIZES) if abs(w - cw) < 0.5 and abs(h - ch) < 0.5), len(SIZES))
        combo.set_active(k)

        def chosen(c):
            i = c.get_active()
            if i < len(SIZES):
                wsp.set_value(SIZES[i][1] / 72)
                hsp.set_value(SIZES[i][2] / 72)
        combo.connect("changed", chosen)
        g.attach(Gtk.Label(label="Slides sized for:", xalign=0), 0, 0, 1, 1)
        g.attach(combo, 1, 0, 1, 1)
        g.attach(Gtk.Label(label="Width (in):", xalign=0), 0, 1, 1, 1)
        g.attach(wsp, 1, 1, 1, 1)
        g.attach(Gtk.Label(label="Height (in):", xalign=0), 0, 2, 1, 1)
        g.attach(hsp, 1, 2, 1, 1)
        d.get_content_area().add(g)
        d.show_all()
        r = d.run()
        w, h = wsp.get_value() * 72, hsp.get_value() * 72
        d.destroy()
        if r == Gtk.ResponseType.OK:
            self._resize(w, h)

    # ------------------------------------------------------------ sections
    def sections(self):
        """slide index -> section name, for the slides that start a section."""
        try:
            return {first: name for name, first, _n in self.deck.sections()}
        except Exception:
            return {}

    def _section_of(self, i):
        secs = self.deck.sections()
        for k, (name, first, n) in enumerate(secs):
            if first <= i < first + max(n, 1) or (n == 0 and first == i):
                return k, secs
        return None, secs

    def act_add_section(self):
        i = self.current or 0
        name = self.dialogs.ask_text("Rename Section", "Section name:", "Untitled Section")
        if not name:
            return
        secs = [(n, f) for n, f, _c in self.deck.sections()]
        if not secs and i > 0:
            secs = [("Default Section", 0)]
        secs = [s for s in secs if s[1] != i] + [(name, i)]
        secs.sort(key=lambda s: s[1])
        self.deck.write_sections(secs, "Add Section")
        self.changed(structure=True)

    def act_rename_section(self):
        k, secs = self._section_of(self.current or 0)
        if k is None:
            return
        name = self.dialogs.ask_text("Rename Section", "Section name:", secs[k][0])
        if name:
            out = [(n, f) for n, f, _c in secs]
            out[k] = (name, out[k][1])
            self.deck.write_sections(out, "Rename Section")
            self.changed(structure=True)

    def act_remove_section(self):
        k, secs = self._section_of(self.current or 0)
        if k is None:
            return
        out = [(n, f) for j, (n, f, _c) in enumerate(secs) if j != k]
        if out:
            out[0] = (out[0][0], 0)
        self.deck.write_sections(out, "Remove Section")
        self.changed(structure=True)

    def act_remove_all_sections(self):
        self.deck.write_sections([], "Remove All Sections")
        self.changed(structure=True)

    def act_collapse_sections(self):
        self.not_available("not-available:Collapsing sections")

    act_expand_sections = act_collapse_sections

    # ------------------------------------------------------------ transitions
    def act_transition(self, kind):
        opts = dict(TRANSITIONS_BY_KIND).get(kind, [])
        cur = self.deck.transition(self.current)
        opt = opts[0][1] if opts else ""
        dur = cur[2] if cur[0] != "none" and cur[2] else 0.75 if kind != "cut" else 0.0
        self.deck.set_transition(self._selected_slides(), kind, opt, dur or 0.75, cur[3], cur[4])
        self.changed(structure=True)
        self._sync_transition()
        if kind not in ("none",):
            self.preview_transition()

    def act_transition_option(self, opt):
        cur = self.deck.transition(self.current)
        self.deck.set_transition(self._selected_slides(), cur[0], opt, cur[2] or 0.75, cur[3], cur[4])
        self.changed(slide=True)
        self.preview_transition()

    def transition_options_menu(self):
        kind = self.deck.transition(self.current)[0] if self.deck.slide_count() else "none"
        opts = dict(TRANSITIONS_BY_KIND).get(kind, [])
        if not opts:
            return [("#", "No effect options for this transition")]
        return [(label, "transition-option:" + v) for label, v in opts]

    def act_transition_duration(self, v):
        cur = self.deck.transition(self.current)
        self.deck.set_transition(self._selected_slides(), cur[0], cur[1], float(v), cur[3], cur[4])
        self.changed(slide=True)

    def act_transition_click(self):
        cur = self.deck.transition(self.current)
        self.deck.set_transition(self._selected_slides(), cur[0], cur[1], cur[2] or 0.75, not cur[3], cur[4])
        self.changed(slide=True)

    def act_transition_after(self, v=None):
        cur = self.deck.transition(self.current)
        if v is None:
            after = -1.0 if cur[4] >= 0 else 0.0
        else:
            after = float(v)
        self.deck.set_transition(self._selected_slides(), cur[0], cur[1], cur[2] or 0.75, cur[3], after)
        self.changed(slide=True)

    def act_transition_apply_all(self):
        cur = self.deck.transition(self.current)
        self.deck.set_transition(list(range(self.deck.slide_count())), cur[0], cur[1], cur[2] or 0.75, cur[3], cur[4])
        self.changed(structure=True)

    def act_transition_preview(self):
        self.preview_transition()

    def preview_transition(self):
        """Play the current slide's transition in the slide area."""
        from . import show
        i = self.current
        if i is None:
            return
        kind, opt, dur, _c, _a = self.deck.transition(i)
        if kind in ("none",):
            return
        prev = i - 1 if i > 0 else None
        show.preview_in(self, prev, i, kind, opt, dur)

    def _sync_transition(self):
        if not self.deck.slide_count() or self.current is None:
            return
        kind, opt, dur, click, after = self.deck.transition(self.current)
        for k, _l, _o in TRANSITIONS:
            self.ribbon.update("tr-" + k, "true" if k == kind else "false")
        dsp = getattr(self, "duration_spin", None)
        if dsp is not None:
            dsp.quiet = True
            dsp.set_value(dur if kind != "none" else 0.0)
            dsp.quiet = False
        if getattr(self, "click_check", None) is not None:
            self.click_check.set_checked(click)
        if getattr(self, "after_check", None) is not None:
            self.after_check.set_checked(after >= 0)
        asp = getattr(self, "after_spin", None)
        if asp is not None:
            asp.quiet = True
            asp.set_value(max(0.0, after))
            asp.quiet = False

    # ------------------------------------------------------------ themes
    def act_theme(self, name):
        for tname, cset, fset in THEMES:
            if tname == name:
                cols = dict(COLOR_SETS)[cset]
                f = next(x for x in FONT_SETS if x[0] == fset)
                self.deck.set_theme(tname, cols, f[1], f[2])
                self.thumbs.forget()
                self.changed(all_slides=True)
                return

    def act_theme_colors(self, name):
        cols = dict(COLOR_SETS).get(name)
        if cols:
            self.deck.set_theme(name, cols, None, None)
            self.thumbs.forget()
            self.changed(all_slides=True)
            from .ribbon_defs import set_active_theme
            set_active_theme([cols[1], cols[0], cols[3], cols[2]] + cols[4:])

    def act_theme_fonts(self, name):
        f = next((x for x in FONT_SETS if x[0] == name), None)
        if f:
            self.deck.set_theme(None, None, f[1], f[2])
            self.thumbs.forget()
            self.changed(all_slides=True)

    def sync_theme_palette(self):
        """The colour pickers show the presentation's theme."""
        try:
            cols, _ma, _mi = self.deck.theme_info()
        except Exception:
            return
        c = dict(cols)
        if not c:
            return
        from .ribbon_defs import set_active_theme
        set_active_theme([c["lt1"], c["dk1"], c["lt2"], c["dk2"]] + [c["accent%d" % k] for k in range(1, 7)] + [c["hlink"], c["folHlink"]])


TRANSITIONS_BY_KIND = [(k, o) for k, _l, o in TRANSITIONS]

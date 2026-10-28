"""SmartArt on slides: Insert SmartArt, Convert to SmartArt, the text pane and the SmartArt
Design tab."""
from gi.repository import GLib, Gtk, Pango

from . import smartart as SA


def draw_preview(cr, k, W, H):
    """A small picture of a layout."""
    m = SA.default_model(k)
    m["items"] = [(lvl, "") for lvl, _t in m["items"]]
    shapes = SA.layout(m, W - 8, H - 8)
    cols = [(0.27, 0.45, 0.77), (0.93, 0.49, 0.19), (0.65, 0.65, 0.65), (1.0, 0.75, 0.0), (0.36, 0.61, 0.84), (0.44, 0.68, 0.28)]
    cr.set_source_rgb(1, 1, 1)
    cr.paint()
    cr.translate(4, 4)
    import math
    for s in shapes:
        x, y, w, h = s["x"], s["y"], s["w"], s["h"]
        cr.save()
        if s.get("rot"):
            cr.translate(x + w / 2, y + h / 2)
            cr.rotate(math.radians(s["rot"]))
            cr.translate(-(x + w / 2), -(y + h / 2))
        c = (0.27, 0.45, 0.77)
        if s.get("kind") == "line":
            cr.set_source_rgb(0.3, 0.4, 0.6)
            cr.set_line_width(1)
            if s.get("flip"):
                cr.move_to(x + w, y)
                cr.line_to(x, y + h)
            else:
                cr.move_to(x, y)
                cr.line_to(x + w, y + h)
            cr.stroke()
            cr.restore()
            continue
        if s["prst"] == "ellipse":
            cr.save()
            cr.translate(x + w / 2, y + h / 2)
            cr.scale(max(w, 0.1) / 2, max(h, 0.1) / 2)
            cr.arc(0, 0, 1, 0, 2 * math.pi)
            cr.restore()
        elif s["prst"] in ("triangle", "trapezoid"):
            inset = w / 2 if s["prst"] == "triangle" else min(w / 2, (w - w * 0.0) * 0.0 + h * 0.5)
            if s["prst"] == "trapezoid":
                inset = w / (2 * (s["k"] + 1)) if s["k"] else w / 2
            cr.move_to(x + inset, y)
            cr.line_to(x + w - inset, y)
            cr.line_to(x + w, y + h)
            cr.line_to(x, y + h)
            cr.close_path()
            if s["prst"] == "triangle":
                cr.new_path()
                cr.move_to(x + w / 2, y)
                cr.line_to(x + w, y + h)
                cr.line_to(x, y + h)
                cr.close_path()
        elif s["prst"] == "rightArrow":
            cr.move_to(x, y + h * 0.25)
            cr.line_to(x + w * 0.6, y + h * 0.25)
            cr.line_to(x + w * 0.6, y)
            cr.line_to(x + w, y + h / 2)
            cr.line_to(x + w * 0.6, y + h)
            cr.line_to(x + w * 0.6, y + h * 0.75)
            cr.line_to(x, y + h * 0.75)
            cr.close_path()
            c = (0.65, 0.73, 0.88)
        else:
            cr.rectangle(x, y, w, h)
        if s.get("kind") == "sub":
            c = (0.82, 0.86, 0.94)
        if SA.LAYOUTS[k][3] == "venn":
            cr.set_source_rgba(*c, 0.55)
        else:
            cr.set_source_rgb(*c)
        cr.fill_preserve()
        cr.set_source_rgb(1, 1, 1)
        cr.set_line_width(1)
        cr.stroke()
        cr.restore()


def gallery_dialog(win, current=0, title="Choose a SmartArt Graphic"):
    d = Gtk.Dialog(title=title, transient_for=win, modal=True)
    d.get_style_context().add_class("folio-dialog")
    d.set_default_size(720, 440)
    d.add_button("Cancel", Gtk.ResponseType.CANCEL)
    ok = d.add_button("OK", Gtk.ResponseType.OK)
    ok.get_style_context().add_class("suggested-action")
    state = {"k": current}
    box = Gtk.Box(spacing=8, margin=8)
    cats = Gtk.ListBox()
    cats.set_size_request(150, -1)
    flow = Gtk.FlowBox()
    flow.set_selection_mode(Gtk.SelectionMode.NONE)
    flow.set_max_children_per_line(4)
    sw = Gtk.ScrolledWindow()
    sw.add(flow)
    right = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
    big = Gtk.DrawingArea()
    big.set_size_request(220, 160)
    big.connect("draw", lambda a, cr: draw_preview(cr, state["k"], a.get_allocated_width(), a.get_allocated_height()))
    name = Gtk.Label(xalign=0)
    right.pack_start(big, False, False, 0)
    right.pack_start(name, False, False, 0)

    def choose(k):
        state["k"] = k
        name.set_markup("<b>%s</b>" % GLib.markup_escape_text(SA.LAYOUTS[k][0]))
        big.queue_draw()

    def show(cat):
        for c in flow.get_children():
            flow.remove(c)
        for k, (label, c, _i, _a) in enumerate(SA.LAYOUTS):
            if cat is not None and c != cat:
                continue
            b = Gtk.Button()
            b.set_tooltip_text(label)
            a = Gtk.DrawingArea()
            a.set_size_request(96, 72)
            a.connect("draw", lambda ar, cr, k=k: draw_preview(cr, k, ar.get_allocated_width(), ar.get_allocated_height()))
            b.add(a)
            b.connect("clicked", lambda _b, k=k: choose(k))
            flow.add(b)
        flow.show_all()
    for label, _c in SA.CATEGORIES:
        cats.add(Gtk.Label(label=label, xalign=0, margin=4))
    cats.connect("row-selected", lambda lb, row: row is not None and show(SA.CATEGORIES[row.get_index()][1]))
    box.pack_start(cats, False, False, 0)
    box.pack_start(sw, True, True, 0)
    box.pack_start(right, False, False, 0)
    d.get_content_area().add(box)
    d.show_all()
    cats.select_row(cats.get_row_at_index(0))
    choose(current)
    r = d.run()
    k = state["k"]
    d.destroy()
    return k if r == Gtk.ResponseType.OK else None


class TextPane(Gtk.Window):
    """'Type your text here': a line per item; Tab and Shift+Tab change its level."""
    def __init__(self, win, sid):
        Gtk.Window.__init__(self, title="Type your text here", transient_for=win)
        self.win = win
        self.sid = sid
        self.set_default_size(300, 320)
        self.get_style_context().add_class("folio-pane")
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin=8)
        self.view = Gtk.TextView()
        self.view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self.view.get_style_context().add_class("folio-outline")
        tabs = Pango.TabArray.new(6, True)
        for k in range(6):
            tabs.set_tab(k, Pango.TabAlign.LEFT, 22 * (k + 1))
        self.view.set_tabs(tabs)
        self.view.connect("key-press-event", self.on_key)
        sw = Gtk.ScrolledWindow()
        sw.add(self.view)
        box.pack_start(sw, True, True, 0)
        hint = Gtk.Label(label="Tab and Shift+Tab move an item down or up a level.", xalign=0, wrap=True)
        hint.get_style_context().add_class("dim-label")
        box.pack_start(hint, False, False, 0)
        self.add(box)
        self._timer = None
        self._quiet = True
        model = win.smartart_model(sid)
        self.view.get_buffer().set_text("\n".join("\t" * lvl + t for lvl, t in model["items"]))
        self.view.get_buffer().connect("changed", self._changed)
        self._quiet = False
        self.connect("destroy", lambda *_: (self.flush(), setattr(win, "smartart_pane", None)))
        self.show_all()

    def items(self):
        b = self.view.get_buffer()
        t = b.get_text(b.get_start_iter(), b.get_end_iter(), False)
        out = []
        for line in t.split("\n"):
            lvl = len(line) - len(line.lstrip("\t"))
            out.append((lvl, line.lstrip("\t")))
        # a first item can't be indented
        if out and out[0][0]:
            out[0] = (0, out[0][1])
        return out or [(0, "")]

    def _changed(self, *_):
        if self._quiet:
            return
        if self._timer:
            GLib.source_remove(self._timer)
        self._timer = GLib.timeout_add(500, self.flush)

    def flush(self):
        if self._timer:
            GLib.source_remove(self._timer)
            self._timer = None
        try:
            self.win.set_smartart_items(self.sid, self.items())
        except Exception:
            pass
        return False

    def on_key(self, view, ev):
        from gi.repository import Gdk
        name = Gdk.keyval_name(ev.keyval)
        if name not in ("Tab", "ISO_Left_Tab"):
            return False
        b = view.get_buffer()
        it = b.get_iter_at_mark(b.get_insert())
        start = b.get_iter_at_line(it.get_line())
        if name == "ISO_Left_Tab" or ev.state & Gdk.ModifierType.SHIFT_MASK:
            if start.get_char() == "\t":
                e = start.copy()
                e.forward_char()
                b.delete(start, e)
        else:
            b.insert(start, "\t")
        return True


class SmartArtCommands:
    def _box_for_new(self):
        for s in self.canvas.shapes:
            if s["empty"] and s["ph"] in ("obj",):
                self.deck.delete_shapes(self.current, [s["id"]])
                return (s["x"], s["y"], s["w"], s["h"])
        sw, sh = self.deck.size()
        return (sw * 0.15, sh * 0.2, sw * 0.7, sh * 0.65)

    def insert_smartart(self, k, items=None, box=None):
        m = SA.default_model(k)
        if items:
            m["items"] = list(items)
        x, y, w, h = box or self._box_for_new()
        p = SA.parts(m, w, h)
        sid = self.deck.insert_diagram(self.current, p["data"], p["layout"], p["style"], p["colors"], p["drawing"], x, y, w, h)
        self.changed(slide=True)
        self.canvas.select([sid])
        return sid

    def act_insert_smartart(self, k=None):
        if self.current is None:
            return None
        if k in (None, ""):
            k = gallery_dialog(self)
            if k is None:
                return None
        sid = self.insert_smartart(int(k))
        self.smartart_pane = TextPane(self, sid)
        return sid

    def _selected_smartart(self):
        c = self.canvas
        if len(c.sel) == 1:
            s = c.shape(c.sel[0])
            if s is not None and s["geom"] == "smartart":
                return s
        return None

    def smartart_model(self, sid):
        parts = self.deck.diagram_parts(self.current, sid)
        if not parts:
            return SA.default_model(0)
        return SA.read_data(self.deck.part_xml(parts[0]) or "")

    def write_smartart(self, sid, m):
        s = [x for x in self.deck.shapes(self.current) if x["id"] == sid]
        if not s:
            return
        s = s[0]
        p = SA.parts(m, s["w"], s["h"])
        self.deck.set_diagram(self.current, sid, p["data"], p["layout"], p["style"], p["colors"], p["drawing"])
        self.changed(slide=True)

    def set_smartart_items(self, sid, items):
        m = self.smartart_model(sid)
        if m["items"] != items:
            m["items"] = items
            self.write_smartart(sid, m)

    def act_smartart(self, spec):
        """smartart:<what>:<arg> on the selected SmartArt: layout, colors, style, add, pane, reset."""
        s = self._selected_smartart()
        if s is None:
            self.dialogs.info("Select a SmartArt graphic first.")
            return None
        what, _, arg = spec.partition(":")
        m = self.smartart_model(s["id"])
        if what == "pane":
            p = getattr(self, "smartart_pane", None)
            if p is not None:
                p.destroy()
            self.smartart_pane = TextPane(self, s["id"])
            return self.smartart_pane
        if what == "layout":
            m["layout"] = int(arg)
        elif what == "colors":
            m["colors"] = int(arg)
        elif what == "style":
            m["style"] = int(arg)
        elif what == "add":
            lvl = m["items"][-1][0] if m["items"] else 0
            m["items"].append((0 if arg != "below" else lvl + 1, ""))
        elif what == "reset":
            m["colors"], m["style"] = 1, 0
        else:
            return None
        self.write_smartart(s["id"], m)
        self.canvas.select([s["id"]])
        return m

    def act_convert_smartart(self, k=None):
        """Convert the text placeholder's bullets to SmartArt."""
        c = self.canvas
        sid = c.edit.base if c.edit is not None else (c.sel[0] if len(c.sel) == 1 else None)
        s = c.shape(sid) if sid is not None else None
        if s is None or not s["has_text"]:
            self.dialogs.info("Select the text you want to convert first.")
            return None
        paras = self.deck.paragraphs(self.current, sid)
        levels = [self.deck.para_props(self.current, sid, k2).get("lvl", 0) for k2 in range(len(paras))]
        items = SA.items_from_paragraphs(paras, levels)
        if not items:
            self.dialogs.info("There's no text to convert.")
            return None
        if k in (None, ""):
            k = 0
        c.leave_text()
        box = (s["x"], s["y"], s["w"], s["h"])
        self.deck.delete_shapes(self.current, [sid])
        return self.insert_smartart(int(k), items, box)


def smartart_tab(win, r, B, Tab):
    t = r.building(Tab("SmartArt Design", "JS", contextual=True))
    B.group(t, "Create Graphic", [B.big("Add Shape", "insertslide", None, "A",
                                        menu=[("Add Shape After", "smartart:add:after"), ("Add Shape Below", "smartart:add:below")]),
                                  B.big("Text Pane", "outlinemode", "smartart:pane", "T")])
    B.group(t, "Layouts", [B.big("Change Layout", "r-smartart", None, "L",
                                 menu=[(label, "smartart:layout:%d" % k) for k, (label, *_r) in enumerate(SA.LAYOUTS)])])
    B.group(t, "SmartArt Styles", [B.big("Change Colors", "diagramarea", None, "C",
                                         menu=[(n, "smartart:colors:%d" % k) for k, (n, *_r) in enumerate(SA.COLORS)]),
                                   B.big("Styles", "autoformat", None, "S",
                                         menu=[(n, "smartart:style:%d" % k) for k, (n, _i) in enumerate(SA.STYLES)])])
    B.group(t, "Reset", [B.big("Reset Graphic", "resetattributes", "smartart:reset", "R")])
    r.add_tab(t)

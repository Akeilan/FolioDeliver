"""Equations: Insert > Equation and editing one (a double-click). An equation is kept as
math (OMML) with a picture of it for programs that don't show math."""
import cairo
from gi.repository import GLib, Gtk

from .eqn import galleries, model as M, omml, render as R

PX = 4.0         # the picture is drawn at 4 pixels per point


def picture(seq, size_pt=28.0):
    """(PNG bytes, width pt, height pt) of an equation."""
    box = R.layout(seq, size_pt * PX, display=True)
    pad = 2 * PX
    w = int(box.w + 2 * pad) + 1
    h = int(box.asc + box.desc + 2 * pad) + 1
    s = cairo.ImageSurface(cairo.FORMAT_ARGB32, max(w, 8), max(h, 8))
    cr = cairo.Context(s)
    cr.set_source_rgb(0, 0, 0)
    box.place(pad, pad + box.asc)
    box.draw(cr)
    from .media_ui import png_bytes
    return png_bytes(s), w / PX, h / PX


def linear_of(xml):
    try:
        return M.to_linear(M.slot(omml.from_omml(xml)))
    except Exception:
        return ""


def equation_dialog(win, text=""):
    """Type an equation (linear format, as on the Equation tab) or pick one; returns the text."""
    d = Gtk.Dialog(title="Equation", transient_for=win, modal=True)
    d.get_style_context().add_class("folio-dialog")
    d.set_default_size(620, 380)
    d.add_button("Cancel", Gtk.ResponseType.CANCEL)
    ok = d.add_button("Insert" if not text else "OK", Gtk.ResponseType.OK)
    ok.get_style_context().add_class("suggested-action")
    box = d.get_content_area()
    box.set_spacing(8)
    box.set_border_width(10)
    row = Gtk.Box(spacing=6)
    latex = Gtk.CheckButton(label="LaTeX")
    entry = Gtk.Entry(text=text)
    entry.set_placeholder_text("Type an equation, e.g. x=(-b±√(b^2-4ac))/2a")
    entry.set_activates_default(True)
    d.set_default_response(Gtk.ResponseType.OK)
    row.pack_start(entry, True, True, 0)
    row.pack_start(latex, False, False, 0)
    box.pack_start(row, False, False, 0)
    prev = Gtk.DrawingArea()
    prev.set_size_request(-1, 140)

    def seq():
        t = entry.get_text()
        try:
            return M.from_latex(t) if latex.get_active() else M.from_linear(t)
        except Exception:
            return None

    def draw(a, cr):
        cr.set_source_rgb(1, 1, 1)
        cr.paint()
        s = seq()
        if s is None or not entry.get_text().strip():
            return
        b = R.layout(s, 32, display=True)
        W, H = a.get_allocated_width(), a.get_allocated_height()
        cr.set_source_rgb(0, 0, 0)
        b.place(max(8, (W - b.w) / 2), (H - b.asc - b.desc) / 2 + b.asc)
        b.draw(cr)
    prev.connect("draw", draw)
    entry.connect("changed", lambda *_: prev.queue_draw())
    latex.connect("toggled", lambda *_: prev.queue_draw())
    frame = Gtk.Frame()
    frame.add(prev)
    box.pack_start(frame, False, False, 0)
    box.pack_start(Gtk.Label(label="Built-in", xalign=0), False, False, 0)
    flow = Gtk.FlowBox()
    flow.set_max_children_per_line(3)
    flow.set_selection_mode(Gtk.SelectionMode.NONE)
    for menu, items in galleries.GALLERIES[:1]:
        for it in items:
            if it[0] == "#" or not it[2]:
                continue
            b = Gtk.Button(label=it[1])
            b.connect("clicked", lambda _b, t=it[2]: (latex.set_active(False), entry.set_text(t)))
            flow.add(b)
    sw = Gtk.ScrolledWindow()
    sw.set_min_content_height(120)
    sw.add(flow)
    box.pack_start(sw, True, True, 0)
    d.show_all()
    r = d.run()
    out = None
    if r == Gtk.ResponseType.OK:
        s = seq()
        out = M.to_linear(s) if s is not None else None
    d.destroy()
    return out


class EquationCommands:
    def act_insert_equation(self, text=None):
        if self.current is None:
            return None
        if text in (None, ""):
            text = equation_dialog(self)
            if not text:
                return None
        return self.insert_equation(text)

    def _equation_parts(self, text):
        seq = M.from_linear(text)
        xml = omml.to_omml(M.export(seq))
        png, w, h = picture(seq)
        return xml, png, w, h

    def insert_equation(self, text):
        xml, png, w, h = self._equation_parts(text)
        sw, sh = self.deck.size()
        sid = self.deck.insert_equation(self.current, xml, png, (sw - w) / 2, (sh - h) / 2, w, h)
        self.changed(slide=True)
        self.canvas.select([sid])
        return sid

    def act_edit_equation(self, sid=None):
        c = self.canvas
        sid = sid or (c.sel[0] if len(c.sel) == 1 else None)
        xml = self.deck.equation(self.current, sid) if sid is not None else None
        if xml is None:
            return None
        text = equation_dialog(self, linear_of(xml))
        if text:
            self.set_equation_text(sid, text)
        return text

    def set_equation_text(self, sid, text):
        xml, png, w, h = self._equation_parts(text)
        self.deck.set_equation(self.current, sid, xml, png, w, h)
        self.changed(slide=True)
        self.canvas.select([sid])

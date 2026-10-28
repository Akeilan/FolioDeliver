"""Draw tab: pens, highlighter and eraser on the slide; Ink to Shape turns a stroke into the shape
it looks like. Strokes are kept as freeform shapes."""
import math

from gi.repository import Gdk

PENS = {"pen": (0x000000, 1.0, 100.0), "pen2": (0xC00000, 2.25, 100.0), "highlighter": (0xFFFF00, 9.0, 50.0)}


def _rdp(pts, tol):
    if len(pts) < 3:
        return pts
    (x0, y0), (x1, y1) = pts[0], pts[-1]
    dx, dy = x1 - x0, y1 - y0
    L = math.hypot(dx, dy) or 1e-9
    far, k = 0.0, 0
    for i, (x, y) in enumerate(pts[1:-1], 1):
        d = abs(dy * x - dx * y + x1 * y0 - y1 * x0) / L
        if d > far:
            far, k = d, i
    if far > tol:
        return _rdp(pts[:k + 1], tol)[:-1] + _rdp(pts[k:], tol)
    return [pts[0], pts[-1]]


def recognize(pts):
    """The shape a stroke looks like: (prst, x, y, w, h, flip) or None."""
    if len(pts) < 4:
        return None
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    x, y, w, h = min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys)
    diag = math.hypot(w, h)
    if diag < 8:
        return None
    length = sum(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(pts, pts[1:]))
    gap = math.hypot(pts[-1][0] - pts[0][0], pts[-1][1] - pts[0][1])
    if gap > 0.3 * diag:
        if gap / max(length, 1e-9) > 0.9:
            (ax, ay), (bx, by) = pts[0], pts[-1]
            return ("line", min(ax, bx), min(ay, by), abs(bx - ax), abs(by - ay), (bx < ax) != (by < ay))
        return None
    # a closed stroke: simplified in two halves (from the start to its farthest point and back)
    far = max(range(len(pts)), key=lambda k: math.hypot(pts[k][0] - pts[0][0], pts[k][1] - pts[0][1]))
    tol = 0.08 * diag
    simple = _rdp(pts[:far + 1], tol) + _rdp(pts[far:] + [pts[0]], tol)[1:]
    # the start is a corner only if the stroke turns there
    if len(simple) > 3:
        (ax, ay), (bx, by), (cx2, cy2) = simple[-2], simple[0], simple[1]
        v1, v2 = (bx - ax, by - ay), (cx2 - bx, cy2 - by)
        cosang = (v1[0] * v2[0] + v1[1] * v2[1]) / ((math.hypot(*v1) * math.hypot(*v2)) or 1e-9)
        if cosang > 0.9:
            simple = simple[1:]
    corners = len(simple) - 1
    # how round: distances from the centre against the mean
    cx, cy = x + w / 2, y + h / 2
    rs = [math.hypot((px - cx) / max(w / 2, 1e-9), (py - cy) / max(h / 2, 1e-9)) for px, py in pts]
    mean = sum(rs) / len(rs)
    spread = math.sqrt(sum((r - mean) ** 2 for r in rs) / len(rs))
    if corners == 3:
        return ("triangle", x, y, w, h, False)
    if corners == 4 and spread > 0.06:
        return ("rect", x, y, w, h, False)
    if spread < 0.12:
        return ("ellipse", x, y, w, h, False)
    if corners == 4:
        return ("rect", x, y, w, h, False)
    return None


class InkCommands:
    def act_ink(self, tool):
        """Draw > Pen / Highlighter / Eraser (tool "off": back to selecting)."""
        c = self.canvas
        c.leave_text()
        if tool in ("off", "", None) or getattr(c, "ink_tool", None) == tool and tool != "eraser":
            c.ink_tool = None
            self.insert_mode_done()
            return None
        c.ink_tool = tool
        c.ink_points = []
        if tool in PENS and not hasattr(self, "ink_pens"):
            self.ink_pens = {k: list(v) for k, v in PENS.items()}
        w = c.area.get_window()
        if w is not None:
            w.set_cursor(Gdk.Cursor.new_from_name(w.get_display(), "cell" if tool == "eraser" else "crosshair"))
        return tool

    def act_ink_color(self, hexv):
        pens = getattr(self, "ink_pens", None) or {k: list(v) for k, v in PENS.items()}
        self.ink_pens = pens
        tool = getattr(self.canvas, "ink_tool", None) or "pen"
        if tool in pens:
            pens[tool][0] = int(hexv, 16)

    def act_ink_width(self, pt):
        pens = getattr(self, "ink_pens", None) or {k: list(v) for k, v in PENS.items()}
        self.ink_pens = pens
        tool = getattr(self.canvas, "ink_tool", None) or "pen"
        if tool in pens:
            pens[tool][1] = float(pt)

    def act_ink_to_shape(self):
        self.ink_shapes = not getattr(self, "ink_shapes", False)
        self.ribbon.update("ink-to-shape", "true" if self.ink_shapes else "false")
        if self.ink_shapes and getattr(self.canvas, "ink_tool", None) not in ("pen", "pen2"):
            self.act_ink("pen")
        return self.ink_shapes

    def finish_stroke(self, pts):
        tool = self.canvas.ink_tool
        pens = getattr(self, "ink_pens", None) or {k: list(v) for k, v in PENS.items()}
        color, width, alpha = pens.get(tool, PENS["pen"])
        if getattr(self, "ink_shapes", False) and tool != "highlighter":
            r = recognize(pts)
            if r is not None:
                prst, x, y, w, h, flip = r
                sid = self.deck.add_shape(self.current, prst, x, y, max(w, 1), max(h, 1))
                if flip:
                    self.deck.flip(self.current, [sid], False)
                self.deck.set_shape_fill(self.current, [sid], "none")
                self.deck.set_shape_line(self.current, [sid], "%06X" % color, width, None)
                self.changed(slide=True)
                return sid
        sid = self.deck.add_ink(self.current, pts, color, width, alpha, "Ink")
        self.changed(slide=True)
        return sid

    def erase_at(self, sx, sy):
        """The eraser takes away the ink stroke under it."""
        for s in reversed(self.canvas.shapes):
            if not s["name"].startswith("Ink"):
                continue
            pad = 4.0
            if s["x"] - pad <= sx <= s["x"] + s["w"] + pad and s["y"] - pad <= sy <= s["y"] + s["h"] + pad:
                self.deck.delete_shapes(self.current, [s["id"]])
                self.changed(slide=True)
                return s["id"]
        return None

    def keep_show_ink(self, st, keep=None):
        """After a show with ink: keep the annotations as ink on the slides?"""
        strokes = {i: s for i, s in getattr(st, "ink", {}).items() if s}
        if not strokes:
            return 0
        if keep is None:
            from gi.repository import Gtk
            d = Gtk.MessageDialog(transient_for=self, modal=True, message_type=Gtk.MessageType.QUESTION,
                                  buttons=Gtk.ButtonsType.NONE, text="Do you want to keep your ink annotations?")
            d.add_button("Keep", 1)
            d.add_button("Discard", 2)
            keep = d.run() == 1
            d.destroy()
        if not keep:
            return 0
        n = 0
        for i, ss in strokes.items():
            for tool, color, width, pts in ss:
                rgb = (int(color[0] * 255) << 16) | (int(color[1] * 255) << 8) | int(color[2] * 255)
                if len(pts) > 1:
                    self.deck.add_ink(i, pts, rgb, width * (4 if tool == "highlighter" else 1), 40.0 if tool == "highlighter" else 100.0, "Ink")
                    n += 1
        self.changed(structure=True)
        return n

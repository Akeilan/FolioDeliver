"""Chart types, their pictures, the Insert Chart dialog and the data sheet: shared with Folio Writer."""
from gi.repository import Gdk, GLib, Gtk


class FDialog(Gtk.Dialog):
    """A modal dialog: content area, OK and Cancel."""
    def __init__(self, parent, title):
        Gtk.Dialog.__init__(self, title=title, transient_for=parent, modal=True)
        self.get_style_context().add_class("folio-dialog")
        self.add_button("Cancel", Gtk.ResponseType.CANCEL)
        ok = self.add_button("OK", Gtk.ResponseType.OK)
        ok.get_style_context().add_class("suggested-action")
        self.set_default_response(Gtk.ResponseType.OK)
        self.box = self.get_content_area()
        self.box.set_spacing(8)
        self.box.set_border_width(12)

    def add(self, widget, expand=False):
        self.box.pack_start(widget, expand, expand, 0)
        return widget

    def ask(self):
        self.show_all()
        return self.run()

    def done(self):
        self.destroy()

TYPES = [
    # (label, diagram service, extra properties)
    ("Clustered Column", "BarDiagram", {"Vertical": False}),
    ("Stacked Column", "BarDiagram", {"Vertical": False, "Stacked": True}),
    ("Clustered Bar", "BarDiagram", {"Vertical": True}),
    ("Line", "LineDiagram", {}),
    ("Line with Markers", "LineDiagram", {"SymbolType": -3}),
    ("Pie", "PieDiagram", {}),
    ("Doughnut", "DonutDiagram", {}),
    ("Area", "AreaDiagram", {}),
    ("Scatter", "XYDiagram", {"Lines": False}),
    ("100% Stacked Column", "BarDiagram", {"Vertical": False,
                                                              "Percent": True}),
    ("Stacked Bar", "BarDiagram", {"Vertical": True, "Stacked": True}),
    ("Stacked Area", "AreaDiagram", {"Stacked": True}),
    ("Radar", "NetDiagram", {}),
    ("Combo: Clustered Column - Line", "BarDiagram",
     {"Vertical": False, "NumberOfLines": 1}),
    ("Histogram", "BarDiagram", {"Vertical": False}),
    ("Waterfall", "BarDiagram", {"Vertical": False, "Stacked": True}),
    ("Box & Whisker", "StockDiagram", {"UpDown": True, "Volume": False}),
    ("Funnel", "BarDiagram", {"Vertical": True, "Stacked": True}),
    ("Treemap", "image", {}),
    ("Sunburst", "image", {}),
]
HISTOGRAM = 14
WATERFALL = 15
BOX = 16
FUNNEL = 17
TREEMAP = 18
SUNBURST = 19
SPECIALS = {HISTOGRAM: "histogram", WATERFALL: "waterfall", BOX: "box", FUNNEL: "funnel"}
IMAGE_TYPES = {TREEMAP: "treemap", SUNBURST: "sunburst"}

DEFAULT_DATA = {
    "rows": ["Category 1", "Category 2", "Category 3", "Category 4"],
    "cols": ["Series 1", "Series 2", "Series 3"],
    "values": [[4.3, 2.4, 2.0], [2.5, 4.4, 2.0], [3.5, 1.8, 3.0], [4.5, 2.8, 5.0]],
}

PALETTE = [0x4472C4, 0xED7D31, 0xA5A5A5, 0xFFC000, 0x5B9BD5, 0x70AD47, 0x264478, 0x9E480E]


def histogram_data(d, bins=None):
    vals = [row[0] for row in d["values"] if row]
    if not vals:
        return d
    lo, hi = min(vals), max(vals)
    import math
    n = bins or max(1, min(12, int(math.ceil(math.log(len(vals), 2) + 1))))
    width = (hi - lo) / float(n) or 1.0
    counts = [0] * n
    for v in vals:
        counts[min(n - 1, int((v - lo) / width))] += 1
    fmt = lambda v: ("%g" % round(v, 2))   # noqa: E731
    rows = ["[%s, %s%s" % (fmt(lo + i * width), fmt(lo + (i + 1) * width),
                           "]" if i == n - 1 else ")") for i in range(n)]
    return {"rows": rows, "cols": [d["cols"][0] if d["cols"] else "Frequency"],
            "values": [[c] for c in counts]}


def waterfall_data(d):
    base, up, down = [], [], []
    run = 0.0
    for row in d["values"]:
        v = row[0] if row else 0.0
        if v >= 0:
            base.append(run)
            up.append(v)
            down.append(0.0)
        else:
            base.append(run + v)
            up.append(0.0)
            down.append(-v)
        run += v
    return {"rows": list(d["rows"]), "cols": ["", "Increase", "Decrease"],
            "values": [[b, u, dn] for b, u, dn in zip(base, up, down)]}


def _quartiles(vals):
    v = sorted(vals)
    n = len(v)
    if not n:
        return 0, 0, 0, 0, 0

    def q(p):
        k = (n - 1) * p
        f = int(k)
        c = min(n - 1, f + 1)
        return v[f] + (v[c] - v[f]) * (k - f)
    return v[0], q(0.25), q(0.5), q(0.75), v[-1]


def box_data(d):
    """One box per series: Q1 (open), minimum (low), maximum (high), Q3 (close)."""
    rows, vals = [], []
    for ci, name in enumerate(d["cols"]):
        col = [row[ci] for row in d["values"] if ci < len(row)]
        lo, q1, med, q3, hi = _quartiles(col)
        rows.append(name)
        vals.append([q1, lo, hi, q3])
    return {"rows": rows, "cols": ["Q1", "Minimum", "Maximum", "Q3"], "values": vals}


def funnel_data(d):
    vals = [row[0] if row else 0.0 for row in d["values"]]
    top = max(vals or [0])
    rows = list(reversed(d["rows"]))
    out = [[(top - v) / 2.0, v] for v in reversed(vals)]
    return {"rows": rows, "cols": ["", d["cols"][0] if d["cols"] else "Value"], "values": out}


def _shown(kind, d):
    return {"histogram": histogram_data, "waterfall": waterfall_data, "box": box_data,
            "funnel": funnel_data}[kind](d)


QUICK_LAYOUTS = [
    # (name, title, legend, axis titles, data labels, major gridlines)
    ("Layout 1", True, "right", False, None, True),
    ("Layout 2", True, "top", False, "outside-end", False),
    ("Layout 3", True, "bottom", False, None, True),
    ("Layout 4", False, "bottom", False, "outside-end", False),
    ("Layout 5", True, "none", True, None, True),
    ("Layout 6", True, "none", True, None, True),
    ("Layout 7", False, "right", True, None, True),
    ("Layout 8", True, "none", True, None, False),
    ("Layout 9", True, "right", True, None, True),
    ("Layout 10", True, "right", False, "inside-end", False),
    ("Layout 11", False, "right", False, None, False),
]


COLORFUL = [
    ("Colorful Palette 1", PALETTE),
    ("Colorful Palette 2", [0xED7D31, 0xFFC000, 0x70AD47, 0x9E480E, 0x997300, 0x43682B]),
    ("Colorful Palette 3", [0xA5A5A5, 0x5B9BD5, 0x264478, 0x636363, 0x255E91, 0x698ED0]),
    ("Colorful Palette 4", [0x70AD47, 0x4472C4, 0xFFC000, 0x43682B, 0x264478, 0x997300]),
]


def _mono(base):
    from .drawing import _tint, _shade
    return [_shade(base, 0.25), base, _tint(base, 0.3), _tint(base, 0.5), _shade(base, 0.5),
            _tint(base, 0.7)]


MONOCHROMATIC = [("Monochromatic Palette %d" % (i + 1), _mono(c)) for i, c in enumerate(
    [0x4472C4, 0xED7D31, 0xA5A5A5, 0xFFC000, 0x5B9BD5, 0x70AD47])]


CHART_STYLES = ["Style 1", "Style 2", "Style 3", "Style 4", "Style 5", "Style 6",
                "Style 7", "Style 8"]


CATEGORIES = [("Column", [0, 1, 9]), ("Line", [3, 4]), ("Pie", [5, 6]), ("Bar", [2, 10]),
              ("Area", [7, 11]), ("X Y (Scatter)", [8]), ("Radar", [12]),
              ("Treemap", [18]), ("Sunburst", [19]), ("Histogram", [14]),
              ("Box & Whisker", [16]), ("Waterfall", [15]), ("Funnel", [17]),
              ("Combo", [13])]


def draw_type(cr, idx, W, H, big=False):
    """A small picture of a chart type."""
    import math
    cols = [(0.27, 0.45, 0.77), (0.93, 0.49, 0.19), (0.65, 0.65, 0.65)]
    data = [[4.3, 2.4, 2.0], [2.5, 4.4, 2.0], [3.5, 1.8, 3.0], [4.5, 2.8, 5.0]]
    pad = 6 if not big else 24
    x0, y0, w, h = pad, pad, W - 2 * pad, H - 2 * pad
    cr.set_source_rgb(1, 1, 1)
    cr.paint()
    label, service, props = TYPES[idx]
    cr.set_line_width(1.2 if not big else 2.5)

    def axis():
        cr.set_source_rgb(0.75, 0.75, 0.75)
        cr.move_to(x0, y0 + h)
        cr.line_to(x0 + w, y0 + h)
        cr.stroke()
    if idx in (5, 6):
        cx, cy, rad = x0 + w / 2, y0 + h / 2, min(w, h) / 2
        vals = [8.2, 3.2, 1.4, 1.2]
        a = -math.pi / 2
        pal = [(0.27, 0.45, 0.77), (0.93, 0.49, 0.19), (0.65, 0.65, 0.65), (1.0, 0.75, 0.0)]
        for i, v in enumerate(vals):
            b = a + v / sum(vals) * 2 * math.pi
            cr.set_source_rgb(*pal[i])
            cr.move_to(cx, cy)
            cr.arc(cx, cy, rad, a, b)
            cr.close_path()
            cr.fill()
            a = b
        if idx == 6:
            cr.set_source_rgb(1, 1, 1)
            cr.arc(cx, cy, rad * 0.5, 0, 2 * math.pi)
            cr.fill()
        return
    if idx == TREEMAP:
        pal = [(0.27, 0.45, 0.77), (0.93, 0.49, 0.19), (0.65, 0.65, 0.65), (1.0, 0.75, 0.0)]
        rects = [(0, 0, 0.55, 1, 0), (0.55, 0, 0.45, 0.55, 1), (0.55, 0.55, 0.25, 0.45, 2),
                 (0.8, 0.55, 0.2, 0.45, 3)]
        for rx, ry, rw, rh, ci in rects:
            cr.set_source_rgb(*pal[ci])
            cr.rectangle(x0 + rx * w + 1, y0 + ry * h + 1, rw * w - 2, rh * h - 2)
            cr.fill()
        return
    if idx == SUNBURST:
        cx, cy, rad = x0 + w / 2, y0 + h / 2, min(w, h) / 2
        pal = [(0.27, 0.45, 0.77), (0.93, 0.49, 0.19), (0.65, 0.65, 0.65)]
        a = -math.pi / 2
        for i, f in enumerate((0.45, 0.35, 0.2)):
            b = a + f * 2 * math.pi
            for rr, alpha in ((rad, 0.6), (rad * 0.6, 1.0)):
                cr.set_source_rgba(pal[i][0], pal[i][1], pal[i][2], alpha)
                cr.move_to(cx, cy)
                cr.arc(cx, cy, rr, a, b)
                cr.close_path()
                cr.fill()
            a = b
        cr.set_source_rgb(1, 1, 1)
        cr.arc(cx, cy, rad * 0.22, 0, 2 * math.pi)
        cr.fill()
        return
    if idx == BOX:
        cr.set_source_rgb(0.75, 0.75, 0.75)
        cr.move_to(x0, y0 + h)
        cr.line_to(x0 + w, y0 + h)
        cr.stroke()
        for i, (lo, q1, q3, hi) in enumerate(((0.1, 0.3, 0.6, 0.85), (0.2, 0.4, 0.75, 0.95),
                                              (0.05, 0.25, 0.5, 0.7))):
            bx = x0 + (i + 0.5) * w / 3.0
            bw = w / 7.0
            cr.set_source_rgb(0.27, 0.45, 0.77)
            cr.move_to(bx, y0 + h - lo * h)
            cr.line_to(bx, y0 + h - hi * h)
            cr.stroke()
            cr.rectangle(bx - bw / 2, y0 + h - q3 * h, bw, (q3 - q1) * h)
            cr.fill()
        return
    if idx == FUNNEL:
        for i, f in enumerate((1.0, 0.8, 0.55, 0.35)):
            bh = h / 4.0
            bw = w * f
            cr.set_source_rgb(0.27, 0.45, 0.77)
            cr.rectangle(x0 + (w - bw) / 2, y0 + i * bh + 1, bw, bh - 2)
            cr.fill()
        return
    if idx == 12:
        cx, cy, rad = x0 + w / 2, y0 + h / 2, min(w, h) / 2
        cr.set_source_rgb(0.8, 0.8, 0.8)
        for k in range(5):
            a = -math.pi / 2 + k * 2 * math.pi / 5
            cr.move_to(cx, cy)
            cr.line_to(cx + rad * math.cos(a), cy + rad * math.sin(a))
        cr.stroke()
        for si, scale in enumerate(([0.9, 0.6, 0.8, 0.5, 0.7], [0.5, 0.9, 0.4, 0.8, 0.6])):
            cr.set_source_rgb(*cols[si])
            for k, f in enumerate(scale + scale[:1]):
                a = -math.pi / 2 + k * 2 * math.pi / 5
                (cr.move_to if k == 0 else cr.line_to)(cx + rad * f * math.cos(a),
                                                        cy + rad * f * math.sin(a))
            cr.stroke()
        return
    axis()
    vmax = 6.0
    if idx in (0, 1, 9, 2, 10, 13, 14, 15):
        horizontal = idx in (2, 10)
        n = len(data)
        group = (w if not horizontal else h) / float(n)
        for gi, row in enumerate(data):
            if idx == 14:
                vals = [[2, 4, 5, 3][gi]]
            elif idx == 15:
                vals = None
            else:
                vals = row
            if idx == 15:
                steps = [3.0, 1.5, -1.0, 2.0]
                run = sum(steps[:gi])
                v = steps[gi]
                lo, hi = (run, run + v) if v >= 0 else (run + v, run)
                cr.set_source_rgb(*(cols[0] if v >= 0 else cols[1]))
                bw = group * 0.6
                cr.rectangle(x0 + gi * group + (group - bw) / 2, y0 + h - hi / vmax * h, bw,
                             (hi - lo) / vmax * h)
                cr.fill()
                continue
            stacked = props.get("Stacked") or props.get("Percent")
            total = sum(vals)
            k = len(vals) if not stacked and idx != 14 else 1
            gap = 0.0 if idx == 14 else 0.25
            bw = group * (1 - gap) / k
            base = 0.0
            for si, v in enumerate(vals):
                if idx == 13 and si == len(vals) - 1:
                    continue
                if props.get("Percent"):
                    v = v / total * vmax
                cr.set_source_rgb(*cols[si % 3])
                if horizontal:
                    yy = y0 + gi * group + group * gap / 2 + (0 if stacked else si * bw)
                    cr.rectangle(x0 + base / vmax * w * (0.6 if stacked else 1), yy,
                                 v / vmax * w * (0.6 if stacked else 1), bw)
                else:
                    xx = x0 + gi * group + group * gap / 2 + (0 if stacked else si * bw)
                    scale = 0.45 if stacked and not props.get("Percent") else 1
                    if props.get("Percent"):
                        scale = 1
                    cr.rectangle(xx, y0 + h - (base + v) / vmax * h * scale, bw,
                                 v / vmax * h * scale)
                cr.fill()
                if stacked:
                    base += v
            if idx == 14:
                cr.set_source_rgb(1, 1, 1)
                cr.rectangle(x0 + gi * group, y0, 1, h)
                cr.fill()
        if idx == 13:
            cr.set_source_rgb(*cols[2])
            for gi, row in enumerate(data):
                px = x0 + gi * group + group / 2
                py = y0 + h - row[2] / vmax * h
                (cr.move_to if gi == 0 else cr.line_to)(px, py)
            cr.stroke()
        return
    n = len(data)
    step = w / float(n - 1)
    for si in range(3):
        pts = []
        for gi, row in enumerate(data):
            v = row[si]
            if props.get("Stacked"):
                v = sum(row[:si + 1]) * 0.5
            pts.append((x0 + gi * step, y0 + h - v / vmax * h))
        cr.set_source_rgb(*cols[si])
        if idx in (7, 11):
            stack_idx = 2 - si if idx == 7 else si
            pts = []
            for gi, row in enumerate(data):
                v = row[stack_idx] if idx == 7 else sum(row[:si + 1]) * 0.5
                pts.append((x0 + gi * step, y0 + h - v / vmax * h))
            cr.set_source_rgb(*cols[stack_idx if idx == 7 else si])
            cr.move_to(x0, y0 + h)
            for p in pts:
                cr.line_to(*p)
            cr.line_to(x0 + w, y0 + h)
            cr.close_path()
            cr.fill()
            continue
        if idx == 8:
            for px, py in pts:
                cr.arc(px, py, 2 if not big else 5, 0, 6.3)
                cr.fill()
            continue
        cr.move_to(*pts[0])
        for p in pts[1:]:
            cr.line_to(*p)
        cr.stroke()
        if idx == 4:
            for px, py in pts:
                cr.arc(px, py, 1.8 if not big else 4, 0, 6.3)
                cr.fill()


def type_dialog(win, current=0, title="Insert Chart"):
    d = FDialog(win, title)
    state = {"idx": current}
    outer = Gtk.Box(spacing=0)
    cats = Gtk.ListBox()
    cats.set_size_request(170, -1)
    cats.get_style_context().add_class("folio-navlist")
    right = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, margin=10)
    subs = Gtk.Box(spacing=6)
    name = Gtk.Label(xalign=0)
    preview = Gtk.DrawingArea()
    preview.set_size_request(460, 300)
    preview.connect("draw", lambda a, cr: draw_type(cr, state["idx"], a.get_allocated_width(),
                                                    a.get_allocated_height(), big=True))
    frame = Gtk.Frame()
    frame.add(preview)
    right.pack_start(subs, False, False, 0)
    right.pack_start(name, False, False, 0)
    right.pack_start(frame, True, True, 0)

    def choose(idx):
        state["idx"] = idx
        name.set_markup("<b>%s</b>" % TYPES[idx][0])
        for b in subs.get_children():
            b.set_relief(Gtk.ReliefStyle.NORMAL if b.idx == idx else Gtk.ReliefStyle.NONE)
        preview.queue_draw()

    def show_cat(ci):
        for c in subs.get_children():
            subs.remove(c)
        for idx in CATEGORIES[ci][1]:
            b = Gtk.Button()
            b.idx = idx
            b.set_tooltip_text(TYPES[idx][0])
            a = Gtk.DrawingArea()
            a.set_size_request(44, 36)
            a.connect("draw", lambda ar, cr, i=idx: draw_type(
                cr, i, ar.get_allocated_width(), ar.get_allocated_height()))
            b.add(a)
            b.connect("clicked", lambda _b, i=idx: choose(i))
            subs.pack_start(b, False, False, 0)
        subs.show_all()
        choose(state["idx"] if state["idx"] in CATEGORIES[ci][1] else CATEGORIES[ci][1][0])

    cur_cat = 0
    for ci, (label, members) in enumerate(CATEGORIES):
        row = Gtk.Box(spacing=8, margin=4)
        a = Gtk.DrawingArea()
        a.set_size_request(22, 18)
        a.connect("draw", lambda ar, cr, i=members[0]: draw_type(
            cr, i, ar.get_allocated_width(), ar.get_allocated_height()))
        row.pack_start(a, False, False, 0)
        row.pack_start(Gtk.Label(label=label, xalign=0), True, True, 0)
        cats.add(row)
        if current in members:
            cur_cat = ci
    cats.connect("row-selected", lambda lb, row: row is not None and show_cat(row.get_index()))
    outer.pack_start(cats, False, False, 0)
    outer.pack_start(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL), False, False, 0)
    outer.pack_start(right, True, True, 0)
    d.add(outer, expand=True)
    cats.select_row(cats.get_row_at_index(cur_cat))
    show_cat(cur_cat)
    choose(current)
    r = d.ask()
    idx = state["idx"]
    d.done()
    return idx if r == Gtk.ResponseType.OK else None




def get_data(obj):
    """Replaced by the chart model (charts_model)."""
    raise NotImplementedError


def set_data(obj, d):
    raise NotImplementedError


def refresh(obj):
    pass


class DataSheet(Gtk.Window):
    """'Chart in <document>': a small grid to edit the chart's numbers."""
    def __init__(self, win, obj):
        Gtk.Window.__init__(self, title="Chart in %s" % win.doc_name())
        self.set_transient_for(win)
        self.set_default_size(560, 300)
        self.win = win
        self.obj = obj
        self.data = get_data(obj)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        box.set_border_width(8)
        self.add(box)
        bar = Gtk.Box(spacing=6)
        self.set_default_size(720, 380)
        for label, cb in (("Add Row", self.add_row), ("Add Series", self.add_col),
                          ("Remove Row", self.del_row), ("Remove Series", self.del_col),
                          ("Switch Row/Column", self.switch), ("Paste", self.paste),
                          ("Import...", self.import_file)):
            b = Gtk.Button(label=label)
            b.connect("clicked", lambda _b, cb=cb: cb())
            bar.pack_start(b, False, False, 0)
        box.pack_start(bar, False, False, 0)
        self.sw = Gtk.ScrolledWindow()
        box.pack_start(self.sw, True, True, 0)
        hint = Gtk.Label(label="Changes appear in the chart as you type.", xalign=0)
        hint.get_style_context().add_class("dim-label")
        box.pack_start(hint, False, False, 0)
        self.build()
        self.show_all()

    def build(self):
        for c in self.sw.get_children():
            self.sw.remove(c)
        ncol = len(self.data["cols"])
        self.store = Gtk.ListStore(*([str] * (ncol + 1)))
        self.store.append([""] + self.data["cols"])
        for name, vals in zip(self.data["rows"], self.data["values"]):
            self.store.append([name] + [("%g" % v) for v in vals])
        tv = Gtk.TreeView(model=self.store)
        tv.set_grid_lines(Gtk.TreeViewGridLines.BOTH)
        for c in range(ncol + 1):
            cell = Gtk.CellRendererText(editable=True)
            cell.connect("edited", self.edited, c)
            col = Gtk.TreeViewColumn("ABCDEFGHIJKLMNOPQRSTUVWXYZ"[c], cell, text=c)
            col.set_min_width(90)
            tv.append_column(col)
        self.tv = tv
        self.sw.add(tv)
        tv.show()

    def edited(self, cell, path, text, col):
        r = int(path)
        self.store[path][col] = text
        if r == 0 and col > 0:
            self.data["cols"][col - 1] = text
        elif col == 0 and r > 0:
            self.data["rows"][r - 1] = text
        elif r > 0:
            try:
                self.data["values"][r - 1][col - 1] = float(text.replace(",", "."))
            except ValueError:
                return
        self.push()

    def push(self):
        try:
            set_data(self.obj, self.data)
        except Exception as e:
            print("chart data:", e)
        if getattr(self, "_rt", None):
            GLib.source_remove(self._rt)
        self._rt = GLib.timeout_add(350, self._refresh)

    def _refresh(self):
        self._rt = None
        refresh(self.obj)
        return False

    def switch(self):
        d = self.data
        self.data = {"rows": list(d["cols"]), "cols": list(d["rows"]),
                     "values": [[d["values"][r][c] for r in range(len(d["rows"]))]
                                for c in range(len(d["cols"]))]}
        self.build()
        self.push()

    def _load_table(self, rows):
        rows = [r for r in rows if any(x.strip() for x in r)]
        if len(rows) < 2 or len(rows[0]) < 2:
            self.win.dialogs.message("The data needs a header row and a label column.")
            return
        cols = [c.strip() or "Series %d" % (i + 1) for i, c in enumerate(rows[0][1:])]
        names, vals = [], []
        for r in rows[1:]:
            names.append(r[0].strip())
            line = []
            for x in r[1:len(cols) + 1]:
                try:
                    line.append(float(x.replace(",", "").strip() or 0))
                except ValueError:
                    line.append(0.0)
            line += [0.0] * (len(cols) - len(line))
            vals.append(line)
        self.data = {"rows": names, "cols": cols, "values": vals}
        self.build()
        self.push()

    def paste(self):
        """Paste a block of cells copied from a spreadsheet (tab separated)."""
        cb = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
        text = cb.wait_for_text() or ""
        if not text.strip():
            return
        sep = "\t" if "\t" in text else ","
        self._load_table([line.split(sep) for line in text.splitlines()])

    def import_file(self):
        import csv
        d = Gtk.FileChooserDialog(title="Import Data", transient_for=self,
                                  action=Gtk.FileChooserAction.OPEN)
        d.add_button("Cancel", Gtk.ResponseType.CANCEL)
        d.add_button("Open", Gtk.ResponseType.ACCEPT)
        f = Gtk.FileFilter()
        f.set_name("Text data (*.csv, *.tsv, *.txt)")
        for p in ("*.csv", "*.tsv", "*.txt"):
            f.add_pattern(p)
        d.add_filter(f)
        path = d.get_filename() if d.run() == Gtk.ResponseType.ACCEPT else None
        d.destroy()
        if not path:
            return
        with open(path, newline="", encoding="utf-8", errors="replace") as fh:
            sample = fh.read(4096)
            fh.seek(0)
            try:
                dialect = csv.Sniffer().sniff(sample, ",;\t")
            except csv.Error:
                dialect = csv.excel
            self._load_table(list(csv.reader(fh, dialect)))

    def add_row(self):
        n = len(self.data["rows"]) + 1
        self.data["rows"].append("Category %d" % n)
        self.data["values"].append([0.0] * len(self.data["cols"]))
        self.build()
        self.push()

    def add_col(self):
        n = len(self.data["cols"]) + 1
        self.data["cols"].append("Series %d" % n)
        for row in self.data["values"]:
            row.append(0.0)
        self.build()
        self.push()

    def del_row(self):
        if len(self.data["rows"]) > 1:
            self.data["rows"].pop()
            self.data["values"].pop()
            self.build()
            self.push()

    def del_col(self):
        if len(self.data["cols"]) > 1:
            self.data["cols"].pop()
            for row in self.data["values"]:
                row.pop()
            self.build()
            self.push()


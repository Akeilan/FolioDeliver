"""The ribbon's tabs, groups and controls, laid out as the original's
desktop ribbon (cloud, sign-in and AI commands are left out)."""
import colorsys

from gi.repository import GLib, Gtk, Pango, PangoCairo

from . import icons
from .ribbon import (CheckControl, ComboControl, Group, MenuButton, RibbonButton, SplitButton, Tab,
                     menu_popover)

FONT_SIZES = ["8", "9", "10", "11", "12", "14", "16", "18", "20", "22", "24", "26", "28", "36",
              "48", "72"]
NUMBER_FORMATS = [("General", "General"), ("Number", "0.00"), ("Currency", '"$"#,##0.00'),
                  ("Accounting", '_("$"* #,##0.00_);_("$"* \\(#,##0.00\\);_("$"* "-"??_);_(@_)'),
                  ("Short Date", "m/d/yyyy"), ("Long Date", "[$-F800]dddd, mmmm dd, yyyy"),
                  ("Time", "[$-F400]h:mm:ss AM/PM"), ("Percentage", "0.00%"), ("Fraction", "# ?/?"),
                  ("Scientific", "0.00E+00"), ("Text", "@")]

# the theme colours of a new workbook (Office 2013–2022 default theme)
THEME_COLORS = [0xFFFFFF, 0x000000, 0xE7E6E6, 0x44546A, 0x4472C4, 0xED7D31, 0xA5A5A5,
                0xFFC000, 0x5B9BD5, 0x70AD47]
STANDARD_COLORS = [0xC00000, 0xFF0000, 0xFFC000, 0xFFFF00, 0x92D050, 0x00B050, 0x00B0F0,
                   0x0070C0, 0x002060, 0x7030A0]


def _remember(win, attr, w):
    setattr(win, attr, w)
    return w


def _color_button(win, btn):
    if not hasattr(win, "color_buttons"):
        win.color_buttons = []
    win.color_buttons.append(btn)
    return btn

def tint(rgb, t):
    r, g, b = ((rgb >> 16) & 255) / 255, ((rgb >> 8) & 255) / 255, (rgb & 255) / 255
    h, l, s = colorsys.rgb_to_hls(r, g, b)
    l = l * (1 + t) if t < 0 else l * (1 - t) + t
    r, g, b = colorsys.hls_to_rgb(h, max(0, min(1, l)), s)
    return (round(r * 255) << 16) | (round(g * 255) << 8) | round(b * 255)


def palette_tints(c):
    """The tints of the five rows under a theme colour (lighter and darker), as the desktop
    spreadsheet picks them for how light the colour is."""
    if c == 0xFFFFFF:
        return (-0.05, -0.15, -0.25, -0.35, -0.5)
    if c == 0x000000:
        return (0.5, 0.35, 0.25, 0.15, 0.05)
    l = colorsys.rgb_to_hls(((c >> 16) & 255) / 255, ((c >> 8) & 255) / 255, (c & 255) / 255)[1]
    if l < 0.2:
        return (0.9, 0.75, 0.5, 0.25, 0.1)
    if l > 0.8:
        return (-0.1, -0.25, -0.5, -0.75, -0.9)
    return (0.8, 0.6, 0.4, -0.25, -0.5)


def palette_rows(c):
    """The five tint/shade rows under each theme colour."""
    return [tint(c, t) for t in palette_tints(c)]


# the theme of the workbook being worked on: the palette's theme columns follow it
ACTIVE_THEME = list(THEME_COLORS) + [0x0563C1, 0x954F72]
THEME_BIT = 0x80000000
TINT_NAMES = {0.8: "Lighter 80%", 0.6: "Lighter 60%", 0.4: "Lighter 40%", 0.25: "Lighter 25%", 0.35: "Lighter 35%",
              0.15: "Lighter 15%", 0.05: "Lighter 5%", 0.5: "Lighter 50%", 0.9: "Lighter 90%", 0.75: "Lighter 75%",
              0.1: "Lighter 10%", -0.25: "Darker 25%", -0.5: "Darker 50%", -0.05: "Darker 5%", -0.15: "Darker 15%",
              -0.35: "Darker 35%", -0.1: "Darker 10%", -0.75: "Darker 75%", -0.9: "Darker 90%"}
SLOT_NAMES = ["Background 1", "Text 1", "Background 2", "Text 2", "Accent 1", "Accent 2", "Accent 3", "Accent 4",
              "Accent 5", "Accent 6"]


def set_active_theme(colors):
    """The palette shows this theme (light 1, dark 1, light 2, dark 2, accents, hyperlinks)."""
    ACTIVE_THEME[:] = list(colors)[:12]
    THEME_COLORS[:] = ACTIVE_THEME[:10]


def theme_ref(slot, t=0.0):
    """A colour kept as a theme reference (it follows the theme): slot and tint."""
    return THEME_BIT | ((slot & 15) << 24) | ((int(round(max(-1, min(1, t)) * 10000)) + 10000) & 0xFFFF)


def split_ref(c):
    if isinstance(c, int) and c & THEME_BIT:
        return (c >> 24) & 15, ((c & 0xFFFF) - 10000) / 10000.0
    return None


def resolve(c):
    """A colour as it shows: a theme reference in the active theme's colours."""
    r = split_ref(c)
    if r is None:
        return c
    slot, t = r
    base = ACTIVE_THEME[slot] if slot < len(ACTIVE_THEME) else 0
    return tint(base, t) if t else base


def color_name(c):
    r = split_ref(c)
    if r is None:
        return "#%06X" % c
    slot, t = r
    name = SLOT_NAMES[slot] if slot < len(SLOT_NAMES) else "Hyperlink"
    near = [v for k, v in TINT_NAMES.items() if abs(k - t) < 0.001]
    return name + (", " + near[0] if near else "")


def color_palette(on_pick, none_label=None, more=None, popref=None):
    """The colour picker: the theme's colours (kept as theme references, so they follow the theme),
    the standard colours, More Colors."""
    def swatch(c):
        b = Gtk.Button()
        b.get_style_context().add_class("folio-swatch")
        css = Gtk.CssProvider()
        css.load_from_data(("button { background: #%06x; }" % resolve(c)).encode())
        b.get_style_context().add_provider(css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 1)
        b.set_tooltip_text(color_name(c))
        b.value = c
        b.connect("clicked", lambda *_: pick(c))
        return b

    def pick(c):
        if popref and popref[0]:
            popref[0].popdown()
        on_pick(c)
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
    box.set_border_width(8)
    if none_label:
        nb = Gtk.Button(label=none_label)
        nb.set_relief(Gtk.ReliefStyle.NONE)
        nb.connect("clicked", lambda *_: pick(None))
        box.pack_start(nb, False, False, 0)
    box.pack_start(Gtk.Label(label="Theme Colors", xalign=0), False, False, 0)
    grid = Gtk.Grid(column_spacing=3, row_spacing=1)
    grid.set_name("theme-colors")
    for col, c in enumerate(ACTIVE_THEME[:10]):
        grid.attach(swatch(theme_ref(col)), col, 0, 1, 1)
        for row, t in enumerate(palette_tints(c), start=1):
            grid.attach(swatch(theme_ref(col, t)), col, row + 0, 1, 1)
    box.pack_start(grid, False, False, 0)
    box.pack_start(Gtk.Label(label="Standard Colors", xalign=0), False, False, 4)
    std = Gtk.Box(spacing=3)
    for c in STANDARD_COLORS:
        std.pack_start(swatch(c), False, False, 0)
    box.pack_start(std, False, False, 0)
    if more:
        mb = Gtk.Button(label="More Colors...")
        mb.set_relief(Gtk.ReliefStyle.NONE)
        mb.connect("clicked", lambda *_: (popref[0].popdown() if popref and popref[0] else None, more()))
        box.pack_start(mb, False, False, 0)
    return box


def system_fonts():
    fm = PangoCairo.FontMap.get_default()
    return sorted({f.get_name() for f in fm.list_families()}, key=str.lower)


class Cmd:
    """A menu callback that remembers its command (the audit reads it)."""
    def __init__(self, win, cmd):
        self.win = win
        self.cmd = cmd

    def __call__(self, *_):
        self.win.run(self.cmd)


class Builder:
    """Shorthands for building groups."""
    def __init__(self, win):
        self.win = win
        self.r = win.ribbon

    def run(self, cmd):
        return Cmd(self.win, cmd)

    def menu(self, items):
        out = []
        for it in items:
            if it is None or isinstance(it, Gtk.Widget) or (isinstance(it, tuple) and it[0] == "#"):
                out.append(it)
            else:
                label, cmd = it[0], it[1]
                if isinstance(cmd, list):
                    out.append((label, self.menu(cmd)))     # a submenu
                    continue
                icon = it[2] if len(it) > 2 else None
                out.append((label, self.run(cmd), icon) if icon else (label, self.run(cmd)))
        return out

    def big(self, label, icon, cmd, keytip, menu=None, tip=None):
        if menu is not None:
            if cmd is None:
                return MenuButton(self.r, label, icon, self.menu(menu) if isinstance(menu, list) else menu,
                                  size="large", keytip=keytip, tooltip=tip or label)
            return SplitButton(self.r, label, icon, cmd, self.menu(menu) if isinstance(menu, list) else menu,
                               size="large", keytip=keytip, tooltip=tip or label)
        return RibbonButton(self.r, label, icon, cmd, size="large", keytip=keytip, tooltip=tip or label)

    def small(self, label, icon, cmd, keytip, menu=None, tip=None, state=None):
        if menu is not None:
            if cmd is None:
                return MenuButton(self.r, label, icon, self.menu(menu) if isinstance(menu, list) else menu,
                                  size="small", keytip=keytip, tooltip=tip or label)
            return SplitButton(self.r, label, icon, cmd, self.menu(menu) if isinstance(menu, list) else menu,
                               size="small", keytip=keytip, tooltip=tip or label, state=state)
        return RibbonButton(self.r, label, icon, cmd, size="small", keytip=keytip, tooltip=tip or label, state=state)

    def icon(self, icon, cmd, keytip, tip, menu=None, state=None):
        if menu is not None:
            b = SplitButton(self.r, None, icon, cmd, self.menu(menu) if isinstance(menu, list) else menu,
                            size="icon", keytip=keytip, tooltip=tip, state=state)
            return b
        return RibbonButton(self.r, None, icon, cmd, size="icon", keytip=keytip, tooltip=tip, state=state)

    def group(self, tab, caption, columns, launcher=None, launcher_keytip=None):
        g = Group(caption, columns, launcher=launcher, ribbon=self.r, launcher_keytip=launcher_keytip)
        tab.add(g)
        return g



# ======================================================================== Deliver
SHAPE_SETS = [
    ("Lines", [("line", "Line", "line"), ("straightConnector1", "Arrow", "lineendstyle")]),
    ("Rectangles", [("rect", "Rectangle", "rect"), ("roundRect", "Rectangle: Rounded Corners", "rect_rounded"),
                    ("snip1Rect", "Rectangle: Single Corner Snipped", None), ("snip2SameRect", "Rectangle: Top Corners Snipped", None),
                    ("round1Rect", "Rectangle: Single Corner Rounded", None)]),
    ("Basic Shapes", [("ellipse", "Oval", "ellipse"), ("triangle", "Isosceles Triangle", "basicshapes.isosceles-triangle"),
                      ("rtTriangle", "Right Triangle", "basicshapes.right-triangle"), ("parallelogram", "Parallelogram", None),
                      ("trapezoid", "Trapezoid", "basicshapes.trapezoid"), ("diamond", "Diamond", "basicshapes.diamond"),
                      ("pentagon", "Pentagon", "basicshapes.pentagon"), ("hexagon", "Hexagon", "basicshapes.hexagon"),
                      ("octagon", "Octagon", "basicshapes.octagon"), ("plus", "Cross", "basicshapes.cross"),
                      ("donut", "Circle: Hollow", "basicshapes.ring"), ("can", "Cylinder", "basicshapes.can"),
                      ("cube", "Cube", "basicshapes.cube"), ("frame", "Frame", "basicshapes.frame"),
                      ("blockArc", "Block Arc", "basicshapes.block-arc"), ("smileyFace", "Smiley Face", None),
                      ("heart", "Heart", "symbolshapes.heart"), ("lightningBolt", "Lightning Bolt", "symbolshapes.lightning"),
                      ("sun", "Sun", "symbolshapes.sun"), ("moon", "Moon", "symbolshapes.moon"),
                      ("cloud", "Cloud", "symbolshapes.cloud"), ("noSmoking", "\"No\" Symbol", "symbolshapes.forbidden"),
                      ("bracketPair", "Double Bracket", "symbolshapes.bracket-pair"), ("bracePair", "Double Brace", "symbolshapes.brace-pair"),
                      ("leftBracket", "Left Bracket", "symbolshapes.left-bracket"), ("rightBracket", "Right Bracket", "symbolshapes.right-bracket"),
                      ("leftBrace", "Left Brace", "symbolshapes.left-brace"), ("rightBrace", "Right Brace", "symbolshapes.right-brace")]),
    ("Block Arrows", [("rightArrow", "Arrow: Right", "arrowshapes.right-arrow"), ("leftArrow", "Arrow: Left", "arrowshapes.left-arrow"),
                      ("upArrow", "Arrow: Up", "arrowshapes.up-arrow"), ("downArrow", "Arrow: Down", "arrowshapes.down-arrow"),
                      ("leftRightArrow", "Arrow: Left-Right", None), ("upDownArrow", "Arrow: Up-Down", "arrowshapes.up-down-arrow"),
                      ("quadArrow", "Arrow: Quad", "arrowshapes.quad-arrow"), ("notchedRightArrow", "Arrow: Notched Right", "arrowshapes.notched-right-arrow"),
                      ("stripedRightArrow", "Arrow: Striped Right", "arrowshapes.striped-right-arrow"),
                      ("homePlate", "Arrow: Pentagon", "arrowshapes.pentagon-right"), ("chevron", "Arrow: Chevron", "arrowshapes.chevron"),
                      ("circularArrow", "Arrow: Circular", "arrowshapes.circular-arrow"),
                      ("rightArrowCallout", "Callout: Right Arrow", "arrowshapes.right-arrow-callout")]),
    ("Flowchart", [("flowChartProcess", "Flowchart: Process", None), ("flowChartAlternateProcess", "Flowchart: Alternate Process", None),
                   ("flowChartDecision", "Flowchart: Decision", "flowchartshapes.flowchart-decision"),
                   ("flowChartInputOutput", "Flowchart: Data", "flowchartshapes.flowchart-data"),
                   ("flowChartPredefinedProcess", "Flowchart: Predefined Process", "flowchartshapes.flowchart-predefined-process"),
                   ("flowChartDocument", "Flowchart: Document", "flowchartshapes.flowchart-document"),
                   ("flowChartMultidocument", "Flowchart: Multidocument", "flowchartshapes.flowchart-multidocument"),
                   ("flowChartTerminator", "Flowchart: Terminator", "flowchartshapes.flowchart-terminator"),
                   ("flowChartPreparation", "Flowchart: Preparation", "flowchartshapes.flowchart-preparation"),
                   ("flowChartManualInput", "Flowchart: Manual Input", "flowchartshapes.flowchart-manual-input"),
                   ("flowChartConnector", "Flowchart: Connector", None),
                   ("flowChartOffpageConnector", "Flowchart: Off-page Connector", "flowchartshapes.flowchart-off-page-connector"),
                   ("flowChartPunchedCard", "Flowchart: Card", "flowchartshapes.flowchart-card"),
                   ("flowChartSort", "Flowchart: Sort", "flowchartshapes.flowchart-sort"),
                   ("flowChartMagneticDisk", "Flowchart: Magnetic Disk", None),
                   ("flowChartDelay", "Flowchart: Delay", "flowchartshapes.flowchart-delay")]),
    ("Stars and Banners", [("star4", "Star: 4 Points", "starshapes.star4"), ("star5", "Star: 5 Points", "starshapes.star5"),
                           ("star6", "Star: 6 Points", "starshapes.star6"), ("star8", "Star: 8 Points", "starshapes.star8"),
                           ("star12", "Star: 12 Points", "starshapes.star12"), ("star24", "Star: 24 Points", "starshapes.star24"),
                           ("irregularSeal1", "Explosion: 8 Points", "starshapes.bang"),
                           ("verticalScroll", "Scroll: Vertical", "starshapes.vertical-scroll"),
                           ("horizontalScroll", "Scroll: Horizontal", "starshapes.horizontal-scroll")]),
    ("Callouts", [("wedgeRectCallout", "Speech Bubble: Rectangle", "calloutshapes.rectangular-callout"),
                  ("wedgeRoundRectCallout", "Speech Bubble: Rectangle with Corners Rounded", None),
                  ("wedgeEllipseCallout", "Speech Bubble: Oval", "calloutshapes.round-callout"),
                  ("cloudCallout", "Thought Bubble: Cloud", "calloutshapes.cloud-callout"),
                  ("borderCallout1", "Callout: Line", "calloutshapes.line-callout-1")]),
]


def shapes_gallery(win, on_pick=None):
    """The shapes drop-down: every preset by category; picking one starts drawing it."""
    pop = Gtk.Popover()
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
    box.set_border_width(6)
    for cat, items in SHAPE_SETS:
        lab = Gtk.Label(xalign=0)
        lab.set_markup("<b>%s</b>" % cat)
        box.pack_start(lab, False, False, 2)
        flow = Gtk.FlowBox()
        flow.set_max_children_per_line(12)
        flow.set_min_children_per_line(12)
        flow.set_selection_mode(Gtk.SelectionMode.NONE)
        for prst, name, icon in items:
            b = Gtk.Button()
            b.set_relief(Gtk.ReliefStyle.NONE)
            b.get_style_context().add_class("folio-shapecell")
            if icon and icons.exists(icon):
                b.add(icons.image(icon, 16))
            else:
                b.add(ShapeGlyph(prst))
            b.set_tooltip_text(name)

            def go(_b, prst=prst):
                pop.popdown()
                (on_pick or (lambda p: win.run("draw-shape:" + p)))(prst)
            b.connect("clicked", go)
            flow.add(b)
        box.pack_start(flow, False, False, 0)
    sw = Gtk.ScrolledWindow()
    sw.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
    sw.set_propagate_natural_height(True)
    sw.set_max_content_height(480)
    sw.set_min_content_width(330)
    sw.add(box)
    sw.show_all()
    pop.add(sw)
    return pop


class ShapeGlyph(Gtk.DrawingArea):
    """A small outline for shapes the icon set has no picture of."""
    def __init__(self, prst):
        Gtk.DrawingArea.__init__(self)
        self.prst = prst
        self.set_size_request(16, 16)
        self.connect("draw", self._draw)

    def _draw(self, w, cr):
        p = self.prst
        cr.set_source_rgb(0.25, 0.25, 0.25)
        cr.set_line_width(1.2)
        if p == "line":
            cr.move_to(2, 14)
            cr.line_to(14, 2)
        elif "Rect" in p or p in ("flowChartProcess", "flowChartAlternateProcess", "flowChartPunchedCard"):
            r = 3 if "round" in p.lower() or "Alternate" in p else 0
            if r:
                import math
                cr.new_sub_path()
                for cx, cy, a in ((13 - r, 4 + r, -90), (13 - r, 12 - r, 0), (3 + r, 12 - r, 90), (3 + r, 4 + r, 180)):
                    cr.arc(cx, cy, r, math.radians(a), math.radians(a + 90))
                cr.close_path()
            else:
                cr.rectangle(2.5, 4.5, 11, 8)
        elif p in ("parallelogram",):
            cr.move_to(5, 4.5)
            cr.line_to(14, 4.5)
            cr.line_to(11, 12.5)
            cr.line_to(2, 12.5)
            cr.close_path()
        elif p == "smileyFace" or p == "flowChartConnector":
            import math
            cr.arc(8, 8, 6, 0, 2 * math.pi)
        elif p == "leftRightArrow":
            cr.move_to(1, 8)
            cr.line_to(5, 4)
            cr.line_to(5, 6)
            cr.line_to(11, 6)
            cr.line_to(11, 4)
            cr.line_to(15, 8)
            cr.line_to(11, 12)
            cr.line_to(11, 10)
            cr.line_to(5, 10)
            cr.line_to(5, 12)
            cr.close_path()
        elif p == "flowChartMagneticDisk":
            cr.rectangle(3, 4, 10, 9)
        else:
            cr.rectangle(3, 3, 10, 10)
        cr.stroke()
        return False


def layouts_menu(win, action="new-slide-layout"):
    """New Slide / Layout gallery: a picture of each layout of each master."""
    pop = Gtk.Popover()
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
    box.set_border_width(8)
    for master, layouts in win.deck.layouts():
        lab = Gtk.Label(xalign=0)
        lab.set_markup("<b>%s</b>" % GLib.markup_escape_text(win.master_name(master)))
        box.pack_start(lab, False, False, 0)
        flow = Gtk.FlowBox()
        flow.set_max_children_per_line(4)
        flow.set_min_children_per_line(3)
        flow.set_selection_mode(Gtk.SelectionMode.NONE)
        for part, name in layouts:
            b = Gtk.Button()
            b.set_relief(Gtk.ReliefStyle.NONE)
            b.get_style_context().add_class("folio-layoutcell")
            v = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            v.pack_start(win.layout_picture(part, 112), False, False, 0)
            l2 = Gtk.Label(label=name)
            l2.set_max_width_chars(16)
            l2.set_line_wrap(True)
            l2.set_justify(Gtk.Justification.CENTER)
            v.pack_start(l2, False, False, 0)
            b.add(v)
            b.set_tooltip_text(name)

            def go(_b, part=part):
                pop.popdown()
                GLib.idle_add(lambda: (win.run("%s:%s" % (action, part)), False)[1])
            b.connect("clicked", go)
            flow.add(b)
        box.pack_start(flow, False, False, 0)
    if action == "new-slide-layout":
        box.pack_start(Gtk.Separator(), False, False, 4)
        for label, cmd in (("Duplicate Selected Slides", "duplicate-slides"), ("Slides from Outline...", "slides-from-outline"),
                           ("Reuse Slides...", "reuse-slides")):
            b = Gtk.ModelButton(text=label)
            b.connect("clicked", lambda _b, c=cmd: (pop.popdown(), win.run(c)))
            box.pack_start(b, False, False, 0)
    sw = Gtk.ScrolledWindow()
    sw.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
    sw.set_propagate_natural_height(True)
    sw.set_propagate_natural_width(True)
    sw.set_max_content_height(560)
    sw.add(box)
    sw.show_all()
    pop.add(sw)
    return pop


def color_menu(win, cmd, none_label, more=True):
    ref = [None]

    def make():
        pop = Gtk.Popover()
        ref[0] = pop

        def pick(c):
            if c is None:
                win.run("%s:none" % cmd)
            else:
                r = split_ref(c)
                if r is not None and abs(r[1]) < 1e-6:
                    slot = ["bg1", "tx1", "bg2", "tx2", "accent1", "accent2", "accent3", "accent4", "accent5", "accent6"][r[0]]
                    win.run("%s:scheme:%s" % (cmd, slot))
                else:
                    win.run("%s:%06X" % (cmd, resolve(c) & 0xFFFFFF))
        pop.add(color_palette(pick, none_label=none_label, more=(lambda: win.run(cmd + ":more")) if more else None, popref=ref))
        return pop
    return make


def custom_shows_menu(win):
    from .show_ui import custom_shows_menu as m
    return m(win)


def build_ribbon(win):
    B = Builder(win)
    r = win.ribbon
    na = lambda name: "not-available:" + name  # noqa: E731

    # ================================================================ Home
    t = r.building(Tab("Home", "H"))
    B.group(t, "Clipboard", [
        B.big("Paste", "r-paste", "paste", "V", menu=[("Use Destination Theme", "paste", "r-paste-sm"),
                                                       ("Keep Text Only", "paste-text"), ("Picture", "paste-picture")]),
        [B.small("Cut", "r-cut-sm", "cut", "X"), B.small("Copy", "r-copy-sm", "copy", "C"),
         B.small("Format Painter", "r-format-painter-sm", "format-painter", "FP")],
    ], launcher="clipboard-pane", launcher_keytip="FO")
    new_slide = SplitButton(r, "New Slide", "insertslide", "new-slide", lambda: layouts_menu(win), size="large",
                            keytip="I", tooltip="New Slide (Ctrl+M)")
    layout_btn = MenuButton(r, "Layout", "assignlayout", lambda: layouts_menu(win, "set-layout"), size="small", keytip="L",
                            tooltip="Layout")
    B.group(t, "Slides", [
        new_slide,
        [layout_btn, B.small("Reset", "resetattributes", "reset-slide", "A",
                             tip="Reset: put placeholders back to their layout's position, size and formatting"),
         B.small("Section", "insertsection", None, "T", menu=[("Add Section", "add-section"), ("Rename Section", "rename-section"),
                                                             ("Remove Section", "remove-section"), None,
                                                             ("Collapse All", "collapse-sections"), ("Expand All", "expand-sections")])],
    ])
    win.font_combo = ComboControl(r, system_fonts(), lambda v: win.run("font-name:" + v), 14, state="font-name",
                                  keytip="FF", tooltip="Font (Ctrl+Shift+F)")
    win.size_combo = ComboControl(r, ["8", "9", "10", "10.5", "11", "12", "14", "16", "18", "20", "24", "28", "32", "36",
                                      "40", "44", "48", "54", "60", "66", "72", "80", "88", "96"],
                                  lambda v: win.run("font-size:" + v), 3, state="font-size", keytip="FS",
                                  tooltip="Font Size (Ctrl+Shift+P)")
    font_color = SplitButton(r, None, "r-font-color-sm", "font-color-last", color_menu(win, "font-color", "Automatic"),
                             size="icon", keytip="FC", tooltip="Font Color")
    win.font_color_button = font_color
    B.group(t, "Font", [
        [[win.font_combo, win.size_combo, B.icon("r-grow-sm", "font-grow", "FG", "Increase Font Size (Ctrl+])"),
          B.icon("r-shrink-sm", "font-shrink", "FK", "Decrease Font Size (Ctrl+[)"),
          B.icon("r-clear-sm", "clear-formatting", "E", "Clear All Formatting (Ctrl+Space)")],
         [B.icon("r-bold-sm", "bold", "1", "Bold (Ctrl+B)", state="bold"),
          B.icon("r-italic-sm", "italic", "2", "Italic (Ctrl+I)", state="italic"),
          B.icon("r-underline-sm", "underline", "3", "Underline (Ctrl+U)", state="underline"),
          B.icon("shadowed", "text-shadow", "5", "Text Shadow"),
          B.icon("strikeout", "strike", "4", "Strikethrough", state="strike"),
          B.icon("spacing", None, "K", "Character Spacing",
                 menu=[("Very Tight", "spacing:-3"), ("Tight", "spacing:-1.5"), ("Normal", "spacing:0"),
                       ("Loose", "spacing:3"), ("Very Loose", "spacing:6")]),
          B.icon("changecasetoupper", None, "7", "Change Case",
                 menu=[("Sentence case.", "case:sentence"), ("lowercase", "case:lower"), ("UPPERCASE", "case:upper"),
                       ("Capitalize Each Word", "case:title"), ("tOGGLE cASE", "case:toggle")]),
          SplitButton(r, None, "r-marker-color-sm", "highlight-last", color_menu(win, "highlight", "No Color", more=False),
                      size="icon", keytip="I", tooltip="Text Highlight Color"),
          font_color]],
    ], launcher="font-dialog", launcher_keytip="FN")
    B.group(t, "Paragraph", [
        [[B.icon("defaultbullet", "bullets", "U", "Bullets",
                 menu=[("None", "bullets:none"), ("Filled Round Bullets", "bullets:char:•"),
                       ("Hollow Round Bullets", "bullets:char:o|Courier New"), ("Filled Square Bullets", "bullets:char:▪"),
                       ("Hollow Square Bullets", "bullets:char:q|Wingdings"), ("Star Bullets", "bullets:char:★"),
                       ("Arrow Bullets", "bullets:char:➢"), ("Checkmark Bullets", "bullets:char:✔")]),
          B.icon("defaultnumbering", "numbering", "N", "Numbering",
                 menu=[("None", "numbering:none"), ("1. 2. 3.", "numbering:arabicPeriod"), ("1) 2) 3)", "numbering:arabicParenR"),
                       ("I. II. III.", "numbering:romanUcPeriod"), ("A. B. C.", "numbering:alphaUcPeriod"),
                       ("a) b) c)", "numbering:alphaLcParenR"), ("a. b. c.", "numbering:alphaLcPeriod"),
                       ("i. ii. iii.", "numbering:romanLcPeriod")]),
          B.icon("decrementindent", "level-down", "AO", "Decrease List Level (Shift+Tab)"),
          B.icon("incrementindent", "level-up", "AI", "Increase List Level (Tab)"),
          B.icon("linespacing" if icons.exists("linespacing") else "r-height-sm", None, "K", "Line Spacing",
                 menu=[("1.0", "line-spacing:1.0"), ("1.5", "line-spacing:1.5"), ("2.0", "line-spacing:2.0"),
                       ("2.5", "line-spacing:2.5"), ("3.0", "line-spacing:3.0")])],
         [B.icon("r-align-left-sm", "align:l", "AL", "Align Left (Ctrl+L)", state="algn-l"),
          B.icon("r-align-center-sm", "align:ctr", "AC", "Center (Ctrl+E)", state="algn-ctr"),
          B.icon("r-align-right-sm", "align:r", "AR", "Align Right (Ctrl+R)", state="algn-r"),
          B.icon("r-align-sm", "align:just", "AJ", "Justify (Ctrl+J)", state="algn-just"),
          B.icon("formatcolumns", None, "AN", "Add or Remove Columns",
                 menu=[("One Column", "columns:1"), ("Two Columns", "columns:2"), ("Three Columns", "columns:3")]),
          B.icon("textdirectiontoptobottom", None, "AD", "Text Direction",
                 menu=[("Horizontal", "text-direction:horz"), ("Rotate all text 90°", "text-direction:vert"),
                       ("Rotate all text 270°", "text-direction:vert270"), ("Stacked", "text-direction:wordArtVert")]),
          B.icon("r-align-middle-sm", None, "AT", "Align Text",
                 menu=[("Top", "anchor:t"), ("Middle", "anchor:ctr"), ("Bottom", "anchor:b")]),
          B.icon("r-smartart", "convert-smartart", "M", "Convert to SmartArt")]],
    ], launcher="paragraph-dialog", launcher_keytip="PG")
    shapes_btn = MenuButton(r, "Shapes", "r-shapes", lambda: shapes_gallery(win), size="large", keytip="SH")
    B.group(t, "Drawing", [
        shapes_btn,
        B.big("Arrange", "r-bring-forward", None, "G", menu=arrange_menu()),
        [SplitButton(r, "Shape Fill", "r-shape-fill-sm", "shape-fill-last", color_menu(win, "shape-fill", "No Fill"),
                     size="small", keytip="SF", tooltip="Shape Fill"),
         SplitButton(r, "Shape Outline", "r-shape-outline-sm", "shape-outline-last", color_menu(win, "shape-outline", "No Outline"),
                     size="small", keytip="SO", tooltip="Shape Outline"),
         B.small("Shape Effects", "r-effects-sm", None, "SE",
                 menu=[("Shadow: Outer Offset", "shape-shadow:on"), ("No Shadow", "shape-shadow:off")])],
    ])
    B.group(t, "Editing", [
        [B.small("Find", "searchdialog", "find", "FD", tip="Find (Ctrl+F)"),
         B.small("Replace", "r-find-select", "replace", "R", tip="Replace (Ctrl+H)"),
         B.small("Select", "selectall", None, "SL", menu=[("Select All", "select-all"), ("Select Objects", "select-objects"),
                                                         ("Selection Pane...", "selection-pane")])],
    ])
    r.add_tab(t)

    # ================================================================ Insert
    t = r.building(Tab("Insert", "N"))
    B.group(t, "Slides", [SplitButton(r, "New Slide", "insertslide", "new-slide", lambda: layouts_menu(win), size="large",
                                      keytip="I", tooltip="New Slide (Ctrl+M)")])
    B.group(t, "Tables", [MenuButton(r, "Table", "r-table", lambda: win.table_menu(), size="large", keytip="T")])
    B.group(t, "Images", [B.big("Pictures", "r-pictures", "insert-picture", "P"),
                          B.big("Screenshot", "r-screenshot", None, "SC",
                                menu=[("Screen Clipping", "screenshot:clip"), ("Whole Screen", "screenshot:screen")]),
                          B.big("Photo Album", "insertgraphic", "photo-album", "A")])
    B.group(t, "Illustrations", [MenuButton(r, "Shapes", "r-shapes", lambda: shapes_gallery(win), size="large", keytip="SH"),
                                 B.big("Icons", "insert-icons", "insert-icons", "Y"),
                                 B.big("SmartArt", "r-smartart", "insert-smartart", "M"),
                                 B.big("Chart", "r-chart-column-sm", "insert-chart", "C")])
    B.group(t, "Links", [B.big("Link", "r-link", "insert-link", "I", tip="Link (Ctrl+K)")])
    B.group(t, "Comments", [B.big("Comment", "r-new-comment", "new-comment", "L")])
    B.group(t, "Text", [B.big("Text Box", "r-text-box", "draw-textbox", "X"),
                        [B.small("Header & Footer", "r-header-footer", "header-footer", "H"),
                         B.small("WordArt", "r-wordart-sm", "wordart", "W"),
                         B.small("Date & Time", "insertdatetimefield" if icons.exists("insertdatetimefield") else "r-recent",
                                 "insert-date", "D")],
                        [B.small("Slide Number", "insertslidenumberfield", "insert-slide-number", "SN"),
                         B.small("Object", "insertobject", "insert-object", "J")]])
    B.group(t, "Symbols", [B.big("Equation", "r-equation", "insert-equation", "E"),
                           B.big("Symbol", "r-symbol", "insert-symbol", "U")])
    B.group(t, "Media", [B.big("Video", "insertvideo", None, "V", menu=[("This Device...", "insert-video")]),
                         B.big("Audio", "insertsound", None, "O", menu=[("Audio on My PC...", "insert-audio"), ("Record Audio...", "record-audio")]),
                         B.big("Screen Recording", "r-screenshot", "screen-recording", "R")])
    r.add_tab(t)

    # ================================================================ Draw
    t = r.building(Tab("Draw", "JI"))
    B.group(t, "Drawing Tools", [B.big("Select", "r-draw-select", "pointer", "S"),
                                 B.big("Pen", "r-draw-pen", "ink:pen", "P", menu=[("Black", "ink-color:000000"), ("Blue", "ink-color:0070C0"),
                                                                                  ("Red", "ink-color:C00000"), ("Green", "ink-color:00B050"), None,
                                                                                  ("0.5 pt", "ink-width:0.5"), ("1 pt", "ink-width:1"),
                                                                                  ("2.25 pt", "ink-width:2.25"), ("3.5 pt", "ink-width:3.5")]),
                                 B.big("Pen 2", "r-draw-pen", "ink:pen2", "P2"),
                                 B.big("Highlighter", "r-draw-highlighter", "ink:highlighter", "H",
                                       menu=[("Yellow", "ink-color:FFFF00"), ("Green", "ink-color:00FF00"), ("Pink", "ink-color:FF66CC"),
                                             ("Turquoise", "ink-color:00FFFF")]),
                                 B.big("Eraser", "r-draw-eraser", "ink:eraser", "E")])
    B.group(t, "Convert", [B.big("Ink to Shape", "r-ink-to-shape", "ink-to-shape", "IS")])
    r.add_tab(t)

    # ================================================================ Design
    from .more_ui import COLOR_SETS, FONT_SETS, THEMES, TRANSITIONS
    t = r.building(Tab("Design", "G"))
    B.group(t, "Themes", [B.big(name, "r-themes", "theme:" + name, "TH" if k == 0 else "T%d" % k, tip=name + " theme")
                          for k, (name, _c, _f) in enumerate(THEMES[:5])] +
            [B.big("More Themes", "r-themes", None, "TM", menu=[(n, "theme:" + n) for n, _c, _f in THEMES])])
    B.group(t, "Variants", [[B.small("Colors", "r-colors-sm", None, "TC", menu=[(n, "theme-colors:" + n) for n, _c in COLOR_SETS]),
                             B.small("Fonts", "r-fonts-sm", None, "TF", menu=[("%s (%s / %s)" % (n, a, b), "theme-fonts:" + n) for n, a, b in FONT_SETS]),
                             B.small("Background Styles", "r-background", "format-background", "BS")]])
    B.group(t, "Customize", [B.big("Slide Size", "slidesetup", None, "S",
                                   menu=[("Standard (4:3)", "slide-size:4:3"), ("Widescreen (16:9)", "slide-size:16:9"),
                                         None, ("Custom Slide Size...", "slide-size:custom")]),
                             B.big("Format Background", "r-background", "format-background", "B")])
    r.add_tab(t)

    # ================================================================ Transitions
    t = r.building(Tab("Transitions", "K"))
    B.group(t, "Preview", [B.big("Preview", "presentationcurrentslide", "transition-preview", "P")])
    tr_buttons = []
    for k, (kind, label, _o) in enumerate(TRANSITIONS):
        tr_buttons.append(RibbonButton(r, label, "slidechangewindow" if kind != "none" else "r-clear-sm", "transition:" + kind,
                                       size="large", state="tr-" + kind, keytip="T%d" % k if k else "TN",
                                       tooltip=label))
    B.group(t, "Transition to This Slide", tr_buttons +
            [MenuButton(r, "Effect Options", "r-effects-sm", lambda: _menu_pop(B, win.transition_options_menu()), size="large", keytip="E")])
    win.duration_spin = TimeSpin(win, "transition-duration", 0, 59, 0.75)
    win.after_spin = TimeSpin(win, "transition-after", 0, 86399, 0.0)
    win.click_check = CheckControl(r, "On Mouse Click", "transition-click", active=True, keytip="M")
    win.after_check = CheckControl(r, "After:", "transition-after", active=False, keytip="AF")
    B.group(t, "Timing", [[_labelled("Duration:", win.duration_spin), B.small("Apply To All", "r-format-painter-sm", "transition-apply-all", "L")],
                          [win.click_check, [win.after_check, win.after_spin]]])
    r.add_tab(t)

    # ================================================================ Animations
    from .more_ui import ENTRANCE, EMPHASIS, EXIT
    t = r.building(Tab("Animations", "A"))
    B.group(t, "Preview", [B.big("Preview", "presentationcurrentslide", "anim-preview", "P")])
    gallery = [RibbonButton(r, "None", "r-clear-sm", "anim:none", size="large", state="an-none", keytip="N0")]
    for k, (p, n) in enumerate(ENTRANCE[:8]):
        gallery.append(RibbonButton(r, n, "animationeffects", "anim:entr-%d" % p, size="large", state="an-entr-%d" % p,
                                    keytip="E%d" % k, tooltip=n + " (entrance)"))
    gallery.append(B.big("More Effects", "animationeffects", None, "AM", menu=win.anim_menu()))
    B.group(t, "Animation", gallery + [MenuButton(r, "Effect Options", "r-effects-sm", lambda: _menu_pop(B, win.anim_options_menu()),
                                                  size="large", keytip="EO")])
    B.group(t, "Advanced Animation", [B.big("Add Animation", "animationeffects", None, "AA", menu=win.anim_menu(add=True)),
                                      [B.small("Animation Pane", "animationeffects", "anim-pane", "C"),
                                       B.small("Trigger", "r-macros", "anim-trigger", "TR"),
                                       B.small("Animation Painter", "r-format-painter-sm", "anim-painter", "PA")]])
    win.anim_start_combo = AnimStart(win)
    win.anim_dur_spin = TimeSpin(win, "anim-duration", 0.01, 59, 0.5)
    win.anim_delay_spin = TimeSpin(win, "anim-delay", 0, 59, 0.0)
    B.group(t, "Timing", [[_labelled("Start:", win.anim_start_combo), _labelled("Duration:", win.anim_dur_spin),
                           _labelled("Delay:", win.anim_delay_spin)],
                          [B.small("Move Earlier", "r-bring-forward-sm", "anim-earlier", "ME"),
                           B.small("Move Later", "r-send-backward-sm", "anim-later", "ML")]])
    r.add_tab(t)

    # ================================================================ Slide Show
    t = r.building(Tab("Slide Show", "S"))
    B.group(t, "Start Slide Show", [B.big("From Beginning", "presentation", "show-start", "B", tip="From Beginning (F5)"),
                                    B.big("From Current Slide", "presentationcurrentslide", "show-current", "C",
                                          tip="From Current Slide (Shift+F5)"),
                                    B.big("Custom Slide Show", "customshowdialog", None, "W", menu=lambda: custom_shows_menu(win))])
    win.presenter_check = CheckControl(r, "Use Presenter View", "toggle-presenter-view",
                                       active=win.app.settings.get("presenter_view", True), keytip="UV")
    B.group(t, "Set Up", [B.big("Set Up Slide Show", "presentationdialog", "setup-show", "S"),
                          B.big("Hide Slide", "hideslide", "hide-slide", "H", tip="Hide Slide", ),
                          B.big("Rehearse Timings", "rehearsetimings", "rehearse-timings", "T")])
    B.group(t, "Monitors", [[win.presenter_check]])
    r.add_tab(t)

    # ================================================================ Record
    t = r.building(Tab("Record", "C"))
    B.group(t, "Record", [B.big("From Current Slide", "mediarecording" if icons.exists("mediarecording") else "insertvideo",
                                "record:current", "C"),
                          B.big("From Beginning", "insertvideo", "record:beginning", "B")])
    B.group(t, "Auto-Play Media", [B.big("Screen Recording", "r-screenshot", "screen-recording", "R"),
                                   B.big("Audio", "insertsound", "insert-audio", "A"), B.big("Video", "insertvideo", "insert-video", "V")])
    B.group(t, "Save", [B.big("Export to Video", "insertvideo", "create-video", "E")])
    r.add_tab(t)

    # ================================================================ Review
    t = r.building(Tab("Review", "R"))
    B.group(t, "Proofing", [B.big("Spelling", "r-spelling", "spelling", "S", tip="Spelling (F7)"),
                            [B.small("Thesaurus", "r-thesaurus-sm", "thesaurus", "E", tip="Thesaurus (Shift+F7)")]])
    B.group(t, "Accessibility", [B.big("Check Accessibility", "r-check-accessibility", "accessibility", "A")])
    B.group(t, "Comments", [B.big("New Comment", "r-new-comment", "new-comment", "C"),
                            B.big("Delete", "deleteannotation", None, "D",
                                  menu=[("Delete", "delete-comment"), ("Delete All Comments on This Slide", "delete-comments-slide"),
                                        ("Delete All Comments in This Presentation", "delete-comments-all")]),
                            [B.small("Previous", "previousannotation", "prev-comment", "V"),
                             B.small("Next", "nextannotation", "next-comment", "N")],
                            B.big("Show Comments", "showannotations", "show-comments", "H")])
    r.add_tab(t)

    # ================================================================ View
    t = r.building(Tab("View", "W"))
    B.group(t, "Presentation Views", [B.big("Normal", "r-view-normal", "view-normal", "L"),
                                      B.big("Outline View", "outlinemode", "view-outline", "PO"),
                                      B.big("Slide Sorter", "slidechangewindow", "view-sorter", "I"),
                                      B.big("Notes Page", "notesmode", "view-notes-page", "T"),
                                      B.big("Reading View", "read-mode", "view-reading", "D")])
    B.group(t, "Master Views", [B.big("Slide Master", "slidemasterpage", "view-slide-master", "M"),
                                B.big("Handout Master", "handoutmode", "view-handout-master", "H"),
                                B.big("Notes Master", "notesmasterpage", "view-notes-master", "N")])
    win.ruler_check = CheckControl(r, "Ruler", "toggle-ruler", keytip="R")
    win.grid_check = CheckControl(r, "Gridlines", "toggle-grid", keytip="GD")
    win.guides_check = CheckControl(r, "Guides", "toggle-guides", keytip="GU")
    B.group(t, "Show", [[win.ruler_check, win.grid_check, win.guides_check], B.big("Notes", "r-notes", "toggle-notes", "NO")])
    B.group(t, "Zoom", [B.big("Zoom", "r-zoom", "zoom-dialog", "Q"), B.big("Fit to Window", "zoomoptimal", "zoom-fit", "F")])
    B.group(t, "Window", [B.big("New Window", "r-new-window", "new-window", "W"),
                          [B.small("Arrange All", "r-arrange-all", "arrange-all", "A"),
                           B.small("Switch Windows", "r-switch-windows", "switch-windows", "S")]])
    B.group(t, "Macros", [B.big("Macros", "r-macros", "out-of-scope:Macros", "PM")])
    r.add_tab(t)

    build_master_tabs(win, r, B)
    from .chart_ui import chart_tab
    chart_tab(win, r, B, Tab)
    from .smartart_ui import smartart_tab
    smartart_tab(win, r, B, Tab)
    t = r.building(Tab("Playback", "JN", contextual=True))
    B.group(t, "Preview", [B.big("Play", "runbasic" if icons.exists("runbasic") else "presentation", "media-play", "P")])
    B.group(t, "Media Options", [B.big("Start", "presentation", None, "S",
                                       menu=[("On Click", "media-start:click"), ("Automatically", "media-start:auto")])])
    r.add_tab(t)

    # ================================================================ Help
    t = r.building(Tab("Help", "Y"))
    B.group(t, "Help", [B.big("Help", "r-help", "help", "H"), B.big("Keyboard Shortcuts", "r-help", "shortcuts", "K"),
                        B.big("About", "r-help", "about", "A")])
    r.add_tab(t)

    # ================================================================ Shape Format (contextual)
    t = r.building(Tab("Shape Format", "JD", contextual=True))
    B.group(t, "Insert Shapes", [MenuButton(r, "Shapes", "r-shapes", lambda: shapes_gallery(win), size="large", keytip="SH"),
                                 B.big("Text Box", "r-text-box", "draw-textbox", "X")])
    B.group(t, "Shape Styles", [[SplitButton(r, "Shape Fill", "r-shape-fill-sm", "shape-fill-last", color_menu(win, "shape-fill", "No Fill"),
                                             size="small", keytip="SF", tooltip="Shape Fill"),
                                 SplitButton(r, "Shape Outline", "r-shape-outline-sm", "shape-outline-last",
                                             color_menu(win, "shape-outline", "No Outline"), size="small", keytip="SO",
                                             tooltip="Shape Outline"),
                                 B.small("Shape Effects", "r-effects-sm", None, "SE",
                                         menu=[("Shadow: Outer Offset", "shape-shadow:on"), ("No Shadow", "shape-shadow:off")])]],
            launcher="format-shape", launcher_keytip="FO")
    B.group(t, "WordArt Styles", [[SplitButton(r, "Text Fill", "r-font-color-sm", "font-color-last", color_menu(win, "font-color", "Automatic"),
                                               size="small", keytip="TI", tooltip="Text Fill")]])
    B.group(t, "Arrange", [[B.small("Bring Forward", "r-bring-forward-sm", "order:forward", "AF",
                                    menu=[("Bring Forward", "order:forward"), ("Bring to Front", "order:front")]),
                            B.small("Send Backward", "r-send-backward-sm", "order:backward", "AE",
                                    menu=[("Send Backward", "order:backward"), ("Send to Back", "order:back")]),
                            B.small("Selection Pane", "r-selection-pane", "selection-pane", "AP")],
                           [B.small("Align", "alignleft", None, "AA", menu=align_menu()),
                            B.small("Group", "r-group-sm", None, "G", menu=[("Group", "group"), ("Ungroup", "ungroup")]),
                            B.small("Rotate", "r-rotate-sm", None, "AY", menu=rotate_menu())]])
    win.height_spin = SizeSpin(win, "h")
    win.width_spin = SizeSpin(win, "w")
    B.group(t, "Size", [[_labelled("Height:", win.height_spin), _labelled("Width:", win.width_spin)]],
            launcher="format-shape", launcher_keytip="SZ")
    r.add_tab(t)

    # ================================================================ Table Design / Layout (contextual)
    t = r.building(Tab("Table Design", "JT", contextual=True))
    win.table_checks = {}
    opts = [("Header Row", "firstRow"), ("Total Row", "lastRow"), ("Banded Rows", "bandRow"),
            ("First Column", "firstCol"), ("Last Column", "lastCol"), ("Banded Columns", "bandCol")]
    for label, key in opts:
        win.table_checks[key] = CheckControl(r, label, "table-option:" + key, state="tbl-" + key, keytip=label[:1] + label.split()[-1][:1])
    B.group(t, "Table Style Options", [[win.table_checks[k] for _l, k in opts[:3]], [win.table_checks[k] for _l, k in opts[3:]]])
    B.group(t, "Table Styles", [[SplitButton(r, "Shading", "r-fill-color-sm", "table-shading:scheme:accent1",
                                             color_menu(win, "table-shading", "No Fill"), size="small", keytip="H", tooltip="Shading")]])
    r.add_tab(t)
    t = r.building(Tab("Table Layout", "JL", contextual=True))
    B.group(t, "Table", [B.big("Select", "selectall", "select-table", "K")])
    B.group(t, "Rows & Columns", [B.big("Delete", "r-delete-cells", None, "D",
                                        menu=[("Delete Columns", "table-delete:cols"), ("Delete Rows", "table-delete:rows"),
                                              ("Delete Table", "table-delete:table")]),
                                  B.big("Insert Above", "r-insert-cells", "table-insert:above", "A"),
                                  B.big("Insert Below", "r-insert-cells", "table-insert:below", "BE"),
                                  [B.small("Insert Left", "r-insert-cells", "table-insert:left", "L"),
                                   B.small("Insert Right", "r-insert-cells", "table-insert:right", "R")]])
    B.group(t, "Alignment", [[B.icon("r-align-left-sm", "align:l", "AL", "Align Left"), B.icon("r-align-center-sm", "align:ctr", "AC", "Center"),
                              B.icon("r-align-right-sm", "align:r", "AR", "Align Right")]])
    r.add_tab(t)

    # ================================================================ Picture Format (contextual)
    t = r.building(Tab("Picture Format", "JP", contextual=True))
    B.group(t, "Adjust", [B.big("Change Picture", "r-pictures", "change-picture", "CP"),
                          B.big("Reset Picture", "resetattributes", "picture-reset", "Q",
                                menu=[("Reset Picture", "picture-reset"), ("Reset Picture & Size", "picture-reset-size")])])
    B.group(t, "Picture Styles", [[SplitButton(r, "Picture Border", "r-shape-outline-sm", "shape-outline-last",
                                               color_menu(win, "shape-outline", "No Outline"), size="small", keytip="PB",
                                               tooltip="Picture Border")]])
    B.group(t, "Arrange", [[B.small("Bring Forward", "r-bring-forward-sm", "order:forward", "AF"),
                            B.small("Send Backward", "r-send-backward-sm", "order:backward", "AE"),
                            B.small("Selection Pane", "r-selection-pane", "selection-pane", "AP")],
                           [B.small("Align", "alignleft", None, "AA", menu=align_menu()),
                            B.small("Group", "r-group-sm", None, "G", menu=[("Group", "group"), ("Ungroup", "ungroup")]),
                            B.small("Rotate", "r-rotate-sm", None, "AY", menu=rotate_menu())]])
    B.group(t, "Size", [B.big("Crop", "crop", "crop", "C",
                                    menu=[("Crop", "crop"), ("#", "Aspect Ratio"), ("Square 1:1", "crop-aspect:1:1"),
                                     ("Landscape 4:3", "crop-aspect:4:3"), ("Landscape 16:9", "crop-aspect:16:9"),
                                     ("Portrait 3:4", "crop-aspect:3:4"), None, ("Reset Crop", "crop-reset")]),
                        [_labelled("Height:", SizeSpin(win, "h")), _labelled("Width:", SizeSpin(win, "w"))]])
    r.add_tab(t)


def arrange_menu():
    return [("#", "Order Objects"), ("Bring to Front", "order:front"), ("Send to Back", "order:back"),
            ("Bring Forward", "order:forward"), ("Send Backward", "order:backward"),
            ("#", "Group Objects"), ("Group", "group"), ("Ungroup", "ungroup"),
            ("#", "Position Objects"), ("Align", align_menu()), ("Rotate", rotate_menu()), None,
            ("Selection Pane...", "selection-pane")]


def align_menu():
    return [("Align Left", "align-obj:left"), ("Align Center", "align-obj:center"), ("Align Right", "align-obj:right"),
            ("Align Top", "align-obj:top"), ("Align Middle", "align-obj:middle"), ("Align Bottom", "align-obj:bottom"), None,
            ("Distribute Horizontally", "align-obj:dist-h"), ("Distribute Vertically", "align-obj:dist-v"), None,
            ("Align to Slide", "align-to:slide"), ("Align Selected Objects", "align-to:objects")]


def rotate_menu():
    return [("Rotate Right 90°", "rotate:90"), ("Rotate Left 90°", "rotate:-90"),
            ("Flip Vertical", "flip:v"), ("Flip Horizontal", "flip:h")]


def _labelled(text, w):
    b = Gtk.Box(spacing=4)
    b.pack_start(Gtk.Label(label=text, xalign=0, width_chars=7), False, False, 0)
    b.pack_start(w, False, False, 0)
    return b


class SizeSpin(Gtk.SpinButton):
    """Height / Width of the selected object, in inches as the original shows them."""
    def __init__(self, win, which):
        adj = Gtk.Adjustment(value=1, lower=0.01, upper=56, step_increment=0.1, page_increment=1)
        Gtk.SpinButton.__init__(self, adjustment=adj, digits=2)
        self.win = win
        self.which = which
        self.set_width_chars(6)
        self.quiet = False
        self.connect("value-changed", self._changed)
        if not hasattr(win, "size_spins"):
            win.size_spins = []
        win.size_spins.append(self)

    def _changed(self, *_):
        if not self.quiet:
            self.win.run("size-%s:%.4f" % (self.which, self.get_value()))

    def show_value(self, inches):
        self.quiet = True
        self.set_value(inches)
        self.quiet = False


def _menu_pop(B, items):
    """A menu built when it opens (its items depend on the slide)."""
    return menu_popover(None, B.menu(items))


class TimeSpin(Gtk.SpinButton):
    """Seconds, shown as PowerPoint shows them (00.75)."""
    def __init__(self, win, cmd, lo, hi, value):
        adj = Gtk.Adjustment(value=value, lower=lo, upper=hi, step_increment=0.25, page_increment=1)
        Gtk.SpinButton.__init__(self, adjustment=adj, digits=2)
        self.win = win
        self.cmd = cmd
        self.quiet = False
        self.set_width_chars(6)
        self.connect("value-changed", self._changed)

    def _changed(self, *_):
        if not self.quiet:
            self.win.run("%s:%.2f" % (self.cmd, self.get_value()))


class AnimStart(Gtk.ComboBoxText):
    """Animations > Timing > Start: On Click, With Previous, After Previous."""
    def __init__(self, win):
        Gtk.ComboBoxText.__init__(self)
        self.win = win
        self.quiet = False
        for k, t in (("click", "On Click"), ("with", "With Previous"), ("after", "After Previous")):
            self.append(k, t)
        self.set_active_id("click")
        self.connect("changed", lambda c: None if self.quiet else win.run("anim-start:" + c.get_active_id()))


def build_master_tabs(win, r, B):
    """Slide Master, Notes Master and Handout Master: shown while that view is open."""
    from .more_ui import COLOR_SETS, FONT_SETS, THEMES
    t = r.building(Tab("Slide Master", "M", contextual=True))
    B.group(t, "Edit Master", [B.big("Insert Slide Master", "insertmasterpage", "master-insert", "A"),
                               B.big("Insert Layout", "insertslide", "master-insert-layout", "I"),
                               [B.small("Delete", "deletemasterpage", "master-delete", "D"),
                                B.small("Rename", "renamemasterpage", "master-rename", "R"),
                                B.small("Preserve", "masterpage", "master-preserve", "P")]])
    B.group(t, "Master Layout", [B.big("Master Layout", "masterlayouts", "master-layout-dialog", "M"),
                                 B.big("Insert Placeholder", "insertslide", None, "C",
                                       menu=[("Content", "master-placeholder:obj"), ("Text", "master-placeholder:body"),
                                             ("Picture", "master-placeholder:pic"), ("Chart", "master-placeholder:chart"),
                                             ("Table", "master-placeholder:tbl"), ("Media", "master-placeholder:media"),
                                             ("Online Image", "master-placeholder:clipArt")]),
                                 [CheckControl(r, "Title", "master-title", active=True, state="master-title", keytip="T"),
                                  CheckControl(r, "Footers", "master-footers", active=True, state="master-footers", keytip="F")]])
    B.group(t, "Edit Theme", [B.big("Themes", "r-themes", None, "H", menu=[(n, "theme:" + n) for n, _c, _f in THEMES]),
                              [B.small("Colors", "r-colors-sm", None, "TC", menu=[(n, "theme-colors:" + n) for n, _c in COLOR_SETS]),
                               B.small("Fonts", "r-fonts-sm", None, "TF", menu=[("%s (%s / %s)" % (n, a, b), "theme-fonts:" + n) for n, a, b in FONT_SETS])]])
    B.group(t, "Background", [B.big("Background Styles", "backgroundcolor", "format-background", "B"),
                              [CheckControl(r, "Hide Background Graphics", "master-hide-bg", state="master-hide-bg", keytip="G")]])
    B.group(t, "Size", [B.big("Slide Size", "slidesetup", None, "S",
                              menu=[("Standard (4:3)", "slide-size:4:3"), ("Widescreen (16:9)", "slide-size:16:9"),
                                    None, ("Custom Slide Size...", "slide-size:custom")])])
    B.group(t, "Close", [B.big("Close Master View", "closemasterview", "close-master", "C")])
    r.add_tab(t)

    for name, key, items in (("Notes Master", "N", [("hdr", "Header"), ("sldImg", "Slide Image"), ("ftr", "Footer"),
                                                     ("dt", "Date"), ("body", "Body"), ("sldNum", "Page Number")]),
                             ("Handout Master", "H", [("hdr", "Header"), ("dt", "Date"), ("ftr", "Footer"), ("sldNum", "Page Number")])):
        t = r.building(Tab(name, key, contextual=True))
        if name == "Handout Master":
            B.group(t, "Page Setup", [B.big("Slides Per Page", "showmultiplepages", None, "P",
                                            menu=[("1 Slide", "handout-per-page:1"), ("2 Slides", "handout-per-page:2"),
                                                  ("3 Slides", "handout-per-page:3"), ("4 Slides", "handout-per-page:4"),
                                                  ("6 Slides", "handout-per-page:6"), ("9 Slides", "handout-per-page:9")])])
        checks = [CheckControl(r, label, "nm-toggle:" + k, active=True, state="nm-" + k) for k, label in items]
        B.group(t, "Placeholders", [checks[:3], checks[3:]])
        B.group(t, "Background", [B.big("Background Styles", "backgroundcolor", "format-background", "B")])
        B.group(t, "Close", [B.big("Close Master View", "closemasterview", "close-master", "C")])
        r.add_tab(t)

# Run inside Folio Show (FOLIO_TEST_SCRIPT): charts and SmartArt.
import os
import sys
import tempfile
import time
import traceback

from gi.repository import Gdk, GLib, Gtk

FAILS = []
OUT = os.environ.get("UI_OUT", "/tmp/ui_out")
os.makedirs(OUT, exist_ok=True)


def pump(t=0.15):
    end = time.time() + t
    while time.time() < end:
        while Gtk.events_pending():
            Gtk.main_iteration_do(False)
        time.sleep(0.003)


def check(cond, what):
    print(("ok   " if cond else "FAIL ") + what)
    sys.stdout.flush()
    if not cond:
        FAILS.append(what)


def shot(name):
    import cairo
    win.queue_draw()
    pump(0.5)
    al = win.get_allocation()
    img = cairo.ImageSurface(cairo.FORMAT_ARGB32, al.width, al.height)
    win.draw(cairo.Context(img))
    img.write_to_png(os.path.join(OUT, name + ".png"))


class Ev:
    """A stand-in for a GDK event (the handlers read only these fields)."""
    def __init__(self, **kw):
        self.__dict__.update(kw)


def key(name, ctrl=False, shift=False, alt=False, widget=None):
    st = 0
    if ctrl:
        st |= Gdk.ModifierType.CONTROL_MASK
    if shift:
        st |= Gdk.ModifierType.SHIFT_MASK
    if alt:
        st |= Gdk.ModifierType.MOD1_MASK
    ev = Ev(keyval=Gdk.keyval_from_name(name), state=Gdk.ModifierType(st), type=Gdk.EventType.KEY_PRESS)
    if widget is not None:
        widget.grab_focus()
    r = win.on_key(win, ev)
    pump(0.05)

def click(x, y, button=1, double=False, shift=False, ctrl=False, release=True, dx=0, dy=0):
    """Press (and drag, release) on the canvas at pixel x, y."""
    a = win.canvas.area
    st = Gdk.ModifierType((Gdk.ModifierType.SHIFT_MASK if shift else 0) | (Gdk.ModifierType.CONTROL_MASK if ctrl else 0))
    ev = Ev(type=Gdk.EventType._2BUTTON_PRESS if double else Gdk.EventType.BUTTON_PRESS, x=float(x), y=float(y),
            button=button, state=st)
    win.canvas.on_press(a, ev)
    if dx or dy:
        for k in range(1, 6):
            m = Ev(type=Gdk.EventType.MOTION_NOTIFY, x=float(x + dx * k / 5), y=float(y + dy * k / 5),
                   state=Gdk.ModifierType(st | Gdk.ModifierType.BUTTON1_MASK))
            win.canvas.on_motion(a, m)
    if release:
        r = Ev(type=Gdk.EventType.BUTTON_RELEASE, x=float(x + dx), y=float(y + dy), button=button, state=st)
        win.canvas.on_release(a, r)
    pump(0.08)


def px(sx, sy):
    return win.canvas.to_px(sx, sy)


def ph(kind):
    for s in win.canvas.shapes:
        if s["ph"] == kind:
            return s
    return None


def typ(text):
    for ch in text:
        if ch == "\n":
            key("Return")
        else:
            win.canvas.type_text(ch)
    pump(0.05)



try:
    pump(0.5)
    d = win.deck
    win.run("new-slide")
    pump(0.2)
    c = win.canvas
    c._surface()
    # a chart into the content placeholder
    ref = win.run("insert-chart:0")
    pump(0.4)
    check(ref is not None and ref.part and ref.part.startswith("ppt/charts/chart"), "Insert Chart: clustered column")
    c._surface()
    s = c.shape(ref.sid)
    check(s is not None and s["geom"] == "chart", "the chart is on the slide")
    check(win.ribbon.tab_by_name("Chart Design").button.get_visible(), "Chart Design tab shows")
    sheets = [w for w in Gtk.Window.list_toplevels() if w.__class__.__name__ == "DataSheet"]
    check(len(sheets) == 1, "the data sheet opens")
    sheet = sheets[0]
    sheet.edited(None, "1", "9.5", 1)
    pump(0.2)
    import folio_deliver.charts_model as CM
    check(abs(CM.get_data(CM.selected(win))["values"][0][0] - 9.5) < 1e-6, "typing in the data sheet changes the chart")
    shot("60_chart")
    sheet.destroy()
    win.run("chart:set_legend:right")
    check(CM.model_of(CM.selected(win))["legend"] == "right", "legend on the right")
    win.run("chart:set_data_labels:outside-end")
    win.run("chart:quick_layout:1")
    win.run("chart:set_chart_style:2")
    win.run("chart:colors:3")
    win.run("chart:switch")
    dd = CM.get_data(CM.selected(win))
    check(len(dd["rows"]) == 3 and len(dd["cols"]) == 4, "Switch Row/Column")
    import folio_deliver.charts_classic as CC
    CC.type_dialog = lambda *a, **k: 5
    win.run("chart:type")
    check(CM.type_index(CM.selected(win)) == 5, "Change Chart Type: pie")
    xlsx = d.chart_workbook(ref.part)
    check(xlsx is not None and xlsx[:2] == b"PK", "the chart's workbook is kept")
    w_, h_, st_, data_, _sh = d.render(1, 0.5, False)
    check(len(data_) > 0, "the slide with the chart renders")
    win.run("undo")
    check(CM.type_index(CM.selected(win)) == 0, "undo the type change")
    # SmartArt
    win.run("new-slide")
    pump(0.2)
    c._surface()
    import folio_deliver.smartart_ui as SU
    sid = win.run("insert-smartart:3")
    pump(0.3)
    c._surface()
    s = c.shape(sid)
    check(s is not None and s["geom"] == "smartart", "Insert SmartArt: Basic Process")
    pane = win.smartart_pane
    check(pane is not None, "the text pane opens")
    pane.view.get_buffer().set_text("Plan\nBuild\n\tTest it\nShip")
    pane.flush()
    pump(0.2)
    m = win.smartart_model(sid)
    check(m["items"] == [(0, "Plan"), (0, "Build"), (1, "Test it"), (0, "Ship")] and m["layout"] == 3, "text pane items: %s" % m["items"])
    shot("61_smartart")
    pane.destroy()
    c.select([sid])
    win.selection_changed()
    check(win.ribbon.tab_by_name("SmartArt Design").button.get_visible(), "SmartArt Design tab shows")
    for k in range(len(__import__("folio_deliver.smartart", fromlist=["x"]).LAYOUTS)):
        win.run("smartart:layout:%d" % k)
        w_, h_, st_, data_, _sh = d.render(2, 0.3, False)
    check(win.smartart_model(sid)["layout"] == 9, "every layout draws")
    win.run("smartart:layout:6")
    win.run("smartart:colors:0")
    win.run("smartart:style:3")
    m = win.smartart_model(sid)
    check(m["layout"] == 6 and m["colors"] == 0 and m["style"] == 3, "layout, colours and style change")
    shot("62_hierarchy")
    win.run("smartart:add:after")
    check(len(win.smartart_model(sid)["items"]) == 5, "Add Shape")
    # Convert to SmartArt
    win.run("new-slide")
    pump(0.2)
    c._surface()
    body = [x for x in c.shapes if x["ph"] not in ("title", None)][0]
    d.set_text(win.current, body["id"], "Research\nDesign\nLaunch")
    win.changed(slide=True)
    c._surface()
    c.select([body["id"]])
    new = win.run("convert-smartart")
    c._surface()
    check(new is not None and win.smartart_model(new)["items"] == [(0, "Research"), (0, "Design"), (0, "Launch")], "Convert to SmartArt")
    path = os.path.join(tempfile.mkdtemp(), "objects.pptx")
    check(win.save_to(path), "save")
    import zipfile
    z = zipfile.ZipFile(path)
    names = z.namelist()
    check(any(n.startswith("ppt/diagrams/data") for n in names) and any(n.startswith("ppt/diagrams/drawing") for n in names)
          and any(n.startswith("ppt/charts/chart") for n in names) and any(n.startswith("ppt/embeddings/") for n in names),
          "chart and SmartArt parts saved")
    from folio_deliver.core import Presentation
    q = Presentation.open(path)
    check(q.chart_part(1, ref.sid) is not None and q.diagram_parts(2, sid) is not None, "reopen keeps the chart and SmartArt")
    print("saved", path)
except Exception:
    traceback.print_exc()
    FAILS.append("exception")
print("UI FAILED: %d" % len(FAILS) if FAILS else "UI all passed")
sys.stdout.flush()
win.deck.modified = False
os._exit(1 if FAILS else 0)

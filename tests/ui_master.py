# Run inside Folio Deliver (FOLIO_TEST_SCRIPT): Slide Master, Notes Master and Handout Master views.
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
    base = d.design_base()

    def lname(part):
        return [x[3] for x in d.design_parts() if x[1] == part][0]
    lay = d.slide_layout(1)
    win.run("view-slide-master")
    pump(0.4)
    check(win.master_mode == "slide" and win.normal_paned.get_child1() is win.design_pane, "Slide Master view opens")
    check(win.design_part() == lay, "at the current slide's layout")
    check(win.ribbon.current.name == "Slide Master", "the Slide Master tab")
    shot("40_slide_master")
    dp = d.design_parts()
    masters = [x for x in dp if x[2] == "master"]
    check(len(masters) == 1 and len([x for x in dp if x[2] == "layout"]) == 11, "one master, eleven layouts")
    # edit the master's title style: bold, shows on the slides
    win.design_go(masters[0][0])
    c._surface()
    t = [s for s in c.shapes if s["ph"] == "title"][0]
    c.start_text(t["id"])
    win.run("select-all")
    win.run("bold")
    c.leave_text()
    pump(0.2)
    # a new layout with a picture placeholder
    win.run("master-insert-layout")
    part = win.design_part()
    check("slideLayouts/" in part and lname(part) == "Custom Layout", "Insert Layout")
    check("title" in d.design_placeholders(part) and "ftr" in d.design_placeholders(part), "with a title and footers")
    win.run("master-placeholder:pic")
    check(c.insert_mode == ("placeholder", "pic"), "Insert Placeholder: Picture")
    x0, y0 = c.to_px(100, 150)
    click(x0, y0, dx=300 * c.scale, dy=200 * c.scale)
    check("pic" in d.design_placeholders(part), "picture placeholder drawn")
    win.dialogs.ask_text = lambda *a, **k: "Photo Page"
    win.run("master-rename")
    check(lname(part) == "Photo Page", "Rename Layout")
    # Footers off
    for ctl in win.ribbon.controls:
        if ctl.state_key == "master-footers":
            ctl.set_active(False)
    check("ftr" not in d.design_placeholders(part), "Footers unchecked removes them")
    for ctl in win.ribbon.controls:
        if ctl.state_key == "master-hide-bg":
            ctl.set_active(True)
    check(not d.shows_master_shapes(part), "Hide Background Graphics")
    shot("41_custom_layout")
    # duplicate, delete
    win.run("master-duplicate")
    dup = win.design_part()
    check(dup != part and lname(dup) == "1_Photo Page", "Duplicate Layout")
    win.run("master-delete")
    check(dup not in [x[1] for x in d.design_parts()], "Delete an unused layout")
    # a used layout can't be deleted
    infos = []
    win.dialogs.info = lambda text, *a, **k: infos.append(text)
    k_used = [x for x in d.design_parts() if x[1] == lay][0][0]
    win.design_go(k_used)
    win.run("master-delete")
    check(lay in [x[1] for x in d.design_parts()] and infos and "used by" in infos[-1], "a used layout is kept")
    # a second master
    win.run("master-insert")
    m2 = win.design_part()
    check("slideMasters/" in m2 and len([x for x in d.design_parts() if x[2] == "master"]) == 2, "Insert Slide Master")
    win.run("master-delete")
    check(len([x for x in d.design_parts() if x[2] == "master"]) == 1, "delete the unused master")
    # slide commands wait for Close Master View
    n = d.slide_count()
    win.run("new-slide")
    check(d.slide_count() == n, "New Slide is not offered in master view")
    win.run("close-master")
    pump(0.3)
    check(win.master_mode is None and win.normal_paned.get_child1() is win.pane and win.current == 1, "Close Master View")
    c._surface()
    t = [s for s in c.shapes if s["ph"] == "title"][0]
    c.start_text(t["id"], (0, 0))
    typ("Bold title")
    rp = d.run_props(1, t["id"], 0, 2)
    check(rp["b"], "the master's bold title shows on the slide")
    c.leave_text()
    # the new layout is offered for new slides
    names = [n for _m, ls in d.layouts() for _p, n in ls]
    check("Photo Page" in names, "the new layout in the layouts list")
    win.run("new-slide-layout:" + part)
    pump(0.2)
    c._surface()
    check(any(s["ph"] == "pic" for s in c.shapes), "a slide on the new layout has its picture placeholder")
    shot("42_slide_on_layout")

    # Notes Master
    win.run("view-notes-master")
    pump(0.3)
    nm = win.design_part()
    check(win.master_mode == "notes" and "notesMaster" in nm, "Notes Master view")
    pw, ph = d.page_size(nm)
    check(abs(pw - 540) < 1 and abs(ph - 720) < 1, "on the notes page size")
    for ctl in win.ribbon.controls:
        if ctl.state_key == "nm-hdr":
            ctl.set_active(False)
            ctl.set_active(True)
    check("hdr" in d.design_placeholders(nm), "Header placeholder")
    shot("43_notes_master")
    win.run("close-master")
    # Handout Master
    win.run("view-handout-master")
    pump(0.3)
    hm = win.design_part()
    check(win.master_mode == "handout" and "handoutMaster" in hm, "Handout Master view")
    win.run("handout-per-page:4")
    shot("44_handout_master")
    for ctl in win.ribbon.controls:
        if ctl.state_key == "nm-dt":
            ctl.set_active(False)
    check("dt" not in d.design_placeholders(hm), "Date unchecked")
    win.run("close-master")
    check(win.master_mode is None, "back to Normal view")
    win.run("undo")
    path = os.path.join(tempfile.mkdtemp(), "master.pptx")
    check(win.save_to(path), "save")
    from folio_deliver.core import Presentation
    q = Presentation.open(path)
    check("Photo Page" in [n for _m, ls in q.layouts() for _p, n in ls], "reopen keeps the new layout")
    check(any("handoutMaster" in x[1] for x in q.design_parts()), "and the handout master")
    print("saved", path)
except Exception:
    traceback.print_exc()
    FAILS.append("exception")
print("UI FAILED: %d" % len(FAILS) if FAILS else "UI all passed")
sys.stdout.flush()
win.deck.modified = False
os._exit(1 if FAILS else 0)

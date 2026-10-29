# Run inside Folio Show (FOLIO_TEST_SCRIPT): drives the window as a user would and checks the results.
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
    pump(0.3)
    gw = win.get_window()
    img = cairo.ImageSurface(cairo.FORMAT_ARGB32, gw.get_width(), gw.get_height())
    cr = cairo.Context(img)
    Gdk.cairo_set_source_window(cr, gw, 0, 0)
    cr.paint()
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
    return r


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
    title = ph("title")
    body = ph("body")
    sid = d.add_shape(1, "ellipse", 600, 300, 120, 120)
    win.changed(slide=True)
    c._surface()
    c.select([title["id"]])
    win.run("anim:entr-10")
    pump(1.0)
    fx = d.animations(1)
    check(len(fx) == 1 and fx[0]["name"] == "Fade" and fx[0]["class"] == "entr", "Fade on the title: %s" % fx)
    c.select([body["id"]])
    win.run("anim:entr-2")
    win.run("anim-option:8")
    fx = d.animations(1)
    check(fx[1]["preset"] == 2 and fx[1]["subtype"] == 8, "Fly In from the left")
    c.select([sid])
    win.run("anim:entr-53")
    win.run("anim-start:after")
    win.run("anim-duration:1.25")
    win.run("anim-delay:0.50")
    fx = d.animations(1)
    check(fx[2]["trigger"] == "after" and abs(fx[2]["dur"] - 1.25) < 0.01 and abs(fx[2]["delay"] - 0.5) < 0.01,
          "after previous, 1.25 s, 0.5 s delay: %s" % fx[2])
    win.run("anim-add:emph-8")
    fx = d.animations(1)
    check(len(fx) == 4 and fx[3]["name"] == "Spin", "Add Animation adds a second effect")
    win.run("anim-earlier")
    check(d.animations(1)[2]["name"] == "Spin", "Move Earlier")
    win.run("anim-later")
    win.run("tab:Animations")
    win.run("anim-pane")
    pump(0.3)
    shot("21_anim_tab")
    win.run("anim-pane")
    # the show: shapes appear click by click
    from folio_deliver.anim import Player
    pl = Player(d, 1)
    check([len(g) for g in pl.groups] == [1, 2, 1] and pl.clicks() == 3, "three click groups: %s" % [len(g) for g in pl.groups])
    s0 = pl.state(0)
    check(s0[title["id"]][6] and s0[sid][6], "entrance objects start hidden")
    s1 = pl.state(1)
    check(not s1[title["id"]][6] and s1[title["id"]][0] == 1.0 and s1[sid][6], "after the first click the title shows")
    mid = pl.state(1, 1, 0.25)
    check(mid[body["id"]][1] < 0, "Fly In from the left starts off to the left")
    win.go_slide(1)
    win.run("show-current")
    st = win.show_state
    pump(0.3)
    check(st.step == 0 and st.index == 1, "show at the first step")
    st.next()
    pump(0.8)
    check(st.step == 1, "a click plays the first group")
    st.next()
    st.next()
    check(st.step == 2, "a click during an animation finishes it")
    st.prev()
    check(st.step == 1, "back one step")
    st.end()
    pump(0.3)
    path = os.path.join(tempfile.mkdtemp(), "anim.pptx")
    check(win.save_to(path), "save")
    from folio_deliver.core import Presentation
    q = Presentation.open(path)
    check([e["name"] for e in q.animations(1)] == ["Fade", "Fly In", "Zoom", "Spin"], "reopen keeps the effects")
    win.run("anim:none")
    check(len(d.animations(1)) == 2, "None removes the selected object's effects")
    print("saved", path)
except Exception:
    traceback.print_exc()
    FAILS.append("exception")
print("UI FAILED: %d" % len(FAILS) if FAILS else "UI all passed")
sys.stdout.flush()
win.deck.modified = False
os._exit(1 if FAILS else 0)

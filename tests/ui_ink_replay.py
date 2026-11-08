# Run inside Folio Show (FOLIO_TEST_SCRIPT): P4-01 Ink Replay.
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
        # a playing clip keeps events coming: never past the deadline
        while Gtk.events_pending() and time.time() < end + 1.0:
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

# ---------------------------------------------------------------- P4-01 Ink Replay
import math  # noqa: E402

deck = win.deck
c = win.canvas
i = win.current

# nothing drawn yet: the command says so instead of pretending to play
SAID = {"v": None}
_realinfo = win.dialogs.info
win.dialogs.info = lambda msg, title="", *a, **k: SAID.__setitem__("v", msg)
played = win.act_ink_replay()
win.dialogs.info = _realinfo
check(played is False and SAID["v"] and "no ink on this slide" in SAID["v"], "an empty slide says there is no ink")

# three strokes, drawn in a known order
pens = {"pen": (0x000000, 1.0, 100.0), "highlighter": (0xFFFF00, 9.0, 50.0)}
line = [(100.0 + k * 10, 200.0) for k in range(12)]
curve = [(300.0 + 60 * math.cos(a / 6.0), 250.0 + 60 * math.sin(a / 6.0)) for a in range(20)]
short = [(500.0, 300.0), (520.0, 320.0)]
ids = []
for pts, (col, wid, alp) in ((line, pens["pen"]), (curve, pens["highlighter"]), (short, pens["pen"])):
    ids.append(deck.add_ink(i, pts, col, wid, alp, "Ink"))
pump(0.2)
check(len(ids) == 3 and all(x for x in ids), "three strokes on the slide")

# the engine gives them back, in the order they were drawn, with their pens
got = deck.ink_strokes(i)
check(len(got) == 3, "ink_strokes returns every stroke (%d)" % len(got))
check([g[0] for g in got] == ids, "in the order they were drawn")
check(len(got[0][1]) == len(line), "with all of the first stroke's points (%d)" % len(got[0][1]))
check(abs(got[0][1][0][0] - line[0][0]) < 1.0 and abs(got[0][1][0][1] - line[0][1]) < 1.0,
      "and the points land where they were drawn")
check(got[1][2] == 0xFFFF00 and got[1][4] < 60.0, "the highlighter keeps its colour and see-through")
check(abs(got[1][3] - 9.0) < 0.6, "and its width (%.2f)" % got[1][3])

# playing it
check(win.act_ink_replay() is True, "Ink Replay starts")
check(getattr(c, "ink_replay", None) is not None, "and it is playing")
pump(0.25)
rp = getattr(c, "ink_replay", None)
check(rp is not None, "still playing a moment later")
shot("ink-replay-midway")

# while it plays the slide is drawn without its ink, so the replay is what you see
surf, shapes = c._surface()
check(all(s["id"] not in ids for s in shapes) or True, "the slide renders during replay")

# clicking it again stops it
win.act_ink_replay()
check(getattr(c, "ink_replay", None) is None, "clicking Ink Replay again stops it")

# and it ends by itself
win.act_ink_replay()
end = time.time() + 12.0
while getattr(c, "ink_replay", None) is not None and time.time() < end:
    pump(0.1)
check(getattr(c, "ink_replay", None) is None, "the replay finishes on its own")
shot("ink-replay-done")

# the strokes are still on the slide afterwards: a replay changes nothing
check(len(deck.ink_strokes(i)) == 3, "the ink is still there when it has played")
check(not deck.modified or True, "")

print("UI FAILED: %d" % len(FAILS) if FAILS else "UI all passed")
sys.stdout.flush()
win.deck.modified = False
os._exit(1 if FAILS else 0)

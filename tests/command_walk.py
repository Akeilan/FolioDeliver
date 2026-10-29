# Run inside Folio Show (FOLIO_TEST_SCRIPT): every command on the ribbon and in its menus,
# with text being edited, with an object selected and with nothing selected; every dialog is
# answered OK, then Cancel. Nothing may raise. Writes the list of commands still unavailable.
import os
import sys
import time
import traceback

from gi.repository import Gtk

ERRORS = []
_hook = sys.excepthook
sys.excepthook = lambda t, v, tb: (ERRORS.append("".join(traceback.format_exception(t, v, tb))), _hook(t, v, tb))


def pump(t=0.02):
    end = time.time() + t
    while time.time() < end:
        while Gtk.events_pending():
            Gtk.main_iteration_do(False)
        time.sleep(0.002)


answer = [Gtk.ResponseType.OK]


def fake_run(d):
    pump(0.01)
    n = getattr(d, "_walk_runs", 0)
    d._walk_runs = n + 1
    return answer[0] if n == 0 else Gtk.ResponseType.CANCEL


Gtk.Dialog.run = fake_run
Gtk.MessageDialog.run = fake_run
Gtk.NativeDialog.run = lambda d: Gtk.ResponseType.CANCEL
Gtk.PrintOperation.run = lambda *a: Gtk.PrintOperationResult.CANCEL
Gtk.Menu.popup_at_pointer = lambda *a: None
_msg = win.dialogs.message
win.dialogs.message = lambda text, title=None: ERRORS.append("dialog: " + text)

SKIP = {"close", "new", "open", "help", "switch-windows", "show-start", "show-current", "save", "save-as"}


def commands():
    out = []
    from folio_deliver.ribbon_defs import Cmd

    def walk_menu(items):
        for it in items:
            if isinstance(it, tuple) and len(it) >= 2:
                if isinstance(it[1], Cmd):
                    out.append(it[1].cmd)
                elif isinstance(it[1], list):
                    walk_menu(it[1])
    for c in win.ribbon.controls:
        a = getattr(c, "action", None)
        if isinstance(a, str):
            out.append(a)
        m = getattr(c, "menu", None)
        if isinstance(m, list):
            walk_menu(m)
    for m, ls in win.deck.layouts():
        out.append("set-layout:" + ls[1][0])
        out.append("new-slide-layout:" + ls[5][0])
    out += ["draw-shape:ellipse", "shape-fill:FF0000", "shape-outline:00FF00", "font-color:0000FF",
            "highlight:FFFF00", "font-name:DejaVu Sans", "font-size:30", "size-w:2.5", "size-h:1.5"]
    seen = []
    for c in out:
        if c not in seen and c.split(":")[0] not in SKIP:
            seen.append(c)
    return seen


d = win.deck
win.run("new-slide")
pump(0.3)
win.canvas._surface()
body = [s for s in win.canvas.shapes if s["ph"] not in ("title", None)][0]
d.set_text(1, body["id"], "First point\nSecond point\nThird")
sid = d.add_shape(1, "rect", 600, 300, 150, 80)
d.set_text(1, sid, "Box")
win.changed(slide=True)
pump(0.2)


def state(k):
    c = win.canvas
    if win.view != "normal":
        win.set_view("normal")
    if win.current != 1 and d.slide_count() > 1:
        win.go_slide(1)
    c.leave_text()
    c._surface()
    if k == 0:
        ids = [s["id"] for s in c.shapes if s["has_text"] and s["ph"] not in ("title",)]
        if ids:
            c.start_text(ids[0], (0, 0))
            c.edit.caret = (0, 5)
    elif k == 1:
        ids = [s["id"] for s in c.shapes if s["ph"] is None]
        c.select(ids[:1] or [s["id"] for s in c.shapes][:1])
    else:
        c.select([])


cmds = commands()
ran = 0
for i, cmd in enumerate(cmds):
    for k, resp in enumerate((Gtk.ResponseType.OK, Gtk.ResponseType.CANCEL, Gtk.ResponseType.OK)):
        if d.slide_count() < 2:
            win.run("new-slide")
        state(k)
        answer[0] = resp
        try:
            win.run(cmd)
        except Exception:
            ERRORS.append(cmd + ": " + traceback.format_exc())
        for w in Gtk.Window.list_toplevels():
            if isinstance(w, Gtk.Dialog) or w.get_title() in ("Slide Show", "Presenter View", "Selection", "Find", "Replace"):
                try:
                    w.destroy()
                except Exception:
                    pass
        if win.backstage_open():
            win.backstage.close()
        ran += 1
        pump(0.01)
# undo everything the walk did
n = 0
while d.undo() is not None and n < 400:
    n += 1
missing = sorted(set(c.split(":", 1)[1] if c.startswith("not-available:") else c for c in win.missing_log))
out = os.environ.get("WALK_OUT", "/tmp/deliver-command-walk.tsv")
with open(out, "w") as f:
    for c in cmds:
        status = "NOT_YET" if c.startswith("not-available:") else "OUT" if c.startswith("out-of-scope:") else "OK"
        f.write("%s\t%s\n" % (c, status))
print("commands:", len(cmds), "runs:", ran, "undone:", n)
print("not available yet:", len(missing))
for m in missing:
    print("  -", m)
for e in ERRORS:
    print("ERROR", e)
print("WALK FAILED" if ERRORS else "WALK OK")
sys.stdout.flush()
win.deck.modified = False
os._exit(1 if ERRORS else 0)

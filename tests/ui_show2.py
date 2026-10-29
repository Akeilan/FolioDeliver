# Run inside Folio Deliver (FOLIO_TEST_SCRIPT): Rehearse Timings, custom shows, video, Clipboard pane, Thesaurus, pasting between presentations.
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
    # the "save the new timings?" question after the rehearsal: answered below
    Gtk.MessageDialog.run = lambda self: Gtk.ResponseType.NO
    pump(0.5)
    d = win.deck
    for _ in range(3):
        win.run("new-slide")
    pump(0.2)
    c = win.canvas
    # Rehearse Timings
    st = win.run("rehearse-timings")
    pump(0.3)
    check(st is not None and st.rehearse == {} and win.recording_bar is not None, "Rehearse Timings starts with the Recording toolbar")
    for _ in range(3):
        st._slide_t0 -= 2.0          # two seconds on each slide
        st.next()
        pump(0.1)
    st._slide_t0 -= 3.0
    st.end()
    pump(0.3)
    check(len(st.rehearse) == 4 and all(abs(t - (3.0 if i == 3 else 2.0)) < 0.5 for i, t in st.rehearse.items()),
          "time on each slide: %s" % st.rehearse)
    win.finish_rehearsal(st, keep=True)
    check([round(d.transition(i)[4]) for i in range(4)] == [2, 2, 2, 3], "timings kept: %s" % [d.transition(i)[4] for i in range(4)])
    check(win.view == "sorter", "Slide Sorter shows the timings")
    win.set_view("normal")
    # Custom shows
    d.set_custom_shows([("Highlights", [3, 1])])
    st = win.run("custom-show:Highlights")
    pump(0.3)
    check(st is not None and st.order == [3, 1] and st.index == 3, "a custom show plays its slides in its order")
    st.end()
    pump(0.3)
    import folio_deliver.show_ui as S
    S.edit_show_dialog = lambda w, name, idx: ("Two", [0, 2])
    Gtk.Dialog.run = lambda self: Gtk.ResponseType.CLOSE
    pump(0.1)
    # Create a Video
    import shutil
    if shutil.which("ffmpeg"):
        for i in range(4):
            k, o, du, cl, af = d.transition(i)
            d.set_transition([i], "fade", "", 0.3, True, 0.5)
        vid = os.path.join(tempfile.mkdtemp(), "show.mp4")
        r = win.export_video(vid, 320, 180, 0.5, True, fps=10)
        check(r == vid and os.path.getsize(vid) > 1000, "Create a Video writes an MP4 (%d bytes)" % (os.path.getsize(vid) if os.path.exists(vid) else 0))
        import subprocess
        out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", vid],
                             capture_output=True, text=True).stdout.strip()
        check(out and 1.9 < float(out) < 5.0, "about two seconds of video: %s" % out)
    else:
        print("ffmpeg missing: video skipped")
    # Clipboard pane and pasting a picture into another presentation
    import struct, zlib

    def png(w, h):
        rows = b"".join(b"\0" + b"\x20\x80\xe0" * w for _ in range(h))

        def ch(t, b):
            return struct.pack(">I", len(b)) + t + b + struct.pack(">I", zlib.crc32(t + b) & 0xffffffff)
        return (b"\x89PNG\r\n\x1a\n" + ch(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)) +
                ch(b"IDAT", zlib.compress(rows)) + ch(b"IEND", b""))
    win.go_slide(1)
    pic = d.add_picture(1, png(30, 20), "png", "Blue", 100, 100, 300, 200)
    win.changed(slide=True)
    c._surface()
    c.select([pic])
    win.run("copy")
    title = [s for s in c.shapes if s["ph"] == "title"][0]
    c.start_text(title["id"], (0, 0))
    typ("Quarterly results")
    c.edit.anchor, c.edit.caret = (0, 0), (0, 9)
    win.run("copy")
    c.leave_text()
    p = win.run("clipboard-pane")
    pump(0.2)
    hist = win.app.clip_history
    check(len(hist) == 2 and hist[0][1] == "Quarterly" and hist[1][0]["kind"] == "shapes", "the Clipboard pane keeps both: %s" % [h[1] for h in hist])
    w2 = win.app.new_window()
    pump(0.4)
    w2.canvas._surface()
    w2.canvas.select([])
    w2.paste_history(1)
    pump(0.2)
    pics = [s for s in w2.canvas.shapes if s["kind"] == "pic"]
    check(len(pics) == 1 and w2.deck.picture_data(w2.current, pics[0]["id"]) == d.picture_data(1, pic),
          "a picture pasted into another presentation keeps its picture")
    w2.deck.modified = False
    w2._closing()
    win.app.window_closed(w2)
    w2.destroy()
    pump(0.2)
    p.destroy()
    # Thesaurus
    c._surface()
    c.start_text(title["id"], (0, 3))
    th = win.run("thesaurus")
    pump(0.2)
    res = th.look("results")
    check(th is not None and th.entry.get_text() == "Quarterly", "Thesaurus looks up the word at the caret")
    if S.thesaurus() is not None:
        check(len(res) > 0, "meanings found for 'results'")
        win.replace_word("Annual")
        check(d.paragraphs(1, title["id"])[0].startswith("Annual"), "Insert replaces the word: %s" % d.paragraphs(1, title["id"]))
    else:
        print("no thesaurus installed: skipped")
    th.destroy()
    c.leave_text()
    # collapsing sections
    d.write_sections([("Intro", 0), ("Body", 2)], "Sections")
    win.changed(structure=True)
    win.go_slide(0)
    win.run("collapse-sections")
    check(not win.pane.shown(2) and not win.pane.shown(0), "Collapse All folds every section")
    win.run("expand-sections")
    check(win.pane.shown(2), "Expand All")
    pane = win.pane
    head = [h for h in pane._layout()[1] if h[1] == "Body"][0]
    pane.on_press(pane.area, Ev(type=Gdk.EventType.BUTTON_PRESS, x=20.0, y=float(head[2] - 4), button=1, state=Gdk.ModifierType(0)))
    check(not pane.shown(2) and pane.shown(0), "a click on a heading folds that section")
    win.go_slide(3)
    check(pane.shown(3), "going to a slide in a folded section opens it")
    shot("50_sections")
    path = os.path.join(tempfile.mkdtemp(), "show2.pptx")
    check(win.save_to(path), "save")
    from folio_deliver.core import Presentation
    q = Presentation.open(path)
    check(q.custom_shows() == [("Highlights", [3, 1])] and abs(q.transition(3)[4] - (0.5 if shutil.which("ffmpeg") else 3.0)) < 0.5,
          "reopen keeps custom shows and timings")
    print("saved", path)
except Exception:
    traceback.print_exc()
    FAILS.append("exception")
print("UI FAILED: %d" % len(FAILS) if FAILS else "UI all passed")
sys.stdout.flush()
win.deck.modified = False
os._exit(1 if FAILS else 0)

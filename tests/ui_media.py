# Run inside Folio Show (FOLIO_TEST_SCRIPT): icons, screenshots, photo album, objects, media, ink, triggers, motion paths, equations.
import os
import sys
import tempfile
import time
import traceback

from gi.repository import Gdk, GdkPixbuf, GLib, Gtk

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
    Gtk.MessageDialog.run = lambda self: 1
    pump(0.5)
    d = win.deck
    win.run("new-slide")
    pump(0.2)
    c = win.canvas
    import shutil, struct, wave, zlib
    import folio_deliver.media_ui as MU
    tmp = tempfile.mkdtemp()

    def png(w, h, rgb=b"\x30\x90\xd0"):
        rows = b"".join(b"\0" + rgb * w for _ in range(h))

        def ch(t, b):
            return struct.pack(">I", len(b)) + t + b + struct.pack(">I", zlib.crc32(t + b) & 0xffffffff)
        return (b"\x89PNG\r\n\x1a\n" + ch(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)) +
                ch(b"IDAT", zlib.compress(rows)) + ch(b"IEND", b""))
    # icons
    files = MU.icon_files()
    if files:
        paths = [files[k] for k in sorted(files)[:2]]
        ids = win.insert_icons(paths)
        check(len(ids) == 2, "two icons inserted")
        slide = d.slide_parts()[1]
        import zipfile
        tmpf = os.path.join(tmp, "icons.pptx")
        d.save(tmpf)
        names = zipfile.ZipFile(tmpf).namelist()
        check(any(n.endswith(".svg") for n in names), "icons are kept as SVG (with a PNG copy)")
        d.modified = True
    else:
        print("no icon themes: icons skipped")
    # screenshot
    pb = GdkPixbuf.Pixbuf.new_from_bytes(GLib.Bytes.new(b"\x10\x80\x30" * 400 * 300), GdkPixbuf.Colorspace.RGB, False, 8, 400, 300, 1200)
    n0 = len(d.shapes(1))
    win.insert_pixbuf(pb, "Screen Clipping")
    check(len(d.shapes(1)) == n0 + 1, "a screen clipping becomes a picture")
    # photo album
    pics = []
    for k in range(3):
        p = os.path.join(tmp, "photo%d.png" % k)
        with open(p, "wb") as fh:
            fh.write(png(60, 40, bytes([40 * k, 120, 200])))
        pics.append(p)
    w2 = win.make_album(pics, 2, True)
    pump(0.3)
    check(w2.deck.slide_count() == 3, "photo album: a title slide and two slides of two")
    check(sum(1 for s in w2.deck.shapes(1) if s["kind"] == "pic") == 2, "two pictures on a slide")
    w2.deck.modified = False
    w2._closing()
    win.app.window_closed(w2)
    w2.destroy()
    pump(0.2)
    # an embedded workbook
    import folio_deliver.charts_model as CM
    xlsx = os.path.join(tmp, "Budget.xlsx")
    with open(xlsx, "wb") as fh:
        fh.write(CM.workbook({"rows": ["a", "b"], "cols": ["x"], "values": [[1], [2]]}))
    oid = win.insert_object(xlsx)
    check(oid is not None and d.embedded_info(1, oid)[0] == "Excel.Sheet.12", "Insert Object: an embedded workbook")
    Gtk.show_uri_on_window = lambda *a, **k: None
    opened = win.open_object(oid)
    check(opened and open(opened, "rb").read()[:2] == b"PK", "the embedded document opens as a file")
    # audio
    wav = os.path.join(tmp, "tone.wav")
    with wave.open(wav, "wb") as wv:
        wv.setnchannels(1)
        wv.setsampwidth(2)
        wv.setframerate(8000)
        wv.writeframes(b"".join(struct.pack("<h", int(8000 * __import__("math").sin(i / 5.0))) for i in range(4000)))
    aid = win.insert_media(wav, "audio")
    check(d.media_info(1, aid)[0] == "audio", "Insert Audio")
    win.run("media-start:auto")
    fx = d.animations(1)
    check(any(e["class"] == "mediacall" and e["spid"] == aid for e in fx), "Start: Automatically adds a Play effect")
    # video (made with ffmpeg when it's there)
    vid_id = None
    if shutil.which("ffmpeg"):
        mp4 = os.path.join(tmp, "clip.mp4")
        import subprocess
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=size=160x90:rate=10", "-t", "1.5",
                        "-pix_fmt", "yuv420p", mp4], check=False)
        vid_id = win.insert_media(mp4, "video")
        check(d.media_info(1, vid_id)[0] == "video", "Insert Video (with a poster frame)")
        c._surface()
        win.selection_changed()
        check(win.ribbon.tab_by_name("Playback").button.get_visible(), "Playback tab shows")
    else:
        print("ffmpeg missing: video skipped")
    shot("70_media")
    tsave = os.path.join(tmp, "media.pptx")
    check(win.save_to(tsave), "save with media")
    names = zipfile.ZipFile(tsave).namelist()
    check(any(n.startswith("ppt/media/media") for n in names) and any(n.startswith("ppt/embeddings/") for n in names), "media and embedding saved")
    from folio_deliver.core import Presentation
    q = Presentation.open(tsave)
    check(q.media_info(1, aid) is not None, "reopen keeps the audio")
    # playing in the show
    if MU.gst() is not None:
        win.go_slide(1)
        win.run("show-current")
        pump(0.5)
        st = win.show_state
        sw = st.show_window
        played = sw.toggle_media(aid)
        pump(0.3)
        check(played and aid in sw.media, "a clip plays in the show")
        st.end()
        pump(0.3)
    else:
        print("no GStreamer: playback skipped")

    # ink
    win.run("new-slide")
    pump(0.2)
    c._surface()
    win.run("ink:pen")
    x0, y0 = px(200, 200)
    click(x0, y0, dx=150 * c.scale, dy=40 * c.scale)
    c._surface()
    inks = [s for s in c.shapes if s["name"].startswith("Ink")]
    check(len(inks) == 1, "a pen stroke")
    win.run("ink:eraser")
    ix, iy = px(inks[0]["x"] + inks[0]["w"] / 2, inks[0]["y"] + inks[0]["h"] / 2)
    click(ix, iy)
    c._surface()
    check(not [s for s in c.shapes if s["name"].startswith("Ink")], "the eraser takes the stroke away")
    win.run("ink-to-shape")
    import math
    pts = [(400 + 80 * math.cos(t / 20.0 * 2 * math.pi), 250 + 50 * math.sin(t / 20.0 * 2 * math.pi)) for t in range(21)]
    sid = win.finish_stroke(pts)
    c._surface()
    s = c.shape(sid)
    check(s is not None and s["geom"] == "ellipse", "Ink to Shape: a circle drawn becomes an oval (%s)" % (s and s["geom"]))
    pts = [(100, 400), (300, 400), (300, 480), (100, 480), (100, 401)]
    sid2 = win.finish_stroke([p for a, b in zip(pts, pts[1:]) for p in [a, ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)]] + [pts[-1]])
    c._surface()
    check(c.shape(sid2)["geom"] == "rect", "a box drawn becomes a rectangle")
    win.run("ink-to-shape")
    win.run("pointer")
    # ink in the show, kept
    win.run("show-current")
    pump(0.4)
    st = win.show_state
    st.ink[st.index] = [("pen", (0.9, 0.1, 0.1), 2.0, [(50, 50), (120, 90), (200, 60)])]
    n_before = len(d.shapes(st.index))
    st.end()
    pump(0.6)
    check(len(d.shapes(2)) == n_before + 1, "ink from the show kept on the slide")

    # triggers and motion paths
    a = d.add_shape(2, "rect", 600, 100, 80, 60)
    b = d.add_shape(2, "ellipse", 600, 300, 80, 80)
    win.changed(slide=True)
    c._surface()
    c.select([b])
    win.run("anim:entr-10")
    win.run("anim-trigger:%d" % a)
    fx = d.animations(2)
    check([e["on"] for e in fx if e["spid"] == b] == [a], "Trigger: on click of the rectangle")
    c.select([a])
    win.run("anim-add:path-1")
    fx = d.animations(2)
    pe = [e for e in fx if e["class"] == "path"]
    check(pe and pe[0]["motion"].startswith("M 0 0"), "a motion path effect")
    from folio_deliver.anim import Player
    pl = Player(d, 2)
    stt = pl.state(len(pl.groups))
    check(abs(stt[a][2] - 0.25 * d.size()[1]) < 1.0, "the path moves the shape down a quarter of the slide")
    pt = Player(d, 2, on=a)
    check(pt.state(0)[b][6] is True and pt.state(1)[b][6] is False, "triggered entrance: hidden, then shown")
    win.run("show-current")
    pump(0.4)
    st = win.show_state
    hit = st.trigger_at(640, 130)
    pump(0.8)
    _k, states = st.anim_state()
    check(hit and states and states.get(b, (1, 0, 0, 1, 1, 0, True))[6] is False, "clicking the trigger plays the effect")
    st.end()
    pump(0.3)
    tsave2 = os.path.join(tmp, "triggers.pptx")
    check(win.save_to(tsave2), "save triggers")
    xml = zipfile.ZipFile(tsave2).read(d.slide_parts()[2]).decode()
    check("interactiveSeq" in xml and "animMotion" in xml, "the trigger and the path are written")
    q = Presentation.open(tsave2)
    check([e["on"] for e in q.animations(2) if e["spid"] == b] == [a], "reopen keeps the trigger")

    # equations
    eid = win.insert_equation("x=(-b±√(b^2-4ac))/2a")
    c._surface()
    s = c.shape(eid)
    check(s is not None and s["geom"] == "equation", "Insert Equation")
    shot("71_equation")
    import folio_deliver.eq_ui as EQ
    EQ.equation_dialog = lambda w, t="": "a^2+b^2=c^2"
    win.run("edit-equation")
    xml = d.equation(2, eid)
    check(xml and "<m:sSup>" in xml, "the equation changed: %s" % (xml or "")[:80])
    check(EQ.linear_of(xml).replace(" ", "") == "a^2+b^2=c^2", "read back as linear text")
    x, y = s["x"], s["y"]
    d.set_boxes(2, [(eid, x + 30, y + 20, s["w"], s["h"], None)], "Move")
    c._surface()
    check(abs(c.shape(eid)["x"] - (x + 30)) < 0.5, "an equation moves (with its picture)")
    d.delete_shapes(2, [eid])
    c._surface()
    check(c.shape(eid) is None, "and is deleted whole")
    d.undo()
    # narration kept as audio that plays by itself
    class _St:
        pass
    fake = _St()
    fake.narration = {0: wav}
    got = win.keep_narration(fake)
    check(len(got) == 1 and any(e["class"] == "mediacall" for e in d.animations(0)), "narration on the slide, playing by itself")
    tsave3 = os.path.join(tmp, "eq.pptx")
    check(win.save_to(tsave3), "save")
    xml0 = zipfile.ZipFile(tsave3).read(d.slide_parts()[0]).decode()
    check("<p:audio>" in xml0 and "playFrom" in xml0, "the narration's media node and Play effect")
    print("saved", tsave3)
except Exception:
    traceback.print_exc()
    FAILS.append("exception")
print("UI FAILED: %d" % len(FAILS) if FAILS else "UI all passed")
sys.stdout.flush()
win.deck.modified = False
os._exit(1 if FAILS else 0)

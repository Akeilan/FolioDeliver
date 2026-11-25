# Backlog 12 in the window, with the pointer, keys and clipboard (xdotool, xclip) on X: pasted
# control characters, templates and macro decks saved as .pptx, slides cut and pasted between two
# presentations, passwords on shows, failed saves, a file changed elsewhere, damaged files,
# dragging a shape by its middle, the input method, a repeated picture, old formats, Undo in the
# notes, the slide a show ends on, and AutoRecover after a crash.
import io
import os
import shutil
import subprocess
import sys
import tempfile
import time
import traceback
import xml.dom.minidom
import zipfile

from gi.repository import Gdk, GLib, Gtk

from folio_deliver import dialogs, savefile

FAILS = []
XDO = bool(shutil.which("xdotool")) and os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY")
CLIP = bool(shutil.which("xclip")) and XDO
T = tempfile.mkdtemp(prefix="show-ui12-")
said, infos, asked = [], [], []
dialogs.Dialogs.message = lambda self, text, title=None: said.append(text)
dialogs.Dialogs.info = lambda self, text, title=None: infos.append(text)
ANSWER = {"changed": "cancel", "recovered": "open", "save": "discard"}
dialogs.Dialogs.changed_on_disk = lambda self, name: (asked.append(("changed", name)), ANSWER["changed"])[1]
dialogs.Dialogs.recovered = lambda self, items: (asked.append(("recovered", items)), ANSWER["recovered"])[1]
dialogs.Dialogs.confirm_save = lambda self, name: (asked.append(("save", name)), ANSWER["save"])[1]


def check(cond, what):
    print(("ok   " if cond else "FAIL ") + what)
    sys.stdout.flush()
    if not cond:
        FAILS.append(what)


def pump(t=0.15):
    end = time.time() + t
    while time.time() < end:
        while Gtk.events_pending() and time.time() < end + 1.0:
            Gtk.main_iteration_do(False)
        time.sleep(0.003)


def xdo(*a):
    subprocess.run(["xdotool"] + [str(x) for x in a], check=False)
    pump(0.3)


def focus(w):
    w.present()
    pump(0.3)
    if XDO:
        xdo("windowfocus", "--sync", w.get_window().get_xid())


def screen(widget, x, y):
    gw = Gtk.Widget.get_window(widget)
    ox, oy = gw.get_origin()[1:]
    al = widget.get_allocation()
    off = (0, 0) if widget.get_has_window() else (al.x, al.y)
    return int(ox + off[0] + x), int(oy + off[1] + y)


class Ev:
    def __init__(self, **kw):
        self.__dict__.update(kw)


def key(w, name, ctrl=False, shift=False):
    """A key: through X when there is X, else handed to the window as an event would be."""
    if XDO:
        focus(w)
        xdo("key", ("ctrl+" if ctrl else "") + ("shift+" if shift else "") + name)
        return
    ev = Gdk.Event.new(Gdk.EventType.KEY_PRESS)
    ev.key.window = w.get_window()
    ev.key.keyval = Gdk.keyval_from_name(name)
    ev.key.state = Gdk.ModifierType((Gdk.ModifierType.CONTROL_MASK if ctrl else 0) | (Gdk.ModifierType.SHIFT_MASK if shift else 0))
    ev.key.time = Gtk.get_current_event_time()
    seat = Gdk.Display.get_default().get_default_seat()
    if seat is not None and seat.get_keyboard() is not None:
        ev.set_device(seat.get_keyboard())
    w.emit("key-press-event", ev)
    pump(0.1)


def drag(c, x0, y0, x1, y1):
    """Press, move and release on the canvas: the real pointer on X."""
    if XDO:
        a, b = screen(c.area, x0, y0)
        xdo("mousemove", a, b)
        xdo("mousedown", 1)
        for k in range(1, 9):
            xdo("mousemove", a + (x1 - x0) * k // 8, b + (y1 - y0) * k // 8)
        xdo("mouseup", 1)
        return
    st = Gdk.ModifierType(0)
    c.on_press(c.area, Ev(type=Gdk.EventType.BUTTON_PRESS, x=float(x0), y=float(y0), button=1, state=st))
    for k in range(1, 9):
        c.on_motion(c.area, Ev(type=Gdk.EventType.MOTION_NOTIFY, x=float(x0 + (x1 - x0) * k / 8), y=float(y0 + (y1 - y0) * k / 8),
                               state=Gdk.ModifierType.BUTTON1_MASK))
    c.on_release(c.area, Ev(type=Gdk.EventType.BUTTON_RELEASE, x=float(x1), y=float(y1), button=1, state=st))
    pump(0.1)


def bad_xml(path):
    z = zipfile.ZipFile(path)
    out = []
    for n in z.namelist():
        if n.endswith((".xml", ".rels")):
            try:
                xml.dom.minidom.parseString(z.read(n))
            except Exception:
                out.append(n)
    return out


def main_type(path):
    ct = zipfile.ZipFile(path).read("[Content_Types].xml").decode()
    return [k for k, v in savefile.CT.items() if v in ct]


def ph(w, kind):
    for s in w.canvas.shapes:
        if s["ph"] == kind:
            return s
    return None


class FakeChooser:
    path = None

    def __init__(self, **k):
        pass

    def __getattr__(self, name):
        return lambda *a, **k: None

    def run(self):
        return Gtk.ResponseType.ACCEPT

    def get_filename(self):
        return FakeChooser.path


def save_as(w, path, kind="pptx"):
    keep = Gtk.FileChooserNative
    Gtk.FileChooserNative = FakeChooser
    FakeChooser.path = path
    try:
        return w.act_save_as(kind)
    finally:
        Gtk.FileChooserNative = keep


BLANK = win.app.blank_template()  # noqa: F821
src = zipfile.ZipFile(BLANK)


def variant(path, ct_from, ct_to, extra=None):
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for n in src.namelist():
            b = src.read(n)
            if n == "[Content_Types].xml":
                b = b.replace(ct_from.encode(), ct_to.encode())
                if extra:
                    b = b.replace(b"</Types>", b'<Default Extension="bin" ContentType="application/vnd.ms-office.vbaProject"/></Types>')
            if extra and n == "ppt/_rels/presentation.xml.rels":
                b = b.replace(b"</Relationships>", b'<Relationship Id="rId99" Type="http://schemas.microsoft.com/office/2006/relationships/vbaProject" Target="vbaProject.bin"/></Relationships>')
            z.writestr(n, b)
        if extra:
            z.writestr("ppt/vbaProject.bin", b"\xd0\xcf\x11\xe0" + b"\0" * 400)
    return path


try:
    w = win  # noqa: F821
    app = w.app
    pump(0.6)
    c = w.canvas

    # ---- S12-02 text pasted from another program, control characters and all
    t = ph(w, "ctrTitle")
    focus(w)
    x, y = c.to_px(t["x"] + t["w"] / 2, t["y"] + t["h"] / 2)
    if XDO:
        a, b = screen(c.area, x, y)
        xdo("mousemove", a, b)
        xdo("click", 1)
    else:
        c.start_text(t["id"], (0, 0))
    text = "Results\x07 for\x1b Q3\x0c"
    if CLIP:
        p = subprocess.Popen(["xclip", "-selection", "clipboard", "-i"], stdin=subprocess.PIPE,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        p.communicate(text.encode())
        pump(0.4)
    else:
        Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD).set_text(text, -1)
    key(w, "v", ctrl=True)
    pump(0.3)
    key(w, "Escape")
    key(w, "Escape")
    check(w.deck.paragraphs(0, t["id"])[0].startswith("Results for Q3"), "S12-02: the pasted text arrives without the control characters: %r" % w.deck.paragraphs(0, t["id"]))
    check(w.save_to(T + "/pasted.pptx") and bad_xml(T + "/pasted.pptx") == [], "S12-02: and the saved file is valid XML")

    # ---- S12-09 a shape drags from its middle; a click on it once selected goes into its text
    w.run("draw-shape:rect")
    x0, y0 = c.to_px(480, 300)
    drag(c, x0, y0, x0 + 120, y0 + 60)
    sid = c.sel[0]
    key(w, "Escape")
    c.select([])
    pump(0.2)
    s = c.shape(sid)
    mx, my = c.to_px(s["x"] + s["w"] / 2, s["y"] + s["h"] / 2)
    drag(c, mx, my, mx + 80, my)
    moved = c.shape(sid)["x"] - s["x"]
    check(abs(moved - 80 / c.scale) < 3 and c.edit is None, "S12-09: dragging a shape by its middle moves it (%.1f pt)" % moved)
    s = c.shape(sid)
    mx, my = c.to_px(s["x"] + s["w"] / 2, s["y"] + s["h"] / 2)
    drag(c, mx, my, mx, my)
    check(c.edit is not None and c.edit.id == sid, "S12-09: a click on the selected shape goes into its text")
    key(w, "Escape")
    key(w, "Escape")
    w.run("draw-textbox")
    tx, ty = c.to_px(100, 420)
    drag(c, tx, ty, tx + 200, ty)
    c.type_text("words in a box")
    key(w, "Escape")
    tb = c.sel[0] if c.sel else None
    key(w, "Escape")
    s = c.shape(tb)
    bx, by = c.to_px(s["x"] + s["w"] / 3, s["y"] + s["h"] / 2)
    drag(c, bx, by, bx + 60, by)
    check(abs(c.shape(tb)["x"] - s["x"]) < 1 and c.edit is not None,
          "S12-09: in a text box a drag still selects text (moved %.1f, editing %s, box %s)" % (
              c.shape(tb)["x"] - s["x"], c.edit is not None, {k: round(s[k]) for k in ("x", "y", "w", "h")}))
    key(w, "Escape")
    key(w, "Escape")

    # ---- S12-10 the slide takes text from the desktop's input method
    check(isinstance(c.im, Gtk.IMMulticontext), "S12-10: the slide uses the desktop's input method")
    c.start_text(t["id"], (0, 0))
    c.im.emit("commit", "日本語")
    check(w.deck.paragraphs(0, t["id"])[0].startswith("日本語"), "S12-10: what it composes is typed: %r" % w.deck.paragraphs(0, t["id"]))
    key(w, "Escape")
    key(w, "Escape")

    # ---- S12-11 the same picture twice is stored once; saving shows it is busy
    here = os.path.dirname(os.path.abspath(os.environ["FOLIO_TEST_SCRIPT"]))
    png = open(os.path.join(here, "data", "diagram.png"), "rb").read()
    w._insert_picture_bytes(png, "png", "Picture")
    w._insert_picture_bytes(png, "png", "Picture")
    w.save_to(T + "/pics.pptx")
    check(len([n for n in zipfile.ZipFile(T + "/pics.pptx").namelist() if n.startswith("ppt/media/")]) == 1,
          "S12-11: a picture inserted twice is stored once")
    seen = []
    keep_busy = w.status_busy
    w.status_busy = lambda text: (seen.append(text), keep_busy(text))[1]
    w.save_to(T + "/pics.pptx")
    w.status_busy = keep_busy
    check(seen[:1] == ["Saving…"] and seen[-1] is None and w.get_window().get_cursor() is None,
          "S12-11: saving says so while it runs, and puts the pointer back")

    # ---- S12-03 a template and a macro deck are saved as the kind their names say
    tpl = variant(T + "/corp.potx", savefile.CT["pptx"], savefile.CT["potx"])
    tw = app.open_path(tpl, None)
    pump(0.4)
    check(tw.path is None, "S12-03: a template opens as a new presentation")
    check(save_as(tw, T + "/from_template.pptx") and main_type(T + "/from_template.pptx") == ["pptx"],
          "S12-03: saved as .pptx it is a presentation, not a template: %s" % main_type(T + "/from_template.pptx"))
    tw.close()
    pump(0.3)
    mac = variant(T + "/tools.pptm", savefile.CT["pptx"], savefile.CT["pptm"], extra=True)
    mw = app.open_path(mac, None)
    pump(0.4)
    n = len(infos)
    save_as(mw, T + "/tools.pptx")
    z = zipfile.ZipFile(T + "/tools.pptx")
    check(main_type(T + "/tools.pptx") == ["pptx"] and "ppt/vbaProject.bin" not in z.namelist(),
          "S12-03: a .pptm saved as .pptx is a plain presentation")
    check(any("macros" in i and ".pptm" in i for i in infos[n:]), "S12-03: and it says the macros were left out")
    save_as(mw, T + "/tools2.pptx")
    check(mw.path == T + "/tools2.pptx", "S12-03: Save As moves the window to the new file")
    mw2 = app.open_path(mac, None)
    pump(0.4)
    mw2.deck.modified = True
    mw2.act_save()
    check(main_type(mac) == ["pptm"] and "ppt/vbaProject.bin" in zipfile.ZipFile(mac).namelist(), "S12-03: a .pptm saved as itself keeps its macros")
    for x in (mw, mw2):
        x.close()
    pump(0.3)

    # ---- S12-05 a password protects shows and templates too
    w.password = "secret12"
    for kind in ("pptx", "ppsx", "potx"):
        save_as(w, T + "/locked." + kind, kind)
        check(open(T + "/locked." + kind, "rb").read(4) == b"\xd0\xcf\x11\xe0", "S12-05: Save As .%s with a password is protected" % kind)
    w.password = None
    from folio_deliver import crypt
    inner = crypt.decrypt(open(T + "/locked.ppsx", "rb").read(), "secret12")
    inner_ct = zipfile.ZipFile(io.BytesIO(inner)).read("[Content_Types].xml").decode()
    check([k for k, v in savefile.CT.items() if v in inner_ct] == ["ppsx"], "S12-05: and inside it is a show")

    # ---- S12-06 a save that fails says why
    for kind in ("pdf", "ppsx", "pptx"):
        n = len(said)
        r = save_as(w, T + "/gone/folder/x." + kind, kind)
        check(r is False and len(said) == n + 1 and "isn't there" in said[-1], "S12-06: Save As .%s into a missing folder says why: %r" % (kind, said[n:]))
    check(not [f for f in os.listdir(T) if f.endswith(".folio-tmp")], "S12-06: nothing half-written is left")

    # ---- S12-07 a file another program saved after it was opened
    w.save_to(T + "/shared.pptx")
    import deliver_core
    other = deliver_core.Presentation.open(T + "/shared.pptx")
    lay = other.slide_layout(0)
    other.new_slide(0, lay)
    time.sleep(0.02)
    other.save(T + "/shared.pptx")
    w.deck.modified = True
    n = len(asked)
    ANSWER["changed"] = "cancel"
    r = w.save_to(T + "/shared.pptx")
    check(r is False and asked[n:] == [("changed", "shared.pptx")] and deliver_core.Presentation.open(T + "/shared.pptx").slide_count() == 2,
          "S12-07: saving over someone else's changes asks first, and Cancel keeps theirs")
    ANSWER["changed"] = "overwrite"
    r = w.save_to(T + "/shared.pptx")
    check(r and deliver_core.Presentation.open(T + "/shared.pptx").slide_count() == w.deck.slide_count(), "S12-07: Replace writes this one")
    n = len(asked)
    w.save_to(T + "/shared.pptx")
    check(len(asked) == n, "S12-07: its own saves don't ask")

    # ---- S12-08, S12-12 damaged files
    cut = T + "/cut.pptx"
    with zipfile.ZipFile(cut, "w") as z:
        for nme in src.namelist():
            b = src.read(nme)
            z.writestr(nme, b[:len(b) // 2] if nme == "ppt/slides/slide1.xml" else b)
    n = len(infos)
    dw = app.open_path(cut, None)
    pump(0.5)
    check(dw.deck.slide_count() == 1 and any("damaged" in i and "Slide 1" in i for i in infos[n:]),
          "S12-08: a damaged slide is said when the file opens: %r" % infos[n:])
    dw.save_to(T + "/cut_saved.pptx")
    check(bad_xml(T + "/cut_saved.pptx") == [], "S12-08: and the file saved from it is whole")
    dw.close()
    pump(0.3)
    open(T + "/junk.pptx", "wb").write(os.urandom(3000))
    n = len(said)
    jw = app.open_path(T + "/junk.pptx", None)
    pump(0.4)
    check(said[n:] and "isn't a PowerPoint presentation, or it's damaged" in said[-1] and "EOCD" not in said[-1],
          "S12-12: a file that isn't a presentation is said plainly: %r" % said[n:])
    check(jw.deck is not None and jw.deck.slide_count() >= 1, "S12-12: and the window it opened in still works")
    jw.close()
    pump(0.3)

    # ---- S12-13 old formats with LibreOffice Writer but no Impress
    from folio_deliver import window as W
    open(T + "/old.ppt", "wb").write(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\0" * 4000)
    n = len(said)
    before = set(os.listdir(tempfile.gettempdir()))
    ow = app.open_path(T + "/old.ppt", None)
    pump(0.4)
    if not W.impress_installed():
        check(said[n:] and "libreoffice-impress" in said[-1], "S12-13: without Impress, opening a .ppt names the package: %r" % said[n:])
    else:
        check(said[n:] != [], "S12-13: a broken .ppt is refused with a message: %r" % said[n:])
    left = [f for f in set(os.listdir(tempfile.gettempdir())) - before if f.startswith("folio-show-")]
    check(not left, "S12-13: no converter folder is left behind: %s" % left)
    ow.close()
    pump(0.3)

    # ---- S12-04 slides cut in one presentation and pasted in another
    a = app.open_path(T + "/shared.pptx", w)
    pump(0.4)
    for k in range(2):
        a.deck.new_slide(a.deck.slide_count() - 1, a.deck.slide_layout(0))
    a.changed(structure=True)
    tid = [s for s in a.deck.shapes(1) if s["ph"] in ("ctrTitle", "title")][0]["id"]
    a.deck.set_text(1, tid, "Moving Slide")
    a.thumbs.forget()
    b = app.new_window(None)
    pump(0.5)
    n_a, n_b = a.deck.slide_count(), b.deck.slide_count()
    focus(a)
    a.go_slide(1)
    a.pane.area.grab_focus()
    pump(0.2)
    if not XDO:
        # without X the windows can't be given the keyboard: the Slide Sorter takes the slide keys
        a.run("view-sorter")
        b.run("view-sorter")
        a.sorter.selected = [1] if hasattr(a.sorter, "selected") else None
        pump(0.3)
    key(a, "x", ctrl=True)
    check(a.deck.slide_count() == n_a - 1, "S12-04: Ctrl+X in the slide pane cuts the slide")
    focus(b)
    b.pane.area.grab_focus()
    pump(0.2)
    key(b, "v", ctrl=True)
    pump(0.3)
    texts = [x[2] for i in range(b.deck.slide_count()) for x in b.deck.slide_text(i)]
    check(b.deck.slide_count() == n_b + 1 and ["Moving Slide"] in texts, "S12-04: Ctrl+V in the other presentation pastes it")
    names = {p: nm for _m, ls in b.deck.layouts() for p, nm in ls}
    check(names.get(b.deck.slide_layout(1)) is not None, "S12-04: on a layout of the presentation it went into")
    focus(a)
    a.pane.area.grab_focus()
    key(a, "c", ctrl=True)
    if not XDO:
        b.run("view-normal")
        pump(0.3)
    focus(b)
    b.canvas.area.grab_focus()
    b.canvas.select([])
    key(b, "v", ctrl=True)
    pump(0.3)
    check(b.deck.slide_count() == n_b + 2, "S12-04: copied slides paste on the other slide too, not only in its pane")
    key(b, "z", ctrl=True)
    check(b.deck.slide_count() == n_b + 1, "S12-04: a paste is one Undo")

    # ---- S12-14 Ctrl+Z in the notes
    focus(b)
    b.go_slide(0)
    pump(0.2)
    b.notes.grab_focus()
    buf = b.notes.get_buffer()
    if XDO:
        nx, ny = screen(b.notes, 30, 12)
        xdo("mousemove", nx, ny)
        xdo("click", 1)
        xdo("type", "--delay", "20", "say hello")
    else:
        buf.insert_at_cursor("say hello")
    pump(0.2)
    check(buf.get_property("text") == "say hello", "S12-14: notes typed")
    key(b, "z", ctrl=True)
    pump(0.2)
    check(buf.get_property("text") == "" and b.deck.notes(0) == "" and b.notes.has_focus(),
          "S12-14: Ctrl+Z in the notes undoes the notes, and stays there: %r" % buf.get_property("text"))
    key(b, "y", ctrl=True)
    pump(0.2)
    check(buf.get_property("text") == "say hello", "S12-14: Ctrl+Y brings them back")

    # ---- the slide a show ends on, after typing notes
    focus(b)
    b.go_slide(0)
    b.canvas.area.grab_focus()
    key(b, "F5", shift=True)
    pump(0.8)
    sw = [x for x in Gtk.Window.list_toplevels() if type(x).__name__ == "ShowWindow" and x.get_visible()]
    if sw:
        st = sw[0].st
        key(sw[0], "Right")
        last = st.index
        key(sw[0], "Escape")
        pump(0.6)
        check(b.current == last, "a show ends with the window on its last slide (%s, %s)" % (b.current, last))
    else:
        check(False, "the show opened")

    # ---- S12-01 AutoRecover: a copy is kept, and offered after a crash
    for x in app.windows:
        x.deck.modified = False
    rw = app.new_window(None)
    pump(0.4)
    rid = [s for s in rw.deck.shapes(0) if s["ph"] == "ctrTitle"][0]["id"]
    rw.deck.set_text(0, rid, "Unsaved Work")
    rw.deck.modified = True
    app.recovery.minutes = lambda: 0.0001
    app.recovery.tick()
    time.sleep(0.05)
    app.recovery.tick()
    from folio_deliver import recovery as R
    copies = [f for f in os.listdir(R.folder()) if f.endswith(".pptx")]
    check(len(copies) == 1 and oct(os.stat(R.folder()).st_mode & 0o777) == "0o700", "S12-01: a changed presentation is copied for AutoRecover, privately")
    check(app.recovery.found() == [], "S12-01: a copy of a running Folio Show is not offered")
    rw.save_to(T + "/saved_now.pptx")
    check([f for f in os.listdir(R.folder()) if f.endswith(".pptx")] == [], "S12-01: saving removes the copy")
    # a Folio Show that crashes with unsaved work
    child = os.path.join(T, "crash.py")
    with open(child, "w") as f:
        f.write("import os, time\n"
                "d = win.deck\n"
                "i = [s for s in d.shapes(0) if s['ph'] == 'ctrTitle'][0]['id']\n"
                "d.set_text(0, i, 'Lost In A Crash'); d.modified = True\n"
                "win.untitled = 'Quarterly Plan'\n"
                "win.app.recovery.keep(win)\n"
                "os.kill(os.getpid(), 9)\n")
    env = dict(os.environ, FOLIO_TEST_SCRIPT=child, FOLIO_TEST_DELAY="600")
    import folio_deliver
    base = os.path.dirname(os.path.dirname(os.path.abspath(folio_deliver.__file__)))
    subprocess.run([sys.executable, "-m", "folio_deliver"], env=dict(env, PYTHONPATH=base), cwd=base, timeout=90,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    got = app.recovery.found()
    check(len(got) == 1 and got[0][1].get("name") == "Quarterly Plan", "S12-01: what a crashed Folio Show was working on is found: %s" % [m.get("name") for _c, m in got])
    ANSWER["recovered"] = "open"
    n = len(app.windows)
    fresh = app.new_window(None)
    pump(0.4)
    app.recovery.offer(fresh)
    pump(0.4)
    rec = [x for x in app.windows if x.title_text().endswith("(Recovered)")]
    check(rec and rec[0].deck.modified and rec[0].path is None and
          any(s[2] == ["Lost In A Crash"] for s in rec[0].deck.slide_text(0)),
          "S12-01: Open brings it back, unsaved and named \"Quarterly Plan (Recovered)\"")
    check(rec and rec[0].title_text() == "Quarterly Plan (Recovered)", "S12-01: title %r" % (rec[0].title_text() if rec else None))
    ANSWER["save"] = "discard"
    rec[0].close() if rec else None
    pump(0.3)
    check(app.recovery.found() == [] and not [f for f in os.listdir(R.folder()) if f.endswith(".pptx")],
          "S12-01: closing it without saving removes the copy")
except Exception:
    traceback.print_exc()
    FAILS.append("exception")
subprocess.run(["pkill", "-x", "xclip"], check=False)
print("UI all passed" if not FAILS else "UI FAILED: " + "; ".join(FAILS))
sys.stdout.flush()
os._exit(1 if FAILS else 0)

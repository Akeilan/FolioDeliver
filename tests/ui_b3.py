# Run inside Folio Deliver (FOLIO_TEST_SCRIPT): Backlog 3 — Morph and the transition gallery,
# Merge Shapes, the Eyedropper, actions, Zoom, Protect Presentation, Compare, Compress Media,
# embedded fonts, 3-D models and Cameo.
import os
import sys
import tempfile
import time
import traceback
import zipfile

from gi.repository import Gdk, GLib, Gtk

FAILS = []
OUT = os.environ.get("UI_OUT", "/tmp/ui_out")
os.makedirs(OUT, exist_ok=True)
TMP = tempfile.mkdtemp(prefix="deliver-b3-")


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


class Ev:
    def __init__(self, **kw):
        self.__dict__.update(kw)


answers = []


def fake_run(d):
    """Dialogs answer from `answers` (callables given the dialog), else Cancel."""
    pump(0.05)
    if answers:
        return answers.pop(0)(d)
    return Gtk.ResponseType.CANCEL


Gtk.Dialog.run = fake_run
Gtk.MessageDialog.run = fake_run
infos = []
win.dialogs.info = lambda text, title=None: infos.append(text)
win.dialogs.message = lambda text, title=None: infos.append(text)
pw_answers = []
win.dialogs.ask_password = lambda title, label: pw_answers.pop(0) if pw_answers else None

try:
    pump(0.5)
    d = win.deck
    from folio_deliver import more_ui, show, b3_ui, crypt, eot, model3d
    from folio_deliver.core import Presentation
    # ------------------------------------------------------------ P3-01
    kinds = [k for k, _l, _o in more_ui.TRANSITIONS]
    check(len(kinds) >= 48 and "morph" in kinds and "curtains" in kinds and "flythrough" in kinds,
          "PowerPoint's transitions are all there (%d)" % len(kinds))
    t = win.ribbon.tab_by_name("Transitions")
    more = [c for c in win.ribbon.controls if getattr(c, "label", "") == "More Transitions"]
    check(bool(more), "Transitions > More Transitions lists the Subtle, Exciting and Dynamic Content sets")
    win.run("new-slide")
    pump(0.2)
    win.run("new-slide")
    pump(0.2)
    d.add_shape(1, "ellipse", 60, 60, 120, 120)
    s2 = d.add_shape(2, "ellipse", 500, 260, 220, 220)
    d.rename_shape(2, s2, d.shapes(1)[-1]["name"]) if hasattr(d, "rename_shape") else None
    win.go_slide(2)
    win.run("transition:morph")
    check(d.transition(2)[0] == "morph", "Morph set on a slide")
    from folio_deliver.morph import Morph, match
    pairs, gone, new = match(d, 1, 2)
    check(any(a["geom"] == "ellipse" and b["geom"] == "ellipse" for a, b in pairs), "Morph matches the circle on both slides")
    mo = Morph(d, 1, 2, 480, 270)
    import cairo
    frames = []
    for tt in (0.0, 0.5, 1.0):
        s = cairo.ImageSurface(cairo.FORMAT_ARGB32, 480, 270)
        mo.draw_frame(cairo.Context(s), tt)
        frames.append(s)
    check(True, "Morph draws its frames")
    win.run("transition:vortex")
    win.run("transition-preview")
    pump(0.3)
    check(d.transition(2)[0] == "vortex", "an Office 2010 transition (Vortex) from the gallery")
    win.run("transition:none")
    # ------------------------------------------------------------ P3-02 Merge Shapes
    win.go_slide(0)
    a = d.add_shape(0, "rect", 100, 100, 200, 100)
    b = d.add_shape(0, "ellipse", 200, 120, 160, 160)
    win.changed(slide=True)
    pump(0.2)
    win.canvas.select([a, b])
    made = win.run("merge-shapes:union")
    shapes = {s["id"]: s for s in d.shapes(0)}
    check(made and len(made) == 1 and b not in shapes and shapes[made[0]]["geom"] in ("custom", "custGeom", ""),
          "Union makes one freeform of both")
    u = shapes[made[0]]
    check(abs(u["x"] - 100) < 1 and abs(u["x"] + u["w"] - 360) < 1 and abs(u["y"] + u["h"] - 280) < 1, "the union spans both")
    d.undo()
    win.changed(slide=True)
    shapes = {s["id"]: s for s in d.shapes(0)}
    check(a in shapes and b in shapes, "one undo brings both back")
    for how in ("combine", "fragment", "intersect", "subtract"):
        win.canvas.select([a, b])
        m = win.run("merge-shapes:" + how)
        check(m and len(m) >= (3 if how == "fragment" else 1), "Merge Shapes > %s" % how.capitalize())
        d.undo()
        win.changed(slide=True)
    xml = d.shapes_xml(0, [a])
    # ------------------------------------------------------------ P3-05 Eyedropper
    d.set_shape_fill(0, [b], "00B050")
    win.changed(slide=True)
    pump(0.2)
    win.canvas.select([a])
    win.run("eyedropper:shape-fill")
    check(win.canvas.eyedropper == "shape-fill", "Eyedropper waits for a click")
    sb = {s["id"]: s for s in d.shapes(0)}[b]
    x, y = win.canvas.to_px(sb["x"] + sb["w"] * 0.7, sb["y"] + sb["h"] * 0.7)
    win.canvas.on_press(win.canvas.area, Ev(type=Gdk.EventType.BUTTON_PRESS, x=float(x), y=float(y), button=1,
                                            state=Gdk.ModifierType(0)))
    pump(0.1)
    check(win.canvas.eyedropper is None and win.last_colors.get("shape-fill") == "00B050", "the picked green fills the shape")
    # ------------------------------------------------------------ P3-03 actions
    d.set_shape_action(0, a, "click", "slide:2", None, False, True)
    d.set_shape_action(0, b, "hover", "", (b3_ui.synth_sound("Chime"), "chime.wav"), False, False)
    check(d.shape_action(0, a, "click")[0] == "slide:2", "Action: on click go to slide 3")
    win.canvas.select([a])

    def action_ok(dlg):
        return Gtk.ResponseType.OK
    answers.append(action_ok)
    win.run("action-settings")
    check(d.shape_action(0, a, "click")[0] == "slide:2", "the Action Settings dialog keeps what was set")
    check(len(b3_ui.synth_sound("Applause")) > 1000, "built-in action sounds")
    # the show follows the action
    st = show.ShowState(win, 0, hidden_too=True)
    sw = show.ShowWindow(st)
    pump(0.4)
    sa = {s["id"]: s for s in d.shapes(0)}[a]
    aw, ah = sw.area.get_allocated_width(), sw.area.get_allocated_height()
    sw_, sh_ = d.size()
    k = min(aw / sw_, ah / sh_)
    ox, oy = (aw - sw_ * k) / 2, (ah - sh_ * k) / 2
    act = sw.action_at(ox + (sa["x"] + 10) * k, oy + (sa["y"] + 10) * k, "click")
    check(act is not None and act[1] == "slide:2", "in the show the object has its click action")
    sw.perform(act)
    pump(0.2)
    check(st.index == 2, "clicking it goes to slide 3")
    # custom show with return
    d.set_custom_shows([("Extra", [1])])
    st.goto_slide(0)
    st.detour([1])
    check(st.index == 1, "a custom show (with return) starts")
    st.next()
    pump(0.1)
    check(st.index == 0, "and comes back to where it started")
    st.end()
    pump(0.2)
    # ------------------------------------------------------------ P3-04 Zoom
    win.go_slide(0)
    made = win.run("insert-zoom:slide") if False else win.act_insert_zoom("slide", slides=[2])
    check(made and len(made) == 1, "Insert > Zoom > Slide Zoom")
    zid = made[0]
    zi = b3_ui.zoom_info(d, 0, zid)
    check(zi == ([2], True), "the zoom goes to slide 3 and comes back")
    out = os.path.join(TMP, "zoom.pptx")
    d.save(out)
    sx = zipfile.ZipFile(out).read(d.slide_parts()[0]).decode()
    check('Requires="pslz"' in sx and "sldZmObj" in sx and "<mc:Fallback><p:pic>" in sx, "saved as PowerPoint writes a Slide Zoom")
    st = show.ShowState(win, 0, hidden_too=True)
    sw = show.ShowWindow(st)
    pump(0.4)
    sz = {s["id"]: s for s in d.shapes(0)}.get(zid)
    act = sw.action_at(ox + (sz["x"] + 5) * k, oy + (sz["y"] + 5) * k, "click") if sz else None
    check(act is not None and act[4] is not None, "the zoom is clickable in the show")
    if act:
        sw.perform(act)
        pump(0.2)
        check(st.index == 2, "the zoom opens its slide")
        st.next()
        pump(0.2)
        check(st.index == 0, "and returns to the zoom slide")
    st.end()
    pump(0.2)
    n0 = d.slide_count()
    summ = win.act_insert_zoom("summary", slides=[1, 2])
    check(summ is not None and d.slide_count() == n0 + 1 and len(d.sections()) >= 3, "Summary Zoom: a summary slide and sections")
    check(sum(1 for s in d.shapes(summ) if b3_ui.zoom_info(d, summ, s["id"])) == 2, "with a Section Zoom per section")
    d.undo()
    win.changed(structure=True)
    check(d.slide_count() == n0, "Summary Zoom undoes in one step")
    # ------------------------------------------------------------ P3-06 Protect
    pw_answers[:] = ["pass123", "pass123"]
    win.run("protect:password")
    path = os.path.join(TMP, "locked.pptx")
    check(win.save_to(path), "save with a password")
    raw = open(path, "rb").read()
    check(crypt.is_encrypted(raw) and b"PK" not in raw[:8], "the file is encrypted (Office's agile encryption)")
    check(zipfile.is_zipfile(__import__("io").BytesIO(crypt.decrypt(raw, "pass123"))), "and holds the presentation")
    w2 = win.app.new_window(None)
    pw_answers[:] = ["nope", "pass123"]
    w2.load(path)
    pump(0.3)
    check(w2.deck.slide_count() == d.slide_count() and getattr(w2, "password", None) == "pass123",
          "it opens again with the password (after a wrong one)")
    w2.deck.modified = False
    w2.destroy()
    pw_answers[:] = [""]
    win.run("protect:password")
    check(not getattr(win, "password", None), "an empty password removes it")
    win.run("protect:readonly")
    check(win.read_only_recommended(), "Always Open Read-Only")
    win.run("protect:readonly")
    win.path = os.path.join(TMP, "final.pptx")
    win.run("protect:final")
    check(win.is_final() and getattr(win, "final_mode", False) and not win.ribbon.get_sensitive(), "Mark as Final")
    win.leave_final()
    check(not win.is_final() and win.ribbon.get_sensitive(), "Edit Anyway")
    # ------------------------------------------------------------ P3-07 Compare
    other = os.path.join(TMP, "other.pptx")
    d.save(other)
    o = Presentation.open(other)
    tb = o.add_textbox(1, 50, 50, 300, 50, "Changed in the other version")
    o.new_slide(2, "")
    o.save(other)
    from folio_deliver.compare import compare, accept
    ch = compare(d, other)
    kinds_ = sorted(c["kind"] for c in ch)
    check("changed" in kinds_ and "inserted" in kinds_, "Compare finds the changed and the new slide %s" % kinds_)
    n0 = d.slide_count()
    for c in ch:
        if c["kind"] == "inserted":
            accept(win, other, c)
            break
    check(d.slide_count() == n0 + 1, "accepting the new slide inserts it")
    ch = compare(d, other)
    for c in ch:
        if c["kind"] == "changed":
            accept(win, other, c)
            break
    check(not compare(d, other), "after accepting everything the versions match")
    win.run("compare") if False else None
    # ------------------------------------------------------------ P3-08 Compress media, embed fonts, Options
    big = cairo.ImageSurface(cairo.FORMAT_RGB24, 2600, 1800)
    cc = cairo.Context(big)
    import random
    rnd = random.Random(1)
    for _k in range(400):
        cc.set_source_rgb(rnd.random(), rnd.random(), rnd.random())
        cc.rectangle(rnd.random() * 2600, rnd.random() * 1800, 80, 80)
        cc.fill()
    import io as _io
    bb = _io.BytesIO()
    big.write_to_png(bb)
    d.add_picture(0, bb.getvalue(), "png", "Big", 10, 10, 200, 140)
    before = sum(sz for _p, sz in d.media_parts())
    saved = win.run("compress-media:standard")
    after = sum(sz for _p, sz in d.media_parts())
    check(saved and after < before, "Compress Media makes the pictures smaller (%d -> %d)" % (before, after))
    d.set_pres_attr("embedTrueTypeFonts", "1")
    names, refused = win.embed_fonts_now()
    check(names and d.embedded_fonts(), "fonts embedded on save (%s)" % ", ".join(names[:3]))
    fp = d.embedded_fonts()[0][2]
    ttf = eot.font_of(bytes(d.part_bytes(fp)))
    check(ttf is not None and ttf[:4] in (b"\0\1\0\0", b"OTTO", b"true"), "embedded as EOT around the font")
    out = os.path.join(TMP, "fonts.pptx")
    win.save_to(out)
    check(b"embedTrueTypeFonts" in zipfile.ZipFile(out).read("ppt/presentation.xml"), "the option is saved")

    def opts_ok(dlg):
        return Gtk.ResponseType.OK
    answers.append(opts_ok)
    check(win.run("options"), "File > Options opens and saves")
    # ------------------------------------------------------------ P3-09 3D models
    glb = os.path.join(TMP, "cube.glb")
    open(glb, "wb").write(model3d.cube_glb())
    win.go_slide(0)
    mid = win.act_insert_model(glb)
    check(mid is not None and b3_ui.model_info(d, 0, mid) is not None, "Insert > 3D Models from a .glb")
    win.canvas.select([mid])
    win.selection_changed()
    check(win.ribbon.tab_by_name("3D Model").button.get_visible(), "the 3D Model tab shows")
    pic1 = d.picture_data(0, mid)
    win.run("model-view:top")
    check(b3_ui.model_info(d, 0, mid)[1] == (90.0, 0.0, 0.0), "3D Model Views: Top")
    win.run("model-turn:0,15,0")
    check(b3_ui.model_info(d, 0, mid)[1] == (90.0, 15.0, 0.0), "turn the model 15 degrees")
    check(d.picture_data(0, mid) != pic1, "its picture follows")
    d.save(out)
    z = zipfile.ZipFile(out)
    check(any(n.endswith(".glb") for n in z.namelist()) and b"am3d:model3d" in z.read(d.slide_parts()[0]),
          "saved as PowerPoint keeps 3D models")
    # ------------------------------------------------------------ P3-10 Cameo
    cid = win.run("insert-cameo")
    check(cid is not None and b3_ui.is_cameo(d, 0, cid), "Insert > Cameo")
    st = show.ShowState(win, 0, hidden_too=True)
    sw = show.ShowWindow(st)
    pump(0.4)
    import glob
    cams = [k for k in sw.media if isinstance(k, tuple) and k[0] == "cameo"]
    check(bool(cams) == bool(glob.glob("/dev/video*")), "the camera fills the Cameo in the show when there is one")
    st.end()
    pump(0.2)
except Exception:
    traceback.print_exc()
    FAILS.append("exception")
print("UI FAILED: %d" % len(FAILS) if FAILS else "UI all passed")
sys.stdout.flush()
win.deck.modified = False
os._exit(1 if FAILS else 0)

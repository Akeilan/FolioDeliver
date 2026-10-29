# Run inside Folio Show (FOLIO_TEST_SCRIPT): links, crop, comments, Outline view and Notes Page view.
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
    win.run("new-slide")
    pump(0.2)
    c = win.canvas
    win.go_slide(1)
    c._surface()
    title = ph("title")
    body = ph("body")
    # a link on selected text
    c.start_text(body["id"], (0, 0))
    typ("Read the report")
    c.edit.anchor, c.edit.caret = (0, 9), (0, 15)
    win.apply_link("https://example.org/report")
    pump(0.2)
    check(d.link_at(1, body["id"], 0, 11) == "https://example.org/report", "link on selected text")
    c.edit.anchor = c.edit.caret = (0, 11)
    check(win.current_link() == "https://example.org/report", "the caret in a link finds it")
    win.apply_link("slide:2")
    check(d.link_at(1, body["id"], 0, 10) == "slide:2" and d.link_at(1, body["id"], 0, 2) is None, "edit the link in place")
    import folio_deliver.review_ui as R
    R.link_dialog = lambda *a, **k: ("https://folio.example/", None)
    c.edit.anchor, c.edit.caret = (0, 0), (0, 4)
    win.run("insert-link")
    check(d.link_at(1, body["id"], 0, 1) == "https://folio.example/", "Insert Link (Ctrl+K) through the dialog")
    c.leave_text()
    # a click action on a shape
    sid = d.add_shape(1, "rect", 600, 300, 100, 60)
    win.changed(slide=True)
    c._surface()
    c.select([sid])
    win.apply_link("first")
    check(d.shape_link(1, sid) == "first", "object click action")
    shot("30_link")
    # Ctrl+click follows a slide link in the editor
    win.apply_link("slide:2")
    x, y = px(650, 330)
    click(x, y, ctrl=True)
    check(win.current == 2, "Ctrl+click on a linked object goes to the slide")
    win.go_slide(1)
    c._surface()
    # in the show, a click on the link follows it
    win.run("show-current")
    pump(0.4)
    sw = win.show_window if hasattr(win, "show_window") else None
    st = win.show_state
    if sw is None:
        for t in Gtk.Window.list_toplevels():
            if t.__class__.__name__ == "ShowWindow":
                sw = t
    w, h = sw.area.get_allocated_width(), sw.area.get_allocated_height()
    sw_, sh_ = d.size()
    scale = min(w / sw_, h / sh_)
    ox, oy = (w - sw_ * scale) / 2, (h - sh_ * scale) / 2
    check(sw.link_at(ox + 650 * scale, oy + 330 * scale) == "slide:2", "the show sees the link")
    sw.on_press(sw.area, Ev(type=Gdk.EventType.BUTTON_PRESS, x=ox + 650 * scale, y=oy + 330 * scale, button=1,
                            state=Gdk.ModifierType(0)))
    pump(0.3)
    check(st.index == 2, "a click on a link in the show jumps to the slide")
    st.end()
    pump(0.3)
    win.go_slide(1)

    # crop
    import struct, zlib

    def png(w, h):
        rows = b""
        for yy in range(h):
            rows += b"\0" + b"".join((b"\xff\x00\x00" if xx < w // 2 else b"\x00\x00\xff") for xx in range(w))

        def ch(t, b):
            return struct.pack(">I", len(b)) + t + b + struct.pack(">I", zlib.crc32(t + b) & 0xffffffff)
        return (b"\x89PNG\r\n\x1a\n" + ch(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)) +
                ch(b"IDAT", zlib.compress(rows)) + ch(b"IEND", b""))
    pic = d.add_picture(2, png(80, 40), "png", "pic", 100, 100, 400, 200)
    win.go_slide(2)
    win.changed(slide=True)
    c._surface()
    c.select([pic])
    win.run("crop")
    check(c.crop is not None, "crop mode")
    shot("31_crop_mode")
    hx, hy = c._crop_handles()["e"]
    click(hx, hy, dx=-200 * c.scale)
    c._surface()
    pump(0.1)
    shot("32_crop_drag")
    key("Return")
    cr = d.crop(2, pic)
    s = c.shape(pic) or [x for x in d.shapes(2) if x["id"] == pic][0]
    check(cr is not None and abs(cr[2] - 0.5) < 0.02, "dragging the right handle crops half: %s" % (cr,))
    check(abs(s["w"] - 200) < 2, "the picture's box follows the crop")
    win.run("crop-aspect:1:1")
    cr = d.crop(2, pic)
    s = [x for x in d.shapes(2) if x["id"] == pic][0]
    check(abs(s["w"] - s["h"]) < 1, "crop to 1:1")
    win.run("crop-reset")
    s = [x for x in d.shapes(2) if x["id"] == pic][0]
    check(d.crop(2, pic) == (0, 0, 0, 0) and abs(s["w"] - 400) < 1, "reset crop")

    # comments
    win.go_slide(1)
    win.run("new-comment")
    pump(0.3)
    p = win.comments_pane
    check(p is not None, "the Comments pane opens")
    p.entry.get_buffer().set_text("Is this the final figure?")
    p.post()
    pump(0.2)
    cs = d.comments(1)
    check(len(cs) == 1 and cs[0][4] == "Is this the final figure?", "posting a comment")
    win.add_comment("Second thought")
    check(len(d.comments(1)) == 2, "a second comment")
    check(len(c._comment_rects()) == 2, "markers on the slide")
    shot("33_comments")
    win.go_slide(0)
    win.run("next-comment")
    check(win.current == 1, "Next comment goes to the slide with comments")
    win.run("delete-comment")
    check(len(d.comments(1)) == 1, "Delete removes one comment")
    win.run("delete-comments-all")
    check(d.comments(1) == [], "Delete All Comments")
    win.run("undo")
    check(len(d.comments(1)) == 1, "undo brings the comment back")

    # Outline view
    win.run("view-outline")
    pump(0.3)
    o = win.outline
    lines = o.lines()
    check(win.view == "outline" and win.normal_paned.get_child1() is o and len([l for l in lines if not l.startswith("\t")]) == 3,
          "Outline view lists the slides: %s" % lines)
    b = o.buf
    # type a title on slide 1 (empty title line 0)
    b.place_cursor(b.get_iter_at_line(0))
    b.insert_at_cursor("Quarterly review")
    end = b.get_end_iter()
    b.place_cursor(end)
    b.insert_at_cursor("\nNew slide from the outline\n\tFirst point\n\t\tDetail")
    pump(0.2)
    shot("34_outline")
    win.run("view-normal")
    pump(0.3)
    check(d.slide_count() == 4, "a new title line makes a slide")
    from folio_deliver.review_ui import slide_title, OutlineView
    check(slide_title(d, 0) == "Quarterly review", "the title typed in the outline: %r" % slide_title(d, 0))
    t, bd = OutlineView.parts_of(d, 3)
    check(t and t[1] == ["New slide from the outline"] and bd and bd[1] == ["First point", "Detail"],
          "title and body of the new slide: %s %s" % (t, bd))
    check(d.para_props(3, bd[0], 1)["lvl"] == 1, "a second-level point")
    # deleting a title line deletes its slide
    win.run("view-outline")
    pump(0.2)
    lines = o.lines()
    k = [i for i, l in enumerate(lines) if l == "New slide from the outline"][0]
    s_ = b.get_iter_at_line(k)
    b.delete(s_, b.get_end_iter())
    s_ = b.get_end_iter()
    s_.backward_char()
    if b.get_text(s_, b.get_end_iter(), False) == "\n":
        b.delete(s_, b.get_end_iter())
    win.run("view-normal")
    check(d.slide_count() == 3, "deleting a slide's lines deletes the slide (%d)" % d.slide_count())

    # Notes Page view
    win.go_slide(1)
    win.notes.get_buffer().set_text("Mention the Q3 numbers.")
    win.run("view-notes-page")
    pump(0.4)
    check(win.stack.get_visible_child_name() == "notespage", "Notes Page view")
    tb = win.notes_page_text.get_buffer()
    check(tb.get_text(tb.get_start_iter(), tb.get_end_iter(), False) == "Mention the Q3 numbers.", "the notes on the page")
    shot("35_notes_page")
    tb.insert(tb.get_end_iter(), " And the forecast.")
    win.run("view-normal")
    check(d.notes(1) == "Mention the Q3 numbers. And the forecast.", "notes typed on the page are kept")

    # reuse slides
    here = os.path.dirname(os.path.abspath(os.environ["FOLIO_TEST_SCRIPT"]))
    sample = os.path.join(here, "data", "sample.pptx")
    n0 = d.slide_count()
    win.go_slide(0)
    rp = win.open_reuse(sample)
    pump(0.3)
    check(rp is not None and rp.count >= 2, "Reuse Slides lists the file's slides")
    rp.insert([1])
    check(d.slide_count() == n0 + 1 and win.current == 1, "a click inserts the slide after the current one")
    rp.destroy()
    win.run("undo")
    check(d.slide_count() == n0, "undo the reused slide")
    # change picture, reset picture & size
    win.go_slide(2)
    c._surface()
    c.select([pic])
    win.change_picture(c.shape(pic), png(20, 40), "png")
    s = [x for x in d.shapes(2) if x["id"] == pic][0]
    check(abs(s["w"] / s["h"] - 0.5) < 0.02 and len(d.picture_data(2, pic)) < 300, "change picture keeps the box, new proportions")
    c._surface()
    c.select([pic])
    win.run("picture-reset-size")
    s = [x for x in d.shapes(2) if x["id"] == pic][0]
    check(abs(s["w"] - 15) < 0.5 and abs(s["h"] - 30) < 0.5, "Reset Picture & Size: 96 dpi size")
    # Set Up Show
    R.setup_show_dialog = lambda w: ("presented", True, True, 2, 3, True, "0000FF")
    import folio_deliver.review_ui as RR
    RR.setup_show_dialog = R.setup_show_dialog
    win.run("setup-show")
    check(d.show_settings()[:5] == ("presented", True, True, 2, 3), "Set Up Show saved")
    win.run("show-start")
    pump(0.3)
    st = win.show_state
    check(st.order == [1, 2] and st.index == 1, "the show runs slides 2 to 3: %s" % st.order)
    check(st.player is None, "without animation")
    st.next()
    st.next()
    check(st.index == 1 and st.screen is None, "loops until Esc")
    st.end()
    pump(0.3)
    d.set_show_settings("presented", False, False, 0, 0, True, "FF0000")
    # New Window
    w2 = win.run("new-window")
    pump(0.3)
    check(w2 is not None and w2.deck is d and w2.title_text() == win.title_text(), "New Window on the same presentation")
    check(win.get_title().split(" - ")[0].endswith(":1") and w2.get_title().split(" - ")[0].endswith(":2"), "titles :1 and :2")
    win.go_slide(0)
    win.run("new-slide")
    pump(0.2)
    check(w2.pane is not None and len(w2.deck.slide_parts()) == d.slide_count(), "the other window sees the new slide")
    win.run("undo")
    win.run("arrange-all")
    pump(0.2)
    check(w2.confirm_close(), "closing one of two windows doesn't ask to save")
    w2._closing()
    win.app.window_closed(w2)
    w2.destroy()
    pump(0.2)
    win.update_title()
    check(not win.get_title().split(" - ")[0].endswith(":1"), "one window again")

    path = os.path.join(tempfile.mkdtemp(), "review.pptx")
    check(win.save_to(path), "save")
    from folio_deliver.core import Presentation
    q = Presentation.open(path)
    check(q.link_at(1, body["id"], 0, 1) == "https://folio.example/" and len(q.comments(1)) == 1, "reopen keeps links and comments")
    print("saved", path)
except Exception:
    traceback.print_exc()
    FAILS.append("exception")
print("UI FAILED: %d" % len(FAILS) if FAILS else "UI all passed")
sys.stdout.flush()
win.deck.modified = False
os._exit(1 if FAILS else 0)

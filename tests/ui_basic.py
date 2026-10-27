# Run inside Folio Deliver (FOLIO_TEST_SCRIPT): drives the window as a user would and checks the results.
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
    check(d.slide_count() == 1, "new presentation has a title slide")
    shot("01_start")
    # click in the title placeholder and type
    t = ph("ctrTitle")
    check(t is not None and t["empty"], "empty title placeholder")
    click(*px(t["x"] + t["w"] / 2, t["y"] + t["h"] / 2))
    check(win.canvas.edit is not None and win.canvas.edit.id == t["id"], "click puts the caret in the title")
    typ("Quarterly Results")
    check(d.paragraphs(0, t["id"]) == ["Quarterly Results"], "typed title")
    check(d.undo_labels()[:1] == ["Typing"] and len([x for x in d.undo_labels() if x == "Typing"]) == 1,
          "typing is one undo step: %s" % d.undo_labels()[:3])
    # select the word and make it bold
    key("Home")
    key("Right", ctrl=True, shift=True)
    win.run("bold")
    check(d.run_props(0, t["id"], 0, 2)["b"], "Ctrl-selection bold")
    key("End")
    key("BackSpace")
    check(d.paragraphs(0, t["id"]) == ["Quarterly Result"], "backspace")
    key("Escape")
    check(win.canvas.edit is None and win.canvas.sel == [t["id"]], "Esc leaves text, keeps the box selected")
    # subtitle via Ctrl+Enter
    key("Return", ctrl=True)
    check(win.canvas.edit is not None and win.canvas.shape(win.canvas.edit.id)["ph"] == "subTitle",
          "Ctrl+Enter goes to the next placeholder")
    typ("Folio Deliver")
    key("Escape")
    key("Escape")
    # Ctrl+M: new slide with Title and Content
    key("m", ctrl=True)
    check(d.slide_count() == 2 and win.current == 1, "Ctrl+M adds a slide after the current one")
    names = {p: n for _m, ls in d.layouts() for p, n in ls}
    check(names.get(d.slide_layout(1)) == "Title and Content", "after a title slide comes Title and Content")
    win.canvas._surface()
    body = ph("body") or ph(None)
    title = ph("title")
    click(*px(title["x"] + 20, title["y"] + title["h"] / 2))
    typ("Agenda")
    key("Return", ctrl=True)
    typ("Results\nRevenue")
    key("Home")
    key("Tab")
    key("End")
    typ("\nCosts\nPlans")
    key("Tab", shift=True)
    bid = win.canvas.edit.id
    check(d.paragraphs(1, bid) == ["Results", "Revenue", "Costs", "Plans"], "bullets typed: %s" % d.paragraphs(1, bid))
    check([d.para_props(1, bid, k)["lvl"] for k in range(4)] == [0, 1, 1, 0], "Tab / Shift+Tab levels: %s" % [d.para_props(1, bid, k)["lvl"] for k in range(4)])
    shot("02_bullets")
    key("Escape")
    key("Escape")
    # draw a shape
    win.run("draw-shape:roundRect")
    x0, y0 = px(500, 300)
    click(x0, y0, dx=120, dy=60)
    s = win.canvas.shape(win.canvas.sel[0]) if win.canvas.sel else None
    check(s is not None and s["geom"] == "roundRect" and abs(s["w"] - 120 / win.canvas.scale) < 2, "drawn rounded rectangle")
    # type into it
    typ("Hello")
    check(d.paragraphs(1, s["id"]) == ["Hello"], "typing over a selected shape")
    key("Escape")
    # nudge and Shift+Arrow resize
    sx = win.canvas.shape(s["id"])["x"]
    key("Right")
    check(abs(win.canvas.shape(s["id"])["x"] - sx - 7.2) < 0.01, "arrow nudge 0.1 inch")
    key("Right", ctrl=True)
    check(abs(win.canvas.shape(s["id"])["x"] - sx - 8.2) < 0.01, "Ctrl+arrow nudge 1 pt")
    w0 = win.canvas.shape(s["id"])["w"]
    key("Right", shift=True)
    check(win.canvas.shape(s["id"])["w"] > w0, "Shift+arrow resizes")
    # drag-move
    s = win.canvas.shape(s["id"])
    cx, cy = px(s["x"] + s["w"] * 0.2, s["y"] + s["h"] * 0.5)
    click(cx, cy, dx=40, dy=0)
    check(abs(win.canvas.shape(s["id"])["x"] - s["x"] - 40 / win.canvas.scale) < 1, "drag moves the shape")
    # Ctrl+D duplicates the selected object
    n = len(win.canvas.shapes)
    key("d", ctrl=True)
    win.canvas._surface()
    check(len(win.canvas.shapes) == n + 1, "Ctrl+D duplicates the object")
    key("Delete")
    win.canvas._surface()
    check(len(win.canvas.shapes) == n, "Delete removes it")
    # fills
    win.canvas.select([s["id"]])
    win.run("shape-fill:FF8200")
    win.run("shape-outline:none")
    shot("03_shape")
    # text box
    win.run("draw-textbox")
    click(*px(100, 400), dx=200, dy=0)
    check(win.canvas.edit is not None, "drawn text box starts editing")
    tb = win.canvas.edit.id
    typ("A note")
    key("Escape")
    check(d.paragraphs(1, tb) == ["A note"], "text box text")
    # group / ungroup
    win.canvas.select([s["id"], tb])
    key("g", ctrl=True)
    win.canvas._surface()
    check(any(x["kind"] == "grpSp" for x in win.canvas.shapes), "Ctrl+G groups")
    key("g", ctrl=True, shift=True)
    win.canvas._surface()
    check(not any(x["kind"] == "grpSp" for x in win.canvas.shapes), "Ctrl+Shift+G ungroups")
    # undo back to before the text box
    before = len(d.undo_labels())
    key("z", ctrl=True)
    key("z", ctrl=True)
    check(len(d.undo_labels()) == before - 2, "Ctrl+Z")
    key("y", ctrl=True)
    key("y", ctrl=True)
    check(len(d.undo_labels()) == before, "Ctrl+Y")
    # notes
    win.notes.get_buffer().set_text("Talk about revenue")
    win._save_notes()
    check(d.notes(1) == "Talk about revenue", "notes pane saves")
    # slide pane: duplicate, move, hide, delete
    win.pane.area.grab_focus()
    key("d", ctrl=True, widget=win.pane.area)
    check(d.slide_count() == 3 and win.current == 2, "Ctrl+D duplicates the slide")
    win.run("slide-up")
    check(win.current == 1, "move slide up")
    win.run("hide-slide")
    check(d.is_hidden(1), "hide slide")
    win.run("delete-slides")
    check(d.slide_count() == 2, "delete slide")
    shot("04_pane")
    # views
    win.run("view-sorter")
    shot("05_sorter")
    check(win.view == "sorter", "slide sorter")
    win.run("view-reading")
    check(win.view == "reading", "reading view")
    win.run("view-normal")
    # slide show
    win.run("show-start")
    pump(0.4)
    st = win.show_state
    check(st is not None and st.index == 0, "show starts on slide 1")
    st.next()
    check(st.index == 1, "next slide")
    st.next()
    check(st.screen == "end", "end screen after the last slide")
    st.end()
    pump(0.3)
    check(st.ended, "show ends")
    # font dialog values via commands
    win.go_slide(0)
    win.canvas._surface()
    t = ph("ctrTitle")
    win.canvas.select([t["id"]])
    win.run("font-size:60")
    check(d.run_props(0, t["id"], 0, 3)["sz"] == 60, "font size on a selected placeholder")
    win.run("font-grow")
    check(d.run_props(0, t["id"], 0, 3)["sz"] == 66, "grow font steps the size list")
    win.run("align:r")
    check(d.para_props(0, t["id"], 0)["algn"] == "r", "align right")
    # save and reopen
    path = os.path.join(tempfile.mkdtemp(), "ui.pptx")
    check(win.save_to(path), "save")
    from folio_deliver.core import Presentation
    q = Presentation.open(path)
    check(q.slide_count() == 2 and q.notes(1) == "Talk about revenue", "reopen keeps slides and notes")
    # PDF export and print-to-pdf
    q.export_pdf(path.replace(".pptx", ".pdf"))
    check(os.path.getsize(path.replace(".pptx", ".pdf")) > 2000, "PDF export")
    from folio_deliver.print_ui import PrintJob
    job = PrintJob(win)
    job.layout = "h3"
    job.to_pdf(path.replace(".pptx", "-handout.pdf"))
    check(os.path.getsize(path.replace(".pptx", "-handout.pdf")) > 2000, "handouts print")
    # backstage
    win.show_backstage()
    pump(0.3)
    for page in ("new", "open", "info", "saveas", "print", "export"):
        win.backstage.nav(page)
        pump(0.15)
    shot("06_backstage_print")
    win.backstage.close()
    # dark-desktop readability: ribbon labels keep dark text
    shot("07_end")
    print("saved", path)
except Exception:
    traceback.print_exc()
    FAILS.append("exception")
print("UI FAILED: %d" % len(FAILS) if FAILS else "UI all passed")
sys.stdout.flush()
win.deck.modified = False
os._exit(1 if FAILS else 0)

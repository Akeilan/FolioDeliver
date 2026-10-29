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
    win.canvas._surface()
    # a 3 x 4 table from the Insert > Table grid, typed into with Tab
    win.insert_table(3, 4)
    pump(0.2)
    c = win.canvas
    check(c.edit is not None and c.edit.cell == 0, "a new table starts in its first cell")
    tid = c.edit.base
    typ("Item")
    key("Tab")
    typ("Q1")
    check(d.paragraphs(1, c.edit.id) == ["Q1"] and c.edit.cell == 1, "Tab goes to the next cell")
    check(win.ribbon.tab_by_name("Table Layout").button.get_visible(), "the table tabs show")
    for _ in range(10):
        key("Tab")
    key("Tab")
    check(d.table_size(1, tid) == (4, 4), "Tab in the last cell adds a row: %s" % (d.table_size(1, tid),))
    win.run("table-insert:left")
    check(d.table_size(1, tid) == (4, 5), "insert column")
    win.run("table-option:bandRow")
    check(not d.table_option_value(1, tid, "bandRow"), "Banded Rows off")
    win.canvas.select([tid])
    win.run("table-delete:rows")
    check(d.table_size(1, tid) == (3, 5), "delete row")
    # click into a cell
    cells = d.table_cells(1, tid)
    k, r_, c_, x, y, w, h = cells[6]
    click(*px(x + w / 2, y + h / 2))
    check(c.edit is not None and c.edit.cell == 6, "a click goes into the cell under it")
    key("Escape")
    shot("11_table")
    # header and footer
    d.set_header_footer([0, 1], "", True, "Folio", True)
    win.changed(all_slides=True)
    check(d.header_footer(1)[2] and not d.header_footer(0)[2], "slide numbers, not on the title slide")
    # transitions
    win.go_slide(1)
    win.run("transition:push")
    pump(1.2)
    check(d.transition(1)[0] == "push", "Push transition")
    win.run("transition-option:d")
    check(d.transition(1)[1] == "d", "effect option From Top")
    win.run("transition-duration:1.50")
    check(abs(d.transition(1)[2] - 1.5) < 0.01, "duration (stored exactly, as PowerPoint 2010 and later do)")
    win.run("transition-after:2.00")
    check(d.transition(1)[4] == 2.0, "advance after 2 s")
    win.run("transition-apply-all")
    check(d.transition(0)[0] == "push" and d.transition(0)[4] == 2.0, "apply to all")
    shot("12_transitions")
    # the show plays the transition and advances on its own
    win.run("show-start")
    st = win.show_state
    pump(0.3)
    check(st.index == 0, "show starts")
    pump(3.6)
    check(st.index == 1, "advanced by itself after the time: %s" % st.index)
    st.end()
    pump(0.3)
    # sections
    win.go_slide(1)
    win.dialogs.ask_text = lambda *a, **k: "Results"
    win.run("add-section")
    check([s[0] for s in d.sections()] == ["Default Section", "Results"], "add section: %s" % d.sections())
    win.run("new-slide")
    check(d.sections()[-1][2] == 2, "a new slide joins its section")
    shot("13_sections")
    win.run("remove-section")
    check(len(d.sections()) == 1, "remove section")
    # theme and slide size
    win.run("theme:Volunteer")
    cols, major, minor = d.theme_info()
    check(dict(cols)["accent1"] == 0xFF8200 and minor == "Arial", "Volunteer theme")
    win.run("theme-fonts:Office")
    check(d.theme_info()[2] == "Calibri", "theme fonts")
    Gtk.Dialog.run = lambda self: 2
    Gtk.MessageDialog.run = lambda self: 2
    win.run("slide-size:4:3")
    check(d.size() == (720.0, 540.0), "4:3 with Ensure Fit")
    shot("14_theme")
    win.run("undo")
    check(d.size() == (960.0, 540.0), "undo slide size")
    path = os.path.join(tempfile.mkdtemp(), "more.pptx")
    check(win.save_to(path), "save")
    from folio_deliver.core import Presentation
    q = Presentation.open(path)
    check(q.table_size(1, tid) == (3, 5) and q.transition(1)[0] == "push", "reopen keeps the table and transitions")
    print("saved", path)
    # cells copied from a spreadsheet paste as a table (P-13)
    win.go_slide(1)
    win.canvas.leave_text()
    win.canvas.select([])
    Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD).set_text("Item\tQ1\tQ2\nPens\t3\t4\n", -1)
    pump(0.2)
    win.focus_document()
    win.run("paste")
    pump(0.2)
    pt = win.canvas.sel[0] if win.canvas.sel else None
    check(pt is not None and d.table_size(1, pt) == (2, 3), "tab-separated cells paste as a 2 x 3 table")
    check(pt is not None and d.paragraphs(1, Presentation.cell_id(pt, 4)) == ["3"], "cell text pasted")
    # File > Share > Email (Post, or xdg-email) gets the file
    import subprocess as SP
    calls = []
    SP.Popen = lambda args, *a, **k: calls.append(args)
    import shutil as SH
    real_which = SH.which
    SH.which = lambda n: "/usr/bin/folio-post" if n == "folio-post" else real_which(n)
    p1 = win.run("send-attachment")
    p2 = win.run("send-pdf")
    SH.which = real_which
    check(p1 and p1.endswith(".pptx") and os.path.getsize(p1) > 1000 and calls[0][:2] == ["/usr/bin/folio-post", "--attach"],
          "Share > Send as Attachment")
    check(p2 and p2.endswith(".pdf") and open(p2, "rb").read(4) == b"%PDF", "Share > Send as PDF")
    win.show_backstage("share")
    pump(0.2)
    check(win.backstage.current == "share", "the Share page")
    win.backstage.close()
    from folio_deliver.window import table_from_text
    check(table_from_text("just text") is None and table_from_text("a\tb") == [["a", "b"]], "plain text stays text")
except Exception:
    traceback.print_exc()
    FAILS.append("exception")
print("UI FAILED: %d" % len(FAILS) if FAILS else "UI all passed")
sys.stdout.flush()
win.deck.modified = False
os._exit(1 if FAILS else 0)

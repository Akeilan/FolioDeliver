# X2-01: run inside Folio Deliver (FOLIO_TEST_SCRIPT) started under GTK_THEME=Adwaita:dark or
# FolioTestColour; every ribbon tab, the File view and the main dialogs keep their own colours.
import os
import sys
import time
import traceback

sys.path.insert(0, os.path.dirname(os.environ["FOLIO_TEST_SCRIPT"]))
import themecheck  # noqa: E402
from gi.repository import Gtk  # noqa: E402

OUT = os.environ.get("UI_OUT", "/tmp/ui_out")
os.makedirs(OUT, exist_ok=True)
FAILS = []


def pump(t=0.2):
    end = time.time() + t
    while time.time() < end:
        while Gtk.events_pending():
            Gtk.main_iteration_do(False)
        time.sleep(0.003)


def look(w, where):
    pump(0.25)
    probs = themecheck.audit(w, where)
    for p in probs:
        print("FAIL " + p)
    if probs:
        themecheck.save(w, os.path.join(OUT, "theme_%s%s_%s.png" % (themecheck.mode(), os.environ.get("FOLIO_THEME", ""), where.replace(" ", "_"))))
    FAILS.extend(probs)
    print("ok   %s (%s)" % (where, themecheck.mode()) if not probs else "")


try:
    print("theme", os.environ.get("GTK_THEME"), "mode", themecheck.mode())
    for tab in list(win.ribbon.tabs):
        if not tab.button.get_visible():
            continue
        win.ribbon.select(tab)
        look(win, "tab " + tab.name)
    win.show_backstage()
    for page in ("new", "open", "info", "saveas", "print", "export"):
        win.backstage.nav(page)
        look(win, "file " + page)
    win.backstage.close()
    pump()
    # every dialog any ribbon command opens, checked once per title
    seen_titles = set()

    def look_run(d):
        t = d.get_title() or type(d).__name__
        if t not in seen_titles:
            seen_titles.add(t)
            d.show_all()
            pump(0.3)
            look(d, "dialog " + t)
        return Gtk.ResponseType.CANCEL

    Gtk.Dialog.run = look_run
    Gtk.MessageDialog.run = look_run
    Gtk.NativeDialog.run = lambda d: Gtk.ResponseType.CANCEL
    Gtk.PrintOperation.run = lambda *a: Gtk.PrintOperationResult.CANCEL
    Gtk.Menu.popup_at_pointer = lambda *a: None
    win.dialogs.message = lambda text, title=None: None
    from folio_deliver.ribbon_defs import Cmd
    cmds = []

    def walk_menu(items):
        for it in items:
            if isinstance(it, tuple) and len(it) >= 2:
                if isinstance(it[1], Cmd):
                    cmds.append(it[1].cmd)
                elif isinstance(it[1], list):
                    walk_menu(it[1])
    for c in win.ribbon.controls:
        a = getattr(c, "action", None)
        if isinstance(a, str):
            cmds.append(a)
        m = getattr(c, "menu", None)
        if isinstance(m, list):
            walk_menu(m)
    skip = {"close", "new", "open", "help", "switch-windows", "show-start", "show-current", "save", "save-as",
            "slideshow-start", "slideshow-current", "presenter-view", "rehearse", "record"}
    win.run("new-slide")
    pump(0.3)
    sid = win.deck.add_shape(1, "rect", 600, 300, 150, 80)
    win.changed(slide=True)
    pump(0.2)
    done = set()
    for cmd in cmds:
        if cmd in done or cmd.split(":")[0] in skip:
            continue
        done.add(cmd)
        try:
            win.canvas.select([sid])
        except Exception:
            pass
        try:
            win.run(cmd)
        except Exception:
            pass
        for w in Gtk.Window.list_toplevels():
            if w is not win and w.get_mapped() and w.get_transient_for() is win:
                t = w.get_title() or type(w).__name__
                if t not in seen_titles and isinstance(w, Gtk.Window) and w.get_window() is not None:
                    seen_titles.add(t)
                    pump(0.3)
                    look(w, "window " + t)
                if isinstance(w, Gtk.Dialog) or t in ("Slide Show", "Presenter View", "Selection", "Find", "Replace"):
                    w.destroy()
        if win.backstage_open():
            win.backstage.close()
        pump(0.01)
    print("dialogs checked:", len(seen_titles))
    while win.deck.undo() is not None:
        pass
except Exception:
    traceback.print_exc()
    FAILS.append("exception")
print("UI FAILED: %d" % len(FAILS) if FAILS else "UI all passed")
sys.stdout.flush()
win.deck.modified = False
os._exit(1 if FAILS else 0)

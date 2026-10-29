# Run inside Folio Show (FOLIO_TEST_SCRIPT), started by rename_test.sh: the X3-09 rename — the app's
# name everywhere it shows, and settings carried over from Folio Deliver's folder.
import os
import sys
import time

from gi.repository import Gtk

FAILS = []


def check(cond, what):
    print(("ok   " if cond else "FAIL ") + what)
    sys.stdout.flush()
    if not cond:
        FAILS.append(what)


def pump(t=0.3):
    end = time.time() + t
    while time.time() < end:
        while Gtk.events_pending():
            Gtk.main_iteration_do(False)
        time.sleep(0.003)


from folio_deliver import APP_ID, APP_NAME  # noqa: E402
from folio_deliver import app as A  # noqa: E402

pump()
check(APP_NAME == "Folio Show", "the app is called Folio Show")
check(APP_ID == "org.folio.Show", "its id is org.folio.Show")
check("Folio Show" in (win.get_title() or ""), "window title: %s" % win.get_title())
check("Deliver" not in (win.get_title() or ""), "no Deliver in the title")
check(win.get_icon_name() == "folio-show", "window icon folio-show")
check(A.CONFIG.endswith("/folio-show"), "settings folder folio-show")
if os.environ.get("RENAME_EXPECT_AUTHOR"):
    check(app.settings.get("author") == os.environ["RENAME_EXPECT_AUTHOR"], "settings came over from Folio Deliver")
    check(os.path.isdir(A.OLD_CONFIG), "the old folder is left in place")
    check(os.path.exists(os.path.join(A.CONFIG, "settings.json")), "the new folder has the settings")
# the About box and the File view
seen = {}
orig = Gtk.Dialog.run


def look(d):
    seen["about"] = (d.get_program_name() if isinstance(d, Gtk.AboutDialog) else d.get_title(), d.get_logo_icon_name() if isinstance(d, Gtk.AboutDialog) else None)
    return Gtk.ResponseType.CANCEL


Gtk.Dialog.run = look
try:
    win.run("about")
except Exception as e:
    print("about:", e)
Gtk.Dialog.run = orig
pump()
for w in Gtk.Window.list_toplevels():
    if isinstance(w, Gtk.AboutDialog):
        seen.setdefault("about", (w.get_program_name(), w.get_logo_icon_name()))
        w.destroy()
check(seen.get("about", ("", ""))[0] == "Folio Show", "About: %s" % (seen.get("about"),))
win.show_backstage()
pump()
texts = []


def walk(w):
    if isinstance(w, Gtk.Label):
        texts.append(w.get_text())
    if isinstance(w, Gtk.Container):
        w.forall(walk)


walk(win)
win.backstage.close()
check(not any("Deliver" in t for t in texts), "no 'Deliver' anywhere in the window and File view")
print("UI FAILED: %d" % len(FAILS) if FAILS else "UI all passed")
sys.stdout.flush()
win.deck.modified = False
os._exit(1 if FAILS else 0)

"""AutoRecover (S12-01): every few minutes a presentation with unsaved changes is copied to a folder
of its own; when Folio Show ends without saving it (a crash, a power cut), the next start offers the
copy back. Saving or closing the presentation removes its copy."""
import json
import os
import time
import uuid

from gi.repository import GLib

from . import savefile

DEFAULT_MINUTES = 10


def folder():
    base = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    return os.path.join(base, "folio-show", "recovery")


def _boot_id():
    try:
        with open("/proc/sys/kernel/random/boot_id") as f:
            return f.read().strip()
    except OSError:
        return ""


def _alive(pid, boot):
    """Whether the Folio Show that wrote a copy is still running (then it isn't lost)."""
    if boot != _boot_id():
        return False
    try:
        os.kill(int(pid), 0)
    except (OSError, ValueError, TypeError):
        return False
    try:
        with open("/proc/%d/cmdline" % int(pid), "rb") as f:
            return b"folio" in f.read()
    except OSError:
        return True


class Recovery:
    def __init__(self, app):
        self.app = app
        self._timer = None
        self._kept = {}             # id(deck) -> (copy id, deck version when copied, time)

    def minutes(self):
        try:
            return max(0, int(self.app.settings.get("autorecover_minutes", DEFAULT_MINUTES)))
        except (TypeError, ValueError):
            return DEFAULT_MINUTES

    def start(self):
        if self._timer is None:
            self._timer = GLib.timeout_add_seconds(30, self.tick)

    def tick(self):
        every = self.minutes() * 60
        if every:
            now = time.time()
            for w in list(self.app.windows):
                d = getattr(w, "deck", None)
                if d is None or not d.modified:
                    continue
                if id(d) not in self._kept:
                    # changed since the last check: the first copy comes one interval from now
                    self._kept[id(d)] = (None, None, now)
                    continue
                _cid, ver, when = self._kept[id(d)]
                if ver != d.version and now - when >= every:
                    self.keep(w)
        return True

    def keep(self, w):
        """Copy this window's presentation now; the copy's id."""
        d = w.deck
        cid, _ver, _t = self._kept.get(id(d), (None, None, None))
        cid = cid or uuid.uuid4().hex
        os.makedirs(folder(), mode=0o700, exist_ok=True)
        data = bytes(d.to_bytes())
        if getattr(w, "password", None):
            from . import crypt
            data = crypt.encrypt(data, w.password)
        base = os.path.join(folder(), cid)
        old = os.umask(0o077)
        try:
            savefile.write_atomic(base + ".pptx", data)
            meta = {"path": w.path or getattr(w, "recovered_from", None), "name": w.title_text(), "time": time.time(),
                    "pid": os.getpid(), "boot": _boot_id()}
            savefile.write_atomic(base + ".json", json.dumps(meta).encode("utf-8"))
        except OSError:
            return None
        finally:
            os.umask(old)
        self._kept[id(d)] = (cid, d.version, time.time())
        return cid

    def forget(self, w):
        """The presentation was saved or closed: its copy goes."""
        d = getattr(w, "deck", None)
        if d is None or any(o is not w and getattr(o, "deck", None) is d for o in self.app.windows):
            return
        cid, _v, _t = self._kept.pop(id(d), (None, None, None))
        if cid:
            self._remove(cid)

    def saved(self, w):
        d = getattr(w, "deck", None)
        if d is not None and id(d) in self._kept:
            self._remove(self._kept[id(d)][0])
            self._kept[id(d)] = (None, d.version, time.time())

    def _remove(self, cid):
        if not cid:
            return
        for ext in (".pptx", ".json"):
            try:
                os.remove(os.path.join(folder(), cid + ext))
            except OSError:
                pass

    def found(self):
        """Copies left by a Folio Show that is no longer running: [(copy id, meta)], newest first."""
        out = []
        try:
            names = os.listdir(folder())
        except OSError:
            return out
        for n in names:
            if not n.endswith(".json"):
                continue
            cid = n[:-5]
            try:
                with open(os.path.join(folder(), n)) as f:
                    meta = json.load(f)
            except (OSError, ValueError):
                continue
            if not os.path.exists(os.path.join(folder(), cid + ".pptx")):
                self._remove(cid)
                continue
            if _alive(meta.get("pid"), meta.get("boot")):
                continue
            out.append((cid, meta))
        out.sort(key=lambda c: -float(c[1].get("time") or 0))
        return out

    def offer(self, win):
        """At start: offer what an earlier Folio Show left unsaved."""
        got = self.found()
        if not got:
            return False
        ans = win.dialogs.recovered([(m.get("name") or "Presentation", m.get("time") or 0) for _c, m in got])
        if ans == "discard":
            for cid, _m in got:
                self._remove(cid)
        elif ans == "open":
            for k, (cid, meta) in enumerate(got):
                w = win if k == 0 and win.path is None and not win.deck.modified and win.deck.undo_label() is None \
                    else self.app.new_window(None)
                w.load_recovered(os.path.join(folder(), cid + ".pptx"), meta)
                # it is this window's own copy now, kept again when it changes
                self._kept[id(w.deck)] = (cid, None, 0.0)
        return True

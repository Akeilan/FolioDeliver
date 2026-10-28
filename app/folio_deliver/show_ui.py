"""Rehearse Timings, Custom Slide Shows, Create a Video, the Clipboard pane and the Thesaurus."""
import glob
import os
import shutil
import subprocess
import time

from gi.repository import Gdk, GLib, Gtk, Pango

from . import APP_NAME


def hms(t):
    t = int(round(t))
    return "%d:%02d:%02d" % (t // 3600, t // 60 % 60, t % 60)


class RecordingBar(Gtk.Window):
    """Rehearse Timings' Recording toolbar: next, pause, this slide's time, repeat, total."""
    def __init__(self, st, parent=None):
        Gtk.Window.__init__(self, title="Recording")
        self.st = st
        self.set_keep_above(True)
        self.set_decorated(True)
        self.set_resizable(False)
        if parent is not None:
            self.set_transient_for(parent)
        box = Gtk.Box(spacing=6, margin=6)
        nxt = Gtk.Button(label="▶")
        nxt.set_tooltip_text("Next")
        nxt.connect("clicked", lambda *_: st.next())
        pause = Gtk.Button(label="❚❚")
        pause.set_tooltip_text("Pause Recording")
        pause.connect("clicked", lambda *_: st.toggle_pause())
        self.slide_time = Gtk.Label(label="0:00:00")
        rep = Gtk.Button(label="↺")
        rep.set_tooltip_text("Repeat")
        rep.connect("clicked", lambda *_: self.repeat())
        self.total = Gtk.Label(label="0:00:00")
        for w in (nxt, pause, self.slide_time, rep, self.total):
            box.pack_start(w, False, False, 0)
        self.add(box)
        self._tick = GLib.timeout_add(250, self.tick)
        self.connect("destroy", lambda *_: GLib.source_remove(self._tick) if self._tick else None)
        self.show_all()
        self.move(16, 16)

    def repeat(self):
        st = self.st
        st._slide_t0 = time.time()
        if st.paused_at is not None:
            st.paused_at = time.time()

    def tick(self):
        st = self.st
        if st.ended:
            self._tick = None
            self.destroy()
            return False
        now = st.paused_at or time.time()
        self.slide_time.set_text(hms(now - st._slide_t0))
        self.total.set_text(hms(sum(st.rehearse.values()) + now - st._slide_t0))
        return True


def custom_shows_menu(win):
    from .ribbon import menu_popover
    items = [(name, lambda n=name: win.run("custom-show:" + n)) for name, _idx in win.deck.custom_shows()]
    if items:
        items.append(None)
    items.append(("Custom Shows...", lambda: win.run("custom-shows-dialog")))
    return menu_popover(None, items)


def edit_show_dialog(win, name, idx):
    """Define Custom Show: a name and the slides, in order. Returns (name, [indexes]) or None."""
    from .review_ui import slide_title
    deck = win.deck
    d = Gtk.Dialog(title="Define Custom Show", transient_for=win, modal=True)
    d.get_style_context().add_class("folio-dialog")
    d.set_default_size(560, 380)
    d.add_button("Cancel", Gtk.ResponseType.CANCEL)
    d.add_button("OK", Gtk.ResponseType.OK)
    box = d.get_content_area()
    box.set_border_width(10)
    box.set_spacing(6)
    row = Gtk.Box(spacing=6)
    row.pack_start(Gtk.Label(label="Slide show name:"), False, False, 0)
    entry = Gtk.Entry(text=name)
    row.pack_start(entry, True, True, 0)
    box.pack_start(row, False, False, 0)
    cols = Gtk.Box(spacing=6)
    left = Gtk.ListStore(int, str)
    for i in range(deck.slide_count()):
        left.append([i, "%d. %s" % (i + 1, slide_title(deck, i) or "Slide %d" % (i + 1))])
    right = Gtk.ListStore(int, str)
    for i in idx:
        if i < deck.slide_count():
            right.append([i, "%d. %s" % (i + 1, slide_title(deck, i) or "Slide %d" % (i + 1))])

    def view(store, title):
        tv = Gtk.TreeView(model=store)
        tv.append_column(Gtk.TreeViewColumn(title, Gtk.CellRendererText(), text=1))
        tv.get_selection().set_mode(Gtk.SelectionMode.MULTIPLE)
        sw = Gtk.ScrolledWindow()
        sw.set_min_content_width(220)
        sw.add(tv)
        return tv, sw
    lt, lsw = view(left, "Slides in presentation")
    rt, rsw = view(right, "Slides in custom show")
    mid = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
    mid.set_valign(Gtk.Align.CENTER)

    def add(*_):
        m, paths = lt.get_selection().get_selected_rows()
        for p in paths:
            right.append(list(m[p]))

    def remove(*_):
        m, paths = rt.get_selection().get_selected_rows()
        for p in reversed(paths):
            m.remove(m.get_iter(p))

    def move(step):
        m, paths = rt.get_selection().get_selected_rows()
        if len(paths) != 1:
            return
        k = paths[0].get_indices()[0]
        j = k + step
        if 0 <= j < len(m):
            m.swap(m.get_iter(k), m.get_iter(j))
    for label, fn in (("Add >>", add), ("Remove", remove), ("▲", lambda *_: move(-1)), ("▼", lambda *_: move(1))):
        b = Gtk.Button(label=label)
        b.connect("clicked", fn)
        mid.pack_start(b, False, False, 0)
    cols.pack_start(lsw, True, True, 0)
    cols.pack_start(mid, False, False, 0)
    cols.pack_start(rsw, True, True, 0)
    box.pack_start(cols, True, True, 0)
    d.show_all()
    r = d.run()
    out = (entry.get_text().strip() or "Custom Show", [row[0] for row in right]) if r == Gtk.ResponseType.OK else None
    d.destroy()
    return out


# ---------------------------------------------------------------- video
VIDEO_SIZES = [("Full HD (1080p)", 1920, 1080), ("HD (720p)", 1280, 720), ("Standard (480p)", 852, 480)]


def video_dialog(win):
    """Create a Video: quality and seconds per slide. Returns (w, h, seconds, use timings) or None."""
    d = Gtk.Dialog(title="Create a Video", transient_for=win, modal=True)
    d.get_style_context().add_class("folio-dialog")
    d.add_button("Cancel", Gtk.ResponseType.CANCEL)
    d.add_button("Create Video", Gtk.ResponseType.OK)
    g = Gtk.Grid(column_spacing=12, row_spacing=8, margin=12)
    d.get_content_area().add(g)
    q = Gtk.ComboBoxText()
    for label, _w, _h in VIDEO_SIZES:
        q.append_text(label)
    q.set_active(0)
    g.attach(Gtk.Label(label="Quality:", xalign=0), 0, 0, 1, 1)
    g.attach(q, 1, 0, 1, 1)
    timings = Gtk.CheckButton(label="Use recorded timings and narrations", active=True)
    g.attach(timings, 0, 1, 2, 1)
    g.attach(Gtk.Label(label="Seconds spent on each slide:", xalign=0), 0, 2, 1, 1)
    secs = Gtk.SpinButton.new_with_range(0.5, 600, 0.5)
    secs.set_value(5.0)
    g.attach(secs, 1, 2, 1, 1)
    d.show_all()
    r = d.run()
    out = None
    if r == Gtk.ResponseType.OK:
        _l, w, h = VIDEO_SIZES[max(0, q.get_active())]
        out = (w, h, secs.get_value(), timings.get_active())
    d.destroy()
    return out


def make_video(win, path, w, h, seconds, use_timings, fps=30, progress=None):
    """Render the show to an MP4 with ffmpeg: transitions, animations (one after another, no
    clicks) and each slide's time."""
    import cairo
    from .anim import Player
    from .show import blend
    deck = win.deck
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raise RuntimeError("Creating a video needs ffmpeg, which isn't installed (package ffmpeg).")
    cmd = [ffmpeg, "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "bgra", "-s", "%dx%d" % (w, h), "-r", str(fps),
           "-i", "-", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-movflags", "+faststart", path]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, preexec_fn=_die_with_parent)
    sw, sh = deck.size()
    scale = min(w / sw, h / sh)
    ox, oy = (w - sw * scale) / 2, (h - sh * scale) / 2
    order = [i for i in range(deck.slide_count()) if not deck.is_hidden(i)]
    out = cairo.ImageSurface(cairo.FORMAT_ARGB32, w, h)
    from .core import surface_from

    def frame(i, anim=None):
        rw, rh, stride, data, _ = deck.render(i, scale, False, anim)
        return surface_from(rw, rh, stride, data)

    def emit(src):
        cr = cairo.Context(out)
        cr.set_source_rgb(0, 0, 0)
        cr.paint()
        if src is not None:
            cr.set_source_surface(src, round(ox), round(oy))
            cr.paint()
        out.flush()
        proc.stdin.write(bytes(out.get_data()))
    frames = 0
    prev = None
    try:
        for k, i in enumerate(order):
            if progress:
                progress(k, len(order))
            kind, opt, dur, _click, after = deck.transition(i)
            pl = Player(deck, i)
            first = pl.state(0) if pl.groups else None
            cur0 = frame(i, first)
            t_used = 0.0
            if kind not in ("none", "") and dur:
                n = max(1, int(dur * fps))
                rw, rh = cur0.get_width(), cur0.get_height()
                for f in range(n):
                    tmp = cairo.ImageSurface(cairo.FORMAT_ARGB32, rw, rh)
                    cr = cairo.Context(tmp)
                    blend(cr, prev, cur0, kind, opt, f / n, rw, rh)
                    emit(tmp)
                    frames += 1
                t_used += dur
            for g in range(len(pl.groups)):
                length = pl.length(g)
                n = max(1, int(length * fps))
                for f in range(n):
                    emit(frame(i, pl.state(g, g, f / fps)))
                    frames += 1
                t_used += length
            last = frame(i, pl.state(len(pl.groups)) if pl.groups else None)
            hold = after if (use_timings and after is not None and after >= 0) else seconds
            for _f in range(max(1, int(max(0.0, hold - (t_used if use_timings and after is not None else 0)) * fps))):
                emit(last)
                frames += 1
            prev = last
    finally:
        proc.stdin.close()
        rc = proc.wait()
    if rc != 0:
        raise RuntimeError("ffmpeg couldn't write the video.")
    return frames


# ---------------------------------------------------------------- thesaurus
class Thesaurus:
    def __init__(self, idx):
        self.dat = idx[:-4] + ".dat"
        self.index = {}
        with open(idx, encoding="utf-8", errors="replace") as f:
            enc = f.readline().strip()
            f.readline()
            for line in f:
                wd, _, off = line.rstrip("\n").rpartition("|")
                if wd:
                    try:
                        self.index[wd.lower()] = int(off)
                    except ValueError:
                        pass
        self.enc = "latin-1" if enc.lower() in ("iso8859-1", "iso-8859-1") else "utf-8"

    def lookup(self, word):
        w = word.lower()
        off = self.index.get(w)
        # plain forms: results -> result, matches -> match, tried -> try, going -> go
        for cut, add in (("ies", "y"), ("es", ""), ("s", ""), ("ied", "y"), ("ed", ""), ("ed", "e"), ("ing", ""), ("ing", "e")):
            if off is not None:
                break
            if w.endswith(cut) and len(w) > len(cut) + 2:
                off = self.index.get(w[:-len(cut)] + add)
        if off is None:
            return []
        out = []
        with open(self.dat, "rb") as f:
            f.seek(off)
            head = f.readline().decode(self.enc, "replace").rstrip("\n")
            try:
                n = int(head.rpartition("|")[2])
            except ValueError:
                return []
            for _ in range(n):
                parts = f.readline().decode(self.enc, "replace").rstrip("\n").split("|")
                if len(parts) < 2:
                    continue
                pos = parts[0].strip("()")
                words = [p.replace(" (generic term)", "").replace(" (similar term)", "").replace(" (related term)", "")
                         .replace(" (antonym)", " (opposite)") for p in parts[1:] if p]
                if words:
                    out.append(("%s (%s)" % (words[0], pos) if pos else words[0], words))
        return out


_TH = {}


def thesaurus(lang="en_US"):
    if lang in _TH:
        return _TH[lang]
    th = None
    for d in ("/usr/share/mythes", "/usr/share/myspell/dicts", "/usr/share/hunspell"):
        for pat in ("th_%s_v2.idx" % lang, "th_%s*.idx" % lang, "th_%s*.idx" % lang.split("_")[0]):
            hits = sorted(glob.glob(os.path.join(d, pat)))
            if hits:
                th = Thesaurus(hits[0])
                break
        if th:
            break
    _TH[lang] = th
    return th


class ThesaurusPane(Gtk.Window):
    """Thesaurus (Shift+F7): meanings and synonyms of the word at the caret; Insert replaces it."""
    def __init__(self, win, word):
        Gtk.Window.__init__(self, title="Thesaurus", transient_for=win)
        self.win = win
        self.set_default_size(300, 480)
        self.get_style_context().add_class("folio-pane")
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin=8)
        row = Gtk.Box(spacing=4)
        self.entry = Gtk.SearchEntry(text=word)
        self.entry.connect("activate", lambda *_: self.look(self.entry.get_text()))
        row.pack_start(self.entry, True, True, 0)
        box.pack_start(row, False, False, 0)
        self.store = Gtk.TreeStore(str, str)
        self.view = Gtk.TreeView(model=self.store, headers_visible=False)
        self.view.append_column(Gtk.TreeViewColumn("", Gtk.CellRendererText(), text=0))
        self.view.connect("row-activated", lambda v, p, c: self.insert(self.store[p][1]))
        sw = Gtk.ScrolledWindow()
        sw.add(self.view)
        box.pack_start(sw, True, True, 0)
        b = Gtk.Button(label="Insert")
        b.connect("clicked", lambda *_: self.insert_picked())
        box.pack_start(b, False, False, 0)
        self.add(box)
        self.connect("destroy", lambda *_: setattr(win, "thesaurus_pane", None))
        self.look(word)
        self.show_all()

    def look(self, word):
        self.store.clear()
        th = thesaurus()
        if th is None:
            self.store.append(None, ["No thesaurus is installed (package mythes-en-us).", ""])
            return []
        res = th.lookup(word.strip()) if word.strip() else []
        if not res:
            self.store.append(None, ["No results for “%s”." % word, ""])
        for head, words in res:
            it = self.store.append(None, [head, words[0].split(" (")[0]])
            for wd in words[1:]:
                self.store.append(it, ["  " + wd, wd.split(" (")[0]])
        self.view.expand_all()
        return res

    def insert_picked(self):
        m, it = self.view.get_selection().get_selected()
        if it is not None and m[it][1]:
            self.insert(m[it][1])

    def insert(self, word):
        if word:
            self.win.replace_word(word)


class ShowCommands:
    # ------------------------------------------------------------ rehearse timings
    def act_rehearse_timings(self):
        if self.deck.slide_count() == 0:
            return
        self._save_notes()
        self.canvas.leave_text()
        from . import show
        st = show.start(self, 0, rehearse=True)
        self.show_state = st
        if st is not None:
            self.recording_bar = RecordingBar(st, getattr(st, "show_window", None))
        return st

    def finish_rehearsal(self, st, keep=None):
        """After a rehearsal: keep the timings (each slide advances after its time)?"""
        times = st.rehearse or {}
        if not times:
            return
        total = sum(times.values())
        if keep is None:
            d = Gtk.MessageDialog(transient_for=self, modal=True, message_type=Gtk.MessageType.QUESTION,
                                  buttons=Gtk.ButtonsType.YES_NO,
                                  text="The total time for the slide show was %s. Do you want to save the new slide timings?" % hms(total))
            d.set_title(APP_NAME)
            keep = d.run() == Gtk.ResponseType.YES
            d.destroy()
        if not keep:
            return
        for i, t in sorted(times.items()):
            kind, opt, dur, click, _after = self.deck.transition(i)
            self.deck.set_transition([i], kind, opt, dur, click, round(t, 2))
        s = self.deck.show_settings()
        if not s[5]:
            self.deck.set_show_settings(s[0], s[1], s[2], s[3], s[4], True, s[6])
        self.changed(structure=True)
        if getattr(self, "view", None) == "normal":
            self.set_view("sorter")

    # ------------------------------------------------------------ custom shows
    def act_custom_show(self, name):
        for n, idx in self.deck.custom_shows():
            if n == name and idx:
                self._save_notes()
                self.canvas.leave_text()
                from . import show
                self.show_state = show.start(self, idx[0], order=idx)
                return self.show_state
        return None

    def act_custom_shows_dialog(self):
        shows = list(self.deck.custom_shows())
        d = Gtk.Dialog(title="Custom Shows", transient_for=self, modal=True)
        d.get_style_context().add_class("folio-dialog")
        d.set_default_size(420, 300)
        d.add_button("Close", Gtk.ResponseType.CLOSE)
        d.add_button("Show", 5)
        box = Gtk.Box(spacing=8, margin=10)
        store = Gtk.ListStore(str)
        for n, _i in shows:
            store.append([n])
        tv = Gtk.TreeView(model=store, headers_visible=False)
        tv.append_column(Gtk.TreeViewColumn("", Gtk.CellRendererText(), text=0))
        sw = Gtk.ScrolledWindow()
        sw.add(tv)
        box.pack_start(sw, True, True, 0)
        side = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)

        def picked():
            m, it = tv.get_selection().get_selected()
            return m.get_path(it).get_indices()[0] if it else None

        def refresh():
            store.clear()
            for n, _i in shows:
                store.append([n])

        def new(*_):
            r = edit_show_dialog(self, "Custom Show %d" % (len(shows) + 1), [])
            if r and r[1]:
                shows.append(r)
                self.deck.set_custom_shows(shows)
                refresh()

        def edit(*_):
            k = picked()
            if k is not None:
                r = edit_show_dialog(self, shows[k][0], shows[k][1])
                if r:
                    shows[k] = r
                    self.deck.set_custom_shows(shows)
                    refresh()

        def remove(*_):
            k = picked()
            if k is not None:
                del shows[k]
                self.deck.set_custom_shows(shows)
                refresh()

        def copy(*_):
            k = picked()
            if k is not None:
                shows.append(("Copy of " + shows[k][0], list(shows[k][1])))
                self.deck.set_custom_shows(shows)
                refresh()
        for label, fn in (("New...", new), ("Edit...", edit), ("Remove", remove), ("Copy", copy)):
            b = Gtk.Button(label=label)
            b.connect("clicked", fn)
            side.pack_start(b, False, False, 0)
        box.pack_start(side, False, False, 0)
        d.get_content_area().add(box)
        d.show_all()
        r = d.run()
        k = picked()
        d.destroy()
        self.update_title()
        if r == 5 and k is not None:
            return self.act_custom_show(shows[k][0])
        return None

    # ------------------------------------------------------------ video
    def act_create_video(self):
        if shutil.which("ffmpeg") is None:
            self.dialogs.info("Creating a video needs ffmpeg, which isn't installed.\n\nInstall it with:  sudo apt install ffmpeg")
            return
        opts = video_dialog(self)
        if opts is None:
            return
        fc = Gtk.FileChooserNative(title="Save as Video", transient_for=self, action=Gtk.FileChooserAction.SAVE)
        fc.set_do_overwrite_confirmation(True)
        fc.set_current_name(os.path.splitext(self.doc_name())[0] + ".mp4")
        r = fc.run()
        path = fc.get_filename() if r == Gtk.ResponseType.ACCEPT else None
        fc.destroy()
        if path:
            self.export_video(path, *opts)

    def export_video(self, path, w, h, seconds, use_timings, fps=30):
        if not path.lower().endswith((".mp4", ".m4v")):
            path += ".mp4"
        self.status.slide_label.set_text("Creating video...")

        def progress(k, n):
            self.status.slide_label.set_text("Creating video: slide %d of %d" % (k + 1, n))
            while Gtk.events_pending():
                Gtk.main_iteration_do(False)
        try:
            make_video(self, path, w, h, seconds, use_timings, fps, progress)
        except Exception as e:
            self.dialogs.message("The video couldn't be created.\n\n%s" % e)
            return None
        finally:
            self.status.set_slide(self.current or 0, self.deck.slide_count())
        return path

    # ------------------------------------------------------------ clipboard pane
    def remember_clip(self, clip, label):
        hist = getattr(self.app, "clip_history", None)
        if hist is None:
            hist = self.app.clip_history = []
        hist.insert(0, (dict(clip), label))
        del hist[24:]
        p = getattr(self, "clipboard_pane", None)
        if p is not None:
            p.refresh()

    def act_clipboard_pane(self):
        p = getattr(self, "clipboard_pane", None)
        if p is not None:
            p.present()
            return p
        self.clipboard_pane = ClipboardPane(self)
        return self.clipboard_pane

    def paste_history(self, k):
        hist = getattr(self.app, "clip_history", [])
        if not 0 <= k < len(hist):
            return
        clip, label = hist[k]
        self.app.clip = clip
        self.clip = clip
        text = clip.get("text") or label
        Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD).set_text(text, -1)
        self._clip_text = text
        self.act_paste()

    # ------------------------------------------------------------ thesaurus
    def word_at_caret(self):
        c = self.canvas
        if c.edit is None:
            return ""
        if c.edit.has_selection():
            return c.selected_text().strip()
        p, o = c.edit.caret
        t = self.deck.paragraphs(self.current, c.edit.id)[p]
        a = o
        while a > 0 and (t[a - 1].isalnum() or t[a - 1] in "'-"):
            a -= 1
        b = o
        while b < len(t) and (t[b].isalnum() or t[b] in "'-"):
            b += 1
        return t[a:b]

    def replace_word(self, word):
        c = self.canvas
        if c.edit is None:
            return
        if not c.edit.has_selection():
            p, o = c.edit.caret
            t = self.deck.paragraphs(self.current, c.edit.id)[p]
            a = o
            while a > 0 and (t[a - 1].isalnum() or t[a - 1] in "'-"):
                a -= 1
            b = o
            while b < len(t) and (t[b].isalnum() or t[b] in "'-"):
                b += 1
            c.edit.anchor, c.edit.caret = (p, a), (p, b)
        c.type_text(word)

    def act_thesaurus(self):
        w = self.word_at_caret()
        p = getattr(self, "thesaurus_pane", None)
        if p is not None:
            p.entry.set_text(w)
            p.look(w)
            p.present()
            return p
        self.thesaurus_pane = ThesaurusPane(self, w)
        return self.thesaurus_pane


class ClipboardPane(Gtk.Window):
    """The Office Clipboard: the last 24 things cut or copied; click one to paste it."""
    def __init__(self, win):
        Gtk.Window.__init__(self, title="Clipboard", transient_for=win)
        self.win = win
        self.set_default_size(280, 460)
        self.get_style_context().add_class("folio-pane")
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin=8)
        top = Gtk.Box(spacing=6)
        pa = Gtk.Button(label="Paste All")
        pa.connect("clicked", lambda *_: self.paste_all())
        ca = Gtk.Button(label="Clear All")
        ca.connect("clicked", lambda *_: self.clear())
        top.pack_start(pa, False, False, 0)
        top.pack_start(ca, False, False, 0)
        box.pack_start(top, False, False, 0)
        self.list = Gtk.ListBox()
        self.list.connect("row-activated", lambda _l, row: win.paste_history(row.get_index()))
        sw = Gtk.ScrolledWindow()
        sw.add(self.list)
        box.pack_start(Gtk.Label(label="Click an item to paste:", xalign=0), False, False, 0)
        box.pack_start(sw, True, True, 0)
        self.add(box)
        self.connect("destroy", lambda *_: setattr(win, "clipboard_pane", None))
        self.refresh()
        self.show_all()

    def refresh(self):
        for c in self.list.get_children():
            self.list.remove(c)
        for clip, label in getattr(self.win.app, "clip_history", []):
            icon = {"text": "Aa", "shapes": "◻", "slides": "▭"}.get(clip.get("kind"), "")
            lab = Gtk.Label(label="%s  %s" % (icon, label), xalign=0, ellipsize=Pango.EllipsizeMode.END, margin=6)
            self.list.add(lab)
        self.list.show_all()

    def paste_all(self):
        n = len(getattr(self.win.app, "clip_history", []))
        for k in reversed(range(n)):
            self.win.paste_history(k)

    def clear(self):
        self.win.app.clip_history = []
        self.refresh()


def _die_with_parent():
    """Child processes (ffmpeg recording) stop when Deliver does, rather than recording on."""
    try:
        import ctypes
        import signal
        ctypes.CDLL("libc.so.6", use_errno=True).prctl(1, signal.SIGTERM)   # PR_SET_PDEATHSIG
    except Exception:
        pass

"""Insert extras: Icons (from the computer's icon themes), Screenshot, Photo Album, Object,
Video and Audio (with playback through GStreamer), narration recording and screen recording."""
import glob
import math
import os
import shutil
import subprocess
import tempfile
import time

import cairo
from gi.repository import Gdk, GdkPixbuf, GLib, Gtk

ICON_DIRS = ["/usr/share/icons/Adwaita/scalable", "/usr/share/icons/Adwaita/symbolic",
             "/usr/share/icons/hicolor/scalable", "/usr/share/icons/Yaru/scalable"]
CATEGORY_NAMES = {"actions": "Actions", "apps": "Apps", "categories": "Categories", "devices": "Devices",
                  "emblems": "Emblems", "emotes": "Faces", "mimetypes": "Files", "places": "Places",
                  "status": "Status", "ui": "Interface"}
VIDEO_EXT = ("mp4", "m4v", "mov", "webm", "avi", "wmv", "mkv")
AUDIO_EXT = ("mp3", "m4a", "wav", "ogg", "oga", "flac", "wma")


def gst():
    """GStreamer, or None when it isn't installed."""
    try:
        import gi
        gi.require_version("Gst", "1.0")
        from gi.repository import Gst
        if not Gst.is_initialized():
            Gst.init(None)
        return Gst
    except (ImportError, ValueError):
        return None


GST_MISSING = ("Playing and recording media needs GStreamer, which isn't installed.\n\n"
               "Install it with:  sudo apt install gir1.2-gstreamer-1.0 gstreamer1.0-gtk3 "
               "gstreamer1.0-plugins-good gstreamer1.0-libav")


def png_bytes(surface):
    import io
    buf = io.BytesIO()
    surface.write_to_png(buf)
    return buf.getvalue()


def icon_files():
    out = {}
    for base in ICON_DIRS:
        if not os.path.isdir(base):
            continue
        for path in glob.glob(os.path.join(base, "*", "*.svg")):
            cat = os.path.basename(os.path.dirname(path))
            name = os.path.splitext(os.path.basename(path))[0].replace("-symbolic", "")
            out.setdefault((cat, name), path)
    return out


def svg_png(path, size=256):
    pb = GdkPixbuf.Pixbuf.new_from_file_at_size(path, size, size)
    ok, data = pb.save_to_bufferv("png", [], [])
    return bytes(data), pb.get_width(), pb.get_height()


def _tint_for_theme(pb):
    """Icons are drawn in near-black; in dark mode show them light so they can be seen
    (the inserted icon keeps its own colour)."""
    from . import appearance
    if not appearance.is_dark():
        return pb
    import cairo
    w, h = pb.get_width(), pb.get_height()
    src = cairo.ImageSurface(cairo.FORMAT_ARGB32, w, h)
    cr = cairo.Context(src)
    Gdk.cairo_set_source_pixbuf(cr, pb, 0, 0)
    cr.paint()
    out = cairo.ImageSurface(cairo.FORMAT_ARGB32, w, h)
    cr = cairo.Context(out)
    cr.set_source_rgb(0.9, 0.9, 0.9)
    cr.mask_surface(src, 0, 0)
    return Gdk.pixbuf_get_from_surface(out, 0, 0, w, h)


def icons_dialog(win):
    """Insert Icons: browse and search; returns the chosen SVG paths."""
    files = icon_files()
    if not files:
        win.dialogs.message("No icon collections were found on this computer.")
        return []
    d = Gtk.Dialog(title="Insert Icons", transient_for=win, modal=True)
    d.get_style_context().add_class("folio-dialog")
    d.set_default_size(720, 520)
    d.add_button("Cancel", Gtk.ResponseType.CANCEL)
    ok = d.add_button("Insert", Gtk.ResponseType.OK)
    ok.get_style_context().add_class("suggested-action")
    box = d.get_content_area()
    box.set_spacing(6)
    box.set_border_width(8)
    search = Gtk.SearchEntry()
    search.set_placeholder_text("Search icons")
    box.pack_start(search, False, False, 0)
    cats = Gtk.Box(spacing=4)
    box.pack_start(cats, False, False, 0)
    flow = Gtk.FlowBox()
    flow.set_max_children_per_line(10)
    flow.set_selection_mode(Gtk.SelectionMode.MULTIPLE)
    flow.set_activate_on_single_click(False)
    sw = Gtk.ScrolledWindow()
    sw.set_size_request(680, 380)
    sw.add(flow)
    box.pack_start(sw, True, True, 0)
    count = Gtk.Label(xalign=0)
    box.pack_start(count, False, False, 0)
    keys = sorted(files)
    catsel = {"v": None}

    def fill(*_):
        for ch in flow.get_children():
            flow.remove(ch)
        q = search.get_text().strip().lower()
        shown = 0
        for c, n in keys:
            if catsel["v"] and c != catsel["v"]:
                continue
            if q and q not in n.lower():
                continue
            try:
                pb = GdkPixbuf.Pixbuf.new_from_file_at_size(files[(c, n)], 40, 40)
            except Exception:
                continue
            img = Gtk.Image.new_from_pixbuf(_tint_for_theme(pb))
            img.set_tooltip_text(n.replace("-", " "))
            img.path = files[(c, n)]
            flow.add(img)
            shown += 1
            if shown >= 400:
                break
        flow.show_all()
        count.set_text("%d icons%s" % (shown, " (the first 400)" if shown >= 400 else ""))
    for c in ["All"] + sorted({c for c, _n in keys}):
        b = Gtk.ToggleButton(label=CATEGORY_NAMES.get(c, c.capitalize()))
        b.connect("toggled", lambda w, c=c: w.get_active() and (catsel.__setitem__("v", None if c == "All" else c),
                                                                 [x.set_active(False) for x in cats.get_children() if x is not w],
                                                                 fill()))
        cats.pack_start(b, False, False, 0)
    search.connect("search-changed", fill)
    fill()
    d.show_all()
    r = d.run()
    picks = [ch.get_child().path for ch in flow.get_selected_children()]
    d.destroy()
    return picks if r == Gtk.ResponseType.OK else []


# ---------------------------------------------------------------- screenshot
def grab_screen():
    """The whole screen as a GdkPixbuf (gnome-screenshot when it's there, else the X root window)."""
    path = tempfile.mktemp(prefix="folio-shot-", suffix=".png")
    tool = shutil.which("gnome-screenshot")
    if tool:
        try:
            subprocess.run([tool, "-f", path], timeout=10, check=False)
            if os.path.exists(path):
                pb = GdkPixbuf.Pixbuf.new_from_file(path)
                os.remove(path)
                return pb
        except Exception:
            pass
    root = Gdk.get_default_root_window()
    return Gdk.pixbuf_get_from_window(root, 0, 0, root.get_width(), root.get_height())


class ClipWindow(Gtk.Window):
    """Screen Clipping: drag a rectangle over the frozen screen."""
    def __init__(self, win, pb, done):
        Gtk.Window.__init__(self)
        self.win, self.pb, self.done = win, pb, done
        self.set_decorated(False)
        self.fullscreen()
        self.set_keep_above(True)
        self.start = self.cur = None
        area = Gtk.DrawingArea()
        area.add_events(Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.BUTTON_RELEASE_MASK | Gdk.EventMask.POINTER_MOTION_MASK)
        area.connect("draw", self._draw)
        area.connect("button-press-event", self._press)
        area.connect("motion-notify-event", self._motion)
        area.connect("button-release-event", self._release)
        self.connect("key-press-event", lambda w, e: e.keyval == Gdk.KEY_Escape and self.destroy())
        self.add(area)
        self.area = area
        self.show_all()

    def _draw(self, a, cr):
        Gdk.cairo_set_source_pixbuf(cr, self.pb, 0, 0)
        cr.paint()
        cr.set_source_rgba(1, 1, 1, 0.45)
        cr.rectangle(0, 0, self.pb.get_width(), self.pb.get_height())
        if self.start and self.cur:
            x0, y0 = self.start
            x1, y1 = self.cur
            cr.rectangle(min(x0, x1), min(y0, y1), abs(x1 - x0), abs(y1 - y0))
            cr.set_fill_rule(cairo.FILL_RULE_EVEN_ODD)
        cr.fill()

    def _press(self, a, ev):
        self.start = self.cur = (ev.x, ev.y)

    def _motion(self, a, ev):
        if self.start:
            self.cur = (ev.x, ev.y)
            a.queue_draw()

    def _release(self, a, ev):
        if not self.start:
            return
        x0, y0 = self.start
        self.destroy()
        x, y = int(min(x0, ev.x)), int(min(y0, ev.y))
        w, h = int(abs(ev.x - x0)), int(abs(ev.y - y0))
        if w >= 4 and h >= 4:
            w = min(w, self.pb.get_width() - x)
            h = min(h, self.pb.get_height() - y)
            self.done(self.pb.new_subpixbuf(x, y, w, h).copy())


# ---------------------------------------------------------------- pictures drawn here
def poster_frame(path, w=640, h=360):
    """A still of a video (with ffmpeg), else a film picture."""
    ff = shutil.which("ffmpeg")
    if ff:
        out = tempfile.mktemp(suffix=".png")
        for at in ("1", "0"):
            try:
                subprocess.run([ff, "-y", "-loglevel", "error", "-ss", at, "-i", path, "-frames:v", "1", out],
                               timeout=30, check=False)
            except (OSError, subprocess.TimeoutExpired):
                break
            if os.path.exists(out) and os.path.getsize(out) > 0:
                with open(out, "rb") as fh:
                    data = fh.read()
                os.remove(out)
                return data
    s = cairo.ImageSurface(cairo.FORMAT_ARGB32, w, h)
    cr = cairo.Context(s)
    cr.set_source_rgb(0.12, 0.12, 0.14)
    cr.paint()
    cr.set_source_rgb(0.3, 0.3, 0.33)
    for k in range(0, w, 40):
        cr.rectangle(k + 10, 10, 20, 18)
        cr.rectangle(k + 10, h - 28, 20, 18)
    cr.fill()
    cr.set_source_rgba(1, 1, 1, 0.9)
    cr.move_to(w / 2 - 30, h / 2 - 40)
    cr.line_to(w / 2 + 40, h / 2)
    cr.line_to(w / 2 - 30, h / 2 + 40)
    cr.close_path()
    cr.fill()
    return png_bytes(s)


def speaker_icon(size=96):
    s = cairo.ImageSurface(cairo.FORMAT_ARGB32, size, size)
    cr = cairo.Context(s)
    k = size / 96.0
    cr.scale(k, k)
    cr.set_source_rgb(0.27, 0.45, 0.77)
    cr.move_to(14, 36)
    cr.line_to(34, 36)
    cr.line_to(56, 16)
    cr.line_to(56, 80)
    cr.line_to(34, 60)
    cr.line_to(14, 60)
    cr.close_path()
    cr.fill()
    cr.set_line_width(6)
    cr.set_line_cap(cairo.LINE_CAP_ROUND)
    for r in (14, 26):
        cr.arc(56, 48, r, -math.pi / 4, math.pi / 4)
        cr.stroke()
    return png_bytes(s)


def document_icon(ext, name, size=128):
    """An icon for an embedded document: the theme's file-type icon and the file name."""
    mime = {"xlsx": "x-office-spreadsheet", "docx": "x-office-document", "pptx": "x-office-presentation"}.get(ext, "text-x-generic")
    s = cairo.ImageSurface(cairo.FORMAT_ARGB32, size, int(size * 1.25))
    cr = cairo.Context(s)
    theme = Gtk.IconTheme.get_default()
    try:
        pb = theme.load_icon(mime, 96, 0)
        Gdk.cairo_set_source_pixbuf(cr, pb, (size - pb.get_width()) / 2, 4)
        cr.paint()
    except Exception:
        cr.set_source_rgb(0.85, 0.85, 0.85)
        cr.rectangle(24, 4, size - 48, 96)
        cr.fill()
    cr.set_source_rgb(0.1, 0.1, 0.1)
    cr.select_font_face("Sans")
    cr.set_font_size(11)
    label = name if len(name) <= 22 else name[:19] + "..."
    e = cr.text_extents(label)
    cr.move_to((size - e.width) / 2, size * 1.2)
    cr.show_text(label)
    return png_bytes(s)


# ---------------------------------------------------------------- playing
class MediaPlayer:
    """One media file playing (GStreamer playbin); video in `widget` (a gtksink) when wanted."""
    def __init__(self, path, video=True, on_end=None):
        Gst = gst()
        self.Gst = Gst
        self.bin = Gst.ElementFactory.make("playbin", None)
        self.bin.set_property("uri", GLib.filename_to_uri(path, None))
        self.widget = None
        if video:
            sink = Gst.ElementFactory.make("gtksink", None)
            if sink is not None:
                self.bin.set_property("video-sink", sink)
                self.widget = sink.get_property("widget")
        else:
            fake = Gst.ElementFactory.make("fakesink", None)
            if fake is not None:
                self.bin.set_property("video-sink", fake)
        bus = self.bin.get_bus()
        bus.add_signal_watch()
        self.on_end = on_end
        bus.connect("message::eos", lambda *_: self._ended())
        bus.connect("message::error", lambda *_: self._ended())
        self.playing = False

    def _ended(self):
        self.stop()
        if self.on_end:
            self.on_end()

    def play(self):
        self.bin.set_state(self.Gst.State.PLAYING)
        self.playing = True

    def pause(self):
        self.bin.set_state(self.Gst.State.PAUSED)
        self.playing = False

    def toggle(self):
        self.pause() if self.playing else self.play()

    def stop(self):
        self.bin.set_state(self.Gst.State.NULL)
        self.playing = False

    def position(self):
        ok, pos = self.bin.query_position(self.Gst.Format.TIME)
        return pos / 1e9 if ok else 0.0


class Recorder:
    """Records the microphone to a WAV file (narration)."""
    def __init__(self, path):
        Gst = gst()
        self.Gst = Gst
        self.path = path
        self.pipe = Gst.parse_launch('autoaudiosrc ! audioconvert ! audioresample ! wavenc ! filesink location="%s"' % path)
        self.started = None

    def start(self):
        self.pipe.set_state(self.Gst.State.PLAYING)
        self.started = time.time()

    def stop(self):
        # let wavenc finish its header
        self.pipe.send_event(self.Gst.Event.new_eos())
        bus = self.pipe.get_bus()
        bus.timed_pop_filtered(2 * self.Gst.SECOND, self.Gst.MessageType.EOS | self.Gst.MessageType.ERROR)
        self.pipe.set_state(self.Gst.State.NULL)
        return time.time() - (self.started or time.time())


class MediaCommands:
    # ------------------------------------------------------------ icons
    def act_insert_icons(self):
        picks = icons_dialog(self)
        return self.insert_icons(picks)

    def insert_icons(self, paths):
        out = []
        sw, sh = self.deck.size()
        for k, p in enumerate(paths):
            with open(p, "rb") as fh:
                svg = fh.read()
            png, pw, ph = svg_png(p)
            size = 72.0
            w, h = (size, size * ph / pw) if pw >= ph else (size * pw / ph, size)
            x = sw / 2 - w / 2 + 18 * k
            y = sh / 2 - h / 2 + 18 * k
            out.append(self.deck.add_svg_picture(self.current, svg, png, os.path.splitext(os.path.basename(p))[0], x, y, w, h))
        if out:
            self.changed(slide=True)
            self.canvas.select(out)
        return out

    # ------------------------------------------------------------ screenshot
    def act_screenshot(self, how="clip"):
        self.iconify()

        def capture():
            pb = grab_screen()
            self.deiconify()
            self.present()
            if pb is None:
                self.dialogs.message("The screen couldn't be captured.")
                return False
            if how == "screen":
                self.insert_pixbuf(pb, "Screenshot")
            else:
                ClipWindow(self, pb, lambda p: self.insert_pixbuf(p, "Screen Clipping"))
            return False
        GLib.timeout_add(700, capture)

    def insert_pixbuf(self, pb, name):
        ok, data = pb.save_to_bufferv("png", [], [])
        self._insert_picture_bytes(bytes(data), "png", name)

    # ------------------------------------------------------------ photo album
    def act_photo_album(self):
        d = Gtk.FileChooserNative(title="Photo Album: Insert New Pictures", transient_for=self, action=Gtk.FileChooserAction.OPEN)
        d.set_select_multiple(True)
        f = Gtk.FileFilter()
        f.set_name("All Pictures")
        for p in ("*.png", "*.jpg", "*.jpeg", "*.gif", "*.bmp", "*.tif", "*.tiff"):
            f.add_pattern(p)
            f.add_pattern(p.upper())
        d.add_filter(f)
        r = d.run()
        files = d.get_filenames() if r == Gtk.ResponseType.ACCEPT else []
        d.destroy()
        if not files:
            return None
        per = self._album_options()
        if per is None:
            return None
        return self.make_album(files, *per)

    def _album_options(self):
        dlg = Gtk.Dialog(title="Photo Album", transient_for=self, modal=True)
        dlg.get_style_context().add_class("folio-dialog")
        dlg.add_button("Cancel", Gtk.ResponseType.CANCEL)
        dlg.add_button("Create", Gtk.ResponseType.OK)
        g = Gtk.Grid(column_spacing=10, row_spacing=8, margin=12)
        dlg.get_content_area().add(g)
        lay = Gtk.ComboBoxText()
        for t in ("Fit to slide", "1 picture", "2 pictures", "4 pictures"):
            lay.append_text(t)
        lay.set_active(1)
        cap = Gtk.CheckButton(label="Captions below ALL pictures")
        g.attach(Gtk.Label(label="Picture layout:", xalign=0), 0, 0, 1, 1)
        g.attach(lay, 1, 0, 1, 1)
        g.attach(cap, 0, 1, 2, 1)
        dlg.show_all()
        r = dlg.run()
        out = ({0: 0, 1: 1, 2: 2, 3: 4}[lay.get_active()], cap.get_active()) if r == Gtk.ResponseType.OK else None
        dlg.destroy()
        return out

    def make_album(self, files, per=1, captions=False):
        """A new presentation: a title slide, then the pictures (per = 0: fit to slide)."""
        from .core import Presentation
        w = self.app.new_window()
        deck = w.deck
        names = {n: p for _m, ls in deck.layouts() for p, n in ls}
        title_l = names.get("Title Slide") or list(names.values())[0]
        blank = names.get("Blank") or list(names.values())[-1]
        title_only = names.get("Title Only") or blank
        if deck.slide_count() == 0:
            deck.new_slide(None, title_l)
        w.canvas._surface()
        for s in deck.shapes(0):
            if s["ph"] in ("title", "ctrTitle"):
                deck.set_text(0, s["id"], "Photo Album")
            elif s["ph"] == "subTitle":
                deck.set_text(0, s["id"], "by " + (GLib.get_real_name() or GLib.get_user_name()))
        sw, sh = deck.size()
        step = max(1, per)
        for k in range(0, len(files), step):
            i = deck.new_slide(deck.slide_count() - 1, blank if per in (0, 1) else title_only)
            group = files[k:k + step]
            if per == 0:
                cells = [(0, 0, sw, sh)]
            elif per == 1:
                cells = [(sw * 0.1, sh * 0.08, sw * 0.8, sh * (0.74 if captions else 0.84))]
            elif per == 2:
                cells = [(sw * 0.05 + c * sw * 0.47, sh * 0.25, sw * 0.43, sh * (0.55 if captions else 0.65)) for c in range(2)]
            else:
                cells = [(sw * 0.1 + (c % 2) * sw * 0.42, sh * 0.22 + (c // 2) * sh * 0.39, sw * 0.38, sh * (0.30 if captions else 0.35))
                         for c in range(4)]
            for path, (cx, cy, cw, ch) in zip(group, cells):
                with open(path, "rb") as fh:
                    data = fh.read()
                ext = os.path.splitext(path)[1][1:].lower()
                size = Presentation.picture_size(data)
                if size is None:
                    continue
                kk = min(cw / size[0], ch / size[1]) if per else max(cw / size[0], ch / size[1])
                pw, ph = size[0] * kk, size[1] * kk
                deck.add_picture(i, data, ext, os.path.basename(path), cx + (cw - pw) / 2, cy + (ch - ph) / 2, pw, ph)
                if captions:
                    deck.add_textbox(i, cx, cy + ch + 4, cw, 24, os.path.splitext(os.path.basename(path))[0])
        w.changed(structure=True, all_slides=True)
        w.go_slide(0)
        return w

    # ------------------------------------------------------------ object
    def act_insert_object(self):
        d = Gtk.FileChooserNative(title="Insert Object: Create from File", transient_for=self, action=Gtk.FileChooserAction.OPEN)
        f = Gtk.FileFilter()
        f.set_name("Documents (*.xlsx, *.docx, *.pptx)")
        for p in ("*.xlsx", "*.docx", "*.pptx"):
            f.add_pattern(p)
            f.add_pattern(p.upper())
        d.add_filter(f)
        r = d.run()
        p = d.get_filename() if r == Gtk.ResponseType.ACCEPT else None
        d.destroy()
        if p:
            return self.insert_object(p)
        return None

    def insert_object(self, path):
        ext = os.path.splitext(path)[1][1:].lower()
        prog = {"xlsx": "Excel.Sheet.12", "docx": "Word.Document.12", "pptx": "PowerPoint.Show.12"}.get(ext)
        if prog is None:
            self.dialogs.info("Documents in the .xlsx, .docx and .pptx formats can be embedded.")
            return None
        with open(path, "rb") as fh:
            data = fh.read()
        name = os.path.basename(path)
        icon = document_icon(ext, name)
        sw, sh = self.deck.size()
        w, h = 96.0, 120.0
        sid = self.deck.add_embedded(self.current, data, ext, prog, icon, name, (sw - w) / 2, (sh - h) / 2, w, h)
        self.changed(slide=True)
        self.canvas.select([sid])
        return sid

    def open_object(self, sid):
        """Open an embedded document in its own program (a copy)."""
        info = self.deck.embedded_info(self.current, sid)
        if not info:
            return None
        prog, part = info
        data = self.deck.part_bytes(part)
        ext = part.rsplit(".", 1)[-1]
        path = os.path.join(tempfile.mkdtemp(prefix="folio-object-"), "Embedded document." + ext)
        with open(path, "wb") as fh:
            fh.write(bytes(data))
        try:
            Gtk.show_uri_on_window(self, GLib.filename_to_uri(path, None), Gdk.CURRENT_TIME)
        except Exception as e:
            self.dialogs.message("The document couldn't be opened.\n\n%s" % e)
        return path

    # ------------------------------------------------------------ video and audio
    def act_insert_video(self):
        return self._insert_media_dialog("video")

    def act_insert_audio(self):
        return self._insert_media_dialog("audio")

    def _insert_media_dialog(self, kind):
        d = Gtk.FileChooserNative(title="Insert Video" if kind == "video" else "Insert Audio", transient_for=self,
                                  action=Gtk.FileChooserAction.OPEN)
        f = Gtk.FileFilter()
        exts = VIDEO_EXT if kind == "video" else AUDIO_EXT
        f.set_name(("Video files" if kind == "video" else "Audio files") + " (%s)" % ", ".join("*." + e for e in exts))
        for e in exts:
            f.add_pattern("*." + e)
            f.add_pattern("*." + e.upper())
        d.add_filter(f)
        r = d.run()
        p = d.get_filename() if r == Gtk.ResponseType.ACCEPT else None
        d.destroy()
        if p:
            return self.insert_media(p, kind)
        return None

    def insert_media(self, path, kind=None, x=None, y=None, name=None):
        ext = os.path.splitext(path)[1][1:].lower()
        kind = kind or ("video" if ext in VIDEO_EXT else "audio")
        with open(path, "rb") as fh:
            data = fh.read()
        sw, sh = self.deck.size()
        if kind == "video":
            poster = poster_frame(path)
            try:
                ld = GdkPixbuf.PixbufLoader()
                ld.write(poster)
                ld.close()
                pb = ld.get_pixbuf()
                pw, ph = pb.get_width(), pb.get_height()
            except Exception:
                pw, ph = 16, 9
            w = sw * 0.6
            h = w * ph / pw
            x = (sw - w) / 2 if x is None else x
            y = (sh - h) / 2 if y is None else y
        else:
            poster = speaker_icon()
            w = h = 36.0
            x = (sw - w) / 2 if x is None else x
            y = (sh - h) / 2 if y is None else y
        sid = self.deck.add_media(self.current, kind, data, ext, poster, name or os.path.basename(path), x, y, w, h)
        self.changed(slide=True)
        self.canvas.select([sid])
        return sid

    def media_file(self, i, sid):
        """A media shape's file, written out to play it."""
        info = self.deck.media_info(i, sid)
        if not info:
            return None, None
        kind, part, ext = info
        cache = getattr(self, "_media_files", None)
        if cache is None:
            cache = self._media_files = {}
        key = (id(self.deck), part)
        if key not in cache or not os.path.exists(cache[key]):
            data = self.deck.part_bytes(part)
            if data is None:
                return None, None
            path = os.path.join(tempfile.mkdtemp(prefix="folio-media-"), "media." + ext)
            with open(path, "wb") as fh:
                fh.write(bytes(data))
            cache[key] = path
        return kind, cache[key]

    def act_media_play(self):
        """Playback > Play: the selected video or audio in a small window."""
        c = self.canvas
        if len(c.sel) != 1:
            return None
        kind, path = self.media_file(self.current, c.sel[0])
        if path is None:
            self.dialogs.info("Select a video or audio clip first.")
            return None
        if gst() is None:
            self.dialogs.info(GST_MISSING)
            return None
        old = getattr(self, "preview_player", None)
        if old is not None:
            old[0].stop()
            if old[1] is not None:
                old[1].destroy()
        pl = MediaPlayer(path, video=kind == "video")
        w = None
        if kind == "video" and pl.widget is not None:
            w = Gtk.Window(title="Video", transient_for=self)
            w.set_default_size(640, 360)
            w.add(pl.widget)
            w.connect("destroy", lambda *_: pl.stop())
            w.show_all()
        pl.on_end = (lambda: w.destroy()) if w is not None else None
        pl.play()
        self.preview_player = (pl, w)
        return pl

    def act_media_start(self, how):
        """Playback > Start: On Click, or Automatically (when the slide comes up)."""
        c = self.canvas
        if len(c.sel) != 1 or not self.deck.media_info(self.current, c.sel[0]):
            return None
        sid = c.sel[0]
        fx = [e for e in self.deck.animations(self.current) if not (e["class"] == "mediacall" and e["spid"] == sid)]
        if how == "auto":
            first = 0
            fx.insert(first, {"spid": sid, "class": "mediacall", "preset": 1, "subtype": 0,
                              "trigger": "after",
                              "delay": 0.0, "dur": 0.001, "repeat": 1.0})
        self.deck.set_animations(self.current, fx, "Start")
        self.changed(slide=True)
        return how

    def act_record_audio(self):
        """Record Sound: record from the microphone, then insert the clip."""
        if gst() is None:
            self.dialogs.info(GST_MISSING)
            return None
        path = os.path.join(tempfile.mkdtemp(prefix="folio-sound-"), "Recorded Sound.wav")
        rec = Recorder(path)
        d = Gtk.Dialog(title="Record Sound", transient_for=self, modal=True)
        d.get_style_context().add_class("folio-dialog")
        d.add_button("Cancel", Gtk.ResponseType.CANCEL)
        d.add_button("OK", Gtk.ResponseType.OK)
        lab = Gtk.Label(label="Recording... 0:00", margin=16)
        d.get_content_area().add(lab)
        t0 = time.time()

        def tick():
            lab.set_text("Recording... %d:%02d" % divmod(int(time.time() - t0), 60))
            return d.get_visible()
        GLib.timeout_add(500, tick)
        rec.start()
        d.show_all()
        r = d.run()
        rec.stop()
        d.destroy()
        if r == Gtk.ResponseType.OK and os.path.exists(path) and os.path.getsize(path) > 100:
            return self.insert_media(path, "audio", name="Recorded Sound")
        return None

    # ------------------------------------------------------------ narration
    def act_record(self, where="current"):
        """Record: the show with the Recording toolbar; each slide's narration and timing are kept."""
        if gst() is None:
            self.dialogs.info(GST_MISSING)
            return None
        start = 0 if where == "beginning" else (self.current or 0)
        st = self.act_rehearse_timings_from(start)
        if st is None:
            return None
        st.narration = {}
        self._narrate(st)
        return st

    def act_rehearse_timings_from(self, start):
        from . import show
        from .show_ui import RecordingBar
        self._save_notes()
        self.canvas.leave_text()
        st = show.start(self, start, rehearse=True)
        self.show_state = st
        if st is not None:
            self.recording_bar = RecordingBar(st, getattr(st, "show_window", None))
        return st

    def _narrate(self, st):
        state = {"i": st.index, "rec": None}

        def begin(i):
            path = os.path.join(tempfile.mkdtemp(prefix="folio-narration-"), "slide%d.wav" % (i + 1))
            r = Recorder(path)
            r.start()
            state["rec"], state["i"], state["path"] = r, i, path

        def end():
            r = state["rec"]
            if r is not None:
                r.stop()
                st.narration[state["i"]] = state["path"]
                state["rec"] = None

        def listen():
            if st.ended:
                end()
                return
            if st.index != state["i"]:
                end()
                if st.index is not None and st.screen is None:
                    begin(st.index)
        st.listeners.append(listen)
        begin(st.index)

    def keep_narration(self, st):
        """After recording: each slide's narration as an audio icon that plays by itself."""
        out = []
        sw, sh = self.deck.size()
        cur = self.current
        for i, path in sorted(getattr(st, "narration", {}).items()):
            if not os.path.exists(path) or os.path.getsize(path) < 100:
                continue
            self.current = i
            with open(path, "rb") as fh:
                data = fh.read()
            sid = self.deck.add_media(i, "audio", data, "wav", speaker_icon(), "Narration", sw - 44, sh - 44, 32, 32)
            fx = self.deck.animations(i)
            fx.insert(0, {"spid": sid, "class": "mediacall", "preset": 1, "subtype": 0, "trigger": "after",
                          "delay": 0.0, "dur": 0.001, "repeat": 1.0})
            self.deck.set_animations(i, fx, "Narration")
            out.append(sid)
        self.current = cur
        self.changed(structure=True)
        return out

    # ------------------------------------------------------------ screen recording
    def act_screen_recording(self):
        ff = shutil.which("ffmpeg")
        if os.environ.get("XDG_SESSION_TYPE") == "wayland" or not os.environ.get("DISPLAY"):
            self.dialogs.info("Screen recording works on an X11 desktop session; this one is Wayland.")
            return None
        if ff is None:
            self.dialogs.info("Screen recording needs ffmpeg, which isn't installed.\n\nInstall it with:  sudo apt install ffmpeg")
            return None
        return self.start_screen_recording()

    def start_screen_recording(self, seconds=None):
        root = Gdk.get_default_root_window()
        w, h = root.get_width() // 2 * 2, root.get_height() // 2 * 2
        path = os.path.join(tempfile.mkdtemp(prefix="folio-screen-"), "Screen Recording.mp4")
        cmd = [shutil.which("ffmpeg"), "-y", "-loglevel", "error", "-f", "x11grab", "-video_size", "%dx%d" % (w, h),
               "-framerate", "15", "-i", os.environ.get("DISPLAY", ":0")]
        if seconds:
            cmd += ["-t", str(seconds)]
        cmd += ["-c:v", "libx264", "-pix_fmt", "yuv420p", path]
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, preexec_fn=_die_with_parent)
        bar = Gtk.Window(title="Screen Recording")
        bar.set_keep_above(True)
        b = Gtk.Button(label="■ Stop Recording")
        bar.add(b)
        bar.move(16, 16)
        self.iconify()
        bar.show_all()
        self.screen_rec = (proc, bar, path)

        def stop(*_):
            try:
                proc.stdin.write(b"q")
                proc.stdin.flush()
            except (BrokenPipeError, ValueError):
                pass
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
            bar.destroy()
            self.deiconify()
            self.present()
            self.screen_rec = None
            if os.path.exists(path) and os.path.getsize(path) > 0:
                self.insert_media(path, "video")
        b.connect("clicked", stop)
        self.stop_screen_recording = stop
        return path


def _die_with_parent():
    """Child processes (ffmpeg recording) stop when Show does, rather than recording on."""
    try:
        import ctypes
        import signal
        ctypes.CDLL("libc.so.6", use_errno=True).prctl(1, signal.SIGTERM)   # PR_SET_PDEATHSIG
    except Exception:
        pass

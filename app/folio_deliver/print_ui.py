"""Printing (File > Print): Full Page Slides, Notes Pages, Outline and Handouts, slide ranges,
hidden slides, a preview, and the system print dialog for the printer."""
import math

import cairo
from gi.repository import Gtk, Pango, PangoCairo

from .core import surface_from

LAYOUTS = [("full", "Full Page Slides"), ("notes", "Notes Pages"), ("outline", "Outline"),
           ("h1", "1 Slide"), ("h2", "2 Slides"), ("h3", "3 Slides"), ("h4", "4 Slides Horizontal"),
           ("h6", "6 Slides Horizontal"), ("h9", "9 Slides Horizontal")]


class PrintJob:
    def __init__(self, win):
        self.win = win
        self.layout = "full"
        self.which = "all"            # all | current | custom
        self.custom = ""
        self.hidden = True
        self.frame = False
        self.gray = False

    def slides(self):
        deck = self.win.deck
        n = deck.slide_count()
        if self.which == "current":
            return [self.win.current or 0]
        if self.which == "custom":
            out = []
            for part in self.custom.replace(" ", "").split(","):
                if not part:
                    continue
                try:
                    if "-" in part:
                        a, b = part.split("-", 1)
                        out += list(range(int(a) - 1, min(n, int(b))))
                    else:
                        out.append(int(part) - 1)
                except ValueError:
                    continue
            return [i for i in out if 0 <= i < n]
        return [i for i in range(n) if self.hidden or not deck.is_hidden(i)]

    def per_page(self):
        return {"h1": 1, "h2": 2, "h3": 3, "h4": 4, "h6": 6, "h9": 9}.get(self.layout, 1)

    def pages(self):
        s = self.slides()
        if self.layout == "outline":
            return [s] if s else []
        k = self.per_page()
        return [s[i:i + k] for i in range(0, len(s), k)]

    def page_size(self):
        """Points: landscape for full slides, portrait otherwise (Letter)."""
        if self.layout == "full":
            sw, sh = self.win.deck.size()
            return (792, 612) if sw >= sh else (612, 792)
        return (612, 792)

    def _slide(self, cr, i, x, y, w, h):
        deck = self.win.deck
        sw, sh = deck.size()
        scale = min(w / sw, h / sh)
        dpi_scale = scale * 300 / 72
        pw, ph, stride, data, _ = deck.render(i, dpi_scale, False)
        surf = surface_from(pw, ph, stride, data)
        cr.save()
        ox = x + (w - sw * scale) / 2
        oy = y + (h - sh * scale) / 2
        cr.translate(ox, oy)
        cr.scale(72 / 300, 72 / 300)
        cr.set_source_surface(surf, 0, 0)
        cr.paint()
        cr.restore()
        if self.frame or self.layout != "full":
            cr.set_source_rgb(0.3, 0.3, 0.3)
            cr.set_line_width(0.75)
            cr.rectangle(ox, oy, sw * scale, sh * scale)
            cr.stroke()

    def _text(self, cr, text, x, y, w, size=11, bold=False):
        lay = PangoCairo.create_layout(cr)
        fd = Pango.FontDescription("Calibri %s %d" % ("Bold" if bold else "", size))
        lay.set_font_description(fd)
        lay.set_width(int(w * Pango.SCALE))
        lay.set_wrap(Pango.WrapMode.WORD_CHAR)
        lay.set_text(text, -1)
        cr.move_to(x, y)
        cr.set_source_rgb(0, 0, 0)
        PangoCairo.show_layout(cr, lay)
        return lay.get_pixel_size()[1]

    def draw_page(self, cr, k, pw, ph):
        """Page k into a pw x ph point area."""
        pages = self.pages()
        if k >= len(pages):
            return
        group = pages[k]
        cr.set_source_rgb(1, 1, 1)
        cr.paint()
        m = 36
        deck = self.win.deck
        if self.layout == "full":
            self._slide(cr, group[0], m / 2, m / 2, pw - m, ph - m)
        elif self.layout == "notes":
            i = group[0]
            self._slide(cr, i, m * 1.5, m * 1.5, pw - m * 3, ph * 0.42)
            self._text(cr, deck.notes(i), m * 1.5, ph * 0.5, pw - m * 3, 12)
            self._text(cr, str(i + 1), pw - m * 1.5, ph - m, 40, 10)
        elif self.layout == "outline":
            y = m
            for i in group:
                for sid, ph_kind, paras in deck.slide_text(i):
                    title = ph_kind in ("title", "ctrTitle")
                    for p in paras:
                        if not p:
                            continue
                        if y > ph - m:
                            break
                        y += self._text(cr, ("%d  " % (i + 1) if title else "      ") + p, m, y, pw - 2 * m,
                                        14 if title else 11, title) + 2
                y += 8
        else:
            n = self.per_page()
            if n == 3:
                cell_h = (ph - 2 * m) / 3
                for j, i in enumerate(group):
                    self._slide(cr, i, m, m + j * cell_h + 6, pw / 2 - m, cell_h - 12)
                    cr.set_source_rgb(0.6, 0.6, 0.6)
                    cr.set_line_width(0.5)
                    for r in range(6):
                        yy = m + j * cell_h + 14 + r * (cell_h - 20) / 6
                        cr.move_to(pw / 2 + 10, yy)
                        cr.line_to(pw - m, yy)
                    cr.stroke()
            else:
                cols = {1: 1, 2: 1, 4: 2, 6: 2, 9: 3}[n]
                rows = math.ceil(n / cols)
                cw = (pw - 2 * m) / cols
                chh = (ph - 2 * m) / rows
                for j, i in enumerate(group):
                    r, c = divmod(j, cols)
                    self._slide(cr, i, m + c * cw + 8, m + r * chh + 8, cw - 16, chh - 16)
        if self.gray:
            cr.set_operator(cairo.OPERATOR_HSL_SATURATION)
            cr.set_source_rgb(0.5, 0.5, 0.5)
            cr.paint()
            cr.set_operator(cairo.OPERATOR_OVER)

    def run(self, parent):
        op = Gtk.PrintOperation()
        op.set_job_name(parent.title_text() if hasattr(parent, "title_text") else "Presentation")
        pages = self.pages()
        op.set_n_pages(max(1, len(pages)))
        setup = Gtk.PageSetup()
        w, h = self.page_size()
        setup.set_orientation(Gtk.PageOrientation.LANDSCAPE if w > h else Gtk.PageOrientation.PORTRAIT)
        op.set_default_page_setup(setup)
        op.set_use_full_page(True)
        op.set_unit(Gtk.Unit.POINTS)

        def draw(op, ctx, k):
            cr = ctx.get_cairo_context()
            self.draw_page(cr, k, ctx.get_width(), ctx.get_height())
        op.connect("draw-page", draw)
        try:
            return op.run(Gtk.PrintOperationAction.PRINT_DIALOG, parent)
        except Exception as e:
            parent.dialogs.message("Printing failed.\n\n%s" % e)
            return None

    def to_pdf(self, path):
        w, h = self.page_size()
        surf = cairo.PDFSurface(path, w, h)
        cr = cairo.Context(surf)
        for k in range(len(self.pages())):
            self.draw_page(cr, k, w, h)
            cr.show_page()
        surf.finish()


def print_page(win, close):
    job = getattr(win, "print_job", None) or PrintJob(win)
    win.print_job = job
    box = Gtk.Box(spacing=24)
    left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
    left.set_size_request(300, -1)
    pb = Gtk.Button(label="Print")
    pb.get_style_context().add_class("suggested-action")
    pb.get_style_context().add_class("folio-bs-printbtn")
    pb.set_size_request(90, 70)
    pb.set_halign(Gtk.Align.START)
    left.pack_start(pb, False, False, 0)
    left.pack_start(Gtk.Label(label="Settings", xalign=0), False, False, 4)
    which = Gtk.ComboBoxText()
    for k, t in (("all", "Print All Slides"), ("current", "Print Current Slide"), ("custom", "Custom Range")):
        which.append(k, t)
    which.set_active_id(job.which)
    left.pack_start(which, False, False, 0)
    rng = Gtk.Entry()
    rng.set_placeholder_text("Slides: e.g. 1-3, 5")
    rng.set_text(job.custom)
    left.pack_start(rng, False, False, 0)
    lay = Gtk.ComboBoxText()
    for k, t in LAYOUTS:
        lay.append(k, t)
    lay.set_active_id(job.layout)
    left.pack_start(lay, False, False, 0)
    hid = Gtk.CheckButton(label="Print Hidden Slides")
    hid.set_active(job.hidden)
    left.pack_start(hid, False, False, 0)
    frm = Gtk.CheckButton(label="Frame Slides")
    frm.set_active(job.frame)
    left.pack_start(frm, False, False, 0)
    gray = Gtk.CheckButton(label="Grayscale")
    gray.set_active(job.gray)
    left.pack_start(gray, False, False, 0)
    box.pack_start(left, False, False, 0)
    right = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
    right.get_style_context().add_class("folio-bs-preview")
    preview = Gtk.DrawingArea()
    preview.set_size_request(520, 420)
    state = {"page": 0}

    def draw(area, cr):
        aw, ah = area.get_allocated_width(), area.get_allocated_height()
        cr.set_source_rgb(0.91, 0.91, 0.91)
        cr.paint()
        pw, ph = job.page_size()
        s = min((aw - 30) / pw, (ah - 30) / ph)
        cr.translate((aw - pw * s) / 2, (ah - ph * s) / 2)
        cr.scale(s, s)
        cr.set_source_rgba(0, 0, 0, 0.2)
        cr.rectangle(3, 3, pw, ph)
        cr.fill()
        cr.rectangle(0, 0, pw, ph)
        cr.clip()
        job.draw_page(cr, state["page"], pw, ph)
    preview.connect("draw", draw)
    right.pack_start(preview, True, True, 0)
    nav = Gtk.Box(spacing=6, halign=Gtk.Align.CENTER)
    prev = Gtk.Button(label="◀")
    nxt = Gtk.Button(label="▶")
    count = Gtk.Label()
    nav.pack_start(prev, False, False, 0)
    nav.pack_start(count, False, False, 0)
    nav.pack_start(nxt, False, False, 0)
    right.pack_start(nav, False, False, 6)
    box.pack_start(right, True, True, 0)

    def refresh(*_):
        job.which = which.get_active_id()
        job.custom = rng.get_text()
        job.layout = lay.get_active_id()
        job.hidden = hid.get_active()
        job.frame = frm.get_active()
        job.gray = gray.get_active()
        rng.set_sensitive(job.which == "custom")
        n = len(job.pages())
        state["page"] = max(0, min(state["page"], n - 1))
        count.set_text("%d of %d" % (state["page"] + 1 if n else 0, n))
        preview.queue_draw()
    for w, sig in ((which, "changed"), (rng, "changed"), (lay, "changed"), (hid, "toggled"),
                   (frm, "toggled"), (gray, "toggled")):
        w.connect(sig, refresh)
    prev.connect("clicked", lambda *_: (state.__setitem__("page", state["page"] - 1), refresh()))
    nxt.connect("clicked", lambda *_: (state.__setitem__("page", state["page"] + 1), refresh()))
    pb.connect("clicked", lambda *_: (close(), job.run(win)))
    refresh()
    return box

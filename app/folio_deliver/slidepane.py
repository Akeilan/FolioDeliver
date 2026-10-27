"""The slide thumbnails pane (Normal view) and the Slide Sorter: click to go, Ctrl/Shift to
select several, drag to reorder, keys and a right-click menu as in the original."""
import cairo
from gi.repository import Gdk, GLib, Gtk, Pango

from .core import surface_from


class Thumbs:
    """Slide pictures, kept per slide part and redrawn only when that slide changes."""
    def __init__(self, win):
        self.win = win
        self.cache = {}            # part -> (width, surface)
        self.dirty = set()

    def forget(self, part=None):
        if part is None:
            self.cache.clear()
        else:
            self.cache.pop(part, None)

    def get(self, i, width):
        deck = self.win.deck
        parts = deck.slide_parts()
        if i >= len(parts):
            return None
        part = parts[i]
        c = self.cache.get(part)
        if c is not None and c[0] == width:
            return c[1]
        sw, sh = deck.size()
        scale = width / sw
        w, h, stride, data, _shapes = deck.render(i, scale, False)
        surf = surface_from(w, h, stride, data)
        self.cache[part] = (width, surf)
        return surf


class SlidePane(Gtk.Box):
    THUMB_W = 168

    def __init__(self, win, sorter=False):
        Gtk.Box.__init__(self, orientation=Gtk.Orientation.VERTICAL)
        self.win = win
        self.sorter = sorter
        self.get_style_context().add_class("folio-slidepane")
        self.area = Gtk.DrawingArea()
        self.area.set_can_focus(True)
        self.area.add_events(Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.BUTTON_RELEASE_MASK |
                             Gdk.EventMask.POINTER_MOTION_MASK | Gdk.EventMask.KEY_PRESS_MASK |
                             Gdk.EventMask.SCROLL_MASK)
        self.area.connect("draw", self.on_draw)
        self.area.connect("button-press-event", self.on_press)
        self.area.connect("button-release-event", self.on_release)
        self.area.connect("motion-notify-event", self.on_motion)
        self.area.connect("key-press-event", self.on_key)
        self.area.connect("focus-in-event", lambda *_: (self.queue(), False)[1])
        self.area.connect("focus-out-event", lambda *_: (self.queue(), False)[1])
        self.scroller = Gtk.ScrolledWindow()
        self.scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.scroller.add(self.area)
        self.scroller.connect("size-allocate", lambda *_: self.relayout())
        self.pack_start(self.scroller, True, True, 0)
        self.selected = [0]
        self.drag = None
        self.drop_at = None
        self.sorter_zoom = 1.0
        if not sorter:
            self.set_size_request(self.THUMB_W + 52, -1)

    # ------------------------------------------------------------ layout
    def thumb_width(self):
        if self.sorter:
            return int(220 * self.sorter_zoom)
        return max(80, self.scroller.get_allocated_width() - 52)

    def columns(self):
        if not self.sorter:
            return 1
        w = self.scroller.get_allocated_width()
        return max(1, int((w - 20) // (self.thumb_width() + 40)))

    HEAD = 26

    def section_starts(self):
        """{first slide index: section name}, cached per change."""
        deck = self.win.deck
        key = (id(deck), deck.version)
        if getattr(self, "_sec_key", None) != key:
            self._sec_key = key
            try:
                self._secs = [(f, n) for n, f, _c in deck.sections()]
            except Exception:
                self._secs = []
        return self._secs

    def cell(self, i):
        """(x, y, w, h) of slide i's picture (sections put a heading before their first slide and,
        in the sorter, start a new row)."""
        sw, sh = self.win.deck.size()
        tw = self.thumb_width()
        th = int(tw * sh / sw)
        cols = self.columns()
        secs = self.section_starts()
        if self.sorter:
            y = 16
            row_start = 0
            col = 0
            starts = {f for f, _n in secs}
            for k in range(i + 1):
                if k in starts:
                    if k != row_start or col:
                        y += th + 46
                    y += self.HEAD
                    col = 0
                    row_start = k
                elif col >= cols:
                    y += th + 46
                    col = 0
                if k < i:
                    col += 1
            return 30 + col * (tw + 40), y, tw, th
        heads = sum(1 for f, _n in secs if f <= i)
        return 36, 10 + i * (th + 14) + heads * self.HEAD, tw, th

    def relayout(self):
        deck = self.win.deck
        if deck is None:
            return
        n = deck.slide_count()
        if n == 0:
            self.area.set_size_request(-1, 60)
            return
        x, y, w, h = self.cell(n - 1)
        self.area.set_size_request(-1, int(y + h + 30))
        self.queue()

    def queue(self):
        self.area.queue_draw()

    def index_at(self, x, y):
        deck = self.win.deck
        for i in range(deck.slide_count()):
            cx, cy, w, h = self.cell(i)
            if cx - 30 <= x <= cx + w + 6 and cy - 6 <= y <= cy + h + 8:
                return i
        return None

    def gap_at(self, x, y):
        """The insertion point (before slide k) nearest a point, for dropping."""
        deck = self.win.deck
        n = deck.slide_count()
        best, bd = n, None
        for i in range(n + 1):
            if i < n:
                cx, cy, w, h = self.cell(i)
                px, py = (cx, cy) if self.sorter else (cx, cy)
            else:
                cx, cy, w, h = self.cell(n - 1)
                px, py = (cx + w, cy) if self.sorter else (cx, cy + h + 8)
            d = (px - x) ** 2 + (py + (h / 2 if self.sorter else 0) - y) ** 2 if self.sorter else abs(py - y)
            if bd is None or d < bd:
                best, bd = i, d
        return best

    def ensure_visible(self, i):
        x, y, w, h = self.cell(i)
        adj = self.scroller.get_vadjustment()
        if y < adj.get_value():
            adj.set_value(max(0, y - 8))
        elif y + h > adj.get_value() + adj.get_page_size():
            adj.set_value(y + h - adj.get_page_size() + 12)

    # ------------------------------------------------------------ drawing
    def on_draw(self, area, cr):
        deck = self.win.deck
        cr.set_source_rgb(0.95, 0.95, 0.95) if not self.sorter else cr.set_source_rgb(0.92, 0.92, 0.92)
        cr.paint()
        if deck is None:
            return
        n = deck.slide_count()
        tw = self.thumb_width()
        clip = cr.clip_extents()
        sections = self.win.sections() if hasattr(self.win, "sections") else {}
        for i in range(n):
            x, y, w, h = self.cell(i)
            if y + h + 20 < clip[1] or y - 20 > clip[3]:
                continue
            surf = self.win.thumbs.get(i, tw)
            cur = i == self.win.current
            sel = i in self.selected
            if sel or cur:
                cr.set_source_rgb(1.0, 0.51, 0.0) if cur else cr.set_source_rgb(1.0, 0.75, 0.5)
                cr.rectangle(x - 3, y - 3, w + 6, h + 6)
                cr.fill()
            cr.set_source_rgb(0.75, 0.75, 0.75)
            cr.rectangle(x - 0.5, y - 0.5, w + 1, h + 1)
            cr.stroke()
            if surf is not None:
                cr.set_source_surface(surf, x, y)
                cr.paint_with_alpha(0.55 if deck.is_hidden(i) else 1.0)
            # number (and the hidden mark)
            cr.set_source_rgb(0.25, 0.25, 0.25)
            cr.select_font_face("Sans")
            cr.set_font_size(11)
            num = str(i + 1)
            ext = cr.text_extents(num)
            if self.sorter:
                cr.move_to(x, y + h + 16)
            else:
                cr.move_to(x - 10 - ext.width, y + 14)
            cr.show_text(num)
            if deck.is_hidden(i):
                # a slashed box round the number
                bx = (x - 14 - ext.width) if not self.sorter else x - 4
                by = (y + 2) if not self.sorter else y + h + 4
                cr.set_line_width(1)
                cr.rectangle(bx, by, ext.width + 8, 15)
                cr.move_to(bx, by + 15)
                cr.line_to(bx + ext.width + 8, by)
                cr.stroke()
        # section headings
        for f, name in self.section_starts():
            if f > n:
                continue
            if f < n:
                x, y, w, h = self.cell(f)
            else:
                x, y, w, h = self.cell(n - 1) if n else (36, 10, tw, 0)
                y += h + 14
            cr.set_source_rgb(0.30, 0.30, 0.30)
            cr.select_font_face("Sans", 0, 1)
            cr.set_font_size(11)
            cr.move_to(8 if not self.sorter else 12, y - 9)
            cr.show_text("\u25be " + name)
            cr.select_font_face("Sans")
        # transition marks (a small star beside the number, as the original's)
        for i in range(n):
            x, y, w, h = self.cell(i)
            if y + h + 20 < clip[1] or y - 20 > clip[3]:
                continue
            try:
                kind = deck.transition(i)[0]
            except Exception:
                kind = "none"
            if kind != "none":
                cr.set_source_rgb(0.45, 0.45, 0.45)
                cr.set_font_size(10)
                if self.sorter:
                    cr.move_to(x + w - 12, y + h + 16)
                else:
                    cr.move_to(x - 22, y + 30)
                cr.show_text("\u2605")
        # drop marker
        if self.drop_at is not None:
            cr.set_source_rgb(1.0, 0.51, 0.0)
            if self.drop_at < n:
                x, y, w, h = self.cell(self.drop_at)
                if self.sorter:
                    cr.rectangle(x - 22, y, 3, h)
                else:
                    cr.rectangle(x, y - 9, w, 3)
            else:
                x, y, w, h = self.cell(n - 1)
                if self.sorter:
                    cr.rectangle(x + w + 17, y, 3, h)
                else:
                    cr.rectangle(x, y + h + 5, w, 3)
            cr.fill()

    # ------------------------------------------------------------ mouse
    def on_press(self, area, ev):
        area.grab_focus()
        i = self.index_at(ev.x, ev.y)
        shift = bool(ev.state & Gdk.ModifierType.SHIFT_MASK)
        ctrl = bool(ev.state & Gdk.ModifierType.CONTROL_MASK)
        if ev.button == 3:
            if i is not None and i not in self.selected:
                self.selected = [i]
                self.win.go_slide(i, keep_selection=True)
            self.win.slide_menu(ev, i)
            return True
        if ev.button != 1:
            return True
        if i is None:
            return True
        if ev.type == Gdk.EventType._2BUTTON_PRESS and self.sorter:
            self.win.go_slide(i)
            self.win.run("view-normal")
            return True
        if ctrl:
            if i in self.selected and len(self.selected) > 1:
                self.selected.remove(i)
            else:
                self.selected.append(i)
            self.win.go_slide(i, keep_selection=True)
        elif shift:
            a = self.win.current or 0
            self.selected = list(range(min(a, i), max(a, i) + 1))
            self.win.go_slide(i, keep_selection=True)
        else:
            if i not in self.selected:
                self.selected = [i]
            self.drag = {"start": (ev.x, ev.y), "index": i, "moved": False}
            self.win.go_slide(i, keep_selection=True)
        self.queue()
        return True

    def on_motion(self, area, ev):
        d = self.drag
        if d is None:
            return True
        if not d["moved"] and abs(ev.y - d["start"][1]) + abs(ev.x - d["start"][0]) < 6:
            return True
        d["moved"] = True
        self.drop_at = self.gap_at(ev.x, ev.y)
        self.queue()
        return True

    def on_release(self, area, ev):
        d = self.drag
        self.drag = None
        if d is not None and d["moved"] and self.drop_at is not None:
            to = self.drop_at
            self.drop_at = None
            idx = sorted(self.selected)
            if not (idx and idx[0] <= to <= idx[-1] + 1 and len(idx) == idx[-1] - idx[0] + 1):
                at = self.win.deck.move_slides(idx, to)
                self.selected = list(range(at, at + len(idx)))
                self.win.changed(structure=True)
                self.win.go_slide(at, keep_selection=True)
        else:
            if d is not None and not d["moved"]:
                self.selected = [d["index"]]
        self.drop_at = None
        self.queue()
        return True

    # ------------------------------------------------------------ keys
    def on_key(self, area, ev):
        name = Gdk.keyval_name(ev.keyval) or ""
        ctrl = bool(ev.state & Gdk.ModifierType.CONTROL_MASK)
        shift = bool(ev.state & Gdk.ModifierType.SHIFT_MASK)
        n = self.win.deck.slide_count()
        cur = self.win.current or 0
        cols = self.columns()
        step = {"Up": -cols, "Down": cols, "Left": -1, "Right": 1, "Page_Up": -1, "Page_Down": 1}
        if name in step and n:
            if ctrl and name in ("Up", "Down"):
                self.win.run("slide-up" if name == "Up" else "slide-down")
                return True
            j = max(0, min(n - 1, cur + step[name]))
            if shift:
                lo = min(self.selected + [cur])
                self.selected = sorted(set(range(min(lo, j), max(lo, j) + 1)))
            else:
                self.selected = [j]
            self.win.go_slide(j, keep_selection=True)
            self.ensure_visible(j)
            return True
        if name in ("Home", "End") and n:
            j = 0 if name == "Home" else n - 1
            self.selected = [j]
            self.win.go_slide(j, keep_selection=True)
            self.ensure_visible(j)
            return True
        if name in ("Delete", "BackSpace", "KP_Delete"):
            self.win.run("delete-slides")
            return True
        if name in ("Return", "KP_Enter") and not ctrl:
            if self.sorter:
                self.win.run("view-normal")
            else:
                self.win.run("new-slide")
            return True
        if ctrl and name in ("a", "A"):
            self.selected = list(range(n))
            self.queue()
            return True
        return False

"""The slide editing area (Normal view): the slide drawn by the engine, objects selected,
moved, resized and rotated with the mouse, and text typed in place."""
import math
import time

import cairo
from gi.repository import Gdk, GLib, Gtk

from .core import surface_from

HANDLE = 4.0          # half size of a sizing handle (px)
ROT_GAP = 22.0        # rotation handle above the top edge (px)
MARGIN = 28.0         # grey margin round the slide (px)
NUDGE = 7.2           # arrow-key nudge (points; Ctrl: 1 point)
ACCENT = (1.0, 0.51, 0.0)


def rot_point(x, y, cx, cy, deg):
    a = math.radians(deg)
    dx, dy = x - cx, y - cy
    return cx + dx * math.cos(a) - dy * math.sin(a), cy + dx * math.sin(a) + dy * math.cos(a)


class TextEdit:
    """The text being edited: its shape, caret and selection anchor."""
    def __init__(self, sid, caret=(0, 0)):
        self.id = sid
        self.caret = caret
        self.anchor = caret
        self.want_x = None

    @property
    def base(self):
        """The shape the text is in (a table's text is in one of its cells)."""
        return self.id & 0xFFFFF

    @property
    def cell(self):
        c = self.id >> 20
        return c - 1 if c else None

    def has_selection(self):
        return self.caret != self.anchor

    def range(self):
        return (min(self.caret, self.anchor), max(self.caret, self.anchor))


class SlideCanvas(Gtk.Box):
    def __init__(self, win):
        Gtk.Box.__init__(self, orientation=Gtk.Orientation.VERTICAL)
        self.win = win
        self.scroller = Gtk.ScrolledWindow()
        self.scroller.get_style_context().add_class("folio-canvas")
        self.area = Gtk.DrawingArea()
        self.area.set_can_focus(True)
        self.area.add_events(Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.BUTTON_RELEASE_MASK |
                             Gdk.EventMask.POINTER_MOTION_MASK | Gdk.EventMask.SCROLL_MASK |
                             Gdk.EventMask.SMOOTH_SCROLL_MASK | Gdk.EventMask.KEY_PRESS_MASK |
                             Gdk.EventMask.FOCUS_CHANGE_MASK)
        self.area.connect("draw", self.on_draw)
        self.area.connect("button-press-event", self.on_press)
        self.area.connect("button-release-event", self.on_release)
        self.area.connect("motion-notify-event", self.on_motion)
        self.area.connect("scroll-event", self.on_scroll)
        self.area.connect("size-allocate", lambda *_: self.queue())
        self.area.connect("focus-in-event", lambda *_: (self.im.focus_in(), False)[1])
        self.area.connect("focus-out-event", lambda *_: (self.im.focus_out(), False)[1])
        self.scroller.add(self.area)
        self.pack_start(self.scroller, True, True, 0)
        self.im = Gtk.IMContextSimple()
        self.im.connect("commit", lambda _im, s: self.type_text(s))
        self.fit = True
        self.zoom = 1.0                  # 100% = 96 px per inch
        self.scale = 1.0                 # px per point now
        self.ox = self.oy = 0.0
        self.cache = None                # (index, version, scale, surface, shapes)
        self.shapes = []
        self.sel = []
        self.edit = None
        self.drag = None
        self.insert_mode = None          # ("shape", prst) | ("textbox",)
        self.blink_on = True
        self._blink = None
        self.show_ruler = False
        self.show_grid = False
        self.show_guides = False

    # ------------------------------------------------------------ geometry
    @property
    def deck(self):
        return self.win.deck

    @property
    def index(self):
        return self.win.current

    def slide_size(self):
        return self.deck.size()

    def compute_scale(self):
        sw, sh = self.slide_size()
        if self.fit:
            aw = max(50, self.scroller.get_allocated_width() - 2 * MARGIN)
            ah = max(50, self.scroller.get_allocated_height() - 2 * MARGIN)
            self.scale = max(0.05, min(aw / sw, ah / sh))
            self.zoom = self.scale * 72.0 / 96.0
            self.area.set_size_request(-1, -1)
        else:
            self.scale = self.zoom * 96.0 / 72.0
            self.area.set_size_request(int(sw * self.scale + 2 * MARGIN), int(sh * self.scale + 2 * MARGIN))
        aw, ah = self.area.get_allocated_width(), self.area.get_allocated_height()
        self.ox = max(MARGIN, (aw - sw * self.scale) / 2)
        self.oy = max(MARGIN, (ah - sh * self.scale) / 2)

    def to_slide(self, x, y):
        return (x - self.ox) / self.scale, (y - self.oy) / self.scale

    def to_px(self, x, y):
        return self.ox + x * self.scale, self.oy + y * self.scale

    def zoom_percent(self):
        return int(round(self.zoom * 100))

    def set_zoom(self, pct=None, fit=False):
        if fit:
            self.fit = True
        else:
            self.fit = False
            self.zoom = max(0.1, min(4.0, pct / 100.0))
        self.queue()
        self.win.status.show_zoom(self.zoom_percent() if not fit else None)

    # ------------------------------------------------------------ rendering
    def invalidate(self):
        self.cache = None
        self.queue()

    def queue(self):
        self.area.queue_draw()

    def _surface(self):
        i = self.index
        if i is None or i >= self.deck.slide_count():
            return None, []
        key = (i, self.deck.version, round(self.scale, 4))
        if self.cache is not None and self.cache[:3] == key:
            return self.cache[3], self.cache[4]
        w, h, stride, data, shapes = self.deck.render(i, self.scale, True)
        surf = surface_from(w, h, stride, data)
        self.cache = key + (surf, shapes)
        self.shapes = shapes
        ids = {s["id"] for s in shapes}
        self.sel = [s for s in self.sel if s in ids]
        if self.edit is not None and self.edit.base not in ids:
            self.edit = None
        return surf, shapes

    def shape(self, sid):
        for s in self.shapes:
            if s["id"] == sid:
                return s
        return None

    def on_draw(self, area, cr):
        self.compute_scale()
        pct = self.zoom_percent()
        if self.fit and getattr(self, "_shown_pct", None) != pct:
            self._shown_pct = pct
            GLib.idle_add(lambda: (self.win.status.show_zoom(pct), False)[1])
        aw, ah = area.get_allocated_width(), area.get_allocated_height()
        cr.set_source_rgb(0.90, 0.90, 0.90)
        cr.paint()
        if self.deck is None or self.deck.slide_count() == 0:
            cr.set_source_rgb(0.45, 0.45, 0.45)
            cr.select_font_face("Sans")
            cr.set_font_size(16)
            t = "Click to add first slide"
            e = cr.text_extents(t)
            cr.move_to((aw - e.width) / 2, ah / 2)
            cr.show_text(t)
            return
        surf, shapes = self._surface()
        if surf is None:
            return
        sw, sh = self.slide_size()
        # shadow and slide
        cr.set_source_rgba(0, 0, 0, 0.18)
        cr.rectangle(self.ox + 2, self.oy + 2, sw * self.scale, sh * self.scale)
        cr.fill()
        ap = getattr(self, "anim_play", None)
        if ap is not None:
            pl, start = ap
            t = time.time() - start
            g = 0
            while g < len(pl.groups) and t > pl.length(g):
                t -= pl.length(g)
                g += 1
            if g >= len(pl.groups):
                self.anim_play = None
            else:
                w_, h_, stride, data, _ = self.deck.render(self.index, self.scale, False, pl.state(g, g, t))
                frame = surface_from(w_, h_, stride, data)
                cr.set_source_surface(frame, round(self.ox), round(self.oy))
                cr.paint()
                return
        pv = getattr(self, "preview", None)
        if pv is not None:
            from .show import blend
            cr.save()
            cr.translate(round(self.ox), round(self.oy))
            blend(cr, pv[0], pv[1], pv[2], pv[3], pv[4], surf.get_width(), surf.get_height())
            cr.restore()
            return
        cr.set_source_surface(surf, round(self.ox), round(self.oy))
        cr.paint()
        if self.show_grid:
            self._draw_grid(cr, sw, sh)
        if self.show_guides:
            cr.set_source_rgba(0.5, 0.5, 0.5, 0.8)
            cr.set_line_width(1)
            cr.set_dash([4, 3])
            x, y = self.to_px(sw / 2, sh / 2)
            cr.move_to(x + 0.5, self.oy)
            cr.line_to(x + 0.5, self.oy + sh * self.scale)
            cr.move_to(self.ox, y + 0.5)
            cr.line_to(self.ox + sw * self.scale, y + 0.5)
            cr.stroke()
            cr.set_dash([])
        cur = getattr(self.win.ribbon, "current", None)
        if cur is not None and cur.name == "Animations":
            self._draw_anim_tags(cr)
        self._draw_selection(cr)
        self._draw_drag(cr)

    def play_animation(self, pl):
        self.anim_play = (pl, time.time())

        def tick():
            if getattr(self, "anim_play", None) is None:
                self.queue()
                return False
            self.queue()
            return True
        GLib.timeout_add(16, tick)

    def _draw_anim_tags(self, cr):
        """On the Animations tab: each animated object's click numbers beside it."""
        try:
            fx = self.deck.animations(self.index)
        except Exception:
            return
        if not fx:
            return
        tags = {}
        n = 0
        for k, e in enumerate(fx):
            if e["trigger"] == "click" or k == 0:
                n += 1 if e["trigger"] == "click" else 0
            tags.setdefault(e["spid"], [])
            label = str(n) if n else "0"
            if label not in tags[e["spid"]]:
                tags[e["spid"]].append(label)
        cr.select_font_face("Sans")
        cr.set_font_size(10)
        for sid, labs in tags.items():
            s = self.shape(sid)
            if s is None:
                continue
            x, y = self.to_px(s["x"], s["y"])
            for j, lab in enumerate(labs):
                ext = cr.text_extents(lab)
                bw = max(14, ext.width + 6)
                bx = x - bw - 3
                by = y + j * 16
                cr.set_source_rgb(0.92, 0.92, 0.92)
                cr.rectangle(bx, by, bw, 14)
                cr.fill_preserve()
                cr.set_source_rgb(0.45, 0.45, 0.45)
                cr.set_line_width(1)
                cr.stroke()
                cr.set_source_rgb(0.1, 0.1, 0.1)
                cr.move_to(bx + (bw - ext.width) / 2, by + 11)
                cr.show_text(lab)

    def _draw_grid(self, cr, sw, sh):
        step = 72.0 / 12 * 2      # 1/6 inch
        cr.set_source_rgba(0.5, 0.5, 0.5, 0.35)
        x = 0.0
        while x <= sw:
            y = 0.0
            while y <= sh:
                px, py = self.to_px(x, y)
                cr.rectangle(px, py, 1, 1)
                y += step
            x += step
        cr.fill()

    def _corners(self, s, pad=0.0):
        x, y, w, h, r = s["x"], s["y"], s["w"], s["h"], s["rot"]
        cx, cy = x + w / 2, y + h / 2
        pts = [(x - pad, y - pad), (x + w + pad, y - pad), (x + w + pad, y + h + pad), (x - pad, y + h + pad)]
        return [self.to_px(*rot_point(px, py, cx, cy, r)) for px, py in pts]

    def handles(self, s):
        """Handle name -> pixel position, for one selected object."""
        x, y, w, h, r = s["x"], s["y"], s["w"], s["h"], s["rot"]
        cx, cy = x + w / 2, y + h / 2
        pts = {"nw": (x, y), "n": (cx, y), "ne": (x + w, y), "e": (x + w, cy), "se": (x + w, y + h),
               "s": (cx, y + h), "sw": (x, y + h), "w": (x, cy)}
        out = {k: self.to_px(*rot_point(px, py, cx, cy, r)) for k, (px, py) in pts.items()}
        if s["kind"] != "cxnSp":
            top = rot_point(cx, y - ROT_GAP / self.scale, cx, cy, r)
            out["rot"] = self.to_px(*top)
        if s["kind"] == "cxnSp":
            fh, fv = s["flip_h"], s["flip_v"]
            a = (x + w if fh else x, y + h if fv else y)
            b = (x if fh else x + w, y if fv else y + h)
            out = {"start": self.to_px(*a), "end": self.to_px(*b)}
        return out

    def _draw_selection(self, cr):
        for sid in self.sel:
            s = self.shape(sid)
            if s is None:
                continue
            editing = self.edit is not None and self.edit.base == sid
            pts = self._corners(s)
            cr.set_line_width(1)
            if editing:
                cr.set_source_rgb(0.55, 0.55, 0.55)
                cr.set_dash([4, 2])
            else:
                cr.set_source_rgb(0.45, 0.45, 0.45)
            if s["kind"] != "cxnSp":
                cr.move_to(*pts[0])
                for p in pts[1:]:
                    cr.line_to(*p)
                cr.close_path()
                cr.stroke()
            cr.set_dash([])
            if len(self.sel) == 1 or True:
                for name, (hx, hy) in self.handles(s).items():
                    if name == "rot":
                        cr.arc(hx, hy, 5.5, 0, 2 * math.pi)
                        cr.set_source_rgb(1, 1, 1)
                        cr.fill_preserve()
                        cr.set_source_rgb(0.35, 0.35, 0.35)
                        cr.stroke()
                        cr.arc(hx, hy, 3, -math.pi * 0.9, math.pi * 0.6)
                        cr.stroke()
                        continue
                    cr.arc(hx, hy, HANDLE + 0.5, 0, 2 * math.pi)
                    cr.set_source_rgb(1, 1, 1)
                    cr.fill_preserve()
                    cr.set_source_rgb(0.35, 0.35, 0.35)
                    cr.stroke()
        if self.edit is not None:
            self._draw_text_edit(cr)

    def _draw_text_edit(self, cr):
        e = self.edit
        s = self.shape(e.base)
        if s is None:
            return
        cx, cy = s["x"] + s["w"] / 2, s["y"] + s["h"] / 2
        cr.save()
        px, py = self.to_px(cx, cy)
        cr.translate(px, py)
        cr.rotate(math.radians(s["rot"]))
        cr.translate(-px, -py)
        if e.has_selection():
            a, b = e.range()
            try:
                rects = self.deck.selection_rects(self.index, e.id, a, b)
            except Exception:
                rects = []
            cr.set_source_rgba(0.2, 0.45, 0.85, 0.32)
            for x, y, w, h in rects:
                X, Y = self.to_px(x, y)
                cr.rectangle(X, Y, w * self.scale, h * self.scale)
            cr.fill()
        elif self.blink_on and self.area.has_focus():
            try:
                c = self.deck.caret(self.index, e.id, *e.caret)
            except Exception:
                c = None
            if c:
                x, y, h, _r = c
                X, Y = self.to_px(x, y)
                cr.set_source_rgb(0, 0, 0)
                cr.rectangle(round(X), Y, 1.2, h * self.scale)
                cr.fill()
        cr.restore()

    def _draw_drag(self, cr):
        d = self.drag
        if d is None:
            return
        cr.set_line_width(1)
        if d["kind"] == "band":
            x0, y0 = d["start"]
            x1, y1 = d["now"]
            cr.set_source_rgba(0.2, 0.45, 0.85, 0.15)
            cr.rectangle(min(x0, x1), min(y0, y1), abs(x1 - x0), abs(y1 - y0))
            cr.fill_preserve()
            cr.set_source_rgba(0.2, 0.45, 0.85, 0.8)
            cr.stroke()
            return
        if d["kind"] == "draw":
            x0, y0 = d["start"]
            x1, y1 = d["now"]
            cr.set_source_rgba(*ACCENT, 0.9)
            cr.set_dash([4, 3])
            if d["what"][0] == "shape" and d["what"][1] in ("line", "straightConnector1"):
                cr.move_to(x0, y0)
                cr.line_to(x1, y1)
            elif d["what"][0] == "shape" and d["what"][1] == "ellipse":
                cr.save()
                cx, cy, rx, ry = (x0 + x1) / 2, (y0 + y1) / 2, max(1, abs(x1 - x0) / 2), max(1, abs(y1 - y0) / 2)
                cr.translate(cx, cy)
                cr.scale(rx, ry)
                cr.arc(0, 0, 1, 0, 2 * math.pi)
                cr.restore()
            else:
                cr.rectangle(min(x0, x1), min(y0, y1), abs(x1 - x0), abs(y1 - y0))
            cr.stroke()
            cr.set_dash([])
            return
        if d.get("moved") and d.get("boxes"):
            cr.set_source_rgba(0.2, 0.2, 0.2, 0.8)
            cr.set_dash([3, 3])
            for sid, (x, y, w, h, r) in d["boxes"].items():
                s = dict(x=x, y=y, w=w, h=h, rot=r)
                pts = self._corners(s)
                cr.move_to(*pts[0])
                for p in pts[1:]:
                    cr.line_to(*p)
                cr.close_path()
            cr.stroke()
            cr.set_dash([])

    # ------------------------------------------------------------ hit testing
    def hit_shape(self, sx, sy, pad=0.0):
        """The topmost object under a slide point."""
        for s in reversed(self.shapes):
            cx, cy = s["x"] + s["w"] / 2, s["y"] + s["h"] / 2
            ux, uy = rot_point(sx, sy, cx, cy, -s["rot"])
            p = pad + (4 / self.scale if s["w"] < 6 or s["h"] < 6 else 0)
            if s["x"] - p <= ux <= s["x"] + s["w"] + p and s["y"] - p <= uy <= s["y"] + s["h"] + p:
                return s
        return None

    def cell_at(self, s, sx, sy):
        """The table cell (index) under a slide point."""
        try:
            cells = self.deck.table_cells(self.index, s["id"])
        except Exception:
            return None
        for k, _r, _c, x, y, w, h in cells:
            if x <= sx <= x + w and y <= sy <= y + h:
                return k
        return None

    def on_edge(self, s, sx, sy):
        """Near the border of a shape (where a click selects it instead of placing the caret)."""
        cx, cy = s["x"] + s["w"] / 2, s["y"] + s["h"] / 2
        ux, uy = rot_point(sx, sy, cx, cy, -s["rot"])
        t = 5 / self.scale
        inside = s["x"] + t < ux < s["x"] + s["w"] - t and s["y"] + t < uy < s["y"] + s["h"] - t
        return not inside

    def hit_handle(self, x, y):
        for sid in self.sel:
            s = self.shape(sid)
            if s is None:
                continue
            for name, (hx, hy) in self.handles(s).items():
                if abs(hx - x) <= HANDLE + 3 and abs(hy - y) <= HANDLE + 3:
                    return s, name
        return None, None

    # ------------------------------------------------------------ selection
    def select(self, ids, edit=None):
        self.sel = list(ids)
        if edit is None and self.edit is not None and self.edit.base not in self.sel:
            self.leave_text()
        self.queue()
        self.win.selection_changed()

    def select_all(self):
        if self.edit is not None:
            paras = self.deck.paragraphs(self.index, self.edit.id)
            self.edit.anchor = (0, 0)
            self.edit.caret = (len(paras) - 1, len(paras[-1]) if paras else 0)
            self.queue()
            self.win.selection_changed()
            return
        self.select([s["id"] for s in self.shapes])

    def clear(self):
        self.leave_text()
        self.select([])

    def start_text(self, sid, caret=None, select_all=False):
        base = sid & 0xFFFFF
        s = self.shape(base)
        if s is None:
            self.compute_scale()
            self._surface()
            s = self.shape(base)
        if s is None or not (s["has_text"] or s["kind"] == "sp" or (s["geom"] == "table" and sid != base)):
            return False
        self.sel = [base]
        paras = self.deck.paragraphs(self.index, sid) or [""]
        if caret is None:
            caret = (len(paras) - 1, len(paras[-1]))
        self.edit = TextEdit(sid, caret)
        if select_all:
            self.edit.anchor = (0, 0)
        self.deck.break_typing()
        self.im.set_client_window(self.area.get_window())
        self.area.grab_focus()
        self._start_blink()
        self.queue()
        self.win.selection_changed()
        return True

    def leave_text(self):
        if self.edit is None:
            return
        sid = self.edit.base
        self.edit = None
        self.deck.break_typing()
        if self._blink:
            GLib.source_remove(self._blink)
            self._blink = None
        self.sel = [sid] if self.shape(sid) else []
        self.queue()
        self.win.selection_changed()

    def _start_blink(self):
        self.blink_on = True
        if self._blink:
            GLib.source_remove(self._blink)

        def tick():
            if self.edit is None:
                self._blink = None
                return False
            self.blink_on = not self.blink_on
            self.queue()
            return True
        self._blink = GLib.timeout_add(530, tick)

    # ------------------------------------------------------------ mouse
    def on_press(self, area, ev):
        area.grab_focus()
        if self.deck is None or self.index is None:
            if self.deck is not None and self.deck.slide_count() == 0 and ev.button == 1:
                self.win.run("new-slide")
            return True
        sx, sy = self.to_slide(ev.x, ev.y)
        shift = bool(ev.state & Gdk.ModifierType.SHIFT_MASK)
        ctrl = bool(ev.state & Gdk.ModifierType.CONTROL_MASK)
        if ev.button == 3:
            s = self.hit_shape(sx, sy)
            if s is not None and s["id"] not in self.sel:
                self.leave_text()
                self.select([s["id"]])
            self.win.context_menu(ev, s)
            return True
        if ev.button != 1:
            return True
        if self.insert_mode is not None:
            self.drag = {"kind": "draw", "what": self.insert_mode, "start": (ev.x, ev.y), "now": (ev.x, ev.y)}
            return True
        if ev.type == Gdk.EventType._2BUTTON_PRESS:
            s = self.hit_shape(sx, sy)
            if s is not None and self.edit is not None and self.edit.base == s["id"]:
                self._select_word()
                return True
            if s is not None and s["kind"] in ("sp",):
                pos = self.deck.hit(self.index, s["id"], sx, sy)
                self.start_text(s["id"], pos)
                self._select_word()
                return True
            if s is not None and s["kind"] == "pic":
                self.win.run("tab:Picture Format")
            return True
        if ev.type == Gdk.EventType._3BUTTON_PRESS and self.edit is not None:
            p = self.edit.caret[0]
            n = len(self.deck.paragraphs(self.index, self.edit.id)[p])
            self.edit.anchor, self.edit.caret = (p, 0), (p, n)
            self.queue()
            return True
        s, handle = self.hit_handle(ev.x, ev.y)
        if s is not None:
            self._begin_drag("rot" if handle == "rot" else "size", ev, s, handle)
            return True
        s = self.hit_shape(sx, sy)
        # a table: the click goes into the cell under it
        if s is not None and s["geom"] == "table" and not self.on_edge(s, sx, sy):
            cell = self.cell_at(s, sx, sy)
            if cell is not None:
                from .core import Presentation
                tid = Presentation.cell_id(s["id"], cell)
                if self.edit is None or self.edit.id != tid:
                    self.leave_text()
                    self.start_text(tid, (0, 0))
                pos = self.deck.hit(self.index, tid, sx, sy)
                self.edit.caret = pos if shift else pos
                if not shift:
                    self.edit.anchor = pos
                self.drag = {"kind": "textsel", "start": (ev.x, ev.y)}
                self.queue()
                self.win.selection_changed()
                return True
        # inside the text being edited: place the caret
        if self.edit is not None and s is not None and s["id"] == self.edit.base and not self.on_edge(s, sx, sy):
            pos = self.deck.hit(self.index, s["id"], sx, sy)
            self.deck.break_typing()
            if shift:
                self.edit.caret = pos
            else:
                self.edit.caret = self.edit.anchor = pos
            self.edit.want_x = None
            self.drag = {"kind": "textsel", "start": (ev.x, ev.y)}
            self._start_blink()
            self.queue()
            self.win.selection_changed()
            return True
        if s is None:
            self.leave_text()
            if not shift and not ctrl:
                self.select([])
            self.drag = {"kind": "band", "start": (ev.x, ev.y), "now": (ev.x, ev.y), "add": shift or ctrl}
            return True
        if shift or ctrl:
            self.leave_text()
            if s["id"] in self.sel:
                self.select([i for i in self.sel if i != s["id"]])
            else:
                self.select(self.sel + [s["id"]])
            return True
        # a click in a text placeholder or text box puts the caret there (PowerPoint)
        textish = s["has_text"] and (s["ph"] is not None or s["geom"] == "rect" and s["kind"] == "sp")
        if textish and not self.on_edge(s, sx, sy) and s["id"] not in self.sel:
            pos = self.deck.hit(self.index, s["id"], sx, sy)
            self.start_text(s["id"], pos)
            self.drag = {"kind": "textsel", "start": (ev.x, ev.y)}
            return True
        if s["id"] in self.sel and textish and not self.on_edge(s, sx, sy) and self.edit is None:
            pos = self.deck.hit(self.index, s["id"], sx, sy)
            self.start_text(s["id"], pos)
            self.drag = {"kind": "textsel", "start": (ev.x, ev.y)}
            return True
        self.leave_text()
        if s["id"] not in self.sel:
            self.select([s["id"]])
        self._begin_drag("move", ev, s, None)
        return True

    def _begin_drag(self, kind, ev, s, handle):
        boxes = {}
        for sid in self.sel:
            t = self.shape(sid)
            if t:
                boxes[sid] = (t["x"], t["y"], t["w"], t["h"], t["rot"])
        self.drag = {"kind": kind, "start": (ev.x, ev.y), "shape": s, "handle": handle, "orig": dict(boxes),
                     "boxes": dict(boxes), "moved": False}

    def on_motion(self, area, ev):
        d = self.drag
        if d is None:
            self._hover(ev)
            return True
        d["now"] = (ev.x, ev.y)
        dx = (ev.x - d["start"][0]) / self.scale
        dy = (ev.y - d["start"][1]) / self.scale
        shift = bool(ev.state & Gdk.ModifierType.SHIFT_MASK)
        if d["kind"] in ("band", "draw"):
            self.queue()
            return True
        if d["kind"] == "textsel":
            if self.edit is not None:
                sx, sy = self.to_slide(ev.x, ev.y)
                self.edit.caret = self.deck.hit(self.index, self.edit.id, sx, sy)
                self.queue()
            return True
        if not d["moved"] and abs(ev.x - d["start"][0]) < 3 and abs(ev.y - d["start"][1]) < 3:
            return True
        d["moved"] = True
        if d["kind"] == "move":
            if shift:
                if abs(dx) > abs(dy):
                    dy = 0
                else:
                    dx = 0
            for sid, (x, y, w, h, r) in d["orig"].items():
                d["boxes"][sid] = (x + dx, y + dy, w, h, r)
        elif d["kind"] == "rot":
            s = d["shape"]
            x, y, w, h, r = d["orig"][s["id"]]
            cx, cy = self.to_px(x + w / 2, y + h / 2)
            ang = math.degrees(math.atan2(ev.y - cy, ev.x - cx)) + 90
            if shift:
                ang = round(ang / 15) * 15
            d["boxes"][s["id"]] = (x, y, w, h, ang % 360)
        elif d["kind"] == "size":
            s = d["shape"]
            d["boxes"] = {s["id"]: self._resized(d["orig"][s["id"]], d["handle"], ev, shift, s)}
        self.queue()
        return True

    def _resized(self, box, handle, ev, shift, s):
        x, y, w, h, r = box
        cx, cy = x + w / 2, y + h / 2
        mx, my = self.to_slide(ev.x, ev.y)
        ux, uy = rot_point(mx, my, cx, cy, -r)
        # local bounds relative to the centre
        l, t, rr, b = -w / 2, -h / 2, w / 2, h / 2
        lx, ly = ux - cx, uy - cy
        if handle in ("start", "end"):
            # a line: move one end
            fh, fv = s["flip_h"], s["flip_v"]
            ax, ay = (x + w if fh else x, y + h if fv else y)
            bx, by = (x if fh else x + w, y if fv else y + h)
            if handle == "start":
                ax, ay = mx, my
            else:
                bx, by = mx, my
            return (min(ax, bx), min(ay, by), abs(bx - ax), abs(by - ay), r)
        if "w" in handle:
            l = min(lx, rr - 1)
        if "e" in handle:
            rr = max(lx, l + 1)
        if "n" in handle:
            t = min(ly, b - 1)
        if "s" in handle:
            b = max(ly, t + 1)
        nw, nh = rr - l, b - t
        keep = shift != (s["kind"] == "pic")
        if keep and len(handle) == 2 and w > 0 and h > 0:
            k = max(nw / w, nh / h)
            nw, nh = w * k, h * k
            if "w" in handle:
                l = rr - nw
            else:
                rr = l + nw
            if "n" in handle:
                t = b - nh
            else:
                b = t + nh
        ncx, ncy = (l + rr) / 2, (t + b) / 2
        wx, wy = rot_point(cx + ncx, cy + ncy, cx, cy, r)
        return (wx - nw / 2, wy - nh / 2, nw, nh, r)

    def _hover(self, ev):
        win = self.area.get_window()
        if win is None:
            return
        name = "default"
        if self.insert_mode is not None:
            name = "crosshair"
        else:
            s, handle = self.hit_handle(ev.x, ev.y)
            if s is not None:
                name = {"n": "n-resize", "s": "s-resize", "e": "e-resize", "w": "w-resize", "ne": "ne-resize",
                        "nw": "nw-resize", "se": "se-resize", "sw": "sw-resize", "rot": "grab",
                        "start": "crosshair", "end": "crosshair"}.get(handle, "default")
            else:
                sx, sy = self.to_slide(ev.x, ev.y)
                s = self.hit_shape(sx, sy)
                if s is not None:
                    textish = s["has_text"] and (s["ph"] is not None or s["geom"] == "rect")
                    name = "text" if textish and not self.on_edge(s, sx, sy) else "move"
        win.set_cursor(Gdk.Cursor.new_from_name(win.get_display(), name))

    def on_release(self, area, ev):
        d = self.drag
        self.drag = None
        if d is None:
            return True
        ctrl = bool(ev.state & Gdk.ModifierType.CONTROL_MASK)
        if d["kind"] == "band":
            x0, y0 = self.to_slide(*d["start"])
            x1, y1 = self.to_slide(ev.x, ev.y)
            lo_x, hi_x, lo_y, hi_y = min(x0, x1), max(x0, x1), min(y0, y1), max(y0, y1)
            if hi_x - lo_x > 2 / self.scale or hi_y - lo_y > 2 / self.scale:
                inside = [s["id"] for s in self.shapes if s["x"] >= lo_x and s["y"] >= lo_y and
                          s["x"] + s["w"] <= hi_x and s["y"] + s["h"] <= hi_y]
                self.select((self.sel + [i for i in inside if i not in self.sel]) if d.get("add") else inside)
            self.queue()
            return True
        if d["kind"] == "draw":
            self._finish_draw(d, ev)
            return True
        if d["kind"] == "textsel":
            self.win.selection_changed()
            return True
        if not d["moved"]:
            self.queue()
            return True
        boxes = [(sid, x, y, w, h, r) for sid, (x, y, w, h, r) in d["boxes"].items()]
        if d["kind"] == "move" and ctrl:
            # Ctrl+drag: copies
            x0, y0 = d["orig"][boxes[0][0]][:2]
            new = self.deck.duplicate_shapes(self.index, list(d["boxes"].keys()), boxes[0][1] - x0, boxes[0][2] - y0)
            self.win.changed(slide=True)
            self.select(new)
            return True
        label = {"move": "Move", "size": "Size", "rot": "Rotate"}[d["kind"]]
        self.deck.set_boxes(self.index, boxes, label)
        self.win.changed(slide=True)
        return True

    def _finish_draw(self, d, ev):
        what = d["what"]
        x0, y0 = self.to_slide(*d["start"])
        x1, y1 = self.to_slide(ev.x, ev.y)
        shift = bool(ev.state & Gdk.ModifierType.SHIFT_MASK)
        w, h = abs(x1 - x0), abs(y1 - y0)
        clicked = w < 3 and h < 3
        line = what[0] == "shape" and what[1] in ("line", "straightConnector1")
        if clicked:
            w, h = (72.0, 72.0) if what[0] == "shape" and not line else (72.0, 0.0) if line else (144.0, 28.0)
            x, y = x0, y0
        else:
            if shift and not line:
                w = h = max(w, h)
            x, y = min(x0, x1), min(y0, y1)
            if shift and not line:
                x = x0 if x1 >= x0 else x0 - w
                y = y0 if y1 >= y0 else y0 - h
        self.insert_mode = None
        self.win.insert_mode_done()
        if what[0] == "textbox":
            sid = self.deck.add_textbox(self.index, x, y, max(w, 20.0), 28.0 if clicked else max(h, 20.0), "")
            self.win.changed(slide=True)
            self.start_text(sid, (0, 0))
            return
        sid = self.deck.add_shape(self.index, what[1], x, y, w, h)
        if line and not clicked and ((x1 < x0) != (y1 < y0)):
            self.deck.flip(self.index, [sid], False)
        self.win.changed(slide=True)
        self.select([sid])

    def on_scroll(self, area, ev):
        ctrl = bool(ev.state & Gdk.ModifierType.CONTROL_MASK)
        if ctrl:
            dy = 0
            if ev.direction == Gdk.ScrollDirection.UP:
                dy = -1
            elif ev.direction == Gdk.ScrollDirection.DOWN:
                dy = 1
            elif ev.direction == Gdk.ScrollDirection.SMOOTH:
                dy = ev.delta_y
            if dy:
                pct = self.zoom_percent() * (1.1 if dy < 0 else 1 / 1.1)
                self.set_zoom(max(10, min(400, pct)))
            return True
        if self.fit:
            # the wheel turns the page in a fitted view, as the original does
            dy = 0
            if ev.direction == Gdk.ScrollDirection.UP:
                dy = -1
            elif ev.direction == Gdk.ScrollDirection.DOWN:
                dy = 1
            elif ev.direction == Gdk.ScrollDirection.SMOOTH:
                self._acc = getattr(self, "_acc", 0) + ev.delta_y
                if abs(self._acc) >= 1:
                    dy = 1 if self._acc > 0 else -1
                    self._acc = 0
            if dy:
                self.win.go_slide(self.index + dy)
            return True
        return False

    # ------------------------------------------------------------ text editing
    def paras(self):
        return self.deck.paragraphs(self.index, self.edit.id) if self.edit else []

    def _after_text(self, label="Typing"):
        sid = self.edit.id
        try:
            self.deck.fit_text(self.index, sid, label)
        except Exception:
            pass
        self.win.changed(slide=True, text=True)
        self.blink_on = True
        self._start_blink()

    def type_text(self, s):
        if self.edit is None:
            if len(self.sel) == 1 and s.isprintable():
                sh = self.shape(self.sel[0])
                if sh is not None and sh["kind"] == "sp":
                    # typing over a selected object replaces its text (PowerPoint)
                    self.deck.set_text(self.index, sh["id"], "")
                    self.win.changed(slide=True)
                    self.start_text(sh["id"], (0, 0))
                else:
                    return
            else:
                return
        e = self.edit
        if e.has_selection():
            a, b = e.range()
            e.caret = e.anchor = self.deck.delete_text(self.index, e.id, a, b, "Typing")
        e.caret = e.anchor = tuple(self.deck.insert_text(self.index, e.id, e.caret[0], e.caret[1], s, "Typing"))
        e.want_x = None
        self._after_text()

    def delete(self, back, word=False):
        e = self.edit
        if e.has_selection():
            a, b = e.range()
        else:
            paras = self.paras()
            p, o = e.caret
            if back:
                if p == 0 and o == 0:
                    # Backspace at the start of an indented paragraph promotes it
                    pp = self.deck.para_props(self.index, e.id, 0)
                    if pp.get("lvl", 0) > 0:
                        self.para_format("lvl", str(pp["lvl"] - 1), label="Decrease List Level")
                    return
                if o == 0:
                    pp = self.deck.para_props(self.index, e.id, p)
                    if pp.get("lvl", 0) > 0:
                        self.para_format("lvl", str(pp["lvl"] - 1), label="Decrease List Level")
                        return
                    a, b = (p - 1, len(paras[p - 1])), (p, 0)
                else:
                    k = o - 1
                    if word:
                        t = paras[p]
                        while k > 0 and t[k - 1] == " ":
                            k -= 1
                        while k > 0 and t[k - 1] not in " \n":
                            k -= 1
                    a, b = (p, k), (p, o)
            else:
                if o >= len(paras[p]):
                    if p + 1 >= len(paras):
                        return
                    a, b = (p, o), (p + 1, 0)
                else:
                    k = o + 1
                    if word:
                        t = paras[p]
                        while k < len(t) and t[k] not in " \n":
                            k += 1
                        while k < len(t) and t[k] == " ":
                            k += 1
                    a, b = (p, o), (p, k)
        e.caret = e.anchor = tuple(self.deck.delete_text(self.index, e.id, a, b, "Typing"))
        self._after_text()

    def next_cell(self, step):
        from .core import Presentation
        e = self.edit
        cells = [c[0] for c in self.deck.table_cells(self.index, e.base)]
        k = cells.index(e.cell) if e.cell in cells else 0
        j = k + step
        if j >= len(cells):
            # Tab in the last cell adds a row (PowerPoint)
            rows, _cols = self.deck.table_size(self.index, e.base)
            self.deck.table_insert_row(self.index, e.base, rows)
            self.win.changed(slide=True)
            cells = [c[0] for c in self.deck.table_cells(self.index, e.base)]
        if j < 0:
            return
        tid = Presentation.cell_id(e.base, cells[j])
        self.edit = None
        self.start_text(tid, (0, 0))
        paras = self.paras()
        self.edit.anchor = (0, 0)
        self.edit.caret = (len(paras) - 1, len(paras[-1]) if paras else 0)
        self.queue()

    def _select_word(self):
        e = self.edit
        if e is None:
            return
        paras = self.paras()
        p, o = e.caret
        t = paras[p] if p < len(paras) else ""
        a = b = min(o, len(t))
        while a > 0 and (t[a - 1].isalnum() or t[a - 1] in "'_"):
            a -= 1
        while b < len(t) and (t[b].isalnum() or t[b] in "'_"):
            b += 1
        while b < len(t) and t[b] == " ":
            b += 1
        e.anchor, e.caret = (p, a), (p, b)
        self.queue()
        self.win.selection_changed()

    def move_caret(self, how, extend):
        e = self.edit
        paras = self.paras()
        p, o = e.caret
        if not extend and e.has_selection() and how in ("left", "right"):
            a, b = e.range()
            e.caret = e.anchor = a if how == "left" else b
            self.queue()
            return
        if how == "left":
            if o > 0:
                o -= 1
            elif p > 0:
                p, o = p - 1, len(paras[p - 1])
        elif how == "right":
            if o < len(paras[p]):
                o += 1
            elif p + 1 < len(paras):
                p, o = p + 1, 0
        elif how == "wleft":
            t = paras[p]
            if o == 0 and p > 0:
                p, o = p - 1, len(paras[p - 1])
            else:
                while o > 0 and t[o - 1] == " ":
                    o -= 1
                while o > 0 and t[o - 1] not in " \n":
                    o -= 1
        elif how == "wright":
            t = paras[p]
            if o >= len(t) and p + 1 < len(paras):
                p, o = p + 1, 0
            else:
                while o < len(t) and t[o] not in " \n":
                    o += 1
                while o < len(t) and t[o] == " ":
                    o += 1
        elif how in ("up", "down"):
            c = self.deck.caret(self.index, e.id, p, o)
            if e.want_x is None and c:
                e.want_x = c[0]
            r = self.deck.vertical(self.index, e.id, p, o, how == "down", e.want_x or 0)
            if r is not None:
                p, o = r
            elif how == "up":
                o = 0 if p == 0 else o
            else:
                o = len(paras[p]) if p == len(paras) - 1 else o
        elif how in ("home", "end"):
            lb = self.deck.line_bounds(self.index, e.id, p, o)
            if lb:
                p, o = lb[0] if how == "home" else lb[1]
        elif how == "pstart":
            if o == 0 and p > 0:
                p -= 1
            o = 0
        elif how == "pend":
            if o == len(paras[p]) and p + 1 < len(paras):
                p += 1
            o = len(paras[p])
        elif how == "dstart":
            p, o = 0, 0
        elif how == "dend":
            p = len(paras) - 1
            o = len(paras[p])
        if how not in ("up", "down"):
            e.want_x = None
        e.caret = (p, o)
        if not extend:
            e.anchor = e.caret
        self.deck.break_typing()
        self.blink_on = True
        self.queue()
        self.win.selection_changed()

    def text_range(self):
        """The edited text's range to format: the selection, else the word at the caret (Word and
        PowerPoint format the whole word when nothing is selected), else the caret."""
        e = self.edit
        if e.has_selection():
            return e.range()
        paras = self.paras()
        p, o = e.caret
        t = paras[p] if p < len(paras) else ""
        a = b = o
        while a > 0 and t[a - 1].isalnum():
            a -= 1
        while b < len(t) and t[b].isalnum():
            b += 1
        if a < o < b:
            return (p, a), (p, b)
        return (p, o), (p, o)

    def para_format(self, key, value, label=None):
        """Paragraph formatting for the paragraphs in the selection (or the whole objects selected)."""
        if self.edit is not None:
            a, b = self.edit.range()
            self.deck.format_paras(self.index, self.edit.id, a[0], b[0], key, value)
            self._after_text(label or "Format")
            return
        for sid in self.sel:
            n = len(self.deck.paragraphs(self.index, sid))
            if n:
                self.deck.format_paras(self.index, sid, 0, n - 1, key, value)
        self.win.changed(slide=True)

    def run_format(self, key, value):
        if self.edit is not None:
            a, b = self.text_range()
            self.deck.format_runs(self.index, self.edit.id, a, b, key, value)
            self._after_text("Format")
            return
        for sid in self.sel:
            paras = self.deck.paragraphs(self.index, sid)
            if paras:
                self.deck.format_runs(self.index, sid, (0, 0), (len(paras) - 1, len(paras[-1])), key, value)
                try:
                    self.deck.fit_text(self.index, sid, "Format")
                except Exception:
                    pass
        self.win.changed(slide=True)

    def current_run(self):
        """Run properties shown on the ribbon."""
        try:
            if self.edit is not None:
                p, o = self.edit.range()[0] if self.edit.has_selection() else self.edit.caret
                if self.edit.has_selection():
                    o += 1
                return self.deck.run_props(self.index, self.edit.id, p, o), \
                    self.deck.para_props(self.index, self.edit.id, p)
            if len(self.sel) >= 1:
                s = self.shape(self.sel[0])
                if s and s["has_text"]:
                    return self.deck.run_props(self.index, s["id"], 0, 1), self.deck.para_props(self.index, s["id"], 0)
        except Exception:
            pass
        return None, None

    def selected_text(self):
        e = self.edit
        if e is None or not e.has_selection():
            return ""
        a, b = e.range()
        paras = self.paras()
        if a[0] == b[0]:
            return paras[a[0]][a[1]:b[1]]
        out = [paras[a[0]][a[1]:]]
        out += paras[a[0] + 1:b[0]]
        out.append(paras[b[0]][:b[1]])
        return "\n".join(out)

    # ------------------------------------------------------------ keys
    def on_key(self, ev):
        """Keys for the canvas (the window hands them on); True when used."""
        k = ev.keyval
        name = Gdk.keyval_name(k) or ""
        ctrl = bool(ev.state & Gdk.ModifierType.CONTROL_MASK)
        shift = bool(ev.state & Gdk.ModifierType.SHIFT_MASK)
        alt = bool(ev.state & Gdk.ModifierType.MOD1_MASK)
        if self.drag is not None and name == "Escape":
            self.drag = None
            self.queue()
            return True
        if self.insert_mode is not None and name == "Escape":
            self.insert_mode = None
            self.win.insert_mode_done()
            return True
        e = self.edit
        if e is not None:
            moves = {"Left": "wleft" if ctrl else "left", "Right": "wright" if ctrl else "right",
                     "Up": "pstart" if ctrl else "up", "Down": "pend" if ctrl else "down",
                     "Home": "dstart" if ctrl else "home", "End": "dend" if ctrl else "end",
                     "KP_Left": "left", "KP_Right": "right", "KP_Up": "up", "KP_Down": "down"}
            if name in moves and not alt:
                self.move_caret(moves[name], shift)
                return True
            if name == "Escape":
                self.leave_text()
                return True
            if name == "BackSpace":
                self.delete(True, ctrl)
                return True
            if name in ("Delete", "KP_Delete"):
                self.delete(False, ctrl)
                return True
            if name in ("Return", "KP_Enter"):
                if ctrl:
                    return False                      # next placeholder (window)
                self.type_text("\x0b" if shift else "\n")
                return True
            if name in ("Tab", "ISO_Left_Tab") and e.cell is not None:
                self.next_cell(-1 if (shift or name == "ISO_Left_Tab") else 1)
                return True
            if name in ("Tab", "ISO_Left_Tab"):
                p, o = e.caret
                pp = self.deck.para_props(self.index, e.id, p)
                at_start = o == 0 or e.has_selection()
                listy = pp.get("bullet", "none") != "none" or pp.get("lvl", 0) > 0
                if (at_start and listy) or shift or name == "ISO_Left_Tab":
                    lvl = pp.get("lvl", 0)
                    lvl = max(0, lvl - 1) if (shift or name == "ISO_Left_Tab") else min(8, lvl + 1)
                    self.para_format("lvl", str(lvl), label="Increase List Level" if not shift else "Decrease List Level")
                else:
                    self.type_text("\t")
                return True
            if ctrl or alt:
                return False
            if self.im.filter_keypress(ev):
                return True
            return False
        # objects selected, no text editing
        if self.sel and not alt:
            arrows = {"Left": (-1, 0), "Right": (1, 0), "Up": (0, -1), "Down": (0, 1)}
            if name in arrows:
                step = 1.0 if ctrl else NUDGE
                dx, dy = arrows[name]
                if shift and not ctrl:
                    # Shift+arrows resize (PowerPoint)
                    boxes = []
                    for sid in self.sel:
                        s = self.shape(sid)
                        if s:
                            boxes.append((sid, s["x"], s["y"], max(1, s["w"] + dx * step), max(1, s["h"] + dy * step), None))
                    self.deck.set_boxes(self.index, boxes, "Size")
                else:
                    boxes = []
                    for sid in self.sel:
                        s = self.shape(sid)
                        if s:
                            boxes.append((sid, s["x"] + dx * step, s["y"] + dy * step, s["w"], s["h"], None))
                    self.deck.set_boxes(self.index, boxes, "Nudge")
                self.win.changed(slide=True)
                return True
            if name in ("Delete", "KP_Delete", "BackSpace"):
                self.win.run("delete")
                return True
            if name == "Escape":
                self.select([])
                return True
            if name in ("Return", "F2", "KP_Enter") and len(self.sel) == 1:
                s = self.shape(self.sel[0])
                if s is not None and s["kind"] == "sp":
                    self.start_text(s["id"], None, select_all=(name == "F2" or True))
                    return True
            if not ctrl and self.im.filter_keypress(ev):
                return True
        if name in ("Tab", "ISO_Left_Tab") and not ctrl and self.shapes:
            # Tab steps through the objects on the slide
            ids = [s["id"] for s in self.shapes]
            cur = ids.index(self.sel[0]) if self.sel and self.sel[0] in ids else -1
            nxt = (cur + (-1 if shift or name == "ISO_Left_Tab" else 1)) % len(ids)
            self.select([ids[nxt]])
            return True
        return False

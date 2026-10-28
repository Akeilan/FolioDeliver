"""Slide Show: the full-screen show with PowerPoint's keys and right-click menu, ink and laser
pointer, black and white screens, and Presenter View (current and next slide, notes, timer)."""
import math
import time

import cairo
from gi.repository import Gdk, GLib, Gtk, Pango

from .core import surface_from

PEN_COLORS = [("Red", (0.9, 0.1, 0.1)), ("Blue", (0.1, 0.3, 0.9)), ("Green", (0.1, 0.6, 0.2)),
              ("Yellow", (1.0, 0.85, 0.0)), ("Black", (0, 0, 0)), ("White", (1, 1, 1))]


class ShowState:
    """What the audience sees, shared by the show window and Presenter View."""
    def __init__(self, win, start, hidden_too=False):
        self.win = win
        self.deck = win.deck
        n = self.deck.slide_count()
        # hidden slides are skipped (unless the show starts on one)
        self.order = [i for i in range(n) if hidden_too or not self.deck.is_hidden(i) or i == start]
        # Set Up Show
        try:
            kind, self.looped, self.no_anim, rfrom, rto, self.use_timings, pen = self.deck.show_settings()
        except Exception:
            kind, self.looped, self.no_anim, rfrom, rto, self.use_timings, pen = "presented", False, False, 0, 0, True, "FF0000"
        self.kiosk = kind == "kiosk" and not hidden_too
        self.browsed = kind == "browsed" and not hidden_too
        if hidden_too:
            self.looped, self.no_anim, self.use_timings = False, False, True
        if (rfrom or rto) and not hidden_too:
            lo, hi = max(1, rfrom) - 1, (rto if rto > 0 else n) - 1
            ranged = [i for i in self.order if lo <= i <= hi]
            if ranged:
                self.order = ranged
                if start not in ranged:
                    start = ranged[0]
        self.pos = self.order.index(start) if start in self.order else 0
        self.screen = None           # None | "black" | "white"
        self.ended = False
        self.ink = {}                # slide index -> [(tool, color, width, [(x, y)])]
        self.tool = "arrow"          # arrow | pen | highlighter | eraser | laser
        self.pen_color = PEN_COLORS[0][1]
        try:
            if pen and pen.upper() != "FF0000":
                v = int(pen, 16)
                self.pen_color = ((v >> 16 & 255) / 255.0, (v >> 8 & 255) / 255.0, (v & 255) / 255.0)
        except ValueError:
            pass
        self.listeners = []
        self.started = time.time()
        self.paused_at = None
        self.paused_total = 0.0
        self.typed = ""
        self.last_viewed = None
        self.cache = {}
        self.trans = None
        self.no_click = False
        self._adv = None
        self.player = None
        self.step = 0
        self.playing = None          # (group, start time)
        self._load_player(at_end=False)

    # ------------------------------------------------------------ animations
    def _load_player(self, at_end=False):
        from .anim import Player
        try:
            self.player = None if getattr(self, "no_anim", False) else Player(self.deck, self.index)
        except Exception:
            self.player = None
        n = len(self.player.groups) if self.player else 0
        self.step = n if at_end else 0
        self.playing = None
        if not at_end and self.player and self.player.auto_first:
            self.play(0)

    def play(self, g):
        self.playing = (g, time.time() + (self.trans[4] if self.trans else 0.0))
        self._tick_anim()

    def _tick_anim(self):
        if getattr(self, "_anim_src", None):
            return

        def tick():
            if self.playing is None or self.ended:
                self._anim_src = None
                return False
            g, start = self.playing
            if time.time() - start >= self.player.length(g):
                self.step = g + 1
                self.playing = None
                self._anim_src = None
                self.changed()
                return False
            self.changed()
            return True
        self._anim_src = GLib.timeout_add(16, tick)

    def anim_state(self):
        """(key, shape states) for the current slide now; key None while it moves."""
        if not self.player or not self.player.effects:
            return ("static",), None
        if self.playing is not None:
            g, start = self.playing
            return None, self.player.state(self.step, g, max(0.0, time.time() - start))
        return ("step", self.step), self.player.state(self.step)

    @property
    def index(self):
        return self.order[self.pos] if self.order else None

    def elapsed(self):
        now = self.paused_at or time.time()
        return now - self.started - self.paused_total

    def toggle_pause(self):
        if self.paused_at is None:
            self.paused_at = time.time()
        else:
            self.paused_total += time.time() - self.paused_at
            self.paused_at = None
        self.changed()

    def reset_timer(self):
        self.started = time.time()
        self.paused_total = 0.0
        if self.paused_at is not None:
            self.paused_at = self.started
        self.changed()

    def changed(self):
        for f in list(self.listeners):
            f()

    def go(self, pos):
        if not self.order:
            return
        if pos >= len(self.order) and getattr(self, "looped", False):
            pos = 0
        if pos >= len(self.order):
            # past the last slide: the black "End of slide show" screen, then out
            if self.screen == "end":
                self.end()
                return
            self.screen = "end"
            self.changed()
            return
        if self.screen == "end":
            self.screen = None
        pos = max(0, pos)
        if pos != self.pos:
            self.last_viewed = self.pos
        old = self.index
        self.pos = pos
        if self.screen in ("black", "white"):
            self.screen = None
        kind, opt, dur, click, after = self.deck.transition(self.index)
        self.no_click = not click or self.kiosk
        if old is not None and pos == (self.order.index(old) + 1 if old in self.order else -1) and kind not in ("none",):
            self.trans = (old, self.index, kind, opt, max(0.05, dur or 0.75), time.time())
        else:
            self.trans = None
        back = getattr(self, "_back", False)
        self._back = False
        self._load_player(at_end=back)
        self._schedule_advance(after)
        self.changed()

    def _schedule_advance(self, after):
        if getattr(self, "_adv", None):
            GLib.source_remove(self._adv)
            self._adv = None
        if not getattr(self, "use_timings", True) and not getattr(self, "kiosk", False):
            after = None
        if after is not None and after >= 0:
            delay = after + (self.trans[4] if self.trans else 0)

            def go():
                self._adv = None
                if not self.ended and self.paused_at is None:
                    self.next()
                return False
            self._adv = GLib.timeout_add(int(delay * 1000) + 1, go)

    def next(self):
        if self.screen not in ("end",) and self.player and self.player.groups:
            if self.playing is not None:
                # a click during an animation finishes it
                self.step = self.playing[0] + 1
                self.playing = None
                self.changed()
                return
            if self.step < len(self.player.groups):
                self.play(self.step)
                return
        self.go(self.pos + 1)

    def prev(self):
        if self.screen == "end":
            self.screen = None
            self.changed()
            return
        if self.player and (self.step > (1 if self.player.auto_first else 0) or self.playing is not None):
            self.playing = None
            self.step = max(0, self.step - 1)
            self.changed()
            return
        self._back = True
        self.go(self.pos - 1)

    def goto_slide(self, i):
        """Go to slide number i (0-based), hidden or not."""
        if i in self.order:
            self.go(self.order.index(i))
        elif 0 <= i < self.deck.slide_count():
            self.order.append(i)
            self.order.sort()
            self.go(self.order.index(i))

    def end(self):
        if self.ended:
            return
        self.ended = True
        if self._adv:
            GLib.source_remove(self._adv)
            self._adv = None
        self.changed()

    def picture(self, i, w, h, initial=False):
        """Slide i fitted into w x h pixels: (surface, x, y, scale). The current slide is drawn
        as its animations have it now; others (and `initial`) as they start."""
        sw, sh = self.deck.size()
        scale = min(w / sw, h / sh)
        anim_key, anim = ("static",), None
        if i == self.index and not initial and self.player is not None:
            anim_key, anim = self.anim_state()
        elif i is not None:
            from .anim import Player
            others = self.__dict__.setdefault("_other_players", {})
            if i not in others:
                try:
                    others[i] = Player(self.deck, i)
                except Exception:
                    others[i] = None
            pl = others[i]
            if pl is not None and pl.effects:
                anim_key, anim = ("start",), pl.state(0)
        key = (i, round(scale, 4), self.deck.version, anim_key)
        s = self.cache.get(key) if anim_key is not None else None
        if s is None:
            pw, ph, stride, data, _ = self.deck.render(i, scale, False, anim)
            s = surface_from(pw, ph, stride, data)
            if anim_key is not None:
                if len(self.cache) > 24:
                    self.cache.clear()
                self.cache[key] = s
        return s, (w - sw * scale) / 2, (h - sh * scale) / 2, scale


def draw_slide(cr, st, i, w, h, ink=True, laser=None):
    cr.set_source_rgb(0, 0, 0)
    cr.paint()
    if i is None:
        return
    surf, x, y, scale = st.picture(i, w, h)
    cr.set_source_surface(surf, round(x), round(y))
    cr.paint()
    if ink:
        for tool, color, width, pts in st.ink.get(i, []):
            if len(pts) < 2:
                continue
            cr.save()
            if tool == "highlighter":
                cr.set_source_rgba(*color, 0.4)
                cr.set_line_width(width * 4 * scale)
            else:
                cr.set_source_rgb(*color)
                cr.set_line_width(width * scale)
            cr.set_line_cap(cairo.LINE_CAP_ROUND)
            cr.set_line_join(cairo.LINE_JOIN_ROUND)
            cr.move_to(x + pts[0][0] * scale, y + pts[0][1] * scale)
            for px, py in pts[1:]:
                cr.line_to(x + px * scale, y + py * scale)
            cr.stroke()
            cr.restore()
    if laser is not None:
        lx, ly = laser
        g = cairo.RadialGradient(lx, ly, 0, lx, ly, 9)
        g.add_color_stop_rgba(0, 1, 0.2, 0.2, 1)
        g.add_color_stop_rgba(0.5, 1, 0, 0, 0.8)
        g.add_color_stop_rgba(1, 1, 0, 0, 0)
        cr.set_source(g)
        cr.arc(lx, ly, 9, 0, 2 * math.pi)
        cr.fill()


class ShowWindow(Gtk.Window):
    """The audience's full-screen view."""
    def __init__(self, st, monitor=None, presenter=None):
        Gtk.Window.__init__(self)
        self.st = st
        self.presenter = presenter
        self.set_title("Slide Show")
        self.set_decorated(False)
        self.override_background_color(Gtk.StateFlags.NORMAL, Gdk.RGBA(0, 0, 0, 1))
        self.area = Gtk.DrawingArea()
        self.area.add_events(Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.BUTTON_RELEASE_MASK |
                             Gdk.EventMask.POINTER_MOTION_MASK | Gdk.EventMask.SCROLL_MASK)
        self.area.connect("draw", self.on_draw)
        self.area.connect("button-press-event", self.on_press)
        self.area.connect("button-release-event", self.on_release)
        self.area.connect("motion-notify-event", self.on_motion)
        self.area.connect("scroll-event", self.on_scroll)
        self.add(self.area)
        self.connect("key-press-event", lambda w, e: on_show_key(st, e, self))
        self.laser = None
        self.stroke = None
        self.hide_pointer = False
        self._idle_cursor = None
        st.listeners.append(self.refresh)
        self.show_all()
        if monitor is not None:
            geo = monitor.get_geometry()
            self.move(geo.x, geo.y)
            self.resize(geo.width, geo.height)
            self.fullscreen_on_monitor(self.get_screen(), self._monitor_index(monitor))
        elif getattr(st, "browsed", False):
            # Browsed by an individual: a window
            self.set_decorated(True)
            self.set_title("%s - Slide Show" % st.win.title_text())
            self.resize(960, 600)
        else:
            self.fullscreen()
        self._set_cursor()

    def _monitor_index(self, m):
        disp = self.get_display()
        for k in range(disp.get_n_monitors()):
            if disp.get_monitor(k) == m:
                return k
        return 0

    def refresh(self):
        if self.st.ended:
            self.destroy()
            return
        self._set_cursor()
        self.area.queue_draw()

    def _set_cursor(self):
        w = self.area.get_window()
        if w is None:
            return
        name = {"pen": "crosshair", "highlighter": "crosshair", "eraser": "cell", "laser": "none"}.get(self.st.tool, "default")
        if self.hide_pointer:
            name = "none"
        w.set_cursor(Gdk.Cursor.new_from_name(w.get_display(), name))

    def to_slide(self, x, y):
        st = self.st
        w, h = self.area.get_allocated_width(), self.area.get_allocated_height()
        sw, sh = st.deck.size()
        scale = min(w / sw, h / sh)
        return (x - (w - sw * scale) / 2) / scale, (y - (h - sh * scale) / 2) / scale

    def on_draw(self, area, cr):
        st = self.st
        w, h = area.get_allocated_width(), area.get_allocated_height()
        if st.screen == "black" or st.screen == "end":
            cr.set_source_rgb(0, 0, 0)
            cr.paint()
            if st.screen == "end":
                cr.set_source_rgb(0.85, 0.85, 0.85)
                cr.select_font_face("Sans")
                cr.set_font_size(18)
                cr.move_to(16, 30)
                cr.show_text("End of slide show, click to exit.")
            return
        if st.screen == "white":
            cr.set_source_rgb(1, 1, 1)
            cr.paint()
            return
        tr = st.trans
        if tr is not None:
            a_i, b_i, kind, opt, dur, start = tr
            t = (time.time() - start) / dur
            if t < 1:
                key = (a_i, b_i, w, h)
                if getattr(self, "_tr_key", None) != key:
                    self._tr_key = key
                    self._tr = (frame_surface(st, a_i, w, h), frame_surface(st, b_i, w, h))
                blend(cr, self._tr[0], self._tr[1], kind, opt, t, w, h)
                GLib.timeout_add(14, lambda: (self.area.queue_draw(), False)[1])
                return
            st.trans = None
        draw_slide(cr, st, st.index, w, h, laser=self.laser if st.tool == "laser" else None)
        if self.stroke is not None and len(self.stroke[3]) > 1:
            sw, sh = st.deck.size()
            scale = min(w / sw, h / sh)
            ox, oy = (w - sw * scale) / 2, (h - sh * scale) / 2
            tool, color, width, pts = self.stroke
            cr.set_source_rgba(*color, 0.4 if tool == "highlighter" else 1)
            cr.set_line_width(width * scale * (4 if tool == "highlighter" else 1))
            cr.set_line_cap(cairo.LINE_CAP_ROUND)
            cr.move_to(ox + pts[0][0] * scale, oy + pts[0][1] * scale)
            for px, py in pts[1:]:
                cr.line_to(ox + px * scale, oy + py * scale)
            cr.stroke()

    def on_press(self, area, ev):
        st = self.st
        if ev.button == 3:
            show_menu(st, ev, self)
            return True
        if ev.button != 1:
            return True
        if st.screen == "end":
            st.end()
            return True
        if st.tool in ("pen", "highlighter"):
            sx, sy = self.to_slide(ev.x, ev.y)
            self.stroke = (st.tool, st.pen_color if st.tool == "pen" else (1.0, 0.9, 0.0), 2.0, [(sx, sy)])
            return True
        if st.tool == "eraser":
            self._erase(ev)
            return True
        t = self.link_at(ev.x, ev.y)
        if t:
            self.follow(t)
            return True
        if st.tool == "laser" or st.no_click:
            return True
        st.next()
        return True

    def link_at(self, x, y):
        """The link (text or object click action) under a window point."""
        st = self.st
        if st.screen is not None or st.tool != "arrow":
            return None
        i = st.index
        cache = getattr(self, "_link_shapes", None)
        if cache is None or cache[0] != (i, st.deck.version):
            shapes = [s for s in st.deck.shapes(i)]
            cache = self._link_shapes = ((i, st.deck.version), shapes)
        sx, sy = self.to_slide(x, y)
        for s in reversed(cache[1]):
            if not (s["x"] <= sx <= s["x"] + s["w"] and s["y"] <= sy <= s["y"] + s["h"]):
                continue
            t = st.deck.shape_link(i, s["id"])
            if t:
                return t
            if s["has_text"]:
                try:
                    p, o = st.deck.hit(i, s["id"], sx, sy)
                    t = st.deck.link_at(i, s["id"], p, o)
                    if t and any(rx <= sx <= rx + rw and ry <= sy <= ry + rh
                                 for rx, ry, rw, rh in st.deck.selection_rects(i, s["id"], (p, max(0, o - 1)), (p, o + 1))):
                        return t
                except Exception:
                    pass
        return None

    def follow(self, t):
        st = self.st
        pos = st.pos
        if t.startswith("slide:"):
            st.goto_slide(int(t[6:]))
        elif t == "next":
            st.go(pos + 1) if pos + 1 < len(st.order) else st.end()
        elif t == "prev":
            st.go(max(0, pos - 1))
        elif t == "first":
            st.go(0)
        elif t == "last":
            st.go(len(st.order) - 1)
        elif t == "end":
            st.end()
        else:
            try:
                Gtk.show_uri_on_window(self, t, Gdk.CURRENT_TIME)
            except Exception:
                pass

    def _erase(self, ev):
        st = self.st
        sx, sy = self.to_slide(ev.x, ev.y)
        strokes = st.ink.get(st.index, [])
        keep = [s for s in strokes if not any((px - sx) ** 2 + (py - sy) ** 2 < 64 for px, py in s[3])]
        if len(keep) != len(strokes):
            st.ink[st.index] = keep
            st.changed()

    def on_motion(self, area, ev):
        st = self.st
        if st.tool == "arrow" and not self.hide_pointer:
            over = self.link_at(ev.x, ev.y) is not None
            if over != getattr(self, "_over_link", False):
                self._over_link = over
                w = area.get_window()
                if w is not None:
                    w.set_cursor(Gdk.Cursor.new_from_name(w.get_display(), "pointer" if over else "default"))
        if st.tool == "laser":
            self.laser = (ev.x, ev.y)
            area.queue_draw()
        if self.stroke is not None:
            self.stroke[3].append(self.to_slide(ev.x, ev.y))
            area.queue_draw()
        elif st.tool == "eraser" and ev.state & Gdk.ModifierType.BUTTON1_MASK:
            self._erase(ev)
        return True

    def on_release(self, area, ev):
        if self.stroke is not None:
            self.st.ink.setdefault(self.st.index, []).append(self.stroke)
            self.stroke = None
            self.st.changed()
        return True

    def on_scroll(self, area, ev):
        if ev.direction == Gdk.ScrollDirection.UP:
            self.st.prev()
        elif ev.direction == Gdk.ScrollDirection.DOWN:
            self.st.next()
        elif ev.direction == Gdk.ScrollDirection.SMOOTH:
            if ev.delta_y > 0.5:
                self.st.next()
            elif ev.delta_y < -0.5:
                self.st.prev()
        return True


def on_show_key(st, ev, w):
    name = Gdk.keyval_name(ev.keyval) or ""
    ctrl = bool(ev.state & Gdk.ModifierType.CONTROL_MASK)
    alt = bool(ev.state & Gdk.ModifierType.MOD1_MASK)
    if name.isdigit() or name.startswith("KP_") and name[3:].isdigit():
        st.typed += name[-1]
        return True
    if name in ("Return", "KP_Enter") and st.typed:
        k = int(st.typed) - 1
        st.typed = ""
        st.goto_slide(k)
        return True
    st.typed = ""
    if ctrl:
        tools = {"p": "pen", "i": "highlighter", "e": "eraser", "l": "laser", "a": "arrow"}
        t = tools.get(name.lower())
        if t:
            st.tool = "arrow" if st.tool == t and t != "arrow" else t
            st.changed()
            return True
        if name.lower() == "h":
            w.hide_pointer = not getattr(w, "hide_pointer", False)
            st.changed()
            return True
        if name.lower() == "s":
            all_slides_dialog(st, w)
            return True
        if name.lower() == "m":
            # show or hide ink
            st.ink_hidden = not getattr(st, "ink_hidden", False)
            st.changed()
            return True
    if alt and name == "F5":
        return True
    if name in ("Right", "Down", "space", "Page_Down", "n", "N", "Return", "KP_Enter"):
        st.next()
    elif name in ("Left", "Up", "BackSpace", "Page_Up", "p", "P"):
        st.prev()
    elif name == "Home":
        st.go(0)
    elif name == "End":
        st.go(len(st.order) - 1)
    elif name in ("b", "B", "period"):
        st.screen = None if st.screen == "black" else "black"
        st.changed()
    elif name in ("w", "W", "comma"):
        st.screen = None if st.screen == "white" else "white"
        st.changed()
    elif name in ("Escape", "minus", "KP_Subtract", "Break"):
        st.end()
    elif name in ("e", "E"):
        st.ink.pop(st.index, None)
        st.changed()
    elif name in ("g", "G"):
        all_slides_dialog(st, w)
    elif name in ("h", "H"):
        # the next slide, even when it is hidden
        nxt = st.index + 1 if st.index is not None else 0
        if nxt < st.deck.slide_count():
            st.goto_slide(nxt)
    elif name in ("F1",):
        show_help(w)
    else:
        return False
    return True


def show_menu(st, ev, w):
    m = Gtk.Menu()

    def item(label, cb, check=None):
        mi = Gtk.CheckMenuItem(label=label) if check is not None else Gtk.MenuItem(label=label)
        if check is not None:
            mi.set_active(check)
        mi.connect("activate", lambda *_: cb())
        m.append(mi)
        return mi
    item("Next", st.next)
    item("Previous", st.prev)
    if st.last_viewed is not None:
        item("Last Viewed", lambda: st.go(st.last_viewed))
    item("See All Slides", lambda: all_slides_dialog(st, w))
    m.append(Gtk.SeparatorMenuItem())
    item("Laser Pointer", lambda: _tool(st, "laser"), st.tool == "laser")
    item("Pen", lambda: _tool(st, "pen"), st.tool == "pen")
    item("Highlighter", lambda: _tool(st, "highlighter"), st.tool == "highlighter")
    item("Eraser", lambda: _tool(st, "eraser"), st.tool == "eraser")
    item("Erase All Ink on Slide", lambda: (st.ink.pop(st.index, None), st.changed()))
    sub = Gtk.Menu()
    for name, c in PEN_COLORS:
        mi = Gtk.MenuItem(label=name)
        mi.connect("activate", lambda _m, c=c: (setattr(st, "pen_color", c), _tool(st, "pen")))
        sub.append(mi)
    ink = Gtk.MenuItem(label="Ink Color")
    ink.set_submenu(sub)
    m.append(ink)
    m.append(Gtk.SeparatorMenuItem())
    scr = Gtk.Menu()
    for label, val in (("Black Screen", "black"), ("White Screen", "white")):
        mi = Gtk.MenuItem(label=label)
        mi.connect("activate", lambda _m, v=val: (setattr(st, "screen", v), st.changed()))
        scr.append(mi)
    sm = Gtk.MenuItem(label="Screen")
    sm.set_submenu(scr)
    m.append(sm)
    if not getattr(w, "presenter", None) and not isinstance(w, PresenterWindow):
        item("Show Presenter View", lambda: st.win.presenter_view(st))
    m.append(Gtk.SeparatorMenuItem())
    item("Help", lambda: show_help(w))
    item("Pause", st.toggle_pause)
    item("End Show", st.end)
    m.show_all()
    m.attach_to_widget(w, None)
    m.popup_at_pointer(ev)


def _tool(st, t):
    st.tool = t
    st.changed()


def show_help(parent):
    rows = [("N, Enter, Page Down, Right, Down, Space, click", "Next"),
            ("P, Page Up, Left, Up, Backspace", "Previous"),
            ("number then Enter", "Go to that slide"), ("Home / End", "First / last slide"),
            ("B or .", "Black screen"), ("W or ,", "White screen"), ("G or Ctrl+S", "See all slides"),
            ("H", "Next slide even if hidden"),
            ("Ctrl+P / Ctrl+I / Ctrl+E", "Pen / highlighter / eraser"), ("Ctrl+L", "Laser pointer"),
            ("Ctrl+A", "Arrow pointer"), ("E", "Erase ink on the slide"), ("Ctrl+H", "Hide the pointer"),
            ("Esc or -", "End the show")]
    d = Gtk.Dialog(title="Slide Show Help", transient_for=parent, modal=True)
    d.add_button("OK", Gtk.ResponseType.OK)
    g = Gtk.Grid(column_spacing=24, row_spacing=4, margin=14)
    for k, (a, b) in enumerate(rows):
        g.attach(Gtk.Label(label=a, xalign=0), 0, k, 1, 1)
        g.attach(Gtk.Label(label=b, xalign=0), 1, k, 1, 1)
    d.get_content_area().add(g)
    d.show_all()
    d.run()
    d.destroy()


def all_slides_dialog(st, parent):
    d = Gtk.Dialog(title="All Slides", transient_for=parent, modal=True)
    d.set_default_size(820, 520)
    flow = Gtk.FlowBox()
    flow.set_max_children_per_line(5)
    flow.set_selection_mode(Gtk.SelectionMode.NONE)
    for i in range(st.deck.slide_count()):
        b = Gtk.Button()
        b.set_relief(Gtk.ReliefStyle.NONE)
        v = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        a = Gtk.DrawingArea()
        a.set_size_request(144, 81)
        a.connect("draw", lambda ar, cr, i=i: draw_slide(cr, st, i, ar.get_allocated_width(), ar.get_allocated_height(), ink=False))
        v.pack_start(a, False, False, 0)
        v.pack_start(Gtk.Label(label=str(i + 1)), False, False, 0)
        b.add(v)
        b.connect("clicked", lambda _b, i=i: (d.response(Gtk.ResponseType.OK), st.goto_slide(i)))
        flow.add(b)
    sw = Gtk.ScrolledWindow()
    sw.add(flow)
    d.get_content_area().pack_start(sw, True, True, 0)
    d.show_all()
    d.run()
    d.destroy()


class PresenterWindow(Gtk.Window):
    """Presenter View: the slide, the next one, the notes, timer and controls."""
    def __init__(self, st, monitor=None):
        Gtk.Window.__init__(self)
        self.st = st
        self.set_title("Presenter View")
        self.set_default_size(1280, 760)
        self.get_style_context().add_class("folio-presenter")
        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        bar = Gtk.Box(spacing=12)
        bar.get_style_context().add_class("folio-presenter-bar")
        self.timer = Gtk.Label(label="0:00:00")
        self.timer.get_style_context().add_class("folio-presenter-timer")
        self.pause_btn = Gtk.Button(label="Pause")
        self.pause_btn.connect("clicked", lambda *_: st.toggle_pause())
        reset = Gtk.Button(label="Reset")
        reset.connect("clicked", lambda *_: st.reset_timer())
        self.clock = Gtk.Label()
        bar.pack_start(self.timer, False, False, 10)
        bar.pack_start(self.pause_btn, False, False, 0)
        bar.pack_start(reset, False, False, 0)
        bar.pack_end(self.clock, False, False, 10)
        root.pack_start(bar, False, False, 4)
        body = Gtk.Paned()
        self.cur = Gtk.DrawingArea()
        self.cur.add_events(Gdk.EventMask.BUTTON_PRESS_MASK)
        self.cur.connect("draw", lambda a, cr: draw_slide(cr, st, st.index if st.screen is None else None,
                                                          a.get_allocated_width(), a.get_allocated_height()))
        self.cur.connect("button-press-event", lambda a, e: (st.next() if e.button == 1 else show_menu(st, e, self), True)[1])
        left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        left.pack_start(self.cur, True, True, 0)
        tools = Gtk.Box(spacing=6, halign=Gtk.Align.CENTER)
        for label, cb in (("Pen", lambda: _tool(st, "pen")), ("Laser", lambda: _tool(st, "laser")),
                          ("Arrow", lambda: _tool(st, "arrow")), ("See All Slides", lambda: all_slides_dialog(st, self)),
                          ("Black/Unblack", lambda: (setattr(st, "screen", None if st.screen == "black" else "black"), st.changed()))):
            b = Gtk.Button(label=label)
            b.connect("clicked", lambda *_, cb=cb: cb())
            tools.pack_start(b, False, False, 0)
        nav = Gtk.Box(spacing=6, halign=Gtk.Align.CENTER)
        prev = Gtk.Button(label="◀")
        prev.connect("clicked", lambda *_: st.prev())
        self.count = Gtk.Label()
        nxt = Gtk.Button(label="▶")
        nxt.connect("clicked", lambda *_: st.next())
        nav.pack_start(prev, False, False, 0)
        nav.pack_start(self.count, False, False, 8)
        nav.pack_start(nxt, False, False, 0)
        left.pack_start(tools, False, False, 4)
        left.pack_start(nav, False, False, 6)
        body.pack1(left, True, False)
        right = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        right.set_size_request(380, -1)
        nl = Gtk.Label(label="Next", xalign=0)
        right.pack_start(nl, False, False, 0)
        self.next_area = Gtk.DrawingArea()
        self.next_area.set_size_request(360, 203)
        self.next_area.connect("draw", self._draw_next)
        right.pack_start(self.next_area, False, False, 0)
        self.notes = Gtk.TextView()
        self.notes.set_editable(False)
        self.notes.set_wrap_mode(Gtk.WrapMode.WORD)
        self.notes.get_style_context().add_class("folio-presenter-notes")
        self.notes_size = 18
        sw = Gtk.ScrolledWindow()
        sw.add(self.notes)
        right.pack_start(sw, True, True, 0)
        zoom = Gtk.Box(spacing=4)
        for label, d in (("A−", -2), ("A+", 2)):
            b = Gtk.Button(label=label)
            b.set_tooltip_text("Make the text smaller" if d < 0 else "Make the text larger")
            b.connect("clicked", lambda *_, d=d: self._notes_zoom(d))
            zoom.pack_start(b, False, False, 0)
        right.pack_start(zoom, False, False, 0)
        body.pack2(right, False, False)
        root.pack_start(body, True, True, 0)
        end = Gtk.Button(label="End Slide Show")
        end.connect("clicked", lambda *_: st.end())
        bar.pack_end(end, False, False, 0)
        self.add(root)
        self.connect("key-press-event", lambda w, e: on_show_key(st, e, self))
        st.listeners.append(self.refresh)
        self.show_all()
        if monitor is not None:
            geo = monitor.get_geometry()
            self.move(geo.x, geo.y)
            self.maximize()
        else:
            self.fullscreen()
        self._tick = GLib.timeout_add(500, self._timer)
        self.refresh()

    def _notes_zoom(self, d):
        self.notes_size = max(8, min(60, self.notes_size + d))
        self._style_notes()

    def _style_notes(self):
        css = Gtk.CssProvider()
        css.load_from_data(("textview { font-size: %dpt; }" % self.notes_size).encode())
        self.notes.get_style_context().add_provider(css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 3)

    def _draw_next(self, area, cr):
        st = self.st
        w, h = area.get_allocated_width(), area.get_allocated_height()
        if st.pos + 1 < len(st.order):
            draw_slide(cr, st, st.order[st.pos + 1], w, h, ink=False)
        else:
            cr.set_source_rgb(0.15, 0.15, 0.15)
            cr.paint()
            cr.set_source_rgb(0.8, 0.8, 0.8)
            cr.select_font_face("Sans")
            cr.set_font_size(14)
            cr.move_to(12, h / 2)
            cr.show_text("End of slide show")

    def _timer(self):
        if self.st.ended:
            self._tick = None
            return False
        e = int(self.st.elapsed())
        self.timer.set_text("%d:%02d:%02d" % (e // 3600, (e // 60) % 60, e % 60))
        self.clock.set_text(time.strftime("%-I:%M %p"))
        self.pause_btn.set_label("Resume" if self.st.paused_at else "Pause")
        return True

    def refresh(self):
        st = self.st
        if st.ended:
            self.destroy()
            return
        self.count.set_text("Slide %d of %d" % ((st.index or 0) + 1, st.deck.slide_count()))
        self.notes.get_buffer().set_text(st.deck.notes(st.index) if st.index is not None else "")
        self._style_notes()
        self.cur.queue_draw()
        self.next_area.queue_draw()


def start(win, index, presenter=False):
    """Start the show from slide `index`; with two screens the audience gets one and
    Presenter View the other."""
    st = ShowState(win, index)
    if not st.order:
        return None
    _k, _o, _d, click, after = st.deck.transition(st.index)
    st.no_click = not click or st.kiosk
    st._schedule_advance(after)
    disp = Gdk.Display.get_default()
    n = disp.get_n_monitors() if disp else 1
    primary = disp.get_primary_monitor() if disp else None
    if primary is None and disp is not None and n:
        primary = disp.get_monitor(0)
    use_presenter = win.app.settings.get("presenter_view", True)
    if n >= 2 and use_presenter and not st.browsed:
        other = None
        for k in range(n):
            m = disp.get_monitor(k)
            if m != primary:
                other = m
                break
        st.show_window = ShowWindow(st, other)
        st.presenter_window = PresenterWindow(st, primary)
    elif presenter:
        st.presenter_window = PresenterWindow(st, None)
    else:
        st.show_window = ShowWindow(st, None)

    def on_end():
        if st.ended and not getattr(st, "_done", False):
            st._done = True
            win.show_ended(st)
    st.listeners.append(on_end)
    return st


# ---------------------------------------------------------------- transitions
def blend(cr, a, b, kind, opt, t, w, h, seed=7):
    """One frame of a transition from picture a to b (cairo surfaces w x h, either may be None
    for black), t from 0 to 1."""
    import random
    t = max(0.0, min(1.0, t))
    e = t * t * (3 - 2 * t)          # ease in and out

    def paint(s, x=0.0, y=0.0, alpha=1.0):
        if s is None:
            cr.set_source_rgb(0, 0, 0)
            cr.rectangle(x, y, w, h)
            cr.fill()
            return
        cr.set_source_surface(s, x, y)
        cr.paint_with_alpha(alpha) if alpha < 1 else cr.paint()
    cr.save()
    cr.rectangle(0, 0, w, h)
    cr.clip()
    vec = {"u": (0, -1), "d": (0, 1), "l": (-1, 0), "r": (1, 0)}.get(opt or "", (-1, 0))
    if kind == "fade":
        if opt == "thruBlk":
            if t < 0.5:
                paint(a)
                cr.set_source_rgba(0, 0, 0, e * 2 if e < 0.5 else 1)
                cr.paint()
            else:
                paint(None)
                paint(b, alpha=(t - 0.5) * 2)
        else:
            paint(a)
            paint(b, alpha=e)
    elif kind == "push":
        dx, dy = vec[0] * w * e, vec[1] * h * e
        paint(a, dx, dy)
        paint(b, dx - vec[0] * w, dy - vec[1] * h)
    elif kind == "cover":
        paint(a)
        paint(b, -vec[0] * w * (1 - e), -vec[1] * h * (1 - e))
    elif kind == "pull":
        paint(b)
        paint(a, vec[0] * w * e, vec[1] * h * e)
    elif kind == "wipe":
        paint(a)
        cr.save()
        if vec[0] < 0:
            cr.rectangle(w * (1 - e), 0, w * e, h)
        elif vec[0] > 0:
            cr.rectangle(0, 0, w * e, h)
        elif vec[1] > 0:
            cr.rectangle(0, 0, w, h * e)
        else:
            cr.rectangle(0, h * (1 - e), w, h * e)
        cr.clip()
        paint(b)
        cr.restore()
    elif kind == "split":
        paint(a)
        cr.save()
        if opt == "vert":
            cr.rectangle(w / 2 * (1 - e), 0, w * e, h)
        else:
            cr.rectangle(0, h / 2 * (1 - e), w, h * e)
        cr.clip()
        paint(b)
        cr.restore()
    elif kind == "randomBar":
        paint(a)
        rnd = random.Random(seed)
        n = 60
        order = list(range(n))
        rnd.shuffle(order)
        k = int(n * t)
        cr.save()
        for j in order[:k]:
            if opt == "vert":
                cr.rectangle(w * j / n, 0, w / n + 1, h)
            else:
                cr.rectangle(0, h * j / n, w, h / n + 1)
        cr.clip()
        paint(b)
        cr.restore()
    elif kind == "dissolve":
        paint(a)
        rnd = random.Random(seed)
        cols, rows = 32, 18
        cells = [(c, r) for c in range(cols) for r in range(rows)]
        rnd.shuffle(cells)
        cr.save()
        for c, r in cells[:int(len(cells) * t)]:
            cr.rectangle(w * c / cols, h * r / rows, w / cols + 1, h / rows + 1)
        cr.clip()
        paint(b)
        cr.restore()
    elif kind == "circle":
        import math
        paint(a)
        cr.save()
        cr.arc(w / 2, h / 2, e * math.hypot(w, h) / 2 + 1, 0, 2 * math.pi)
        cr.clip()
        paint(b)
        cr.restore()
    elif kind == "zoom":
        paint(a)
        cr.save()
        k = 0.3 + 0.7 * e
        cr.translate(w / 2, h / 2)
        cr.scale(k, k)
        cr.translate(-w / 2, -h / 2)
        paint(b, alpha=e)
        cr.restore()
    else:
        paint(b)
    cr.restore()


def frame_surface(st, i, w, h):
    """Slide i letterboxed into a w x h picture (None: black)."""
    if i is None:
        return None
    s = cairo.ImageSurface(cairo.FORMAT_ARGB32, max(1, int(w)), max(1, int(h)))
    cr = cairo.Context(s)
    draw_slide(cr, st, i, w, h, ink=False)
    return s


def preview_in(win, prev, i, kind, opt, dur):
    """Play a transition in the editing window's slide area (Transitions > Preview)."""
    c = win.canvas
    sw, sh = win.deck.size()
    w, h = int(sw * c.scale), int(sh * c.scale)
    if w < 2 or h < 2:
        return
    st = ShowState(win, i, hidden_too=True)
    a = frame_surface(st, prev, w, h) if prev is not None else None
    b = frame_surface(st, i, w, h)
    start = time.time()
    dur = max(0.2, dur or 0.75)
    c.preview = None

    def tick():
        t = (time.time() - start) / dur
        if t >= 1:
            c.preview = None
            c.queue()
            return False
        c.preview = (a, b, kind, opt, t)
        c.queue()
        return True
    GLib.timeout_add(16, tick)

"""The status bar: slide number, Notes, the view buttons, zoom and Fit to Window."""
from gi.repository import Gtk

from . import icons

ZOOM_STEPS = [10, 25, 33, 50, 66, 75, 100, 150, 200, 300, 400]


class StatusBar(Gtk.Box):
    def __init__(self, win):
        Gtk.Box.__init__(self, spacing=6)
        self.win = win
        self.get_style_context().add_class("folio-status")
        self.slide_label = Gtk.Label(label="Slide 1 of 1", xalign=0)
        self.slide_label.set_margin_start(10)
        self.pack_start(self.slide_label, False, False, 0)
        self.lang = Gtk.Label(label="English (United States)", xalign=0)
        self.pack_start(self.lang, False, False, 14)
        self.pack_start(Gtk.Box(), True, True, 0)

        def flat(label=None, icon=None, tip=None, cb=None):
            b = Gtk.Button()
            if icon:
                b.add(icons.image(icon, 16))
            if label:
                b.add(Gtk.Label(label=label)) if not icon else None
            b.set_relief(Gtk.ReliefStyle.NONE)
            b.set_focus_on_click(False)
            b.get_style_context().add_class("folio-status-btn")
            if tip:
                b.set_tooltip_text(tip)
            if cb:
                b.connect("clicked", lambda *_: cb())
            return b
        self.notes_btn = flat(label="≡ Notes", tip="Notes: show or hide the notes pane", cb=lambda: win.run("toggle-notes"))
        self.comments_btn = flat(label="Comments", tip="Comments", cb=lambda: win.run("comments-pane"))
        self.pack_start(self.notes_btn, False, False, 0)
        self.pack_start(self.comments_btn, False, False, 0)
        self.view_btns = {}
        for key, icon, tip in (("normal", "r-view-normal-sm", "Normal"),
                               ("sorter", "slidechangewindow", "Slide Sorter"),
                               ("reading", "read-mode", "Reading View"),
                               ("show", "presentationcurrentslide", "Slide Show (Shift+F5)")):
            b = flat(icon=icon, tip=tip, cb=lambda k=key: win.run({"normal": "view-normal", "sorter": "view-sorter",
                                                                     "reading": "view-reading", "show": "show-current"}[k]))
            self.view_btns[key] = b
            self.pack_start(b, False, False, 0)
        minus = flat(label="−", tip="Zoom Out", cb=lambda: self.step_zoom(-1))
        plus = flat(label="+", tip="Zoom In", cb=lambda: self.step_zoom(1))
        self.slider = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 10, 400, 1)
        self.slider.set_draw_value(False)
        self.slider.set_size_request(110, -1)
        self.slider.add_mark(100, Gtk.PositionType.BOTTOM, None)
        self.slider.connect("value-changed", self.on_slider)
        self.zoom_btn = flat(label="100%", tip="Zoom level", cb=lambda: win.run("zoom-dialog"))
        self.fit_btn = flat(icon="zoomoptimal", tip="Fit slide to current window", cb=lambda: win.run("zoom-fit"))
        self.pack_start(minus, False, False, 0)
        self.pack_start(self.slider, False, False, 0)
        self.pack_start(plus, False, False, 0)
        self.pack_start(self.zoom_btn, False, False, 2)
        self.pack_start(self.fit_btn, False, False, 4)
        self._quiet = False

    def set_slide(self, i, n, hidden=False):
        self.slide_label.set_text("Slide %d of %d" % (i + 1, n) if n else "No slides")

    def show_zoom(self, pct):
        if pct is None:
            pct = self.win.canvas.zoom_percent()
        self._quiet = True
        self.slider.set_value(pct)
        self._quiet = False
        label = self.zoom_btn.get_child()
        if isinstance(label, Gtk.Label):
            label.set_text("%d%%" % pct)

    def on_slider(self, s):
        if self._quiet:
            return
        self.win.canvas.set_zoom(int(s.get_value()))

    def step_zoom(self, d):
        cur = self.win.canvas.zoom_percent()
        steps = [z for z in ZOOM_STEPS if (z > cur if d > 0 else z < cur)]
        if steps:
            self.win.canvas.set_zoom(steps[0] if d > 0 else steps[-1])

    def set_view(self, view):
        for k, b in self.view_btns.items():
            ctx = b.get_style_context()
            (ctx.add_class if k == view else ctx.remove_class)("checked")

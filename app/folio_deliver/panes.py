"""Dialogs and panes: Selection Pane, Symbol, Font, Paragraph, Format Shape, Format Background,
Find and Replace, Spelling, Accessibility, Keyboard Shortcuts."""
from gi.repository import Gdk, GLib, Gtk, Pango

from . import APP_NAME


def _dialog(win, title, ok="OK"):
    d = Gtk.Dialog(title=title, transient_for=win, modal=True)
    d.get_style_context().add_class("folio-dialog")
    if ok:
        d.add_button("Cancel", Gtk.ResponseType.CANCEL)
        d.add_button(ok, Gtk.ResponseType.OK)
        d.set_default_response(Gtk.ResponseType.OK)
    box = d.get_content_area()
    box.set_border_width(12)
    box.set_spacing(8)
    return d, box


def _row(grid, r, label, w):
    grid.attach(Gtk.Label(label=label, xalign=0), 0, r, 1, 1)
    grid.attach(w, 1, r, 1, 1)


# ---------------------------------------------------------------- selection pane
def selection_pane(win):
    """The objects on the slide, top first: click to select, double-click to rename."""
    d, box = _dialog(win, "Selection", ok=None)
    d.set_modal(False)
    d.add_button("Close", Gtk.ResponseType.CLOSE)
    d.set_default_size(300, 420)
    store = Gtk.ListStore(int, str)
    tv = Gtk.TreeView(model=store)
    tv.set_headers_visible(False)
    rend = Gtk.CellRendererText()
    rend.set_property("editable", True)
    tv.append_column(Gtk.TreeViewColumn("Name", rend, text=1))

    def fill():
        store.clear()
        for s in reversed(win.canvas.shapes):
            store.append([s["id"], s["name"] or s["kind"]])
    fill()

    def picked(sel):
        model, it = sel.get_selected()
        if it is not None:
            win.canvas.leave_text()
            win.canvas.select([model[it][0]])

    def renamed(_r, path, text):
        sid = store[path][0]
        win.deck.rename_shape(win.current, sid, text)
        win.changed(slide=True)
        fill()
    tv.get_selection().connect("changed", picked)
    rend.connect("edited", renamed)
    sw = Gtk.ScrolledWindow()
    sw.add(tv)
    box.pack_start(sw, True, True, 0)
    row = Gtk.Box(spacing=6)
    for label, how in (("Bring Forward", "forward"), ("Send Backward", "backward")):
        b = Gtk.Button(label=label)
        b.connect("clicked", lambda _b, h=how: (win.run("order:" + h), fill()))
        row.pack_start(b, False, False, 0)
    box.pack_start(row, False, False, 0)
    d.connect("response", lambda *_: d.destroy())
    d.show_all()


# ---------------------------------------------------------------- symbol
SYMBOLS = ("©®™§¶†‡•…–—‘’“”«»"
           "°±×÷≠≤≥≈∞√∑∏∫∂∆∇π"
           "αβγδεθλμσφωΩ←↑→↓↔"
           "⇒⇔★☆✓✔✗✘☐☑☒■□▲▼◆●"
           "○♠♣♥♦☺☹♪♫€£¥¢¼½¾⅓"
           "⅔¹²³⁰⁴⁵₀₁₂¿¡éèêàç"
           "ñüöäßæøå")


def symbol_dialog(win):
    d, box = _dialog(win, "Symbol", ok="Insert")
    grid = Gtk.FlowBox()
    grid.set_max_children_per_line(16)
    grid.set_min_children_per_line(16)
    grid.set_selection_mode(Gtk.SelectionMode.SINGLE)
    for ch in SYMBOLS:
        lab = Gtk.Label(label=ch)
        lab.set_size_request(28, 28)
        grid.add(lab)
    box.pack_start(grid, True, True, 0)
    code = Gtk.Entry()
    code.set_placeholder_text("Character code (hex), e.g. 263A")
    box.pack_start(code, False, False, 0)
    grid.connect("child-activated", lambda *_: d.response(Gtk.ResponseType.OK))
    d.show_all()
    r = d.run()
    out = None
    if r == Gtk.ResponseType.OK:
        t = code.get_text().strip()
        if t:
            try:
                out = chr(int(t, 16))
            except ValueError:
                out = None
        else:
            sel = grid.get_selected_children()
            if sel:
                out = sel[0].get_child().get_text()
    d.destroy()
    return out


# ---------------------------------------------------------------- font
def font_dialog(win):
    c = win.canvas
    rp, _pp = c.current_run()
    if rp is None:
        return
    d, box = _dialog(win, "Font")
    g = Gtk.Grid(column_spacing=12, row_spacing=8)
    font = Gtk.FontButton()
    font.set_use_size(False)
    font.set_show_size(False)
    font.set_level(Gtk.FontChooserLevel.FAMILY)
    font.set_font(rp.get("font") or "Calibri")
    style = Gtk.ComboBoxText()
    for s in ("Regular", "Italic", "Bold", "Bold Italic"):
        style.append_text(s)
    style.set_active((2 if rp.get("b") else 0) + (1 if rp.get("i") else 0))
    size = Gtk.SpinButton.new_with_range(1, 4000, 1)
    size.set_digits(1)
    size.set_value(rp.get("sz", 18))
    color = Gtk.ColorButton()
    col = rp.get("color")
    if col:
        rgba = Gdk.RGBA()
        rgba.parse("#" + col)
        color.set_rgba(rgba)
    under = Gtk.ComboBoxText()
    for k, t in (("none", "(none)"), ("sng", "Single"), ("dbl", "Double"), ("heavy", "Heavy"), ("dotted", "Dotted"),
                 ("dash", "Dashed"), ("wavy", "Wavy")):
        under.append(k, t)
    under.set_active_id("sng" if rp.get("u") else "none")
    _row(g, 0, "Latin text font:", font)
    _row(g, 1, "Font style:", style)
    _row(g, 2, "Size:", size)
    _row(g, 3, "Font color:", color)
    _row(g, 4, "Underline style:", under)
    effects = {}
    for k, (label, key, on, off) in enumerate((("Strikethrough", "strike", "sngStrike", "noStrike"),
                                               ("Double Strikethrough", "strike", "dblStrike", "noStrike"),
                                               ("Superscript", "baseline", "30", "0"),
                                               ("Subscript", "baseline", "-25", "0"),
                                               ("Small Caps", "cap", "small", "none"),
                                               ("All Caps", "cap", "all", "none"))):
            cb = Gtk.CheckButton(label=label)
            if key == "strike" and on == "sngStrike":
                cb.set_active(bool(rp.get("strike")))
            if key == "baseline":
                cb.set_active((rp.get("baseline", 0) > 0) if on == "30" else (rp.get("baseline", 0) < 0))
            effects[label] = (cb, key, on, off)
            g.attach(cb, 2 + k // 3, k % 3, 1, 1)
    box.pack_start(g, False, False, 0)
    d.show_all()
    if d.run() == Gtk.ResponseType.OK:
        fam = font.get_font_family().get_name() if font.get_font_family() else rp.get("font")
        s = style.get_active()
        changes = [("font", fam), ("b", "1" if s >= 2 else "0"), ("i", "1" if s % 2 else "0"),
                   ("sz", "%g" % size.get_value()), ("u", under.get_active_id())]
        rgba = color.get_rgba()
        changes.append(("color", "%02X%02X%02X" % (int(rgba.red * 255), int(rgba.green * 255), int(rgba.blue * 255))))
        seen = set()
        for label, (cb, key, on, off) in effects.items():
            if cb.get_active():
                changes.append((key, on))
                seen.add(key)
        for label, (cb, key, on, off) in effects.items():
            if key not in seen:
                changes.append((key, off))
                seen.add(key)
        for k, v in changes:
            c.run_format(k, v)
    d.destroy()


# ---------------------------------------------------------------- paragraph
def paragraph_dialog(win):
    c = win.canvas
    rp, pp = c.current_run()
    if pp is None:
        return
    d, box = _dialog(win, "Paragraph")
    g = Gtk.Grid(column_spacing=12, row_spacing=8)
    algn = Gtk.ComboBoxText()
    for k, t in (("l", "Left"), ("ctr", "Centered"), ("r", "Right"), ("just", "Justified"), ("dist", "Distributed")):
        algn.append(k, t)
    algn.set_active_id(pp.get("algn", "l"))
    before = Gtk.SpinButton.new_with_range(0, 22, 0.1)
    before.set_digits(2)
    special = Gtk.ComboBoxText()
    for k, t in (("none", "(none)"), ("first", "First line"), ("hanging", "Hanging")):
        special.append(k, t)
    special.set_active_id("none")
    by = Gtk.SpinButton.new_with_range(0, 22, 0.1)
    by.set_digits(2)
    sb = Gtk.SpinButton.new_with_range(0, 1584, 1)
    sa = Gtk.SpinButton.new_with_range(0, 1584, 1)
    ls = Gtk.ComboBoxText()
    for k, t in (("1.0", "Single"), ("1.5", "1.5 lines"), ("2.0", "Double"), ("multi", "Multiple")):
        ls.append(k, t)
    cur = pp.get("lnSpc", 1.0)
    ls.set_active_id("%.1f" % cur if "%.1f" % cur in ("1.0", "1.5", "2.0") else "multi")
    at = Gtk.SpinButton.new_with_range(0, 9.99, 0.1)
    at.set_digits(2)
    at.set_value(cur)
    for r, (label, w) in enumerate((("Alignment:", algn), ("Before text (in):", before), ("Special:", special),
                                    ("By (in):", by), ("Spacing before (pt):", sb), ("Spacing after (pt):", sa),
                                    ("Line Spacing:", ls), ("At:", at))):
        _row(g, r, label, w)
    box.pack_start(g, False, False, 0)
    d.show_all()
    if d.run() == Gtk.ResponseType.OK:
        c.para_format("algn", algn.get_active_id(), label="Paragraph")
        c.para_format("marL", "%g" % (before.get_value() * 72), label="Paragraph")
        sp = special.get_active_id()
        ind = by.get_value() * 72
        c.para_format("indent", "%g" % (0 if sp == "none" else (ind if sp == "first" else -ind)), label="Paragraph")
        c.para_format("spcBef", "%g" % sb.get_value(), label="Paragraph")
        c.para_format("spcAft", "%g" % sa.get_value(), label="Paragraph")
        v = ls.get_active_id()
        c.para_format("lnSpc", "%g" % (at.get_value() if v == "multi" else float(v)), label="Paragraph")
    d.destroy()


# ---------------------------------------------------------------- format shape / background
def _rgba_hex(btn):
    r = btn.get_rgba()
    return "%02X%02X%02X" % (int(r.red * 255), int(r.green * 255), int(r.blue * 255))


def format_shape_dialog(win):
    c = win.canvas
    shapes = [c.shape(s) for s in c.sel]
    shapes = [s for s in shapes if s]
    if not shapes:
        return
    s0 = shapes[0]
    d, box = _dialog(win, "Format Shape")
    g = Gtk.Grid(column_spacing=12, row_spacing=8)
    fill = Gtk.ComboBoxText()
    for k, t in (("keep", "(unchanged)"), ("none", "No fill"), ("solid", "Solid fill")):
        fill.append(k, t)
    fill.set_active_id("keep")
    fcol = Gtk.ColorButton()
    line = Gtk.ComboBoxText()
    for k, t in (("keep", "(unchanged)"), ("none", "No line"), ("solid", "Solid line")):
        line.append(k, t)
    line.set_active_id("keep")
    lcol = Gtk.ColorButton()
    width = Gtk.SpinButton.new_with_range(0, 1584, 0.25)
    width.set_digits(2)
    width.set_value(0.75)
    dash = Gtk.ComboBoxText()
    for k in ("(unchanged)", "solid", "sysDot", "sysDash", "dash", "dashDot", "lgDash", "lgDashDot", "lgDashDotDot"):
        dash.append(k, k)
    dash.set_active_id("(unchanged)")
    h = Gtk.SpinButton.new_with_range(0.01, 56, 0.01)
    h.set_digits(2)
    h.set_value(s0["h"] / 72)
    w = Gtk.SpinButton.new_with_range(0.01, 56, 0.01)
    w.set_digits(2)
    w.set_value(s0["w"] / 72)
    rot = Gtk.SpinButton.new_with_range(-360, 360, 1)
    rot.set_value(s0["rot"])
    x = Gtk.SpinButton.new_with_range(-100, 100, 0.01)
    x.set_digits(2)
    x.set_value(s0["x"] / 72)
    y = Gtk.SpinButton.new_with_range(-100, 100, 0.01)
    y.set_digits(2)
    y.set_value(s0["y"] / 72)
    for r, (label, wd) in enumerate((("Fill:", fill), ("Fill color:", fcol), ("Line:", line), ("Line color:", lcol),
                                     ("Line width (pt):", width), ("Dash type:", dash), ("Height (in):", h),
                                     ("Width (in):", w), ("Rotation:", rot), ("Horizontal position (in):", x),
                                     ("Vertical position (in):", y))):
        _row(g, r, label, wd)
    box.pack_start(g, False, False, 0)
    d.show_all()
    if d.run() == Gtk.ResponseType.OK:
        ids = [s["id"] for s in shapes]
        i = win.current
        if fill.get_active_id() == "none":
            win.deck.set_shape_fill(i, ids, "none")
        elif fill.get_active_id() == "solid":
            win.deck.set_shape_fill(i, ids, _rgba_hex(fcol))
        lc = {"none": "none", "solid": _rgba_hex(lcol)}.get(line.get_active_id())
        ds = dash.get_active_id()
        win.deck.set_shape_line(i, ids, lc, width.get_value(), None if ds == "(unchanged)" else ds)
        if len(shapes) == 1:
            win.deck.set_boxes(i, [(s0["id"], x.get_value() * 72, y.get_value() * 72, w.get_value() * 72,
                                    h.get_value() * 72, rot.get_value())], "Size and Position")
        win.changed(slide=True)
    d.destroy()


def background_dialog(win):
    d, box = _dialog(win, "Format Background")
    d.add_button("Apply to All", 7)
    kind = Gtk.ComboBoxText()
    for k, t in (("solid", "Solid fill"), ("reset", "Reset Background (follow the layout)")):
        kind.append(k, t)
    kind.set_active_id("solid")
    col = Gtk.ColorButton()
    rgba = Gdk.RGBA()
    rgba.parse("#FFFFFF")
    col.set_rgba(rgba)
    g = Gtk.Grid(column_spacing=12, row_spacing=8)
    _row(g, 0, "Fill:", kind)
    _row(g, 1, "Color:", col)
    box.pack_start(g, False, False, 0)
    d.show_all()
    r = d.run()
    if r in (Gtk.ResponseType.OK, 7):
        spec = "" if kind.get_active_id() == "reset" else _rgba_hex(col)
        idx = list(range(win.deck.slide_count())) if r == 7 else win._selected_slides()
        win.deck.set_background(idx, spec)
        win.thumbs.forget()
        win.changed(all_slides=True)
    d.destroy()


# ---------------------------------------------------------------- find / replace
def _all_text(win):
    """(slide, shape id, paragraph, text) for every paragraph in the presentation."""
    for i in range(win.deck.slide_count()):
        for sid, _ph, paras in win.deck.slide_text(i):
            for p, t in enumerate(paras):
                yield i, sid, p, t


def find_dialog(win, replace=False):
    d = Gtk.Dialog(title="Replace" if replace else "Find", transient_for=win, modal=False)
    d.get_style_context().add_class("folio-dialog")
    box = d.get_content_area()
    box.set_border_width(12)
    box.set_spacing(8)
    g = Gtk.Grid(column_spacing=10, row_spacing=8)
    what = Gtk.Entry()
    what.set_activates_default(True)
    with_ = Gtk.Entry()
    case = Gtk.CheckButton(label="Match case")
    whole = Gtk.CheckButton(label="Find whole words only")
    _row(g, 0, "Find what:", what)
    if replace:
        _row(g, 1, "Replace with:", with_)
    g.attach(case, 0, 2, 2, 1)
    g.attach(whole, 0, 3, 2, 1)
    box.pack_start(g, False, False, 0)
    msg = Gtk.Label(xalign=0)
    box.pack_start(msg, False, False, 0)
    d.add_button("Find Next", 1)
    if replace:
        d.add_button("Replace", 2)
        d.add_button("Replace All", 3)
    d.add_button("Close", Gtk.ResponseType.CLOSE)
    d.set_default_response(1)
    sel = win.canvas.selected_text()
    if sel and "\n" not in sel:
        what.set_text(sel)

    def match(t, needle, start=0):
        a, b = (t, needle) if case.get_active() else (t.lower(), needle.lower())
        k = a.find(b, start)
        while k >= 0 and whole.get_active():
            before = k == 0 or not a[k - 1].isalnum()
            after = k + len(b) >= len(a) or not a[k + len(b)].isalnum()
            if before and after:
                break
            k = a.find(b, k + 1)
        return k

    def find_next():
        needle = what.get_text()
        if not needle:
            return False
        c = win.canvas
        # from the caret on, then round from the start
        shape_order = {}
        candidates = []
        for i, sid, p, t in _all_text(win):
            shape_order.setdefault((i, sid), len(shape_order))
            k = match(t, needle)
            while k >= 0:
                candidates.append(((i, shape_order[(i, sid)], p, k), (i, sid, p, k)))
                k = match(t, needle, k + 1)
        if not candidates:
            msg.set_text("The search item wasn't found.")
            return False
        cur_slide = win.current or 0
        if c.edit is not None:
            e = c.edit.range()[0]
            here = (cur_slide, shape_order.get((cur_slide, c.edit.id), -1), e[0], e[1])
        else:
            here = (cur_slide, -1, -1, -1)
        later = [cd for key, cd in candidates if key > here]
        pick = later[0] if later else candidates[0][1]
        i, sid, p, k = pick
        if i != win.current:
            win.go_slide(i)
        c._surface()
        c.start_text(sid, (p, k + len(needle)))
        c.edit.anchor = (p, k)
        c.queue()
        msg.set_text("")
        return True

    def replace_one():
        c = win.canvas
        if c.edit is not None and c.edit.has_selection():
            t = c.selected_text()
            n = what.get_text()
            if (t == n) or (not case.get_active() and t.lower() == n.lower()):
                c.type_text(with_.get_text())
        find_next()

    def replace_all():
        n = 0
        needle = what.get_text()
        if not needle:
            return
        for i in range(win.deck.slide_count()):
            for sid, _ph, paras in win.deck.slide_text(i):
                for p in range(len(paras)):
                    while True:
                        t = win.deck.paragraphs(i, sid)[p]
                        k = match(t, needle)
                        if k < 0:
                            break
                        win.deck.delete_text(i, sid, (p, k), (p, k + len(needle)), "Replace All")
                        if with_.get_text():
                            win.deck.insert_text(i, sid, p, k, with_.get_text(), "Replace All")
                        n += 1
                        if with_.get_text() and match(with_.get_text(), needle) >= 0:
                            break
        win.thumbs.forget()
        win.changed(all_slides=True)
        msg.set_text("%s made %d replacement%s." % (APP_NAME, n, "" if n == 1 else "s"))

    def resp(_d, r):
        if r == 1:
            find_next()
        elif r == 2:
            replace_one()
        elif r == 3:
            replace_all()
        else:
            d.destroy()
    d.connect("response", resp)
    d.show_all()


# ---------------------------------------------------------------- spelling
def _speller(win):
    try:
        import enchant
    except ImportError:
        return None
    lang = win.app.settings.get("language", "en_US")
    try:
        return enchant.Dict(lang)
    except Exception:
        try:
            return enchant.Dict("en_US")
        except Exception:
            return None


def spelling_dialog(win):
    sp = _speller(win)
    if sp is None:
        win.dialogs.info("Spelling needs a dictionary (packages python3-enchant and hunspell-en-us).")
        return
    import re
    ignored = set(win.app.settings.get("ignore_words", []))
    issues = []
    for i, sid, p, t in _all_text(win):
        for m in re.finditer(r"[A-Za-zÀ-ɏ']+", t):
            w = m.group(0).strip("'")
            if len(w) < 2 or w in ignored or w.isupper() or any(ch.isdigit() for ch in w):
                continue
            if not sp.check(w):
                issues.append((i, sid, p, m.start(), w))
    if not issues:
        win.dialogs.info("Spelling check complete. You're good to go!")
        return
    d = Gtk.Dialog(title="Spelling", transient_for=win, modal=True)
    box = d.get_content_area()
    box.set_border_width(12)
    box.set_spacing(8)
    word = Gtk.Label(xalign=0)
    box.pack_start(word, False, False, 0)
    store = Gtk.ListStore(str)
    tv = Gtk.TreeView(model=store)
    tv.set_headers_visible(False)
    tv.append_column(Gtk.TreeViewColumn("", Gtk.CellRendererText(), text=0))
    tv.set_size_request(260, 160)
    box.pack_start(tv, True, True, 0)
    for k, label in ((1, "Ignore Once"), (2, "Ignore All"), (3, "Add"), (4, "Change"), (5, "Change All")):
        d.add_button(label, k)
    d.add_button("Close", Gtk.ResponseType.CLOSE)
    state = {"k": 0, "shift": {}}

    def show():
        while state["k"] < len(issues) and issues[state["k"]][4] in ignored:
            state["k"] += 1
        if state["k"] >= len(issues):
            d.response(Gtk.ResponseType.CLOSE)
            win.dialogs.info("Spelling check complete.")
            return
        i, sid, p, o, w = issues[state["k"]]
        word.set_markup("Not in Dictionary: <b>%s</b>" % GLib.markup_escape_text(w))
        store.clear()
        for s in sp.suggest(w)[:8]:
            store.append([s])
        if len(store):
            tv.get_selection().select_path(0)
        o += state["shift"].get((i, sid, p), 0)
        if i != win.current:
            win.go_slide(i)
        win.canvas._surface()
        win.canvas.start_text(sid, (p, o + len(w)))
        win.canvas.edit.anchor = (p, o)
        win.canvas.queue()

    def change(all_=False):
        model, it = tv.get_selection().get_selected()
        if it is None:
            return
        new = model[it][0]
        targets = [state["k"]] if not all_ else [k for k in range(state["k"], len(issues)) if issues[k][4] == issues[state["k"]][4]]
        for k in targets:
            i, sid, p, o, w = issues[k]
            o += state["shift"].get((i, sid, p), 0)
            win.deck.delete_text(i, sid, (p, o), (p, o + len(w)), "Spelling")
            win.deck.insert_text(i, sid, p, o, new, "Spelling")
            state["shift"][(i, sid, p)] = state["shift"].get((i, sid, p), 0) + len(new) - len(w)
        win.changed(slide=True)

    def resp(_d, r):
        if r == Gtk.ResponseType.CLOSE or r == Gtk.ResponseType.DELETE_EVENT:
            d.destroy()
            return
        w = issues[state["k"]][4]
        if r == 2:
            ignored.add(w)
        elif r == 3:
            try:
                sp.add(w)
            except Exception:
                ignored.add(w)
            win.app.settings.setdefault("ignore_words", []).append(w)
        elif r == 4:
            change()
        elif r == 5:
            change(True)
        state["k"] += 1
        show()
    d.connect("response", resp)
    d.show_all()
    show()


# ---------------------------------------------------------------- accessibility
def accessibility_report(win):
    rows = []
    for i in range(win.deck.slide_count()):
        shapes = win.deck.shapes(i)
        titles = [s for s in shapes if s["ph"] in ("title", "ctrTitle") and not s["empty"]]
        if not titles:
            rows.append(("Missing slide title", "Slide %d" % (i + 1)))
        for s in shapes:
            if s["kind"] in ("pic", "graphicFrame", "grpSp") and not s.get("descr"):
                rows.append(("Missing alternative text", "%s (Slide %d)" % (s["name"], i + 1)))
    d, box = _dialog(win, "Accessibility", ok=None)
    d.add_button("Close", Gtk.ResponseType.CLOSE)
    if not rows:
        box.pack_start(Gtk.Label(label="No accessibility issues found. People with disabilities should not have difficulty reading this presentation."), False, False, 0)
    else:
        g = Gtk.Grid(column_spacing=16, row_spacing=4)
        for k, (a, b) in enumerate(rows[:60]):
            g.attach(Gtk.Label(label=a, xalign=0), 0, k, 1, 1)
            g.attach(Gtk.Label(label=b, xalign=0), 1, k, 1, 1)
        sw = Gtk.ScrolledWindow()
        sw.set_size_request(480, 300)
        sw.add(g)
        box.pack_start(sw, True, True, 0)
    d.show_all()
    d.run()
    d.destroy()


# ---------------------------------------------------------------- shortcuts
SHORTCUTS = [
    ("Presentations", [("Ctrl+N", "New presentation"), ("Ctrl+O", "Open"), ("Ctrl+S", "Save"), ("F12", "Save As"),
                       ("Ctrl+P", "Print"), ("Ctrl+W", "Close")]),
    ("Slides", [("Ctrl+M", "New slide"), ("Ctrl+D", "Duplicate slide (or object)"), ("Ctrl+Enter", "Next placeholder"),
                ("Delete", "Delete slide (slide pane)"), ("Ctrl+Up / Ctrl+Down", "Move slide (slide pane)"),
                ("Page Up / Page Down", "Previous / next slide")]),
    ("Slide Show", [("F5", "From beginning"), ("Shift+F5", "From current slide"), ("Alt+F5", "Presenter View"),
                    ("N / P", "Next / previous"), ("B / W", "Black / white screen"), ("Esc", "End show")]),
    ("Text", [("Ctrl+B / I / U", "Bold / italic / underline"), ("Ctrl+] / Ctrl+[", "Larger / smaller font"),
              ("Ctrl+E / L / R / J", "Center / left / right / justify"), ("Ctrl+= / Ctrl+Shift+=", "Subscript / superscript"),
              ("Ctrl+Space", "Clear formatting"), ("Tab / Shift+Tab", "Demote / promote list level"),
              ("Shift+Enter", "Line break"), ("Ctrl+T", "Font dialog")]),
    ("Objects", [("Arrows / Ctrl+Arrows", "Nudge"), ("Shift+Arrows", "Resize"), ("Ctrl+G / Ctrl+Shift+G", "Group / ungroup"),
                 ("Tab", "Next object"), ("Ctrl+drag", "Copy"), ("Shift+drag", "Straight / proportional"),
                 ("Enter or F2", "Edit text")]),
    ("Ribbon", [("Alt or F10", "KeyTips"), ("Alt+Q", "Search")]),
]


def shortcuts_dialog(win):
    d, box = _dialog(win, "Keyboard Shortcuts", ok=None)
    d.add_button("Close", Gtk.ResponseType.CLOSE)
    g = Gtk.Grid(column_spacing=24, row_spacing=3)
    r = 0
    for head, rows in SHORTCUTS:
        lab = Gtk.Label(xalign=0)
        lab.set_markup("<b>%s</b>" % head)
        lab.set_margin_top(6)
        g.attach(lab, 0, r, 2, 1)
        r += 1
        for k, t in rows:
            g.attach(Gtk.Label(label=k, xalign=0), 0, r, 1, 1)
            g.attach(Gtk.Label(label=t, xalign=0), 1, r, 1, 1)
            r += 1
    sw = Gtk.ScrolledWindow()
    sw.set_size_request(520, 480)
    sw.add(g)
    box.pack_start(sw, True, True, 0)
    d.show_all()
    d.run()
    d.destroy()


# ---------------------------------------------------------------- animation pane
class AnimationPane(Gtk.Window):
    """The Animation Pane: the slide's effects in order; pick one to change it, play from it."""
    def __init__(self, win):
        Gtk.Window.__init__(self, title="Animation Pane", transient_for=win)
        self.win = win
        self.set_default_size(320, 460)
        self.get_style_context().add_class("folio-pane")
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin=8)
        top = Gtk.Box(spacing=6)
        play = Gtk.Button(label="▶ Play All")
        play.connect("clicked", lambda *_: win.run("anim-preview"))
        top.pack_start(play, False, False, 0)
        for label, cmd in (("▲", "anim-earlier"), ("▼", "anim-later"), ("Remove", "anim-remove")):
            b = Gtk.Button(label=label)
            b.connect("clicked", lambda _b, c=cmd: win.run(c))
            top.pack_end(b, False, False, 0)
        box.pack_start(top, False, False, 0)
        self.store = Gtk.ListStore(int, str, str, str)
        self.view = Gtk.TreeView(model=self.store)
        for k, title in ((1, "#"), (2, "Effect"), (3, "Object")):
            self.view.append_column(Gtk.TreeViewColumn(title, Gtk.CellRendererText(), text=k))
        self.view.get_selection().connect("changed", self._picked)
        sw = Gtk.ScrolledWindow()
        sw.add(self.view)
        box.pack_start(sw, True, True, 0)
        self.add(box)
        self.connect("destroy", lambda *_: setattr(win, "anim_pane", None) or setattr(win, "anim_pick", None))
        self._quiet = False
        self.refresh()
        self.show_all()

    def refresh(self):
        w = self.win
        self._quiet = True
        self.store.clear()
        names = {s["id"]: s["name"] for s in w.canvas.shapes}
        n = 0
        for k, e in enumerate(w.deck.animations(w.current) if w.current is not None else []):
            if e["trigger"] == "click":
                n += 1
            mark = {"entr": "★", "exit": "☆", "emph": "✶"}.get(e["class"], "")
            num = str(n) if e["trigger"] == "click" else ""
            self.store.append([k, num, "%s %s" % (mark, e["name"]), names.get(e["spid"], "Object %d" % e["spid"])])
        if w.anim_pick is not None and w.anim_pick < len(self.store):
            self.view.get_selection().select_path(w.anim_pick)
        self._quiet = False

    def _picked(self, sel):
        if self._quiet:
            return
        model, it = sel.get_selected()
        if it is None:
            return
        self.win.anim_pick = model[it][0]
        e = self.win.deck.animations(self.win.current)[self.win.anim_pick]
        self.win.canvas.leave_text()
        self.win.canvas.sel = [e["spid"]]
        self.win.canvas.queue()
        self.win.sync_animation()


def animation_pane(win):
    if getattr(win, "anim_pane", None) is not None:
        win.anim_pane.destroy()
        win.anim_pane = None
        return
    win.anim_pane = AnimationPane(win)

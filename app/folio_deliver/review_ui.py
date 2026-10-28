"""Links, cropping, comments, Outline view and Notes Page view."""
import datetime

from gi.repository import Gdk, GLib, Gtk, Pango

TITLE_PH = ("title", "ctrTitle")
BODY_PH = ("body", "obj", "subTitle", None)
JUMPS = [("first", "First Slide"), ("last", "Last Slide"), ("next", "Next Slide"), ("prev", "Previous Slide")]


def author_name():
    n = GLib.get_real_name() or ""
    if not n or n == "Unknown":
        n = GLib.get_user_name() or "Author"
    return n


def initials(name):
    parts = [p for p in name.replace(".", " ").split() if p]
    return "".join(p[0].upper() for p in parts[:3]) or "?"


def describe_link(win, target):
    if target is None:
        return ""
    if target.startswith("slide:"):
        k = int(target[6:])
        return "Slide %d" % (k + 1)
    return dict(JUMPS).get(target, target)


def slide_title(deck, i):
    for _sid, ph, paras in deck.slide_text(i):
        if ph in TITLE_PH:
            return " ".join(p for p in paras if p).strip()
    return ""


def follow_link(win, target, goto):
    """Open a link: an address in the browser or mail program, a slide with goto(i)."""
    if not target:
        return
    n = win.deck.slide_count()
    if target.startswith("slide:"):
        goto(int(target[6:]))
    elif target in ("first", "last", "next", "prev"):
        cur = win.current or 0
        goto({"first": 0, "last": n - 1, "next": min(n - 1, cur + 1), "prev": max(0, cur - 1)}[target])
    elif target == "end":
        pass
    else:
        try:
            Gtk.show_uri_on_window(win, target, Gdk.CURRENT_TIME)
        except Exception as e:
            win.dialogs.message("This link can't be opened.\n\n%s" % e)


# ---------------------------------------------------------------- Insert Link dialog
def link_dialog(win, current=None, display=None):
    """PowerPoint's Insert Hyperlink: an address, a place in this presentation or an e-mail address.
    Returns (target, text to display) — target "" removes the link — or None."""
    d = Gtk.Dialog(title="Edit Link" if current else "Insert Link", transient_for=win, modal=True)
    d.get_style_context().add_class("folio-dialog")
    d.set_default_size(560, 380)
    if current:
        d.add_button("Remove Link", 3)
    d.add_button("Cancel", Gtk.ResponseType.CANCEL)
    d.add_button("OK", Gtk.ResponseType.OK)
    d.set_default_response(Gtk.ResponseType.OK)
    box = d.get_content_area()
    box.set_border_width(10)
    box.set_spacing(8)
    show = None
    if display is not None:
        row = Gtk.Box(spacing=8)
        row.pack_start(Gtk.Label(label="Text to display:"), False, False, 0)
        show = Gtk.Entry(text=display)
        row.pack_start(show, True, True, 0)
        box.pack_start(row, False, False, 0)
    body = Gtk.Box(spacing=8)
    side = Gtk.StackSidebar()
    stack = Gtk.Stack()
    side.set_stack(stack)
    body.pack_start(side, False, False, 0)
    body.pack_start(stack, True, True, 0)
    box.pack_start(body, True, True, 0)
    # web page or file
    web = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
    web.pack_start(Gtk.Label(label="Address:", xalign=0), False, False, 0)
    addr = Gtk.Entry()
    addr.set_activates_default(True)
    addr.set_placeholder_text("https://")
    web.pack_start(addr, False, False, 0)
    browse = Gtk.Button(label="Browse for File...")
    web.pack_start(browse, False, False, 0)

    def pick_file(*_):
        fc = Gtk.FileChooserNative(title="Link to File", transient_for=d, action=Gtk.FileChooserAction.OPEN)
        if fc.run() == Gtk.ResponseType.ACCEPT:
            addr.set_text(fc.get_uri())
    browse.connect("clicked", pick_file)
    stack.add_titled(web, "web", "Existing File or Web Page")
    # place in this document
    place = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
    place.pack_start(Gtk.Label(label="Select a place in this document:", xalign=0), False, False, 0)
    store = Gtk.ListStore(str, str)
    for key, label in JUMPS:
        store.append([key, label])
    for i in range(win.deck.slide_count()):
        store.append(["slide:%d" % i, "%d. %s" % (i + 1, slide_title(win.deck, i) or "Slide %d" % (i + 1))])
    tv = Gtk.TreeView(model=store, headers_visible=False)
    tv.append_column(Gtk.TreeViewColumn("", Gtk.CellRendererText(), text=1))
    sw = Gtk.ScrolledWindow()
    sw.set_min_content_height(200)
    sw.add(tv)
    place.pack_start(sw, True, True, 0)
    stack.add_titled(place, "place", "Place in This Document")
    # e-mail
    mail = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
    mail.pack_start(Gtk.Label(label="E-mail address:", xalign=0), False, False, 0)
    to = Gtk.Entry()
    mail.pack_start(to, False, False, 0)
    mail.pack_start(Gtk.Label(label="Subject:", xalign=0), False, False, 0)
    subj = Gtk.Entry()
    mail.pack_start(subj, False, False, 0)
    stack.add_titled(mail, "mail", "E-mail Address")
    d.show_all()
    if current:
        if current.startswith("slide:") or current in dict(JUMPS):
            stack.set_visible_child_name("place")
            for k, row in enumerate(store):
                if row[0] == current:
                    tv.get_selection().select_path(Gtk.TreePath(k))
        elif current.startswith("mailto:"):
            stack.set_visible_child_name("mail")
            a, _, q = current[7:].partition("?")
            to.set_text(a)
            subj.set_text(GLib.uri_unescape_string(q[8:], None) if q.startswith("subject=") else "")
        else:
            addr.set_text(current)
    r = d.run()
    which = stack.get_visible_child_name()
    target = None
    if r == 3:
        target = ""
    elif r == Gtk.ResponseType.OK:
        if which == "web":
            target = addr.get_text().strip()
            if target and "://" not in target and not target.startswith(("mailto:", "/")):
                target = "https://" + target
        elif which == "place":
            m, it = tv.get_selection().get_selected()
            target = m[it][0] if it else None
        else:
            a = to.get_text().strip()
            if a:
                target = "mailto:" + a + ("?subject=" + GLib.uri_escape_string(subj.get_text(), None, False) if subj.get_text() else "")
    text = show.get_text() if show is not None else None
    d.destroy()
    if target is None:
        return None
    return target, text


# ---------------------------------------------------------------- Comments pane
class CommentsPane(Gtk.Window):
    """The Comments pane: the slide's comments, a box for a new one, previous and next."""
    def __init__(self, win):
        Gtk.Window.__init__(self, title="Comments", transient_for=win)
        self.win = win
        self.set_default_size(330, 520)
        self.get_style_context().add_class("folio-pane")
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin=8)
        top = Gtk.Box(spacing=4)
        for label, cmd in (("New", "new-comment"), ("◀ Previous", "prev-comment"), ("Next ▶", "next-comment")):
            b = Gtk.Button(label=label)
            b.connect("clicked", lambda _b, c=cmd: win.run(c))
            top.pack_start(b, False, False, 0)
        box.pack_start(top, False, False, 0)
        self.list = Gtk.ListBox()
        self.list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        sw = Gtk.ScrolledWindow()
        sw.add(self.list)
        box.pack_start(sw, True, True, 0)
        self.entry = Gtk.TextView()
        self.entry.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self.entry.set_size_request(-1, 64)
        self.entry.get_style_context().add_class("folio-comment-entry")
        frame = Gtk.Frame()
        frame.add(self.entry)
        box.pack_start(frame, False, False, 0)
        post = Gtk.Button(label="Post")
        post.connect("clicked", lambda *_: self.post())
        row = Gtk.Box()
        row.pack_end(post, False, False, 0)
        box.pack_start(row, False, False, 0)
        self.add(box)
        self.connect("destroy", lambda *_: setattr(win, "comments_pane", None) or win.canvas.queue())
        self.refresh()
        self.show_all()

    def post(self):
        b = self.entry.get_buffer()
        t = b.get_text(b.get_start_iter(), b.get_end_iter(), False).strip()
        if t:
            self.win.add_comment(t)
            b.set_text("")

    def refresh(self, pick=None):
        w = self.win
        for c in self.list.get_children():
            self.list.remove(c)
        cs = w.deck.comments(w.current) if w.current is not None else []
        if not cs:
            lab = Gtk.Label(label="There are no comments on this slide.", xalign=0, margin=8)
            lab.get_style_context().add_class("dim-label")
            self.list.add(lab)
        for idx, author, ini, dt, text, _x, _y in cs:
            row = Gtk.ListBoxRow()
            row.idx = idx
            v = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, margin=6)
            head = Gtk.Box(spacing=6)
            badge = Gtk.Label(label=ini)
            badge.get_style_context().add_class("folio-comment-badge")
            head.pack_start(badge, False, False, 0)
            name = Gtk.Label(xalign=0)
            name.set_markup("<b>%s</b>" % GLib.markup_escape_text(author))
            head.pack_start(name, False, False, 0)
            when = Gtk.Label(label=nice_date(dt), xalign=1)
            when.get_style_context().add_class("dim-label")
            head.pack_end(when, False, False, 0)
            v.pack_start(head, False, False, 0)
            body = Gtk.Label(label=text, xalign=0, wrap=True)
            body.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
            body.set_selectable(True)
            v.pack_start(body, False, False, 0)
            acts = Gtk.Box(spacing=4)
            for label, fn in (("Edit", self.edit), ("Delete", self.delete)):
                b = Gtk.Button(label=label)
                b.get_style_context().add_class("flat")
                b.connect("clicked", lambda _b, k=idx, f=fn: f(k))
                acts.pack_end(b, False, False, 0)
            v.pack_start(acts, False, False, 0)
            row.add(v)
            self.list.add(row)
            if pick == idx:
                self.list.select_row(row)
        self.list.show_all()

    def picked(self):
        r = self.list.get_selected_row()
        return getattr(r, "idx", None) if r is not None else None

    def edit(self, idx):
        w = self.win
        cur = [c for c in w.deck.comments(w.current) if c[0] == idx]
        t = w.dialogs.ask_text("Edit Comment", "Comment:", cur[0][4] if cur else "")
        if t is not None:
            w.deck.edit_comment(w.current, idx, t)
            w.comments_changed(idx)

    def delete(self, idx):
        w = self.win
        w.deck.delete_comment(w.current, idx)
        w.comments_changed()


def nice_date(dt):
    try:
        d = datetime.datetime.fromisoformat(dt[:19])
        return d.strftime("%d %b %Y %H:%M")
    except ValueError:
        return dt[:10]


# ---------------------------------------------------------------- Outline view
class OutlineView(Gtk.ScrolledWindow):
    """Every slide's title and body text as one outline: a line without indent is a slide title,
    indented lines (Tab, Shift+Tab) are its bullet levels; Enter on a title starts a new slide."""
    GUTTER = 46

    def __init__(self, win):
        Gtk.ScrolledWindow.__init__(self)
        self.win = win
        self.view = Gtk.TextView()
        self.view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self.view.set_left_margin(10)
        self.view.set_top_margin(12)
        self.view.set_border_window_size(Gtk.TextWindowType.LEFT, self.GUTTER)
        self.view.get_style_context().add_class("folio-outline")
        tabs = Pango.TabArray.new(10, True)
        for k in range(10):
            tabs.set_tab(k, Pango.TabAlign.LEFT, 28 * (k + 1))
        self.view.set_tabs(tabs)
        self.buf = self.view.get_buffer()
        self.buf.create_tag("title", weight=Pango.Weight.BOLD, scale=1.25, pixels_above_lines=10)
        self.view.connect("key-press-event", self.on_key)
        self.view.connect_after("draw", self.on_draw)
        self.buf.connect("changed", self._changed)
        self.add(self.view)
        self.marks = []
        self.dirty = False
        self._quiet = False
        self._timer = None
        self.buf.connect("mark-set", lambda _b, _it, m: self._moved() if m.get_name() == "insert" else None)

    # the slide's texts
    @staticmethod
    def parts_of(deck, i):
        title = body = None
        for sid, ph, paras in deck.slide_text(i):
            if ph in TITLE_PH and title is None:
                title = (sid, paras)
            elif ph in BODY_PH and ph is not None and body is None:
                body = (sid, paras)
        return title, body

    def load(self):
        deck = self.win.deck
        self._quiet = True
        self.buf.set_text("")
        for m in self.marks:
            if not m.get_deleted():
                self.buf.delete_mark(m)
        self.marks = []
        parts = deck.slide_parts()
        for i in range(deck.slide_count()):
            title, body = self.parts_of(deck, i)
            it = self.buf.get_end_iter()
            if i:
                self.buf.insert(it, "\n")
            it = self.buf.get_end_iter()
            m = self.buf.create_mark("slide:" + parts[i], it, True)
            self.marks.append(m)
            self.buf.insert(it, " ".join(p for p in (title[1] if title else []) if p))
            if body and any(body[1]):
                for k, p in enumerate(body[1]):
                    lvl = deck.para_props(i, body[0], k).get("lvl", 0)
                    self.buf.insert(self.buf.get_end_iter(), "\n" + "\t" * (lvl + 1) + p)
        self._retag()
        self._quiet = False
        self.dirty = False
        self.view.queue_draw()

    def _changed(self, *_):
        if not self._quiet:
            self.dirty = True
            self._retag()
            if self._timer:
                GLib.source_remove(self._timer)
            self._timer = GLib.timeout_add(900, self._apply_later)

    def _apply_later(self):
        self._timer = None
        if self.win.view == "outline":
            self.apply()
        return False

    def _moved(self, *_):
        """The cursor's slide shows on the right."""
        if self._quiet:
            return
        b = self.buf
        ln = b.get_iter_at_mark(b.get_insert()).get_line()
        part = None
        for k in range(ln, -1, -1):
            s = b.get_iter_at_line(k)
            if s.get_char() != "\t":
                part = self._part_at(k)
                break
        parts = self.win.deck.slide_parts()
        if part in parts and parts.index(part) != self.win.current:
            self.win.go_slide(parts.index(part))

    def _part_at(self, ln):
        for m in self.marks:
            if not m.get_deleted():
                it = self.buf.get_iter_at_mark(m)
                if it.starts_line() and it.get_line() == ln:
                    return m.get_name()[6:]
        return None

    def _retag(self):
        b = self.buf
        b.remove_tag_by_name("title", b.get_start_iter(), b.get_end_iter())
        for ln in range(b.get_line_count()):
            s = b.get_iter_at_line(ln)
            if s.get_char() != "\t" and not s.ends_line():
                e = s.copy()
                e.forward_to_line_end()
                b.apply_tag_by_name("title", s, e)

    def lines(self):
        b = self.buf
        return b.get_text(b.get_start_iter(), b.get_end_iter(), False).split("\n")

    def on_key(self, view, ev):
        name = Gdk.keyval_name(ev.keyval)
        b = self.buf
        it = b.get_iter_at_mark(b.get_insert())
        start = b.get_iter_at_line(it.get_line())
        shift = bool(ev.state & Gdk.ModifierType.SHIFT_MASK)
        if name in ("Tab", "ISO_Left_Tab"):
            if shift or name == "ISO_Left_Tab":
                if start.get_char() == "\t":
                    e = start.copy()
                    e.forward_char()
                    b.delete(start, e)
            else:
                b.insert(start, "\t")
            return True
        if name in ("Return", "KP_Enter") and not shift:
            # a new line at the same level
            tabs = 0
            k = start.copy()
            while k.get_char() == "\t":
                tabs += 1
                k.forward_char()
            b.insert_at_cursor("\n" + "\t" * tabs)
            self.view.scroll_mark_onscreen(b.get_insert())
            return True
        return False

    def on_draw(self, view, cr):
        lw = view.get_window(Gtk.TextWindowType.LEFT)
        if lw is None or not Gtk.cairo_should_draw_window(cr, lw):
            return False
        cr.save()
        Gtk.cairo_transform_to_window(cr, view, lw)
        cr.set_source_rgb(0.42, 0.42, 0.42)
        cr.select_font_face("Sans")
        cr.set_font_size(11)
        b = self.buf
        n = 0
        for ln in range(b.get_line_count()):
            s = b.get_iter_at_line(ln)
            if s.get_char() == "\t":
                continue
            n += 1
            y, h = view.get_line_yrange(s)
            _x, wy = view.buffer_to_window_coords(Gtk.TextWindowType.LEFT, 0, y)
            cr.move_to(6, wy + h * 0.7)
            cr.show_text(str(n))
            # a small slide icon
            cr.rectangle(24, wy + h * 0.25, 16, 11)
            cr.set_line_width(1)
            cr.stroke()
        cr.restore()
        return False

    def parse(self):
        """[(slide part or None, title, [(level, text)])] from the outline."""
        b = self.buf
        at_line = {}
        for m in self.marks:
            if m.get_deleted():
                continue
            it = b.get_iter_at_mark(m)
            if it.starts_line():
                at_line.setdefault(it.get_line(), []).append(m.get_name()[6:])
        out = []
        for ln, text in enumerate(self.lines()):
            if not text.startswith("\t"):
                own = at_line.get(ln, [])
                out.append([own[0] if own else None, text, [], ln])
            else:
                lvl = len(text) - len(text.lstrip("\t"))
                if not out:
                    out.append([None, "", [], 0])
                out[-1][2].append((min(lvl, 9) - 1, text.lstrip("\t")))
        return out

    def apply(self):
        """Write the outline back to the slides."""
        if not self.dirty:
            return
        self.dirty = False
        w = self.win
        deck = w.deck
        items = self.parse()
        keep = [it[0] for it in items if it[0]]
        # slides whose title line went away
        gone = [i for i, p in enumerate(deck.slide_parts()) if p not in keep]
        if gone:
            deck.delete_slides(gone)
        layout = w._layout_for_new()
        prev = -1
        for part, title, body, ln in items:
            parts = deck.slide_parts()
            if part is None or part not in parts:
                i = deck.new_slide(prev if prev >= 0 else None, layout)
                # the new title line stands for the new slide now
                m = self.buf.create_mark("slide:" + deck.slide_parts()[i], self.buf.get_iter_at_line(ln), True)
                self.marks.append(m)
            else:
                i = parts.index(part)
            prev = i
            t, bd = self.parts_of(deck, i)
            if t is not None and " ".join(p for p in t[1] if p) != title:
                deck.set_text(i, t[0], title)
            if bd is not None:
                now = [(deck.para_props(i, bd[0], k).get("lvl", 0), p) for k, p in enumerate(bd[1])]
                want = body or [(0, "")]
                if now != want and not (not body and all(not p for _l, p in now)):
                    deck.set_text(i, bd[0], "\n".join(p for _l, p in want))
                    for k, (lvl, _p) in enumerate(want):
                        if lvl:
                            deck.format_paras(i, bd[0], k, k, "lvl", str(lvl))
        cur = w.current
        w.changed(structure=True, all_slides=True)
        self.view.queue_draw()
        if cur is not None and cur < deck.slide_count():
            w.go_slide(cur)


# ---------------------------------------------------------------- the commands
class ReviewCommands:
    # ------------------------------------------------------------ links
    def _link_context(self):
        """What a link would go on: ("text", tid, a, b) for selected text, ("caret", tid, pos),
        ("shape", id) or None."""
        c = self.canvas
        if c.edit is not None:
            if c.edit.has_selection():
                a, b = c.edit.range()
                return ("text", c.edit.id, a, b)
            return ("caret", c.edit.id, c.edit.caret)
        if len(c.sel) == 1:
            return ("shape", c.sel[0])
        return None

    def current_link(self):
        ctx = self._link_context()
        if ctx is None:
            return None
        if ctx[0] == "shape":
            return self.deck.shape_link(self.current, ctx[1])
        pos = ctx[2]
        return self.deck.link_at(self.current, ctx[1], pos[0], max(0, pos[1] - (0 if ctx[0] == "text" else 1)))

    def act_insert_link(self):
        ctx = self._link_context()
        if ctx is None:
            self.dialogs.info("Select some text or an object to link first.")
            return
        cur = self.current_link()
        display = None
        if ctx[0] == "caret" and not cur:
            display = ""
        elif ctx[0] == "text":
            display = self.canvas.selected_text()
        r = link_dialog(self, cur, display)
        if r is None:
            return
        self.apply_link(r[0], r[1])

    def _link_word_range(self, tid, pos):
        """The run of linked text around pos (for editing a link with the caret in it)."""
        p, off = pos
        n = len(self.deck.paragraphs(self.current, tid)[p])
        tgt = self.deck.link_at(self.current, tid, p, max(0, off - 1))
        a = max(0, off - 1)
        while a > 0 and self.deck.link_at(self.current, tid, p, a - 1) == tgt:
            a -= 1
        b = off
        while b < n and self.deck.link_at(self.current, tid, p, b) == tgt:
            b += 1
        return (p, a), (p, b)

    def apply_link(self, target, display=None):
        """Link the selection (text or object) to target ("" removes the link)."""
        ctx = self._link_context()
        if ctx is None:
            return
        c = self.canvas
        if ctx[0] == "shape":
            self.deck.set_shape_link(self.current, ctx[1], target)
        elif ctx[0] == "text":
            tid, a, b = ctx[1], ctx[2], ctx[3]
            if display is not None and display != c.selected_text() and display:
                c.type_text(display)
                b = c.edit.caret
                a = (b[0], b[1] - len(display))
            self.deck.set_link(self.current, tid, a, b, target)
        else:
            tid, pos = ctx[1], ctx[2]
            cur = self.deck.link_at(self.current, tid, pos[0], max(0, pos[1] - 1))
            if cur:
                a, b = self._link_word_range(tid, pos)
                self.deck.set_link(self.current, tid, a, b, target)
            elif target:
                text = display or describe_link(self, target)
                c.type_text(text)
                b = c.edit.caret
                self.deck.set_link(self.current, tid, (b[0], b[1] - len(text)), b, target)
        self.changed(slide=True)

    def act_remove_link(self):
        self.apply_link("")

    def act_open_link(self):
        follow_link(self, self.current_link(), self.go_slide)

    def act_copy_link(self):
        t = self.current_link()
        if t:
            Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD).set_text(t, -1)

    def link_under(self, s, sx, sy):
        """The link at slide point (sx, sy) on shape s, if any."""
        t = self.deck.shape_link(self.current, s["id"])
        if t:
            return t
        if s["has_text"]:
            pos = self.deck.hit(self.current, s["id"], sx, sy)
            return self.deck.link_at(self.current, s["id"], pos[0], pos[1])
        return None

    # ------------------------------------------------------------ crop
    def act_crop(self):
        c = self.canvas
        if c.crop is not None:
            c.finish_crop()
            return
        pics = [c.shape(s) for s in c.sel]
        if len(pics) != 1 or pics[0] is None or pics[0]["kind"] != "pic":
            self.dialogs.info("Select a picture to crop.")
            return
        c.start_crop(pics[0]["id"])

    def act_crop_reset(self):
        c = self.canvas
        if len(c.sel) != 1:
            return
        s = c.shape(c.sel[0])
        cr = self.deck.crop(self.current, s["id"])
        if not cr:
            return
        l, t, r, b = cr
        fw, fh = s["w"] / max(0.01, 1 - l - r), s["h"] / max(0.01, 1 - t - b)
        self.deck.set_crop(self.current, s["id"], 0, 0, 0, 0, s["x"] - l * fw, s["y"] - t * fh, fw, fh)
        self.changed(slide=True)

    def act_crop_aspect(self, v):
        """Crop to an aspect ratio "w:h", centred."""
        c = self.canvas
        if len(c.sel) != 1:
            return
        s = c.shape(c.sel[0])
        cr = self.deck.crop(self.current, s["id"])
        if cr is None:
            return
        aw, ah = (float(x) for x in v.split(":"))
        l, t, r, b = cr
        fx, fy = s["x"] - l * s["w"] / max(0.01, 1 - l - r), s["y"] - t * s["h"] / max(0.01, 1 - t - b)
        fw, fh = s["w"] / max(0.01, 1 - l - r), s["h"] / max(0.01, 1 - t - b)
        if fw / fh > aw / ah:
            w, h = fh * aw / ah, fh
        else:
            w, h = fw, fw * ah / aw
        x, y = fx + (fw - w) / 2, fy + (fh - h) / 2
        self.deck.set_crop(self.current, s["id"], (x - fx) / fw, (y - fy) / fh, (fx + fw - x - w) / fw, (fy + fh - y - h) / fh,
                           x, y, w, h)
        self.changed(slide=True)

    # ------------------------------------------------------------ comments
    def add_comment(self, text, x=None, y=None):
        if self.current is None:
            return None
        c = self.canvas
        if x is None:
            if c.sel and c.shape(c.sel[0]):
                s = c.shape(c.sel[0])
                x, y = s["x"] + s["w"], s["y"]
            else:
                n = len(self.deck.comments(self.current))
                x, y = 10.0, 10.0 + 26 * n
        name = author_name()
        k = self.deck.add_comment(self.current, text, name, initials(name), x, y)
        self.comments_changed(k)
        return k

    def comments_changed(self, pick=None):
        self.changed(slide=True)
        p = getattr(self, "comments_pane", None)
        if p is not None:
            p.refresh(pick)

    def act_new_comment(self):
        p = getattr(self, "comments_pane", None)
        if p is None:
            self.comments_pane = p = CommentsPane(self)
        p.present()
        p.entry.grab_focus()

    def act_show_comments(self):
        p = getattr(self, "comments_pane", None)
        if p is not None:
            p.destroy()
            self.comments_pane = None
        else:
            self.comments_pane = CommentsPane(self)
        self.canvas.queue()

    def act_delete_comment(self):
        p = getattr(self, "comments_pane", None)
        idx = p.picked() if p is not None else None
        cs = self.deck.comments(self.current) if self.current is not None else []
        if idx is None and cs:
            idx = cs[-1][0]
        if idx is not None:
            self.deck.delete_comment(self.current, idx)
            self.comments_changed()

    def act_delete_comments_slide(self):
        if self.current is not None:
            self.deck.delete_comment(self.current, None)
            self.comments_changed()

    def act_delete_comments_all(self):
        for i in range(self.deck.slide_count()):
            if self.deck.comments(i):
                self.deck.delete_comment(i, None)
        self.comments_changed()

    def _comment_step(self, step):
        n = self.deck.slide_count()
        if n == 0:
            return
        p = getattr(self, "comments_pane", None)
        cur = self.current or 0
        cs = self.deck.comments(cur)
        pick = p.picked() if p is not None else None
        ids = [c[0] for c in cs]
        if pick in ids:
            k = ids.index(pick) + step
            if 0 <= k < len(ids):
                self._show_comment(cur, ids[k])
                return
        for j in range(1, n + 1):
            i = (cur + step * j) % n
            cs = self.deck.comments(i)
            if cs:
                self._show_comment(i, cs[0 if step > 0 else -1][0])
                return
        self.dialogs.info("There are no other comments in this presentation.")

    def _show_comment(self, i, idx):
        self.go_slide(i)
        if getattr(self, "comments_pane", None) is None:
            self.comments_pane = CommentsPane(self)
        self.comments_pane.refresh(idx)

    def act_next_comment(self):
        self._comment_step(1)

    def act_prev_comment(self):
        self._comment_step(-1)

    def comment_markers(self):
        """[(idx, initials, x, y)] for the comment markers on the current slide."""
        if self.current is None:
            return []
        return [(c[0], c[2], c[5], c[6]) for c in self.deck.comments(self.current)]

    # ------------------------------------------------------------ outline and notes page
    def build_outline_view(self):
        # Outline view takes the slide pane's place in Normal view
        self.outline = OutlineView(self)

    def act_view_outline(self):
        self.set_view("outline")

    def build_notes_page(self):
        """Notes Page view: the page with the slide on top and its notes below (the notes are
        the same as in the notes pane)."""
        sw = Gtk.ScrolledWindow()
        sw.get_style_context().add_class("folio-canvas")
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        page.get_style_context().add_class("folio-notes-page")
        page.set_halign(Gtk.Align.CENTER)
        page.set_valign(Gtk.Align.START)
        page.set_margin_top(24)
        page.set_margin_bottom(24)
        page.set_size_request(612, 792)
        pic = Gtk.DrawingArea()
        pic.set_size_request(612, 360)
        pic.connect("draw", self._draw_notes_slide)
        page.pack_start(pic, False, False, 0)
        tv = Gtk.TextView(buffer=self.notes.get_buffer())
        tv.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        tv.set_left_margin(56)
        tv.set_right_margin(56)
        tv.get_style_context().add_class("folio-notes-page-text")
        tv.connect("focus-out-event", lambda *_: (self._save_notes(), False)[1])
        page.pack_start(tv, True, True, 0)
        sw.add(page)
        self.notes_page_pic = pic
        self.notes_page_text = tv
        self.stack.add_named(sw, "notespage")

    def _draw_notes_slide(self, area, cr):
        if self.current is None:
            return
        from .core import surface_from
        w = area.get_allocated_width()
        h = area.get_allocated_height()
        sw, sh = self.deck.size()
        scale = min((w - 112) / sw, (h - 36) / sh)
        rw, rh, stride, data, _ = self.deck.render(self.current, scale, False, None)
        surf = surface_from(rw, rh, stride, data)
        x, y = (w - rw) / 2, 36
        cr.set_source_surface(surf, x, y)
        cr.paint()
        cr.set_source_rgb(0, 0, 0)
        cr.set_line_width(1)
        cr.rectangle(x - 0.5, y - 0.5, rw + 1, rh + 1)
        cr.stroke()

    def act_view_notes_page(self):
        self.set_view("notespage")


# ---------------------------------------------------------------- reuse slides, pictures, Set Up Show
def pick_file(win, title, patterns, name):
    d = Gtk.FileChooserNative(title=title, transient_for=win, action=Gtk.FileChooserAction.OPEN)
    f = Gtk.FileFilter()
    f.set_name(name)
    for p in patterns:
        f.add_pattern(p)
        f.add_pattern(p.upper())
    d.add_filter(f)
    r = d.run()
    p = d.get_filename() if r == Gtk.ResponseType.ACCEPT else None
    d.destroy()
    return p


class ReusePane(Gtk.Window):
    """Reuse Slides: another presentation's slides; a click inserts one after the current slide,
    in this presentation's theme."""
    def __init__(self, win, path):
        from .core import Presentation, surface_from
        Gtk.Window.__init__(self, title="Reuse Slides", transient_for=win)
        self.win = win
        self.path = path
        self.set_default_size(300, 600)
        self.get_style_context().add_class("folio-pane")
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin=8)
        import os
        box.pack_start(Gtk.Label(label=os.path.basename(path), xalign=0), False, False, 0)
        flow = Gtk.FlowBox()
        flow.set_max_children_per_line(1)
        flow.set_selection_mode(Gtk.SelectionMode.NONE)
        src = Presentation.open(path)
        sw_, sh_ = src.size()
        self.count = src.slide_count()
        for i in range(self.count):
            scale = 240.0 / sw_
            w, h, stride, data, _ = src.render(i, scale, False)
            surf = surface_from(w, h, stride, data)
            area = Gtk.DrawingArea()
            area.set_size_request(w, h)
            area.connect("draw", lambda _a, cr, s=surf: (cr.set_source_surface(s, 0, 0), cr.paint()))
            b = Gtk.Button()
            v = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            v.pack_start(area, False, False, 0)
            v.pack_start(Gtk.Label(label="%d. %s" % (i + 1, slide_title(src, i) or "Slide %d" % (i + 1)), xalign=0,
                                   ellipsize=Pango.EllipsizeMode.END), False, False, 0)
            b.add(v)
            b.set_tooltip_text("Insert this slide")
            b.connect("clicked", lambda _b, k=i: self.insert([k]))
            flow.add(b)
        sw = Gtk.ScrolledWindow()
        sw.add(flow)
        box.pack_start(sw, True, True, 0)
        allb = Gtk.Button(label="Insert All")
        allb.connect("clicked", lambda *_: self.insert(list(range(self.count))))
        box.pack_start(allb, False, False, 0)
        self.add(box)
        self.show_all()

    def insert(self, which):
        w = self.win
        after = w.current if w.deck.slide_count() else None
        i = w.deck.reuse_slides(self.path, which, after, w._layout_for_new())
        w.changed(structure=True)
        w.go_slide(i + len(which) - 1)


def setup_show_dialog(win):
    """Set Up Show: show type, which slides, options, advance, pen colour. Returns the settings or None."""
    deck = win.deck
    kind, looped, no_anim, rfrom, rto, timings, pen = deck.show_settings()
    d = Gtk.Dialog(title="Set Up Show", transient_for=win, modal=True)
    d.get_style_context().add_class("folio-dialog")
    d.add_button("Cancel", Gtk.ResponseType.CANCEL)
    d.add_button("OK", Gtk.ResponseType.OK)
    d.set_default_response(Gtk.ResponseType.OK)
    g = Gtk.Grid(column_spacing=24, row_spacing=6, margin=12)
    d.get_content_area().add(g)

    def head(t, col, row):
        lab = Gtk.Label(xalign=0)
        lab.set_markup("<b>%s</b>" % t)
        g.attach(lab, col, row, 1, 1)
    head("Show type", 0, 0)
    r1 = Gtk.RadioButton.new_with_label(None, "Presented by a speaker (full screen)")
    r2 = Gtk.RadioButton.new_with_label_from_widget(r1, "Browsed by an individual (window)")
    r3 = Gtk.RadioButton.new_with_label_from_widget(r1, "Browsed at a kiosk (full screen)")
    {"presented": r1, "browsed": r2, "kiosk": r3}.get(kind, r1).set_active(True)
    for k, r in enumerate((r1, r2, r3)):
        g.attach(r, 0, 1 + k, 1, 1)
    head("Show options", 0, 4)
    c_loop = Gtk.CheckButton(label="Loop continuously until 'Esc'", active=looped)
    c_anim = Gtk.CheckButton(label="Show without animation", active=no_anim)
    g.attach(c_loop, 0, 5, 1, 1)
    g.attach(c_anim, 0, 6, 1, 1)
    pr = Gtk.Box(spacing=6)
    pr.pack_start(Gtk.Label(label="Pen color:"), False, False, 0)
    cb = Gtk.ColorButton()
    v = int(pen, 16) if pen else 0xFF0000
    from gi.repository import Gdk as _G
    cb.set_rgba(_G.RGBA((v >> 16 & 255) / 255.0, (v >> 8 & 255) / 255.0, (v & 255) / 255.0, 1))
    pr.pack_start(cb, False, False, 0)
    g.attach(pr, 0, 7, 1, 1)
    head("Show slides", 1, 0)
    n = deck.slide_count()
    s_all = Gtk.RadioButton.new_with_label(None, "All")
    s_rng = Gtk.RadioButton.new_with_label_from_widget(s_all, "From:")
    fr = Gtk.SpinButton.new_with_range(1, max(1, n), 1)
    to = Gtk.SpinButton.new_with_range(1, max(1, n), 1)
    fr.set_value(rfrom or 1)
    to.set_value(rto or n)
    (s_rng if (rfrom or rto) else s_all).set_active(True)
    g.attach(s_all, 1, 1, 1, 1)
    rb = Gtk.Box(spacing=6)
    rb.pack_start(s_rng, False, False, 0)
    rb.pack_start(fr, False, False, 0)
    rb.pack_start(Gtk.Label(label="To:"), False, False, 0)
    rb.pack_start(to, False, False, 0)
    g.attach(rb, 1, 2, 1, 1)
    head("Advance slides", 1, 4)
    a_man = Gtk.RadioButton.new_with_label(None, "Manually")
    a_tim = Gtk.RadioButton.new_with_label_from_widget(a_man, "Using timings, if present")
    (a_tim if timings else a_man).set_active(True)
    g.attach(a_man, 1, 5, 1, 1)
    g.attach(a_tim, 1, 6, 1, 1)
    d.show_all()
    r = d.run()
    out = None
    if r == Gtk.ResponseType.OK:
        c = cb.get_rgba()
        pen = "%02X%02X%02X" % (int(c.red * 255), int(c.green * 255), int(c.blue * 255))
        kind = "kiosk" if r3.get_active() else "browsed" if r2.get_active() else "presented"
        a, b = (int(fr.get_value()), int(to.get_value())) if s_rng.get_active() else (0, 0)
        out = (kind, c_loop.get_active(), c_anim.get_active(), min(a, b) if a else 0, max(a, b) if b else 0,
               a_tim.get_active(), pen)
    d.destroy()
    return out


class PictureCommands:
    def act_reuse_slides(self):
        p = pick_file(self, "Reuse Slides", ("*.pptx", "*.pptm", "*.potx", "*.ppsx"), "Presentations")
        if p:
            self.open_reuse(p)

    def open_reuse(self, path):
        try:
            self.reuse_pane = ReusePane(self, path)
        except Exception as e:
            self.dialogs.message("These slides can't be read.\n\n%s" % e)
            return None
        return self.reuse_pane

    def _one_picture(self):
        c = self.canvas
        s = c.shape(c.sel[0]) if len(c.sel) == 1 else None
        return s if s is not None and s["kind"] == "pic" else None

    def act_change_picture(self):
        s = self._one_picture()
        if s is None:
            self.dialogs.info("Select a picture to change.")
            return
        p = pick_file(self, "Change Picture", ("*.png", "*.jpg", "*.jpeg", "*.gif", "*.bmp", "*.tif", "*.tiff"), "All Pictures")
        if p:
            import os
            with open(p, "rb") as fh:
                self.change_picture(s, fh.read(), os.path.splitext(p)[1][1:])

    def change_picture(self, s, data, ext):
        """The new picture fits the old one's box, keeping its own proportions."""
        from .core import Presentation
        size = Presentation.picture_size(data)
        if size is None:
            self.dialogs.message("This picture can't be read.")
            return
        self.deck.replace_picture(self.current, s["id"], data, ext)
        k = min(s["w"] / size[0], s["h"] / size[1])
        w, h = size[0] * k, size[1] * k
        self.deck.set_boxes(self.current, [(s["id"], s["x"] + (s["w"] - w) / 2, s["y"] + (s["h"] - h) / 2, w, h, None)], "Change Picture")
        self.changed(slide=True)

    def act_picture_reset(self):
        if self._one_picture() is not None:
            self.act_crop_reset()

    def act_picture_reset_size(self):
        s = self._one_picture()
        if s is None:
            return
        from .core import Presentation
        size = Presentation.picture_size(self.deck.picture_data(self.current, s["id"]) or b"")
        if size is None:
            return
        w, h = size[0] * 0.75, size[1] * 0.75
        self.deck.set_crop(self.current, s["id"], 0, 0, 0, 0, s["x"], s["y"], w, h)
        self.changed(slide=True)

    def act_setup_show(self):
        r = setup_show_dialog(self)
        if r is not None:
            self.deck.set_show_settings(*r)
            self.update_title()

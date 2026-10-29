"""Review > Compare: the differences between this presentation and another version of it, slide
by slide, in a Revisions pane where each one is accepted or rejected (P3-07)."""
import re

from gi.repository import Gtk

from .core import Presentation


def _ids(deck):
    from .b3_ui import _pres
    return _pres(deck)[0]


def _signature(deck, i):
    """What a slide says and holds, for telling changed slides apart."""
    text = []
    for _sid, ph, paras in deck.slide_text(i):
        text.append((ph or "", tuple(p.strip() for p in paras)))
    shapes = []
    for s in deck.shapes(i):
        shapes.append((s["kind"], s.get("geom") or "", round(s["x"]), round(s["y"]), round(s["w"]), round(s["h"])))
    try:
        xml = deck.shapes_xml(i, [s["id"] for s in deck.shapes(i)])
        xml = re.sub(r'\b(id|r:id|r:embed|r:link)="[^"]*"', "", xml)
    except Exception:
        xml = ""
    return tuple(text), tuple(shapes), xml, deck.transition(i)[:2], deck.notes(i) if hasattr(deck, "notes") else ""


def _title(deck, i):
    for _sid, ph, paras in deck.slide_text(i):
        if ph in ("title", "ctrTitle") and paras and paras[0].strip():
            return paras[0].strip()
    return "Slide %d" % (i + 1)


def _describe(a, b):
    """What changed on a slide, in a few words."""
    what = []
    if a[0] != b[0]:
        what.append("text")
    if [(k, g) for k, g, *_r in a[1]] != [(k, g) for k, g, *_r in b[1]]:
        what.append("objects inserted or deleted")
    elif a[1] != b[1]:
        what.append("objects moved or resized")
    elif a[2] != b[2] and a[0] == b[0]:
        what.append("formatting")
    if a[3] != b[3]:
        what.append("transition")
    if a[4] != b[4]:
        what.append("notes")
    return ", ".join(what) or "changes"


def compare(deck, path):
    """[{kind: "changed" | "inserted" | "deleted", mine, theirs, title, detail}] in slide order."""
    other = Presentation.open(path)
    mine_ids, their_ids = _ids(deck), _ids(other)
    by_id_theirs = {v: k for k, v in their_ids.items()}
    n, m = deck.slide_count(), other.slide_count()
    pairs = {}
    # slides keep their ids between versions; otherwise match by title
    for i in range(n):
        sid = mine_ids.get(i)
        if sid is not None and sid in by_id_theirs:
            pairs[i] = by_id_theirs[sid]
    used = set(pairs.values())
    their_titles = {}
    for j in range(m):
        if j not in used:
            their_titles.setdefault(_title(other, j), []).append(j)
    for i in range(n):
        if i in pairs:
            continue
        cand = their_titles.get(_title(deck, i))
        if cand:
            pairs[i] = cand.pop(0)
            used.add(pairs[i])
    out = []
    for i in range(n):
        if i not in pairs:
            out.append({"kind": "deleted", "mine": i, "theirs": None, "title": _title(deck, i),
                        "detail": "Slide deleted in the other version"})
            continue
        j = pairs[i]
        a, b = _signature(deck, i), _signature(other, j)
        if a != b:
            out.append({"kind": "changed", "mine": i, "theirs": j, "title": _title(deck, i), "detail": _describe(a, b)})
    for j in range(m):
        if j not in used:
            # it goes after the slide before it in the other version, when that one is here
            before = [i for i, jj in pairs.items() if jj < j]
            after = max(before) if before else None
            out.append({"kind": "inserted", "mine": after, "theirs": j, "title": _title(other, j),
                        "detail": "Slide inserted in the other version"})
    out.sort(key=lambda c: ((c["mine"] if c["mine"] is not None else -1), c["kind"] != "deleted"))
    return out


def accept(win, path, ch):
    """Take one change from the other version into this one (one undo step)."""
    deck = win.deck
    fallback = win._layout_for_new()
    if ch["kind"] == "deleted":
        deck.delete_slides([ch["mine"]])
    elif ch["kind"] == "inserted":
        deck.reuse_slides(path, [ch["theirs"]], ch["mine"], fallback)
    else:
        deck.reuse_slides(path, [ch["theirs"]], ch["mine"], fallback)
        deck.delete_slides([ch["mine"]])
        deck.merge_undo(2, "Accept Change")
    win.changed(structure=True)


class RevisionsPane(Gtk.Window):
    """The Revisions pane: every difference, with Accept and Reject, Previous and Next."""
    def __init__(self, win, path, changes):
        Gtk.Window.__init__(self, title="Revisions", transient_for=win)
        self.win, self.path = win, path
        self.set_default_size(340, 460)
        self.get_style_context().add_class("folio-pane")
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin=8)
        self.add(box)
        bar = Gtk.Box(spacing=4)
        for label, fn in (("Accept", self.on_accept), ("Reject", self.on_reject), ("Previous", self.on_prev), ("Next", self.on_next)):
            b = Gtk.Button(label=label)
            b.connect("clicked", lambda *_a, f=fn: f())
            bar.pack_start(b, False, False, 0)
        box.pack_start(bar, False, False, 0)
        bar2 = Gtk.Box(spacing=4)
        for label, fn in (("Accept All Changes", self.on_accept_all), ("Reject All Changes", self.on_reject_all),
                          ("End Review", self.destroy)):
            b = Gtk.Button(label=label)
            b.connect("clicked", lambda *_a, f=fn: f())
            bar2.pack_start(b, False, False, 0)
        box.pack_start(bar2, False, False, 0)
        self.list = Gtk.ListBox()
        self.list.connect("row-selected", lambda _l, r: self._show(r))
        sw = Gtk.ScrolledWindow()
        sw.add(self.list)
        box.pack_start(sw, True, True, 0)
        self.changes = changes
        self.fill()

    def fill(self):
        for r in self.list.get_children():
            self.list.remove(r)
        for ch in self.changes:
            lab = Gtk.Label(xalign=0)
            where = "Slide %d" % (ch["mine"] + 1) if ch["mine"] is not None else "Start"
            lab.set_markup("<b>%s</b> (%s)\n%s" % (GLibEsc(ch["title"]), where, GLibEsc(ch["detail"])))
            lab.set_margin_top(4)
            lab.set_margin_bottom(4)
            row = Gtk.ListBoxRow()
            row.add(lab)
            row.change = ch
            self.list.add(row)
        self.list.show_all()
        rows = self.list.get_children()
        if rows:
            self.list.select_row(rows[0])

    def _show(self, row):
        if row is None:
            return
        ch = row.change
        k = ch["mine"] if ch["mine"] is not None else 0
        if 0 <= k < self.win.deck.slide_count():
            self.win.go_slide(k)

    def current(self):
        r = self.list.get_selected_row()
        return r.change if r is not None else None

    def _refresh(self):
        from .compare import compare as again
        self.changes = again(self.win.deck, self.path)
        self.fill()
        if not self.changes:
            self.win.dialogs.info("There are no more changes.", "Revisions")

    def on_accept(self):
        ch = self.current()
        if ch is not None:
            accept(self.win, self.path, ch)
            self._refresh()

    def on_reject(self):
        r = self.list.get_selected_row()
        if r is not None:
            self.changes.remove(r.change)
            self.fill()

    def on_accept_all(self):
        while True:
            chs = compare(self.win.deck, self.path)
            if not chs:
                break
            accept(self.win, self.path, chs[0])
        self.changes = []
        self.fill()

    def on_reject_all(self):
        self.changes = []
        self.fill()

    def _move(self, d):
        rows = self.list.get_children()
        r = self.list.get_selected_row()
        if not rows:
            return
        k = rows.index(r) if r in rows else -1
        k = max(0, min(len(rows) - 1, k + d))
        self.list.select_row(rows[k])

    def on_prev(self):
        self._move(-1)

    def on_next(self):
        self._move(1)


def GLibEsc(s):
    from gi.repository import GLib
    return GLib.markup_escape_text(s or "")

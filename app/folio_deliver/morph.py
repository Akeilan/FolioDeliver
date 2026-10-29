"""Morph (P3-01): objects found on both slides move, resize, turn and blend from where they
are on the first slide to where they are on the next; the rest fade out and in.

Objects are matched as PowerPoint does it: first by name (a name starting with "!!" forces the
match), then by the same kind of object with the same text, then by the same kind and shape
nearest to each other."""
import math

from .core import surface_from


def _ease(t):
    t = max(0.0, min(1.0, t))
    return t * t * (3 - 2 * t)


def _text(deck, i, s):
    if not s.get("has_text"):
        return ""
    try:
        return "\n".join(p for p in deck.paragraphs(i, s["id"]))[:200]
    except Exception:
        return ""


def match(deck, ai, bi):
    """Pairs (shape of slide ai, shape of slide bi), then the unmatched of each."""
    a = [s for s in deck.shapes(ai) if not s.get("group")]
    b = [s for s in deck.shapes(bi) if not s.get("group")]
    pairs = []
    used_a, used_b = set(), set()

    def take(x, y):
        pairs.append((x, y))
        used_a.add(x["id"])
        used_b.add(y["id"])
    # 1. names (each name once on each slide, or forced with "!!")
    names_a = {}
    for s in a:
        names_a.setdefault(s["name"], []).append(s)
    names_b = {}
    for s in b:
        names_b.setdefault(s["name"], []).append(s)
    for n, la in names_a.items():
        lb = names_b.get(n)
        if not lb:
            continue
        if (len(la) == 1 and len(lb) == 1) or n.startswith("!!"):
            for x, y in zip(la, lb):
                take(x, y)
    # 2. same kind and text
    for x in a:
        if x["id"] in used_a:
            continue
        tx = _text(deck, ai, x)
        if not tx:
            continue
        for y in b:
            if y["id"] in used_b or y["kind"] != x["kind"]:
                continue
            if _text(deck, bi, y) == tx:
                take(x, y)
                break
    # 3. same kind and shape, nearest first (pictures: same size ratio)
    cand = []
    for x in a:
        if x["id"] in used_a:
            continue
        for y in b:
            if y["id"] in used_b or y["kind"] != x["kind"] or (x.get("geom") or "") != (y.get("geom") or ""):
                continue
            if x.get("has_text") != y.get("has_text") or x.get("ph") != y.get("ph"):
                continue
            d = math.hypot(x["x"] + x["w"] / 2 - y["x"] - y["w"] / 2, x["y"] + x["h"] / 2 - y["y"] - y["h"] / 2)
            cand.append((d, x["id"], y["id"], x, y))
    for _d, xa, yb, x, y in sorted(cand, key=lambda c: c[0]):
        if xa in used_a or yb in used_b:
            continue
        take(x, y)
    return pairs, [s for s in a if s["id"] not in used_a], [s for s in b if s["id"] not in used_b]


class Morph:
    """Frames of a Morph from slide ai to slide bi, letterboxed into w x h pixels."""
    def __init__(self, deck, ai, bi, w, h):
        self.deck, self.ai, self.bi = deck, ai, bi
        sw, sh = deck.size()
        self.scale = min(w / sw, h / sh)
        self.ox, self.oy = (w - sw * self.scale) / 2, (h - sh * self.scale) / 2
        self.w, self.h = w, h
        self.pairs, self.gone, self.new = match(deck, ai, bi) if ai is not None else ([], [], [])
        self.bg_a = self._render(ai, None, 2) if ai is not None else None
        self.bg_b = self._render(bi, None, 2)

    def _render(self, i, anim, layers):
        pw, ph, stride, data, _ = self.deck.render(i, self.scale, False, anim, layers)
        return surface_from(pw, ph, stride, data)

    @staticmethod
    def _toward(s, cx, cy, w, h, rot, alpha):
        """The anim tuple that draws shape s with its centre at (cx, cy), w x h, turned rot."""
        scx, scy = s["x"] + s["w"] / 2, s["y"] + s["h"] / 2
        sx = w / s["w"] if s["w"] > 0.01 else 1.0
        sy = h / s["h"] if s["h"] > 0.01 else 1.0
        return (alpha, cx - scx, cy - scy, sx, sy, rot - (s.get("rot") or 0.0), False, "", 0.0)

    def draw_frame(self, cr, t):
        e = _ease(t)
        cr.set_source_rgb(0, 0, 0)
        cr.paint()
        cr.save()
        cr.translate(round(self.ox), round(self.oy))
        if self.bg_a is not None:
            cr.set_source_surface(self.bg_a, 0, 0)
            cr.paint()
        cr.set_source_surface(self.bg_b, 0, 0)
        cr.paint_with_alpha(e) if self.bg_a is not None else cr.paint()
        if self.ai is not None:
            anim_a = {}
            for x, y in self.pairs:
                cx = (x["x"] + x["w"] / 2) * (1 - e) + (y["x"] + y["w"] / 2) * e
                cy = (x["y"] + x["h"] / 2) * (1 - e) + (y["y"] + y["h"] / 2) * e
                w = x["w"] * (1 - e) + y["w"] * e
                h = x["h"] * (1 - e) + y["h"] * e
                r = (x.get("rot") or 0) * (1 - e) + (y.get("rot") or 0) * e
                anim_a[x["id"]] = self._toward(x, cx, cy, w, h, r, 1.0 - _ease(max(0.0, (t - 0.35) / 0.65)))
            for x in self.gone:
                anim_a[x["id"]] = (1.0 - e, 0, 0, 1, 1, 0, False, "", 0.0)
            cr.set_source_surface(self._render(self.ai, anim_a, 1), 0, 0)
            cr.paint()
        anim_b = {}
        for x, y in self.pairs:
            cx = (x["x"] + x["w"] / 2) * (1 - e) + (y["x"] + y["w"] / 2) * e
            cy = (x["y"] + x["h"] / 2) * (1 - e) + (y["y"] + y["h"] / 2) * e
            w = x["w"] * (1 - e) + y["w"] * e
            h = x["h"] * (1 - e) + y["h"] * e
            r = (x.get("rot") or 0) * (1 - e) + (y.get("rot") or 0) * e
            anim_b[y["id"]] = self._toward(y, cx, cy, w, h, r, _ease(min(1.0, t / 0.65)))
        for y in self.new:
            anim_b[y["id"]] = (e, 0, 0, 1, 1, 0, False, "", 0.0)
        cr.set_source_surface(self._render(self.bi, anim_b, 1), 0, 0)
        cr.paint()
        cr.restore()

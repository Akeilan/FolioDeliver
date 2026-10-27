"""Playing a slide's animations: its effects grouped by clicks, and how each shape looks at a
moment of the show (passed to the engine's renderer)."""
import math


def ease(p):
    p = max(0.0, min(1.0, p))
    return p * p * (3 - 2 * p)


class Player:
    def __init__(self, deck, i):
        self.deck = deck
        self.i = i
        self.effects = deck.animations(i) if i is not None else []
        sw, sh = deck.size()
        self.sw, self.sh = sw, sh
        self.boxes = {}
        if self.effects:
            for s in deck.shapes(i):
                self.boxes[s["id"]] = (s["x"], s["y"], s["w"], s["h"])
        # groups: [[(effect, start)]] and their lengths
        self.groups = []
        part_start = 0.0
        part_end = 0.0
        for e in self.effects:
            if e["trigger"] == "click" or not self.groups:
                self.groups.append([])
                part_start = 0.0
                part_end = 0.0
            elif e["trigger"] == "after":
                part_start = part_end
            start = part_start + e["delay"]
            self.groups[-1].append((e, start))
            part_end = max(part_end, start + e["dur"] * max(1.0, e["repeat"]))
        self.auto_first = bool(self.effects) and self.effects[0]["trigger"] != "click"

    def length(self, g):
        if g >= len(self.groups):
            return 0.0
        return max((s + e["dur"] * max(1.0, e["repeat"]) for e, s in self.groups[g]), default=0.0)

    def clicks(self):
        """Clicks the slide takes before the next slide (the first group may play by itself)."""
        return len(self.groups) - (1 if self.auto_first else 0)

    def state(self, done, playing=None, t=0.0):
        """Shape id -> (alpha, dx, dy, sx, sy, rot, hidden, clip, amount) after `done` groups,
        with group `playing` at t seconds."""
        out = {}
        # every shape whose first effect is an entrance starts hidden
        first = {}
        for e in self.effects:
            first.setdefault(e["spid"], e)
        st = {sid: [1.0, 0.0, 0.0, 1.0, 1.0, 0.0, e["class"] == "entr", "", 1.0] for sid, e in first.items()}
        for g, effects in enumerate(self.groups):
            if g < done:
                ts = None              # finished
            elif g == playing:
                ts = t
            else:
                break
            for e, start in effects:
                if ts is None:
                    p = 1.0
                else:
                    if ts < start:
                        continue
                    p = (ts - start) / max(0.001, e["dur"])
                    if e["repeat"] > 1:
                        p = p % 1.0 if ts < start + e["dur"] * e["repeat"] else 1.0
                    p = min(1.0, p)
                self._apply(st[e["spid"]], e, p)
        for sid, v in st.items():
            out[sid] = tuple(v)
        return out

    def _apply(self, v, e, p):
        cls, pre, sub = e["class"], e["preset"], e["subtype"]
        q = ease(p)
        x, y, w, h = self.boxes.get(e["spid"], (0, 0, 0, 0))
        if cls == "entr":
            v[6] = False
            if pre == 1:
                pass
            elif pre in (10, 21, 14):
                v[0] *= q
            elif pre == 2:
                if sub == 1:
                    v[2] += -(y + h) * (1 - q)
                elif sub == 2:
                    v[1] += (self.sw - x) * (1 - q)
                elif sub == 8:
                    v[1] += -(x + w) * (1 - q)
                else:
                    v[2] += (self.sh - y) * (1 - q)
            elif pre == 42:
                v[0] *= q
                v[2] += self.sh * 0.1 * (1 - q)
            elif pre == 16:
                v[7], v[8] = ("barnv" if sub == 26 else "barnh"), q
            elif pre == 22:
                v[7], v[8] = {1: "down", 2: "left", 8: "right"}.get(sub, "up"), q
            elif pre == 17:
                v[7], v[8] = "in", q
            elif pre == 31:
                v[3] *= max(0.01, q)
                v[4] *= max(0.01, q)
                v[5] += 90 * (1 - q)
            elif pre == 53:
                v[3] *= max(0.01, q)
                v[4] *= max(0.01, q)
            elif pre == 26:
                # falls in and bounces
                b = abs(math.cos(p * math.pi * 2.5)) * (1 - p)
                v[2] += -h * 1.5 * b if p < 1 else 0
            else:
                v[0] *= q
            if p <= 0:
                v[6] = True
        elif cls == "exit":
            if pre == 1:
                if p >= 1:
                    v[6] = True
            elif pre in (10, 21, 14):
                v[0] *= 1 - q
            elif pre == 2:
                if sub == 1:
                    v[2] += -(y + h) * q
                elif sub == 2:
                    v[1] += (self.sw - x) * q
                elif sub == 8:
                    v[1] += -(x + w) * q
                else:
                    v[2] += (self.sh - y) * q
            elif pre == 42:
                v[0] *= 1 - q
                v[2] += self.sh * 0.1 * q
            elif pre == 22:
                v[7], v[8] = {1: "down", 2: "left", 8: "right"}.get(sub, "up"), 1 - q
            elif pre in (53, 31):
                v[3] *= max(0.01, 1 - q)
                v[4] *= max(0.01, 1 - q)
                if pre == 31:
                    v[5] += 90 * q
            else:
                v[0] *= 1 - q
            if p >= 1:
                v[6] = True
        elif cls == "emph":
            if pre == 8:
                v[5] += 360 * q
            elif pre == 6:
                k = 1 + 0.5 * q
                v[3] *= k
                v[4] *= k
            elif pre == 9:
                v[0] *= 1 - 0.5 * q
            elif pre == 32:
                v[5] += 4 * math.sin(p * math.pi * 6) * (1 - p)
            else:
                k = 1 + 0.06 * math.sin(math.pi * p)
                v[3] *= k
                v[4] *= k

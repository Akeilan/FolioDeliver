"""SmartArt: graphics made from a list of items (text and level). Each is kept as the format
keeps them — the data model, the layout, style and colour definitions, and a drawing of the
shapes — so other programs show it and can re-lay it out; Folio lays out its own set of
layouts and redraws the shapes whenever the text or layout changes."""
import math
import re
import uuid
from xml.sax.saxutils import escape

NS = ('xmlns:dgm="http://schemas.openxmlformats.org/drawingml/2006/diagram" '
      'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
      'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"')
DSP = "http://schemas.microsoft.com/office/drawing/2008/diagram"
URN = "urn:microsoft.com/office/officeart/2005/8/"
EMU = 12700

# (label, category, layout id, algorithm)
LAYOUTS = [
    ("Basic Block List", "list", "layout/default", "blocks"),
    ("Vertical Bullet List", "list", "layout/vList2", "vlist"),
    ("Horizontal Bullet List", "list", "layout/hList1", "hlist"),
    ("Basic Process", "process", "layout/process1", "process"),
    ("Step Up Process", "process", "layout/StepUpProcess", "steps"),
    ("Basic Cycle", "cycle", "layout/cycle2", "cycle"),
    ("Hierarchy", "hierarchy", "layout/hierarchy1", "hierarchy"),
    ("Basic Pyramid", "pyramid", "layout/pyramid1", "pyramid"),
    ("Basic Venn", "relationship", "layout/venn1", "venn"),
    ("Basic Matrix", "matrix", "layout/matrix1", "matrix"),
]
CATEGORIES = [("All", None), ("List", "list"), ("Process", "process"), ("Cycle", "cycle"), ("Hierarchy", "hierarchy"),
              ("Relationship", "relationship"), ("Matrix", "matrix"), ("Pyramid", "pyramid")]
COLORS = [("Colorful - Accent Colors", "colors/colorful1", "colorful"), ("Primary Theme Colors", "colors/accent1_2", "accent1"),
          ("Accent 2", "colors/accent2_2", "accent2"), ("Accent 3", "colors/accent3_2", "accent3"),
          ("Accent 4", "colors/accent4_2", "accent4"), ("Accent 5", "colors/accent5_2", "accent5"),
          ("Accent 6", "colors/accent6_2", "accent6")]
STYLES = [("Simple Fill", "quickstyle/simple1"), ("White Outline", "quickstyle/simple2"),
          ("Subtle Effect", "quickstyle/simple3"), ("Moderate Effect", "quickstyle/simple4"),
          ("Intense Effect", "quickstyle/simple5")]
DEFAULT_ITEMS = [(0, ""), (0, ""), (0, ""), (0, ""), (0, "")]


def guid():
    return "{%s}" % str(uuid.uuid4()).upper()


def layout_index(lo_id):
    for k, (_l, _c, i, _a) in enumerate(LAYOUTS):
        if lo_id.endswith(i):
            return k
    return 0


# ---------------------------------------------------------------- the model
def default_model(layout=0):
    items = [(0, "")] * (3 if LAYOUTS[layout][3] in ("venn", "pyramid") else 5 if LAYOUTS[layout][3] == "blocks" else 3)
    if LAYOUTS[layout][3] == "hierarchy":
        items = [(0, ""), (1, ""), (2, ""), (2, ""), (1, ""), (2, "")]
    if LAYOUTS[layout][3] == "matrix":
        items = [(0, "")] * 4
    return {"layout": layout, "colors": 1 if LAYOUTS[layout][3] != "blocks" else 1, "style": 0, "items": list(items)}


def tree(items):
    """[(level, text)] → nested [(text, [children])] (a deeper level after a shallower one is its child)."""
    root = []
    stack = [(-1, root)]
    for lvl, text in items:
        node = (text, [])
        while stack and stack[-1][0] >= lvl:
            stack.pop()
        stack[-1][1].append(node)
        stack.append((lvl, node[1]))
    return root


# ---------------------------------------------------------------- layout
def _fit_size(text, w, h, base=28.0):
    """A font size the text fits in (roughly, as SmartArt shrinks text together)."""
    if not text:
        return base
    lines = max(1, text.count("\n") + 1)
    longest = max(len(t) for t in text.split("\n")) or 1
    by_w = w / (longest * 0.55)
    by_h = h / (lines * 1.35)
    return max(8.0, min(base, by_w, by_h))


def layout(model, w, h):
    """Shapes for the model in a w x h box (points): [(prst, x, y, w, h, colour index, text, level, extra)]."""
    alg = LAYOUTS[model["layout"]][3]
    top = tree(model["items"])
    n = max(1, len(top))
    out = []

    def add(prst, x, y, ww, hh, k, text, lvl=0, children=None, **kw):
        out.append({"prst": prst, "x": x, "y": y, "w": ww, "h": hh, "k": k, "text": text, "lvl": lvl,
                    "sub": [c[0] for c in (children or [])], **kw})
    if alg == "blocks":
        cols = max(1, int(math.ceil(math.sqrt(n * w / max(h, 1) / 1.6))))
        rows = int(math.ceil(n / cols))
        cw, ch = w / (cols + (cols - 1) * 0.1), h / (rows + (rows - 1) * 0.1)
        ch = min(ch, cw * 0.6)
        cw2 = min(cw, ch / 0.6)
        tw = cols * cw2 + (cols - 1) * cw2 * 0.1
        th = rows * ch + (rows - 1) * ch * 0.1
        ox, oy = (w - tw) / 2, (h - th) / 2
        for k, (t, kids) in enumerate(top):
            r, c = divmod(k, cols)
            # the last row is centred
            in_row = min(cols, n - r * cols)
            rx = ox + (tw - (in_row * cw2 + (in_row - 1) * cw2 * 0.1)) / 2
            add("rect", rx + c * cw2 * 1.1, oy + r * ch * 1.1, cw2, ch, k, t, children=kids)
    elif alg == "vlist":
        gap = 0.08
        bh = h / (n + (n - 1) * gap) if n else h
        for k, (t, kids) in enumerate(top):
            y = k * bh * (1 + gap)
            if kids:
                add("roundRect", 0, y, w, bh * 0.45, k, t, children=[])
                add("rect", 0, y + bh * 0.45, w, bh * 0.55, k, "\n".join("• " + c[0] for c in kids), 1, kind="sub")
            else:
                add("roundRect", 0, y, w, bh, k, t)
    elif alg == "hlist":
        gap = 0.06
        bw = w / (n + (n - 1) * gap)
        for k, (t, kids) in enumerate(top):
            x = k * bw * (1 + gap)
            add("rect", x, 0, bw, h * 0.3, k, t)
            add("rect", x, h * 0.3, bw, h * 0.7, k, "\n".join("• " + c[0] for c in kids), 1, kind="sub")
    elif alg == "process":
        aw = 0.35            # arrow width relative to a box
        bw = w / (n + (n - 1) * (aw + 0.1))
        bh = min(h, bw * 0.6)
        y = (h - bh) / 2
        for k, (t, kids) in enumerate(top):
            x = k * bw * (1 + aw + 0.1)
            add("rect", x, y, bw, bh, k, t, children=kids)
            if k < n - 1:
                add("rightArrow", x + bw * 1.05, y + bh * 0.3, bw * aw, bh * 0.4, k, "", kind="arrow")
    elif alg == "steps":
        sw = w / n
        for k, (t, kids) in enumerate(top):
            sh = h * (0.35 + 0.65 * (k + 1) / n)
            add("corner", k * sw, h - sh, sw * 0.95, sh, k, t, children=kids)
    elif alg == "cycle":
        r = min(w, h) / 2
        cx, cy = w / 2, h / 2
        d = r * (0.62 if n > 3 else 0.7) * (2 * math.sin(math.pi / max(n, 2)) if n > 1 else 1)
        d = min(d, r * 0.75)
        rr = r - d / 2
        for k, (t, kids) in enumerate(top):
            a = -math.pi / 2 + 2 * math.pi * k / n
            add("ellipse", cx + rr * math.cos(a) - d / 2, cy + rr * math.sin(a) - d / 2, d, d, k, t, children=kids)
            if n > 1:
                b = a + math.pi / n
                aw2 = d * 0.3
                add("rightArrow", cx + rr * math.cos(b) - aw2 / 2, cy + rr * math.sin(b) - aw2 / 3, aw2, aw2 * 0.66, k, "",
                    kind="arrow", rot=math.degrees(b) + 90)
    elif alg == "hierarchy":
        levels = []

        def walk(nodes, depth):
            while len(levels) <= depth:
                levels.append([])
            for t, kids in nodes:
                levels[depth].append((t, kids))
                walk(kids, depth + 1)
        walk(top, 0)
        rows = len(levels)
        bh = h / (rows + (rows - 1) * 0.5)
        # leaves spread evenly; parents centre over their children
        pos = {}

        def leaves(node):
            t, kids = node
            return sum(leaves(c) for c in kids) if kids else 1
        total = sum(leaves(nd) for nd in top) or 1
        bw = min(w / (total + (total - 1) * 0.15), bh * 1.6)
        span = total * bw * 1.15 - bw * 0.15
        ox = (w - span) / 2
        k_ref = [0]

        def place(nodes, depth, start):
            x = start
            for nd in nodes:
                t, kids = nd
                lw = leaves(nd)
                if kids:
                    place(kids, depth + 1, x)
                cx = ox + (x + lw / 2) * bw * 1.15 - bw * 0.15 / 2
                y = depth * bh * 1.5
                pos[id(nd)] = (cx, y)
                add("roundRect", cx - bw / 2, y, bw, bh, k_ref[0], t, depth)
                k_ref[0] += 1
                x += lw
        place(top, 0, 0)

        def lines(nodes):
            for nd in nodes:
                px, py = pos[id(nd)]
                for c in nd[1]:
                    qx, qy = pos[id(c)]
                    out.insert(0, {"prst": "line", "x": min(px, qx), "y": py + bh, "w": abs(qx - px) or 0.1, "h": qy - py - bh,
                                   "k": 0, "text": "", "lvl": 0, "sub": [], "kind": "line", "flip": qx < px})
                lines(nd[1])
        lines(top)
    elif alg == "pyramid":
        bh = h / n
        for k, (t, kids) in enumerate(top):
            # each band a trapezoid; the top one a triangle
            y = k * bh
            ww = w * (k + 1) / n
            add("triangle" if k == 0 else "trapezoid", (w - ww) / 2, y, ww, bh, k, t, children=kids,
                adj=None if k == 0 else 50000 * (w / n) / max(bh, 1) / 1.0)
    elif alg == "venn":
        r = min(w / (1 + 0.65 * max(n - 1, 0)), h) / 2 if n < 4 else min(w, h) / 3.2
        cx, cy = w / 2, h / 2
        for k, (t, kids) in enumerate(top):
            if n <= 3:
                a = -math.pi / 2 + 2 * math.pi * k / n if n == 3 else (math.pi if k == 0 else 0)
                d = r * (0.55 if n == 3 else 0.62) if n > 1 else 0
                px, py = cx + d * math.cos(a), cy + d * math.sin(a) + (r * 0.12 if n == 3 else 0)
            else:
                a = -math.pi / 2 + 2 * math.pi * k / n
                px, py = cx + r * 0.7 * math.cos(a), cy + r * 0.7 * math.sin(a)
            add("ellipse", px - r, py - r, 2 * r, 2 * r, k, t, children=kids, alpha=50000)
    elif alg == "matrix":
        s = min(w, h)
        ox, oy = (w - s) / 2, (h - s) / 2
        for k, (t, kids) in enumerate(top[:4]):
            r, c = divmod(k, 2)
            add("roundRect", ox + c * s * 0.51, oy + r * s * 0.51, s * 0.49, s * 0.49, k, t, children=kids)
    return out


# ---------------------------------------------------------------- the parts
def _colour(model, k, n):
    cs = COLORS[model.get("colors", 1)][2]
    if cs == "colorful":
        return "accent%d" % (k % 5 + 2)
    return cs


def _para_xml(text, size, algn="ctr", color=None, bullet=False):
    out = []
    for line in (text.split("\n") if text else [""]):
        clr = '<a:solidFill><a:schemeClr val="%s"/></a:solidFill>' % color if color else ""
        if line:
            out.append('<a:p><a:pPr algn="%s"/><a:r><a:rPr lang="en-US" sz="%d" kern="1200">%s</a:rPr><a:t>%s</a:t></a:r></a:p>'
                       % (algn if not bullet else "l", int(size * 100), clr, escape(line)))
        else:
            out.append('<a:p><a:pPr algn="%s"/><a:endParaRPr lang="en-US" sz="%d" kern="1200"/></a:p>' % (algn, int(size * 100)))
    return "".join(out)


def drawing_xml(model, w, h, ids):
    """The dsp:drawing part: the shapes as laid out (what other programs show)."""
    shapes = layout(model, w, h)
    style = model.get("style", 0)
    body = []
    texts = [s for s in shapes if s.get("kind") not in ("arrow", "line")]
    size = min([_fit_size(s["text"], s["w"] * 0.85, s["h"] * 0.8, 28 if s.get("kind") != "sub" else 18)
                for s in texts if s["text"]] or [28])
    sub_size = min(size * 0.75, 18)
    n_main = len([s for s in shapes if s.get("kind") is None])
    for k, s in enumerate(shapes):
        mid = ids[k] if k < len(ids) else guid()
        e = lambda v: int(round(v * EMU))  # noqa: E731
        col = _colour(model, s["k"], n_main)
        kind = s.get("kind")
        rot = ' rot="%d"' % int(s.get("rot", 0) * 60000) if s.get("rot") else ""
        flip = ' flipH="1"' if s.get("flip") else ""
        geom = '<a:prstGeom prst="%s"><a:avLst/></a:prstGeom>' % s["prst"]
        if s.get("adj"):
            geom = '<a:prstGeom prst="%s"><a:avLst><a:gd name="adj" fmla="val %d"/></a:avLst></a:prstGeom>' % (s["prst"], int(s["adj"]))
        if kind == "line":
            fill = '<a:noFill/>'
            ln = '<a:ln w="12700"><a:solidFill><a:schemeClr val="%s"><a:shade val="60000"/></a:schemeClr></a:solidFill></a:ln>' % col
        elif kind == "sub":
            fill = '<a:solidFill><a:schemeClr val="%s"><a:alpha val="90000"/><a:tint val="40000"/></a:schemeClr></a:solidFill>' % col
            ln = '<a:ln w="12700"><a:solidFill><a:schemeClr val="%s"><a:alpha val="90000"/><a:tint val="40000"/></a:schemeClr></a:solidFill></a:ln>' % col
        elif kind == "arrow":
            fill = '<a:solidFill><a:schemeClr val="%s"><a:tint val="60000"/></a:schemeClr></a:solidFill>' % col
            ln = '<a:ln><a:noFill/></a:ln>'
        else:
            alpha = '<a:alpha val="%d"/>' % s["alpha"] if s.get("alpha") else ""
            fill = '<a:solidFill><a:schemeClr val="%s">%s</a:schemeClr></a:solidFill>' % (col, alpha)
            ln = ('<a:ln w="12700"><a:solidFill><a:schemeClr val="lt1"/></a:solidFill></a:ln>' if style in (0, 1)
                  else '<a:ln><a:noFill/></a:ln>')
        effect = ""
        if style >= 3 and kind is None:
            effect = ('<a:effectLst><a:outerShdw blurRad="%d" dist="%d" dir="5400000" rotWithShape="0"><a:srgbClr val="000000"><a:alpha val="%d"/></a:srgbClr></a:outerShdw></a:effectLst>'
                      % (40000 if style == 3 else 63500, 23000 if style == 3 else 38100, 35000 if style == 3 else 45000))
        txt = ""
        if kind not in ("arrow", "line"):
            sz = sub_size if kind == "sub" else size
            tc = "tx1" if kind == "sub" or s.get("alpha") else "lt1"
            txt = ('<dsp:txBody><a:bodyPr spcFirstLastPara="0" vert="horz" wrap="square" lIns="%d" tIns="%d" rIns="%d" bIns="%d" numCol="1" spcCol="1270" anchor="%s" anchorCtr="0"><a:noAutofit/></a:bodyPr><a:lstStyle/>%s</dsp:txBody>'
                   % (e(sz * 0.3), e(sz * 0.3), e(sz * 0.3), e(sz * 0.3), "t" if kind == "sub" else "ctr",
                      _para_xml(s["text"], sz, "ctr", tc, bullet=kind == "sub")))
            txt += '<dsp:txXfrm><a:off x="%d" y="%d"/><a:ext cx="%d" cy="%d"/></dsp:txXfrm>' % (e(s["x"]), e(s["y"]), e(s["w"]), e(s["h"]))
        body.append('<dsp:sp modelId="%s"><dsp:nvSpPr><dsp:cNvPr id="0" name=""/><dsp:cNvSpPr/></dsp:nvSpPr>'
                    '<dsp:spPr><a:xfrm%s%s><a:off x="%d" y="%d"/><a:ext cx="%d" cy="%d"/></a:xfrm>%s%s%s%s</dsp:spPr>'
                    '<dsp:style><a:lnRef idx="2"><a:scrgbClr r="0" g="0" b="0"/></a:lnRef><a:fillRef idx="1"><a:scrgbClr r="0" g="0" b="0"/></a:fillRef>'
                    '<a:effectRef idx="0"><a:scrgbClr r="0" g="0" b="0"/></a:effectRef><a:fontRef idx="minor"><a:schemeClr val="lt1"/></a:fontRef></dsp:style>%s</dsp:sp>'
                    % (mid, rot, flip, e(s["x"]), e(s["y"]), e(max(s["w"], 0.1)), e(max(s["h"], 0.1)), geom, fill, ln, effect, txt))
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<dsp:drawing xmlns:dgm="http://schemas.openxmlformats.org/drawingml/2006/diagram" '
            'xmlns:dsp="%s" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"><dsp:spTree><dsp:nvGrpSpPr><dsp:cNvPr id="0" name=""/>'
            '<dsp:cNvGrpSpPr/></dsp:nvGrpSpPr><dsp:grpSpPr/>%s</dsp:spTree></dsp:drawing>' % (DSP, "".join(body)))


def _t(text):
    if text:
        return '<dgm:t><a:bodyPr/><a:lstStyle/><a:p><a:r><a:rPr lang="en-US"/><a:t>%s</a:t></a:r></a:p></dgm:t>' % escape(text)
    return '<dgm:t><a:bodyPr/><a:lstStyle/><a:p><a:endParaRPr lang="en-US"/></a:p></dgm:t>'


def data_xml(model):
    """The data model: the document point, a point per item, the connections between them."""
    lo = LAYOUTS[model["layout"]]
    cs = COLORS[model.get("colors", 1)]
    qs = STYLES[model.get("style", 0)]
    doc = guid()
    pts = ['<dgm:pt modelId="%s" type="doc"><dgm:prSet loTypeId="%s%s" loCatId="%s" qsTypeId="%s%s" qsCatId="simple" '
           'csTypeId="%s%s" csCatId="%s" phldr="1"/><dgm:spPr/>%s</dgm:pt>'
           % (doc, URN, lo[2], lo[1], URN, qs[1], URN, cs[1], cs[2], _t(""))]
    cxns = []
    parents = [(-1, doc)]
    order = {}
    for lvl, text in model["items"]:
        nid = guid()
        ph = ' phldrT="[Text]"' + (' phldr="1"' if not text else "")
        pts.append('<dgm:pt modelId="%s"><dgm:prSet%s/><dgm:spPr/>%s</dgm:pt>' % (nid, ph, _t(text)))
        while parents and parents[-1][0] >= lvl:
            parents.pop()
        par = parents[-1][1]
        cid, pid, sid = guid(), guid(), guid()
        for ty, mid in (("parTrans", pid), ("sibTrans", sid)):
            pts.append('<dgm:pt modelId="%s" type="%s" cxnId="%s"><dgm:prSet/><dgm:spPr/>%s</dgm:pt>' % (mid, ty, cid, _t("")))
        k = order.get(par, 0)
        order[par] = k + 1
        cxns.append('<dgm:cxn modelId="%s" srcId="%s" destId="%s" srcOrd="%d" destOrd="0" parTransId="%s" sibTransId="%s"/>'
                    % (cid, par, nid, k, pid, sid))
        parents.append((lvl, nid))
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<dgm:dataModel %s><dgm:ptLst>%s</dgm:ptLst><dgm:cxnLst>%s</dgm:cxnLst>'
            '<dgm:bg/><dgm:whole/><dgm:extLst><a:ext uri="http://schemas.microsoft.com/office/drawing/2008/diagram">'
            '<dsp:dataModelExt xmlns:dsp="%s" relId="{DRAWING_RID}" minVer="http://schemas.openxmlformats.org/drawingml/2006/diagram"/>'
            '</a:ext></dgm:extLst></dgm:dataModel>' % (NS, "".join(pts), "".join(cxns), DSP))


_ALG = {"blocks": "snake", "vlist": "lin", "hlist": "lin", "process": "lin", "steps": "lin", "cycle": "cycle",
        "hierarchy": "hierChild", "pyramid": "pyra", "venn": "cycle", "matrix": "snake"}
_SHAPE = {"blocks": "rect", "vlist": "roundRect", "hlist": "rect", "process": "rect", "steps": "corner", "cycle": "ellipse",
          "hierarchy": "roundRect", "pyramid": "trapezoid", "venn": "ellipse", "matrix": "roundRect"}


def layout_xml(model):
    """The layout definition, named by its id (programs that know the layout use their own)."""
    label, cat, lid, alg = LAYOUTS[model["layout"]]
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<dgm:layoutDef %s uniqueId="%s%s"><dgm:title val=""/><dgm:desc val=""/>'
            '<dgm:catLst><dgm:cat type="%s" pri="1000"/></dgm:catLst>'
            '<dgm:layoutNode name="diagram"><dgm:varLst><dgm:dir/><dgm:resizeHandles val="exact"/></dgm:varLst>'
            '<dgm:alg type="%s"/><dgm:shape xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" r:blip=""><dgm:adjLst/></dgm:shape>'
            '<dgm:presOf/><dgm:constrLst><dgm:constr type="w" for="ch" forName="node" refType="w"/></dgm:constrLst><dgm:ruleLst/>'
            '<dgm:forEach name="Name0" axis="ch" ptType="node"><dgm:layoutNode name="node"><dgm:varLst><dgm:bulletEnabled val="1"/></dgm:varLst>'
            '<dgm:alg type="tx"/><dgm:shape xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" type="%s" r:blip=""><dgm:adjLst/></dgm:shape>'
            '<dgm:presOf axis="desOrSelf" ptType="node"/><dgm:constrLst><dgm:constr type="tMarg" refType="primFontSz" fact="0.3"/></dgm:constrLst>'
            '<dgm:ruleLst><dgm:rule type="primFontSz" val="5" fact="NaN" max="NaN"/></dgm:ruleLst></dgm:layoutNode></dgm:forEach>'
            '</dgm:layoutNode></dgm:layoutDef>' % (NS, URN, lid, cat, _ALG[alg], _SHAPE[alg]))


def style_xml(model):
    name, sid = STYLES[model.get("style", 0)]
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<dgm:styleDef %s uniqueId="%s%s"><dgm:title val=""/><dgm:desc val=""/>'
            '<dgm:catLst><dgm:cat type="simple" pri="10100"/></dgm:catLst><dgm:scene3d><a:camera prst="orthographicFront"/><a:lightRig rig="threePt" dir="t"/></dgm:scene3d>'
            '<dgm:styleLbl name="node1"><dgm:scene3d><a:camera prst="orthographicFront"/><a:lightRig rig="threePt" dir="t"/></dgm:scene3d><dgm:sp3d/>'
            '<dgm:txPr/><dgm:style><a:lnRef idx="2"><a:scrgbClr r="0" g="0" b="0"/></a:lnRef><a:fillRef idx="1"><a:scrgbClr r="0" g="0" b="0"/></a:fillRef>'
            '<a:effectRef idx="0"><a:scrgbClr r="0" g="0" b="0"/></a:effectRef><a:fontRef idx="minor"><a:schemeClr val="lt1"/></a:fontRef></dgm:style></dgm:styleLbl>'
            '</dgm:styleDef>' % (NS, URN, sid))


def colors_xml(model):
    name, cid, cat = COLORS[model.get("colors", 1)]
    fills = ("".join('<a:schemeClr val="accent%d"/>' % k for k in range(2, 7)) if cat == "colorful"
             else '<a:schemeClr val="%s"/>' % cat)
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<dgm:colorsDef %s uniqueId="%s%s"><dgm:title val=""/><dgm:desc val=""/>'
            '<dgm:catLst><dgm:cat type="%s" pri="10100"/></dgm:catLst>'
            '<dgm:styleLbl name="node1"><dgm:fillClrLst meth="repeat">%s</dgm:fillClrLst><dgm:linClrLst meth="repeat"><a:schemeClr val="lt1"/></dgm:linClrLst>'
            '<dgm:effectClrLst/><dgm:txLinClrLst/><dgm:txFillClrLst meth="repeat"><a:schemeClr val="lt1"/></dgm:txFillClrLst><dgm:txEffectClrLst/></dgm:styleLbl>'
            '</dgm:colorsDef>' % (NS, URN, cid, cat, fills))


def parts(model, w, h):
    return {"data": data_xml(model), "layout": layout_xml(model), "style": style_xml(model),
            "colors": colors_xml(model), "drawing": drawing_xml(model, w, h, [])}


# ---------------------------------------------------------------- reading one back
_PT = re.compile(r"<dgm:pt\b([^>]*)>(.*?)</dgm:pt>|<dgm:pt\b([^>]*)/>", re.S)


def _attr(raw, name):
    m = re.search(r'\b%s="([^"]*)"' % name, raw)
    return m.group(1) if m else None


def read_data(xml):
    """The model from a data part: layout, colours, style and the items with their levels."""
    pts = {}
    doc = None
    lo = cs = qs = ""
    for m in _PT.finditer(xml):
        raw = m.group(1) or m.group(3) or ""
        inner = m.group(2) or ""
        mid = _attr(raw, "modelId")
        ty = _attr(raw, "type") or "node"
        if ty == "doc":
            doc = mid
            ps = re.search(r"<dgm:prSet\b([^>]*)", inner)
            if ps:
                lo, cs, qs = _attr(ps.group(1), "loTypeId") or "", _attr(ps.group(1), "csTypeId") or "", _attr(ps.group(1), "qsTypeId") or ""
        if ty in ("node", "doc"):
            text = "\n".join("".join(re.findall(r"<a:t>([^<]*)</a:t>", p)) for p in re.findall(r"<a:p>.*?</a:p>|<a:p/>", inner, re.S))
            from xml.sax.saxutils import unescape
            pts[mid] = unescape(text).strip("\n")
    kids = {}
    for m in re.finditer(r"<dgm:cxn\b([^>]*)/?>", xml):
        raw = m.group(1)
        if (_attr(raw, "type") or "parOf") != "parOf":
            continue
        src, dst = _attr(raw, "srcId"), _attr(raw, "destId")
        kids.setdefault(src, []).append((int(_attr(raw, "srcOrd") or 0), dst))
    items = []

    def walk(node, lvl):
        for _o, c in sorted(kids.get(node, [])):
            if c in pts and c != doc:
                items.append((lvl, pts[c]))
                walk(c, lvl + 1)
    walk(doc, 0)
    model = {"layout": layout_index(lo), "items": items or list(DEFAULT_ITEMS), "style": 0, "colors": 1}
    for k, (_n, cid, _c) in enumerate(COLORS):
        if cs.endswith(cid):
            model["colors"] = k
    for k, (_n, sid) in enumerate(STYLES):
        if qs.endswith(sid):
            model["style"] = k
    return model


# ---------------------------------------------------------------- from bullets
def items_from_paragraphs(paras, levels):
    return [(min(l, 4), t) for t, l in zip(paras, levels) if t.strip()]

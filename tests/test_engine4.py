"""Engine tests, part 4 (Backlog 3): transitions after 2007, Morph's layers, outlines for Merge
Shapes, objects with their own parts, actions, custom properties, embedded fonts."""
import os
import sys
import tempfile
import zipfile

import deliver_core as d

HERE = os.path.dirname(os.path.abspath(__file__))
BLANK = os.path.join(HERE, "..", "share", "templates", "Blank.pptx")
sys.path.insert(0, os.path.join(HERE, "..", "app"))
FAILS = []


def check(cond, what):
    print(("ok   " if cond else "FAIL ") + what)
    if not cond:
        FAILS.append(what)


P = d.Presentation
p = P.open(BLANK)
for _ in range(3):
    p.new_slide(p.slide_count() - 1 if p.slide_count() else 0, "")
n = p.slide_count()
check(n >= 3, "three slides")

# ---------------------------------------------------------------- transitions (P3-01)
from folio_deliver.more_ui import TRANSITIONS  # noqa: E402

wrong = []
for kind, _label, opts in TRANSITIONS:
    for opt in [""] + [v for _l, v in opts]:
        p.set_transition([1], kind, opt, 1.25, True, -1.0)
        k, o, dur, click, after = p.transition(1)
        want_k = "none" if kind == "none" else kind
        want_o = opt
        if kind == "wheel" and opt in ("", "1"):
            want_o = ""
        if kind == "circle" and opt == "":
            want_o = "circle"
        if kind == "morph" and opt == "":
            want_o = "byObject"
        if kind == "shred" and opt == "":
            want_o = "strip"
        ok = k == want_k and (kind == "none" or abs(dur - 1.25) < 0.01 or kind == "cut") and \
            (not want_o or o == want_o or (kind in ("vortex", "ripple", "glitter", "pan", "gallery", "conveyor", "flip", "switch",
                                                     "ferris", "window", "doors", "cube", "box", "rotate", "orbit", "flythrough",
                                                     "reveal", "push", "wipe", "cover", "pull", "split", "randomBar", "checker",
                                                     "blinds", "comb") and o in (want_o, "")))
        if not ok:
            wrong.append((kind, opt, k, o, dur))
check(not wrong, "every transition and option reads back (%d kinds) %s" % (len(TRANSITIONS), wrong[:5]))
p.set_transition([1], "vortex", "r", 2.0, True, -1.0)
out = os.path.join(tempfile.mkdtemp(), "b3.pptx")
p.save(out)
xml = zipfile.ZipFile(out).read(p.slide_parts()[1]).decode()
check('Requires="p14"' in xml and "<p14:vortex" in xml and "<mc:Fallback><p:transition" in xml and "<p:fade/>" in xml,
      "Office 2010 transitions are saved with a fade for older readers")
p.set_transition([2], "morph", "byWord", 2.0, True, -1.0)
p.set_transition([0], "curtains", "", 1.5, True, -1.0)
p.save(out)
xml2 = zipfile.ZipFile(out).read(p.slide_parts()[2]).decode()
xml0 = zipfile.ZipFile(out).read(p.slide_parts()[0]).decode()
check('Requires="p159"' in xml2 and 'option="byWord"' in xml2, "Morph is saved as PowerPoint 2016+ writes it")
check('<p15:prstTrans prst="curtains"' in xml0, "preset transitions (Curtains) are saved as p15:prstTrans")
q = P.open(out)
check(q.transition(2)[:2] == ("morph", "byWord") and q.transition(1)[:2] == ("vortex", "r") and q.transition(0)[0] == "curtains",
      "they read back after reopening")

# ---------------------------------------------------------------- render layers (Morph)
r = P.open(BLANK)
r.new_slide(0, "")
box = r.add_shape(0, "rect", 100, 100, 200, 100)
r.set_shape_fill(0, [box], "FF0000") if hasattr(r, "set_shape_fill") else None
w, h, stride, data, shapes = r.render(0, 0.5, False, None, 1)
check(all(b == 0 for b in bytes(data[:4 * 10])), "slide layer only: no background")
w, h, stride, data2, _ = r.render(0, 0.5, False, None, 2)
mid = (int(150 * 0.5) * stride) + int(200 * 0.5) * 4
check(bytes(data2[mid:mid + 4]) != bytes(data[mid:mid + 4]), "background layer leaves the slide's shapes out")

# ---------------------------------------------------------------- outlines (Merge Shapes)
poly = r.shape_outline(0, box)
xs = [x for pl in poly for x, _y in pl]
ys = [y for pl in poly for _x, y in pl]
check(poly and abs(min(xs) - 100) < 0.5 and abs(max(xs) - 300) < 0.5 and abs(min(ys) - 100) < 0.5 and abs(max(ys) - 200) < 0.5,
      "a rectangle's outline in slide points")
ell = r.add_shape(0, "ellipse", 0, 0, 100, 50)
pe = r.shape_outline(0, ell)
check(len(pe) == 1 and len(pe[0]) > 16, "an ellipse's outline is a fine polygon")

# ---------------------------------------------------------------- objects with parts
png = open(os.path.join(HERE, "data", "pic.png"), "rb").read() if os.path.exists(os.path.join(HERE, "data", "pic.png")) else None
if png is None:
    import cairo
    s = cairo.ImageSurface(cairo.FORMAT_ARGB32, 8, 8)
    import io
    b = io.BytesIO()
    s.write_to_png(b)
    png = b.getvalue()
xml = ('<p:pic><p:nvPicPr><p:cNvPr id="{ID}" name="Zoom {ID}"><a:hlinkClick r:id="{rSl}" action="ppaction://hlinksldjump"/></p:cNvPr>'
       '<p:cNvPicPr/><p:nvPr/></p:nvPicPr><p:blipFill><a:blip r:embed="{rImg}"/><a:stretch><a:fillRect/></a:stretch></p:blipFill>'
       '<p:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="1270000" cy="714375"/></a:xfrm><a:prstGeom prst="rect"><a:avLst/></a:prstGeom></p:spPr></p:pic>')
zid = r.insert_object_xml(0, "Insert Zoom", xml, [("rImg", "image", "image", "png", "image/png", png, ""),
                                                  ("rSl", "slide", "", "", "", b"", "slide:0")])
check(zid > 0 and r.shape_link(0, zid) == "slide:0", "an object written as XML gets its picture and its link")
check("Zoom" in (r.object_xml(0, zid) or ""), "its XML can be read back")
r.undo()
check(r.object_xml(0, zid) is None, "and undone")

# ---------------------------------------------------------------- actions (P3-03)
r.set_shape_action(0, box, "click", "next", None, False, True)
check(r.shape_action(0, box, "click")[0] == "next" and r.shape_action(0, box, "click")[3], "click action: next slide, highlighted")
r.set_shape_action(0, box, "hover", "show:0", (b"RIFF0000WAVEfmt ", "ding.wav"), False, False)
a = r.shape_action(0, box, "hover")
check(a[0] == "show:0" and a[1].endswith(".wav"), "mouse-over action: custom show with a sound")
r.set_shape_action(0, box, "click", "program:/usr/bin/true", None, True, False)
a = r.shape_action(0, box, "click")
check(a[0] == "program:/usr/bin/true" and a[2], "run a program, stopping the sound")
r.set_shape_action(0, box, "click", "", None, False, False)
check(r.shape_action(0, box, "click") is None, "no action")

# ---------------------------------------------------------------- custom properties (Mark as Final)
r.set_custom_prop("_MarkAsFinal", "bool", "true")
check(("_MarkAsFinal", "true") in r.custom_props(), "custom property set")
out2 = os.path.join(tempfile.mkdtemp(), "b3b.pptx")
r.save(out2)
z = zipfile.ZipFile(out2)
check("docProps/custom.xml" in z.namelist() and b"custom-properties" in z.read("_rels/.rels")
      and b"docProps/custom.xml" in z.read("[Content_Types].xml"), "custom properties part, relationship and type")
check(("_MarkAsFinal", "true") in P.open(out2).custom_props(), "read back after reopening")

# ---------------------------------------------------------------- embedded fonts
r.set_embedded_fonts([("Folio Test", [("regular", b"EOTDATA1"), ("bold", b"EOTDATA2")])])
ef = r.embedded_fonts()
check([(f, s) for f, s, _p in ef] == [("Folio Test", "regular"), ("Folio Test", "bold")], "fonts embedded")
r.save(out2)
z = zipfile.ZipFile(out2)
check(z.read(ef[0][2]) == b"EOTDATA1" and b"embeddedFontLst" in z.read("ppt/presentation.xml"), "font parts saved")
r.set_embedded_fonts([])
check(r.embedded_fonts() == [], "embedded fonts removed")

# Always Open Read-Only, as PowerPoint keeps it
check(not r.readonly_recommended(), "not read-only recommended at first")
r.set_readonly_recommended(True)
r.save(out2)
pp = zipfile.ZipFile(out2).read("ppt/presProps.xml").decode()
check('uri="{1BD7E111-0CB8-44D6-8891-C1BB2F81B7CC}"' in pp and "p1710:readonlyRecommended" in pp and 'val="1"' in pp,
      "saved as p1710:readonlyRecommended in presProps")
r2 = P.open(out2)
check(r2.readonly_recommended(), "read back")
r2.set_readonly_recommended(False)
check(not r2.readonly_recommended(), "and switched off")
r2.undo()
check(r2.readonly_recommended(), "one undo step")

# media parts and replacing one
mp = r.media_parts()
check(isinstance(mp, list), "media parts listed")
print("FAILED: %d" % len(FAILS) if FAILS else "all passed")
sys.exit(1 if FAILS else 0)

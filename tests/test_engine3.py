"""Engine tests, part 3: links, cropping, comments."""
import os
import sys
import tempfile
import zipfile

import deliver_core as d

HERE = os.path.dirname(os.path.abspath(__file__))
BLANK = os.path.join(HERE, "..", "share", "templates", "Blank.pptx")
FAILS = []


def check(cond, what):
    print(("ok   " if cond else "FAIL ") + what)
    if not cond:
        FAILS.append(what)


P = d.Presentation
p = P.open(BLANK)
p.new_slide(0, "")
p.new_slide(1, "")
tb = p.add_textbox(0, 50, 50, 400, 60, "Visit the site now")
p.set_link(0, tb, (0, 10), (0, 14), "https://example.org/")
check(p.run_props(0, tb, 0, 11).get("link") == "https://example.org/", "text link to an address")
check(p.run_props(0, tb, 0, 11)["u"] and p.run_props(0, tb, 0, 11)["color"] == "0563C1", "links are blue and underlined")
check("link" not in p.run_props(0, tb, 0, 2), "text outside the link has none")
check(p.link_at(0, tb, 0, 12) == "https://example.org/", "link under a position")
p.set_link(0, tb, (0, 0), (0, 5), "slide:2")
check(p.link_at(0, tb, 0, 1) == "slide:2", "link to a slide")
p.set_link(0, tb, (0, 0), (0, 5), "next")
check(p.link_at(0, tb, 0, 1) == "next", "link to the next slide")
p.set_link(0, tb, (0, 0), (0, 5), "")
check(p.link_at(0, tb, 0, 1) is None, "link removed")
p.undo()
check(p.link_at(0, tb, 0, 1) == "next", "undo brings the link back")
sh = p.add_shape(1, "rect", 100, 100, 100, 100)
p.set_shape_link(1, sh, "slide:0")
check(p.shape_link(1, sh) == "slide:0", "shape click action")

# crop
import struct, zlib
def png(w, h):
    raw = b"".join(b"\0" + b"\xff\x00\x00" * w for _ in range(h))
    def ch(t, b):
        return struct.pack(">I", len(b)) + t + b + struct.pack(">I", zlib.crc32(t + b) & 0xffffffff)
    return b"\x89PNG\r\n\x1a\n" + ch(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)) + ch(b"IDAT", zlib.compress(raw)) + ch(b"IEND", b"")
pic = p.add_picture(2, png(40, 40), "png", "red", 100, 100, 200, 200)
check(p.crop(2, pic) == (0, 0, 0, 0), "uncropped picture")
p.set_crop(2, pic, 0.25, 0, 0, 0.5, 150, 100, 150, 100)
c = p.crop(2, pic)
check(abs(c[0] - 0.25) < 1e-6 and abs(c[3] - 0.5) < 1e-6, "crop stored")
s = [x for x in p.shapes(2) if x["id"] == pic][0]
check(abs(s["x"] - 150) < 0.5 and abs(s["w"] - 150) < 0.5, "crop sets the box")
p.undo(); p.undo()
check(p.crop(2, pic) == (0, 0, 0, 0), "crop undone")
p.redo(); p.redo()

# comments
check(p.comments(0) == [], "no comments")
k = p.add_comment(0, "Check this number", "Ron Shillings", "RS", 40, 30)
k2 = p.add_comment(0, "And this one", "Ron Shillings", "RS", 80, 30)
cs = p.comments(0)
check(len(cs) == 2 and cs[0][1] == "Ron Shillings" and cs[0][4] == "Check this number" and cs[1][0] == k2 != k, "comments added")
check(abs(cs[0][5] - 40) < 0.5, "comment position")
p.edit_comment(0, k, "Fixed")
check(p.comments(0)[0][4] == "Fixed", "comment edited")
p.delete_comment(0, k2)
check(len(p.comments(0)) == 1, "comment deleted")
p.add_comment(1, "On slide two", "Someone Else", "SE")

out = os.path.join(tempfile.mkdtemp(), "t3.pptx")
p.save(out)
q = P.open(out)
check(q.link_at(0, tb, 0, 12) == "https://example.org/", "link survives saving")
check(len(q.comments(0)) == 1 and q.comments(1)[0][1] == "Someone Else", "comments survive saving")
check(abs(q.crop(2, pic)[0] - 0.25) < 1e-6, "crop survives saving")
z = zipfile.ZipFile(out)
names = z.namelist()
check("ppt/commentAuthors.xml" in names and any(n.startswith("ppt/comments/") for n in names), "comment parts written")
ct = z.read("[Content_Types].xml").decode()
check("commentAuthors+xml" in ct and "comments+xml" in ct, "content types")
rels = z.read("ppt/slides/_rels/slide1.xml.rels").decode()
check('TargetMode="External"' in rels and "hyperlink" in rels, "external link relationship")

# reuse slides from another presentation
SAMPLE = os.path.join(HERE, "data", "sample.pptx")
src = P.file_slides(SAMPLE)
check(len(src) >= 2, "slides of another file: %s" % src)
before = q.slide_count()
fallback = [x for _m, ls in q.layouts() for x, n in ls][0]
at = q.reuse_slides(SAMPLE, [0, 1], 0, fallback)
check(q.slide_count() == before + 2 and at == 1, "two slides reused after the first")
o = P.open(SAMPLE)
check(q.slide_text(1) and [t for _i, _p, t in q.slide_text(1)] == [t for _i, _p, t in o.slide_text(0)], "reused slide keeps its text")
w, h, _s, data, _sh = q.render(1, 0.25, False)
check(w > 0 and len(data) > 0, "reused slide renders")
q.undo()
check(q.slide_count() == before, "undo reuse")
q.redo()
# change picture
q.replace_picture(4, pic, png(10, 30), "png")
check(q.crop(4, pic) == (0, 0, 0, 0) and len(q.picture_data(4, pic)) < 400, "change picture")
# set up show
check(q.show_settings()[0] == "presented", "default show settings")
q.set_show_settings("kiosk", True, True, 2, 3, False, "00FF00")
check(q.show_settings() == ("kiosk", True, True, 2, 3, False, "00FF00"), "set up show: %s" % (q.show_settings(),))
out2 = os.path.join(tempfile.mkdtemp(), "t3b.pptx")
q.save(out2)
r = P.open(out2)
check(r.slide_count() == before + 2 and r.show_settings()[0] == "kiosk", "reopen keeps reused slides and show settings")
z = zipfile.ZipFile(out2)
check(z.testzip() is None, "package is sound")
# custom shows
r.set_custom_shows([("Short", [2, 0]), ("Just one", [1])])
check(r.custom_shows() == [("Short", [2, 0]), ("Just one", [1])], "custom shows")
r.undo()
check(r.custom_shows() == [], "undo custom shows")
r.redo()
# pictures pasted into another presentation
xml = r.shapes_xml(4, [pic])
media = r.shape_media(4, xml)
check(len(media) == 1 and media[0][1].endswith("/image") and len(media[0][3]) > 20, "copied picture carries its file")
t = P.open(BLANK)
new = t.paste_shapes_media(0, xml, [(a, b, c, bytes(dd), e, f) for a, b, c, dd, e, f in media], 0, 0)
check(len(new) == 1 and t.picture_data(0, new[0]) == bytes(media[0][3]), "the picture arrives in the other presentation")
new2 = t.paste_shapes_media(0, xml, [(a, b, c, bytes(dd), e, f) for a, b, c, dd, e, f in media], 10, 10)
z2 = os.path.join(tempfile.mkdtemp(), "t3c.pptx")
t.save(z2)
check(len([n for n in zipfile.ZipFile(z2).namelist() if n.startswith("ppt/media/")]) == 1, "the same picture is stored once")
print("saved", out, out2)
print("FAILED: %d" % len(FAILS) if FAILS else "all passed")
sys.exit(1 if FAILS else 0)

"""Engine and file tests for Backlog 12: characters XML can't hold, damaged slides put right, a
repeated picture stored once, text boxes told apart, slides copied between presentations, and the
file writer (kinds, macros, links, permissions, failures, plain messages). deliver_core on PYTHONPATH."""
import os
import stat
import sys
import tempfile
import xml.dom.minidom
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "app"))
import deliver_core as d  # noqa: E402
from folio_deliver import savefile  # noqa: E402

BLANK = os.path.join(HERE, "..", "share", "templates", "Blank.pptx")
T = tempfile.mkdtemp(prefix="show-b12-")
FAILS = []


def check(cond, what):
    print(("ok   " if cond else "FAIL ") + what)
    sys.stdout.flush()
    if not cond:
        FAILS.append(what)


def bad_xml(path):
    z = zipfile.ZipFile(path)
    out = []
    for n in z.namelist():
        if n.endswith((".xml", ".rels")):
            try:
                xml.dom.minidom.parseString(z.read(n))
            except Exception:
                out.append(n)
    return out


def rezip(path, drop=(), change=None, add=None):
    src = zipfile.ZipFile(BLANK)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for n in src.namelist():
            if n in drop:
                continue
            b = src.read(n)
            if change and n in change:
                b = change[n](b)
            z.writestr(n, b)
        for n, b in (add or {}).items():
            z.writestr(n, b)
    return path


def layout(p, name):
    return [part for _m, ls in p.layouts() for part, n in ls if n == name][0]


def title(p, i=0):
    return [s for s in p.shapes(i) if s["ph"] in ("ctrTitle", "title")][0]["id"]


# ---- S12-02 characters XML can't hold are left out
p = d.Presentation.open(BLANK)
tid = title(p)
p.set_text(0, tid, "bell\x07 null\x00 esc\x1b ff\x0c x￾y tab\tok")
p.set_notes(0, "notes\x01 too\x1f")
p.add_comment(0, "comment\x02", "A\x03uthor", "AU", 10, 10)
p.save(T + "/ctrl.pptx")
check(bad_xml(T + "/ctrl.pptx") == [], "S12-02: text with control characters still makes valid XML")
q = d.Presentation.open(T + "/ctrl.pptx")
check(q.paragraphs(0, tid) == ["bell null esc ff xy tab\tok"], "S12-02: the characters around them are kept: %r" % q.paragraphs(0, tid))
check(q.notes(0) == "notes too", "S12-02: notes too")
p = d.Presentation.open(BLANK)
p.set_text(0, title(p), "日本語 שלום 👋🏽 é <&>")
p.save(T + "/scripts.pptx")
check(d.Presentation.open(T + "/scripts.pptx").paragraphs(0, title(p)) == ["日本語 שלום 👋🏽 é <&>"], "S12-02: every script and XML's own characters still round-trip")

# ---- S12-08 a damaged slide is put right and said
cut = rezip(T + "/cut.pptx", change={"ppt/slides/slide1.xml": lambda b: b[:len(b) // 2]})
q = d.Presentation.open(cut)
check(q.repair() == ([1], 0), "S12-08: a slide whose XML is cut short is emptied, and named")
q.save(T + "/cut_saved.pptx")
check(bad_xml(T + "/cut_saved.pptx") == [] and d.Presentation.open(T + "/cut_saved.pptx").slide_count() == 1,
      "S12-08: and the file saved from it is whole")
gone = rezip(T + "/gone.pptx", drop={"ppt/slides/slide1.xml"})
q = d.Presentation.open(gone)
check(q.repair() == ([], 1), "S12-08: a slide the file lists but doesn't hold is counted")
q.save(T + "/gone_saved.pptx")
z = zipfile.ZipFile(T + "/gone_saved.pptx")
check("<p:sldId " not in z.read("ppt/presentation.xml").decode() and "slides/slide1.xml" not in z.read("ppt/_rels/presentation.xml.rels").decode(),
      "S12-08: and the saved file no longer lists it")
q = d.Presentation.open(BLANK)
check(q.repair() == ([], 0) and not q.modified, "S12-08: a whole file needs nothing")

# ---- S12-11 the same picture again is stored once
img = open(os.path.join(HERE, "data", "diagram.png"), "rb").read()
p = d.Presentation.open(BLANK)
for i in range(5):
    p.new_slide(i, layout(p, "Blank"))
for i in range(6):
    p.add_picture(i, img, "png", "Picture", 10, 10, 200, 100)
p.add_picture(0, img + b"\0", "png", "Other", 10, 10, 200, 100)
p.save(T + "/pics.pptx")
media = [n for n in zipfile.ZipFile(T + "/pics.pptx").namelist() if n.startswith("ppt/media/")]
check(len(media) == 2, "S12-11: six copies of one picture are stored once (and a different one apart): %s" % media)
for k in range(3):
    p.undo()
p.save(T + "/pics2.pptx")
check(len([n for n in zipfile.ZipFile(T + "/pics2.pptx").namelist() if n.startswith("ppt/media/")]) == 1,
      "S12-11: undoing some of them keeps the picture the rest use")
q = d.Presentation.open(T + "/pics2.pptx")
check(sum(1 for i in range(q.slide_count()) for s in q.shapes(i) if s["kind"] == "pic") == 4, "S12-11: the other pictures still show it")

# ---- S12-09 text boxes are told apart from shapes
p = d.Presentation.open(BLANK)
tb = p.add_textbox(0, 10, 10, 100, 30, "words")
sh = p.add_shape(0, "rect", 100, 100, 80, 40)
info = {s["id"]: s for s in p.shapes(0)}
check(info[tb]["txbox"] is True and info[sh]["txbox"] is False, "S12-09: a text box says so; a rectangle doesn't")

# ---- S12-04 slides from another presentation's bytes
src = d.Presentation.open(BLANK)
src.new_slide(0, layout(src, "Title and Content"))
src.set_text(1, title(src, 1), "From elsewhere")
data = bytes(src.to_bytes())
dst = d.Presentation.open(BLANK)
at = dst.reuse_slides_from(data, [1], 0, dst.slide_layout(0))
check(at == 1 and dst.slide_count() == 2 and any(s[2] == ["From elsewhere"] for s in dst.slide_text(1)),
      "S12-04: copied slides go into another presentation from its bytes")
dst.undo()
check(dst.slide_count() == 1, "S12-04: as one undo step")

# ---- S12-03 the package is the kind its name says
MACRO = savefile.CT["pptm"]
src = zipfile.ZipFile(BLANK)
with zipfile.ZipFile(T + "/m.pptm", "w", zipfile.ZIP_DEFLATED) as z:
    for n in src.namelist():
        b = src.read(n)
        if n == "[Content_Types].xml":
            b = b.replace(savefile.CT["pptx"].encode(), MACRO.encode()).replace(
                b"</Types>", b'<Default Extension="bin" ContentType="application/vnd.ms-office.vbaProject"/></Types>')
        if n == "ppt/_rels/presentation.xml.rels":
            b = b.replace(b"</Relationships>", b'<Relationship Id="rId99" Type="http://schemas.microsoft.com/office/2006/relationships/vbaProject" Target="vbaProject.bin"/></Relationships>')
        z.writestr(n, b)
    z.writestr("ppt/vbaProject.bin", b"\xd0\xcf\x11\xe0" + b"\0" * 400)
raw = bytes(d.Presentation.open(T + "/m.pptm").to_bytes())
out, dropped = savefile.package_as(raw, "pptx")
z = zipfile.ZipFile(__import__("io").BytesIO(out))
ct = z.read("[Content_Types].xml").decode()
check(dropped and savefile.CT["pptx"] in ct and MACRO not in ct and "ppt/vbaProject.bin" not in z.namelist()
      and "vbaProject" not in z.read("ppt/_rels/presentation.xml.rels").decode() and "vbaProject" not in ct,
      "S12-03: a macro deck saved as .pptx is a plain presentation, macros left out and said")
out, dropped = savefile.package_as(raw, "pptm")
check(not dropped and "ppt/vbaProject.bin" in zipfile.ZipFile(__import__("io").BytesIO(out)).namelist()
      and MACRO in zipfile.ZipFile(__import__("io").BytesIO(out)).read("[Content_Types].xml").decode(),
      "S12-03: saved as .pptm it keeps them")
with zipfile.ZipFile(T + "/t.potx", "w", zipfile.ZIP_DEFLATED) as z:
    for n in src.namelist():
        b = src.read(n)
        if n == "[Content_Types].xml":
            b = b.replace(savefile.CT["pptx"].encode(), savefile.CT["potx"].encode())
        z.writestr(n, b)
raw = bytes(d.Presentation.open(T + "/t.potx").to_bytes())
for kind in ("pptx", "ppsx", "potx"):
    out, _ = savefile.package_as(raw, kind)
    ct = zipfile.ZipFile(__import__("io").BytesIO(out)).read("[Content_Types].xml").decode()
    check(savefile.CT[kind] in ct and sum(v in ct for v in savefile.CT.values()) == 1,
          "S12-03: a deck from a template saved as .%s has that type only" % kind)
check(savefile.kind_of("a/b.PPSX") == "ppsx" and savefile.kind_of("x.odp") == "pptx", "S12-03: the kind comes from the name")

# ---- S12-06, S12-07 the writer
f = T + "/w.pptx"
open(f, "wb").write(b"old")
os.chmod(f, 0o640)
savefile.write_atomic(f, b"new")
check(open(f, "rb").read() == b"new" and stat.S_IMODE(os.stat(f).st_mode) == 0o640, "S12-06: saving keeps the file's permissions")
os.symlink(f, T + "/link.pptx")
savefile.write_atomic(T + "/link.pptx", b"through the link")
check(os.path.islink(T + "/link.pptx") and open(f, "rb").read() == b"through the link", "S12-06: saving through a link keeps the link")
try:
    savefile.write_atomic(T + "/no/such/folder/x.pptx", b"x")
    check(False, "S12-06: a missing folder fails")
except OSError as e:
    check(savefile.plain_error(e) == "The folder isn't there any more.", "S12-06: a missing folder is said plainly: %s" % savefile.plain_error(e))
check(not [n for n in os.listdir(T) if n.endswith(".folio-tmp")], "S12-06: no half-written file is left behind")
a = savefile.stamp(f)
import time  # noqa: E402
time.sleep(0.02)
open(f, "ab").write(b"!")
check(savefile.stamp(f) != a, "S12-07: a save by another program is noticed")
check(savefile.plain_error(ValueError("not a valid document package: invalid Zip archive: Could not find EOCD"))
      == "It isn't a PowerPoint presentation, or it's damaged.", "S12-12: a damaged file is said in plain words")

print("all passed" if not FAILS else "FAILED: %d" % len(FAILS))
sys.exit(1 if FAILS else 0)

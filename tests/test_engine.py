"""Engine tests: editing, undo and round-trip. Run with deliver_core on PYTHONPATH."""
import os, sys, tempfile, zipfile
import deliver_core as d

HERE = os.path.dirname(os.path.abspath(__file__))
BLANK = os.path.join(HERE, "..", "share", "templates", "Blank.pptx")
FAILS = []


def check(cond, what):
    print(("ok   " if cond else "FAIL ") + what)
    if not cond:
        FAILS.append(what)


def layout_named(p, name):
    for m, ls in p.layouts():
        for part, n in ls:
            if n == name:
                return part
    raise KeyError(name)


p = d.Presentation.open(BLANK)
check(p.slide_count() == 1, "blank has one slide")
check(p.size() == (960.0, 540.0), "16:9 size")
names = [n for m, ls in p.layouts() for _, n in ls]
check(len(names) == 11 and "Title and Content" in names, "11 layouts")

# title slide text
sh = {s["ph"]: s for s in p.shapes(0)}
check(sh["ctrTitle"]["empty"], "title starts empty")
p.set_text(0, sh["ctrTitle"]["id"], "Hello Deliver")
check(p.paragraphs(0, sh["ctrTitle"]["id"]) == ["Hello Deliver"], "set title text")
p.undo()
check(p.paragraphs(0, sh["ctrTitle"]["id"]) == [""], "undo title text")
p.redo()
check(p.paragraphs(0, sh["ctrTitle"]["id"]) == ["Hello Deliver"], "redo title text")

# typing, splitting, deleting
tid = sh["ctrTitle"]["id"]
pos = p.insert_text(0, tid, 0, 5, ",")
check(pos == (0, 6) and p.paragraphs(0, tid) == ["Hello, Deliver"], "insert in run")
pos = p.insert_text(0, tid, 0, 6, "\nnew")
check(p.paragraphs(0, tid) == ["Hello,", "new Deliver"] and pos == (1, 3), "split paragraph")
p.delete_text(0, tid, (0, 6), (1, 0))
check(p.paragraphs(0, tid) == ["Hello,new Deliver"], "join paragraphs")
p.delete_text(0, tid, (0, 0), (0, 6))
check(p.paragraphs(0, tid) == ["new Deliver"], "delete range")
p.insert_text(0, tid, 0, 3, "\x0b")
check(p.paragraphs(0, tid) == ["new\n Deliver"], "line break")

# formatting
p.format_runs(0, tid, (0, 0), (0, 3), "b", "1")
check(p.run_props(0, tid, 0, 1)["b"] and not p.run_props(0, tid, 0, 6)["b"], "bold part of a paragraph")
p.format_runs(0, tid, (0, 0), (0, 3), "sz", "60")
check(p.run_props(0, tid, 0, 2)["sz"] == 60, "font size")
p.format_runs(0, tid, (0, 0), (0, 3), "color", "FF8200")
check(p.run_props(0, tid, 0, 2)["color"] == "FF8200", "font colour")
p.format_paras(0, tid, 0, 0, "algn", "r")
check(p.para_props(0, tid, 0)["algn"] == "r", "align right")

# slides
tc = layout_named(p, "Title and Content")
i = p.new_slide(0, tc)
check(i == 1 and p.slide_count() == 2, "new slide")
check(p.slide_layout(1) == tc, "new slide layout")
phs = sorted(str(s["ph"]) for s in p.shapes(1))
check(phs == ["None", "title"] or phs == ["body", "title"], "placeholders copied: %s" % phs)
body = [s for s in p.shapes(1) if s["ph"] != "title"][0]["id"]
p.set_text(1, body, "One\nTwo\nThree")
p.format_paras(1, body, 1, 1, "lvl", "1")
check(p.para_props(1, body, 1)["lvl"] == 1, "demote")
j = p.duplicate_slides([1])
check(j == 2 and p.slide_count() == 3, "duplicate")
check(p.paragraphs(2, body) == ["One", "Two", "Three"], "duplicate keeps text")
p.move_slides([2], 0)
check(p.paragraphs(0, body) == ["One", "Two", "Three"], "move to front")
p.set_hidden([0], True)
check(p.is_hidden(0), "hide")
p.delete_slides([0])
check(p.slide_count() == 2, "delete")
p.undo()
check(p.slide_count() == 3 and p.is_hidden(0), "undo delete")
p.redo()
p.set_layout([1], layout_named(p, "Title Only"))
check([s["ph"] for s in p.shapes(1)] == ["title", "body"], "change layout keeps a body with text")
p.set_layout([0], layout_named(p, "Blank"))
check([s["ph"] for s in p.shapes(0)] == ["ctrTitle"], "change layout keeps a title with text, drops the empty subtitle: %s" % [s["ph"] for s in p.shapes(0)])
p.undo()

# shapes
sid = p.add_shape(0, "roundRect", 100, 100, 200, 100)
tb = p.add_textbox(0, 100, 300, 300, 40, "A text box")
check(len(p.shapes(0)) == 4, "two objects added")
p.set_boxes(0, [(sid, 120, 110, 220, 90, 15.0)])
s = [x for x in p.shapes(0) if x["id"] == sid][0]
check(abs(s["x"] - 120) < 0.01 and abs(s["rot"] - 15) < 0.01, "move and rotate")
g = p.group(0, [sid, tb])
check([x["kind"] for x in p.shapes(0)][-1] == "grpSp", "group")
p.ungroup(0, g)
check(sorted(x["id"] for x in p.shapes(0) if x["kind"] != "grpSp")[-2:] == sorted([sid, tb]), "ungroup")
p.reorder(0, [sid], "back")
check(p.shapes(0)[0]["id"] == sid, "send to back")
dup = p.duplicate_shapes(0, [sid], 10, 10)
check(len(dup) == 1 and len(p.shapes(0)) == 5, "duplicate shape")
p.delete_shapes(0, dup)
check(len(p.shapes(0)) == 4, "delete shape")

# picture
png = os.path.join(tempfile.mkdtemp(), "x.png")
p.export_png(1, png, 200)
data = open(png, "rb").read()
pid = p.add_picture(0, data, "png", "x.png", 500, 300, 200, 112)
check(any(x["id"] == pid and x["kind"] == "pic" for x in p.shapes(0)), "picture")

# caret and hit
c = p.caret(1, [s for s in p.shapes(1) if s["ph"] == "title"][0]["id"], 0, 0)
check(c is not None, "caret")

# save and reopen
out = os.path.join(tempfile.mkdtemp(), "t.pptx")
p.save(out)
q = d.Presentation.open(out)
check(q.slide_count() == 2, "reopen slide count")
check(q.paragraphs(0, tb) == ["A text box"], "reopen text")
with zipfile.ZipFile(out) as z:
    bad = z.testzip()
    check(bad is None, "zip ok")
    names = z.namelist()
    check(sum(1 for n in names if n.startswith("ppt/slides/slide") and n.endswith(".xml")) == 2, "slide parts on disk")
pdf = out.replace(".pptx", ".pdf")
q.export_pdf(pdf)
check(os.path.getsize(pdf) > 1000, "pdf export")
print("saved", out)
print("FAILED: %d" % len(FAILS) if FAILS else "all passed")
sys.exit(1 if FAILS else 0)

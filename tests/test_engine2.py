"""Engine tests, part 2: tables, header and footer, slide size, sections, transitions, theme."""
import os
import sys
import tempfile

import deliver_core as d

HERE = os.path.dirname(os.path.abspath(__file__))
BLANK = os.path.join(HERE, "..", "share", "templates", "Blank.pptx")
FAILS = []


def check(cond, what):
    print(("ok   " if cond else "FAIL ") + what)
    if not cond:
        FAILS.append(what)


def layout_named(p, name):
    for _m, ls in p.layouts():
        for part, n in ls:
            if n == name:
                return part
    raise KeyError(name)


P = d.Presentation
p = P.open(BLANK)
p.new_slide(0, layout_named(p, "Title Only"))
p.new_slide(1, layout_named(p, "Title and Content"))

# tables
t = p.add_table(1, 3, 4, 60, 120, 840)
check(p.table_size(1, t) == (3, 4), "3 x 4 table")
cells = p.table_cells(1, t)
check(len(cells) == 12 and abs(cells[1][3] - cells[0][3] - 210) < 0.5, "cells laid out on the grid")
c5 = P.cell_id(t, 5)
check(P.split_id(c5) == (t, 5), "cell ids")
p.insert_text(1, c5, 0, 0, "Revenue")
check(p.paragraphs(1, c5) == ["Revenue"], "typing in a cell")
p.format_runs(1, c5, (0, 0), (0, 7), "b", "1")
check(p.run_props(1, c5, 0, 2)["b"], "bold in a cell")
check(p.caret(1, c5, 0, 3) is not None, "caret in a cell")
p.table_insert_row(1, t, 1)
check(p.table_size(1, t) == (4, 4) and p.paragraphs(1, P.cell_id(t, 9)) == ["Revenue"], "row inserted above keeps text below")
p.table_insert_col(1, t, 4)
check(p.table_size(1, t) == (4, 5), "column inserted at the end")
p.table_delete_col(1, t, 0)
check(p.table_size(1, t) == (4, 4), "column deleted")
p.table_option(1, t, "bandRow", False)
check(not p.table_option_value(1, t, "bandRow") and p.table_option_value(1, t, "firstRow"), "table style options")
p.table_shade(1, t, [0, 1], "FF8200")
p.undo()
p.redo()
check(p.table_size(1, t) == (4, 4), "undo/redo in tables")

# header and footer
p.set_header_footer([0, 1, 2], "", True, "Folio test", True)
hf0 = p.header_footer(0)
hf1 = p.header_footer(1)
check(hf0 == (False, "", False, False, ""), "not on the title slide: %s" % (hf0,))
check(hf1[0] and hf1[1] == "" and hf1[2] and hf1[3] and hf1[4] == "Folio test", "date, number and footer: %s" % (hf1,))
phs = [s["ph"] for s in p.shapes(1)]
check("sldNum" in phs and "ftr" in phs and "dt" in phs, "footer placeholders on the slide")
p.set_header_footer([1], "1/2/2027", False, None, False)
check(p.header_footer(1) == (True, "1/2/2027", False, False, ""), "fixed date only: %s" % (p.header_footer(1),))

# slide size
before = [s for s in p.shapes(1) if s["id"] == t][0]
p.set_slide_size(720, 540, "fit")
check(p.size() == (720.0, 540.0), "4:3")
after = [s for s in p.shapes(1) if s["id"] == t][0]
check(abs(after["w"] - before["w"] * 0.75) < 1 and after["x"] >= 0, "content scaled to fit")
p.undo()
check(p.size() == (960.0, 540.0), "undo slide size")

# sections
check(p.sections() == [], "no sections")
p.write_sections([("Intro", 0), ("Body", 1)], "Add Section")
s = p.sections()
check(s == [("Intro", 0, 1), ("Body", 1, 2)], "two sections: %s" % (s,))
p.move_slides([2], 0)
s = p.sections()
check(s == [("Intro", 0, 2), ("Body", 2, 1)], "a slide moved to the front joins the first section: %s" % (s,))
p.undo()

# transitions
check(p.transition(0)[0] == "none", "no transition")
p.set_transition([0, 1], "push", "l", 1.0, True, 3.0)
tr = p.transition(1)
check(tr[0] == "push" and tr[1] == "l" and tr[2] == 1.0 and tr[3] and tr[4] == 3.0, "push from left, after 3 s: %s" % (tr,))
p.set_transition([1], "fade", "", 0.5, False, -1)
tr = p.transition(1)
check(tr[0] == "fade" and not tr[3], "fade, no click: %s" % (tr,))

# theme
cols, major, minor = p.theme_info()
check(dict(cols)["accent1"] == 0x4472C4 and minor == "Calibri", "Office theme")
p.set_theme("Folio Orange", [0, 0xFFFFFF, 0x333333, 0xEEEEEE, 0xFF8200, 0x58595B, 0xA7A9AC, 0xFFB81C, 0x006C93, 0x4E2A84,
                            0x0563C1, 0x954F72], "Liberation Serif", "Liberation Sans")
cols, major, minor = p.theme_info()
check(dict(cols)["accent1"] == 0xFF8200 and major == "Liberation Serif", "theme colours and fonts changed")

out = os.path.join(tempfile.mkdtemp(), "t2.pptx")
p.save(out)
q = P.open(out)
check(q.slide_count() == 3 and len(q.sections()) == 2 and q.transition(1)[0] == "fade", "reopen keeps sections and transitions")
print("saved", out)
print("FAILED: %d" % len(FAILS) if FAILS else "all passed")
sys.exit(1 if FAILS else 0)

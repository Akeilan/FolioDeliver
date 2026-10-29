"""Outlines for Insert > New Slide > Slides from Outline: a text file (indent = level) or a
Folio Page / Word document (Heading 1 = slide title, Heading 2..n = bullet levels)."""
import re
import zipfile

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def _from_text(path):
    items = []
    with open(path, encoding="utf-8-sig", errors="replace") as f:
        for line in f:
            raw = line.rstrip("\n\r")
            if not raw.strip():
                continue
            tabs = len(raw) - len(raw.lstrip("\t"))
            spaces = len(raw) - len(raw.lstrip(" "))
            level = tabs or spaces // 4
            text = raw.strip()
            if level == 0 or not items:
                items.append((text, []))
            else:
                items[-1][1].append((level - 1, text))
    return items


def _from_docx(path):
    import xml.etree.ElementTree as ET
    with zipfile.ZipFile(path) as z:
        root = ET.fromstring(z.read("word/document.xml"))
        styles = {}
        try:
            sroot = ET.fromstring(z.read("word/styles.xml"))
            for st in sroot.iter(W + "style"):
                sid = st.get(W + "styleId")
                name = st.find(W + "name")
                styles[sid] = name.get(W + "val") if name is not None else sid
        except KeyError:
            pass
    items = []
    for p in root.iter(W + "p"):
        ps = p.find(W + "pPr/" + W + "pStyle")
        style = styles.get(ps.get(W + "val"), ps.get(W + "val")) if ps is not None else ""
        text = "".join(t.text or "" for t in p.iter(W + "t")).strip()
        if not text:
            continue
        m = re.match(r"(?i)heading\s*(\d)", style or "")
        if m:
            lvl = int(m.group(1))
            if lvl == 1 or not items:
                items.append((text, []))
            else:
                items[-1][1].append((lvl - 2, text))
        elif items:
            items[-1][1].append((0, text))
    return items


def read_outline(path):
    if path.lower().endswith(".docx"):
        return _from_docx(path)
    return _from_text(path)

"""Package into a folder (P4-02): the deck and the files it links to, together in one folder so
the lot can be carried on a stick and opened anywhere."""
import os
import re
import shutil
import zipfile

LINKS_DIR = "Linked Files"
# a rels target that points at a file on this computer, rather than a web address
_SCHEME = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*:")


def local_path(target, base_dir):
    """The file a relationship target points at on this computer, or None for a web address."""
    t = (target or "").strip()
    if not t:
        return None
    if t.lower().startswith("file:///"):
        from urllib.parse import unquote
        return unquote(t[7:])
    if t.lower().startswith("file://"):
        from urllib.parse import unquote
        return unquote(t[5:])
    if _SCHEME.match(t):
        return None                      # http, https, mailto, ms-help and the like
    if t.startswith("#") or t.startswith("ppaction:"):
        return None
    t = t.replace("\\", "/")
    if t.startswith("/") or t.startswith("~"):
        return os.path.expanduser(t)
    return os.path.normpath(os.path.join(base_dir, t))


def externals(path):
    """Every external relationship of a .pptx: (part, id, target)."""
    out = []
    with zipfile.ZipFile(path) as z:
        for name in z.namelist():
            if not name.endswith(".rels"):
                continue
            xml = z.read(name).decode("utf-8", "replace")
            for m in re.finditer(r"<Relationship\b[^>]*>", xml):
                tag = m.group(0)
                if 'TargetMode="External"' not in tag:
                    continue
                rid = re.search(r'Id="([^"]+)"', tag)
                tgt = re.search(r'Target="([^"]*)"', tag)
                if rid and tgt:
                    out.append((name, rid.group(1), tgt.group(1)))
    return out


def package(deck_bytes, deck_name, dest, base_dir=""):
    """Write the deck into `dest` with the files it links to beside it, and point the links at
    the copies. Returns (the deck's path, the files copied, the links that could not be found)."""
    os.makedirs(dest, exist_ok=True)
    if not deck_name.lower().endswith((".pptx", ".ppsx", ".potx")):
        deck_name += ".pptx"
    out_deck = os.path.join(dest, deck_name)
    with open(out_deck, "wb") as f:
        f.write(deck_bytes)

    wanted = {}          # the file on this computer -> its name in the package
    missing = []
    for _part, _rid, target in externals(out_deck):
        p = local_path(target, base_dir)
        if p is None:
            continue
        if not os.path.isfile(p):
            missing.append(target)
            continue
        if p not in wanted:
            name = os.path.basename(p)
            taken = set(wanted.values())
            stem, ext = os.path.splitext(name)
            n = 2
            while name in taken:
                name = "%s %d%s" % (stem, n, ext)
                n += 1
            wanted[p] = name
    if not wanted:
        return out_deck, [], missing

    links = os.path.join(dest, LINKS_DIR)
    os.makedirs(links, exist_ok=True)
    copied = []
    for src, name in wanted.items():
        shutil.copy2(src, os.path.join(links, name))
        copied.append(name)

    # point every link at the copy beside the deck
    tmp = out_deck + ".tmp"
    with zipfile.ZipFile(out_deck) as z, zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as w:
        for item in z.infolist():
            data = z.read(item.filename)
            if item.filename.endswith(".rels"):
                xml = data.decode("utf-8", "replace")
                def fix(m, base_dir=base_dir):
                    tag = m.group(0)
                    if 'TargetMode="External"' not in tag:
                        return tag
                    tgt = re.search(r'Target="([^"]*)"', tag)
                    if not tgt:
                        return tag
                    p = local_path(tgt.group(1), base_dir)
                    if p is None or p not in wanted:
                        return tag
                    rel = "%s/%s" % (LINKS_DIR.replace(" ", "%20"), wanted[p].replace(" ", "%20"))
                    return tag.replace('Target="%s"' % tgt.group(1), 'Target="../../%s"' % rel)
                xml = re.sub(r"<Relationship\b[^>]*>", fix, xml)
                data = xml.encode("utf-8")
            w.writestr(item, data)
    os.replace(tmp, out_deck)
    return out_deck, sorted(copied), missing

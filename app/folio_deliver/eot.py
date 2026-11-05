"""Embedded fonts (File > Options > Save > Embed fonts in the file): PowerPoint keeps them as
Embedded OpenType (.fntdata). Writing an EOT around a TrueType/OpenType font, reading the font
back out of one, and finding the files of the fonts a presentation uses."""
import os
import struct
import subprocess

# fsType: embedding permissions in the font's OS/2 table
RESTRICTED = 0x0002


def _tables(ttf):
    if len(ttf) < 12:
        return {}
    n = struct.unpack_from(">H", ttf, 4)[0]
    out = {}
    for k in range(n):
        tag, _chk, off, ln = struct.unpack_from(">4sIII", ttf, 12 + 16 * k)
        out[tag.decode("latin-1")] = ttf[off:off + ln]
    return out


def _names(name_tbl):
    out = {}
    if len(name_tbl) < 6:
        return out
    _fmt, count, soff = struct.unpack_from(">HHH", name_tbl, 0)
    for k in range(count):
        pid, eid, lid, nid, ln, off = struct.unpack_from(">HHHHHH", name_tbl, 6 + 12 * k)
        raw = name_tbl[soff + off:soff + off + ln]
        if pid == 3 and nid not in out:
            out[nid] = raw.decode("utf-16-be", "replace")
        elif pid == 1 and nid not in out:
            out.setdefault(nid, raw.decode("mac_roman", "replace"))
    return out


def info(ttf):
    """family, style, fsType of a font file's bytes."""
    t = _tables(ttf)
    n = _names(t.get("name", b""))
    os2 = t.get("OS/2", b"")
    fstype = struct.unpack_from(">H", os2, 8)[0] if len(os2) >= 10 else 0
    return n.get(1, ""), n.get(2, ""), fstype


def can_embed(ttf):
    return not (info(ttf)[2] & 0x000F) == RESTRICTED


def _lpstr(s):
    b = s.encode("utf-16-le")
    return struct.pack("<H", len(b)) + b


def make(ttf):
    """An EOT (version 0x00020001, not compressed) around TrueType/OpenType font bytes."""
    t = _tables(ttf)
    os2 = t.get("OS/2", b"\0" * 96)
    head = t.get("head", b"\0" * 54)
    names = _names(t.get("name", b""))
    panose = os2[32:42] if len(os2) >= 42 else b"\0" * 10
    weight = struct.unpack_from(">H", os2, 4)[0] if len(os2) >= 6 else 400
    fstype = struct.unpack_from(">H", os2, 8)[0] if len(os2) >= 10 else 0
    ur = struct.unpack_from(">IIII", os2, 42) if len(os2) >= 58 else (0, 0, 0, 0)
    fs_sel = struct.unpack_from(">H", os2, 62)[0] if len(os2) >= 64 else 0
    cpr = struct.unpack_from(">II", os2, 78) if len(os2) >= 86 else (0, 0)
    chk = struct.unpack_from(">I", head, 8)[0] if len(head) >= 12 else 0
    body = (panose + struct.pack("<BB", 1, 1 if fs_sel & 1 else 0) + struct.pack("<I", weight) +
            struct.pack("<HH", fstype, 0x504C) + struct.pack("<IIII", *ur) + struct.pack("<II", *cpr) +
            struct.pack("<I", chk) + struct.pack("<IIII", 0, 0, 0, 0) + struct.pack("<H", 0) +
            _lpstr(names.get(1, "")) + struct.pack("<H", 0) + _lpstr(names.get(2, "")) + struct.pack("<H", 0) +
            _lpstr(names.get(5, "")) + struct.pack("<H", 0) + _lpstr(names.get(4, "")) + struct.pack("<H", 0) +
            struct.pack("<H", 0))
    head_len = 16 + len(body)
    return struct.pack("<IIII", head_len + len(ttf), len(ttf), 0x00020001, 0) + body + ttf


def font_of(eot):
    """The TrueType/OpenType bytes inside an EOT (None when MicroType-compressed)."""
    if len(eot) < 16:
        return None
    size, data_size, version, flags = struct.unpack_from("<IIII", eot, 0)
    if eot[:4] in (b"\0\1\0\0", b"OTTO", b"true"):
        return eot                         # some files store the font as it is
    if flags & 0x4:
        return None                        # MTX compression
    data = eot[size - data_size:size] if size <= len(eot) else eot[-data_size:]
    if flags & 0x10000000:
        data = bytes(b ^ 0x50 for b in data)
    return data if data[:4] in (b"\0\1\0\0", b"OTTO", b"true") else None


def find_font_file(family, bold=False, italic=False):
    """The file of an installed font (fontconfig), or None."""
    style = ":weight=%s:slant=%s" % ("bold" if bold else "regular", "italic" if italic else "roman")
    try:
        out = subprocess.run(["fc-match", "-f", "%{file}\n%{family}", family + style], capture_output=True, text=True,
                             timeout=10).stdout.splitlines()
    except Exception:
        return None
    if len(out) < 2:
        return None
    fam = [f.strip().lower() for f in out[1].split(",")]
    if family.lower() not in fam:
        return None                        # only that font, not a substitute
    return out[0] if os.path.exists(out[0]) else None


EMBED_DIR = os.path.join(os.path.expanduser("~"), ".local", "share", "fonts", "folio-embedded")


def install_for_show(data, name):
    """Put an embedded font where the font search finds it (removed when Show closes)."""
    os.makedirs(EMBED_DIR, exist_ok=True)
    path = os.path.join(EMBED_DIR, name)
    with open(path, "wb") as f:
        f.write(data)
    return path


def remove_installed():
    try:
        for f in os.listdir(EMBED_DIR):
            os.remove(os.path.join(EMBED_DIR, f))
        os.rmdir(EMBED_DIR)
    except OSError:
        pass


# ---------------------------------------------------------------- subsetting (P3-11)

def _cmap_glyphs(cmap, chars):
    """Glyph ids the font's Unicode cmap gives these characters."""
    if len(cmap) < 4:
        return set()
    n = struct.unpack_from(">H", cmap, 2)[0]
    subs = []
    for k in range(n):
        pid, eid, off = struct.unpack_from(">HHI", cmap, 4 + 8 * k)
        if (pid, eid) in ((3, 10), (0, 4), (0, 6), (3, 1), (0, 3), (0, 1), (0, 0)):
            subs.append(off)
    wanted = {ord(c) for c in chars}
    out = set()
    for off in subs:
        fmt = struct.unpack_from(">H", cmap, off)[0]
        if fmt == 4:
            seg2 = struct.unpack_from(">H", cmap, off + 6)[0]
            ends = off + 14
            starts = ends + seg2 + 2
            deltas = starts + seg2
            ranges = deltas + seg2
            for i in range(seg2 // 2):
                end = struct.unpack_from(">H", cmap, ends + 2 * i)[0]
                start = struct.unpack_from(">H", cmap, starts + 2 * i)[0]
                delta = struct.unpack_from(">h", cmap, deltas + 2 * i)[0]
                ro = struct.unpack_from(">H", cmap, ranges + 2 * i)[0]
                for c in wanted:
                    if start <= c <= end:
                        if ro == 0:
                            g = (c + delta) & 0xFFFF
                        else:
                            p = ranges + 2 * i + ro + 2 * (c - start)
                            g = struct.unpack_from(">H", cmap, p)[0] if p + 2 <= len(cmap) else 0
                            g = (g + delta) & 0xFFFF if g else 0
                        if g:
                            out.add(g)
        elif fmt == 12:
            ngroups = struct.unpack_from(">I", cmap, off + 12)[0]
            for i in range(ngroups):
                s, e, g0 = struct.unpack_from(">III", cmap, off + 16 + 12 * i)
                for c in wanted:
                    if s <= c <= e:
                        out.add(g0 + c - s)
    return out


def _checksum(b):
    b = b + b"\0" * (-len(b) % 4)
    return sum(struct.unpack(">%dI" % (len(b) // 4), b)) & 0xFFFFFFFF


def subset(ttf, chars):
    """The font with only the outlines of `chars` (and .notdef, and the parts composite glyphs
    are built from). Glyph numbers, the character map and the metrics stay as they were, so
    the file still reads everywhere; the other outlines are left empty, as PowerPoint's
    "embed only the characters used" does. Fonts without TrueType outlines come back whole."""
    if ttf[:4] not in (b"\0\1\0\0", b"true"):
        return ttf
    n = struct.unpack_from(">H", ttf, 4)[0]
    dirs = {}
    for k in range(n):
        tag, _chk, off, ln = struct.unpack_from(">4sIII", ttf, 12 + 16 * k)
        dirs[tag.decode("latin-1")] = (off, ln)
    if not all(t in dirs for t in ("glyf", "loca", "head", "maxp", "cmap")):
        return ttf
    tab = {t: ttf[o:o + l] for t, (o, l) in dirs.items()}
    head = bytearray(tab["head"])
    long_loca = struct.unpack_from(">h", head, 50)[0] == 1
    nglyphs = struct.unpack_from(">H", tab["maxp"], 4)[0]
    loca = tab["loca"]
    if long_loca:
        offs = list(struct.unpack(">%dI" % (nglyphs + 1), loca[:4 * (nglyphs + 1)]))
    else:
        offs = [2 * v for v in struct.unpack(">%dH" % (nglyphs + 1), loca[:2 * (nglyphs + 1)])]
    glyf = tab["glyf"]
    keep = {0} | {g for g in _cmap_glyphs(tab["cmap"], chars) if g < nglyphs}
    todo = list(keep)
    while todo:                            # composite glyphs pull in their parts
        g = todo.pop()
        a, b = offs[g], offs[g + 1]
        if b - a < 10 or struct.unpack_from(">h", glyf, a)[0] >= 0:
            continue
        p = a + 10
        while True:
            flags, comp = struct.unpack_from(">HH", glyf, p)
            if comp < nglyphs and comp not in keep:
                keep.add(comp)
                todo.append(comp)
            p += 4 + (4 if flags & 0x0001 else 2)
            if flags & 0x0008:
                p += 2
            elif flags & 0x0040:
                p += 4
            elif flags & 0x0080:
                p += 8
            if not flags & 0x0020:
                break
    new_glyf = bytearray()
    new_offs = []
    for g in range(nglyphs):
        new_offs.append(len(new_glyf))
        if g in keep:
            new_glyf += glyf[offs[g]:offs[g + 1]]
            new_glyf += b"\0" * (-len(new_glyf) % 4)
    new_offs.append(len(new_glyf))
    tab["glyf"] = bytes(new_glyf)
    tab["loca"] = struct.pack(">%dI" % len(new_offs), *new_offs)
    struct.pack_into(">h", head, 50, 1)    # long offsets
    struct.pack_into(">I", head, 8, 0)     # checksum adjustment, set below
    tab["head"] = bytes(head)
    tags = sorted(tab)
    numt = len(tags)
    es = max(k for k in range(16) if 2 ** k <= numt)
    out = bytearray(struct.pack(">IHHHH", 0x00010000, numt, 16 * 2 ** es, es, numt * 16 - 16 * 2 ** es))
    off = 12 + 16 * numt
    body = bytearray()
    recs = []
    for t in tags:
        data = tab[t]
        recs.append(struct.pack(">4sIII", t.encode("latin-1"), _checksum(data), off + len(body), len(data)))
        body += data + b"\0" * (-len(data) % 4)
    out += b"".join(recs) + body
    adj = (0xB1B0AFBA - _checksum(bytes(out))) & 0xFFFFFFFF
    hp = off + sum(len(tab[t]) + (-len(tab[t]) % 4) for t in tags[:tags.index("head")])
    struct.pack_into(">I", out, hp + 8, adj)
    return bytes(out)

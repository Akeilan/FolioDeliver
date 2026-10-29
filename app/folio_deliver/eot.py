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

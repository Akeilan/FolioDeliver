"""Writing a presentation file: the package made the kind its name says (S12-03), and the bytes put
on disk so that a failed save never leaves half a file, a link stays a link and the file keeps who
may read it."""
import io
import os
import re
import zipfile

CT = {
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml",
    "pptm": "application/vnd.ms-powerpoint.presentation.macroEnabled.main+xml",
    "ppsx": "application/vnd.openxmlformats-officedocument.presentationml.slideshow.main+xml",
    "ppsm": "application/vnd.ms-powerpoint.slideshow.macroEnabled.main+xml",
    "potx": "application/vnd.openxmlformats-officedocument.presentationml.template.main+xml",
    "potm": "application/vnd.ms-powerpoint.template.macroEnabled.main+xml",
}
MACRO_KINDS = ("pptm", "ppsm", "potm")
VBA_TYPES = ("application/vnd.ms-office.vbaProject", "application/vnd.ms-office.vbaProjectSignature",
             "application/vnd.ms-office.vbaProjectSignatureAgile", "application/vnd.ms-office.vbaProjectSignatureV3",
             "application/vnd.ms-office.vbaData+xml")
_MAIN = re.compile(r'(<Override\b[^>]*ContentType=")(' + "|".join(re.escape(v) for v in CT.values()) + r')(")')


def kind_of(path):
    """The kind of presentation a file name asks for ("pptx" for anything else)."""
    ext = os.path.splitext(path)[1].lower().lstrip(".")
    return ext if ext in CT else "pptx"


def package_as(data, kind):
    """The package as the kind its name says: its main part's type set to match, and the macros left
    out of a kind that can't hold them. Returns (bytes, whether macros were left out)."""
    src = zipfile.ZipFile(io.BytesIO(data))
    names = src.namelist()
    ct = src.read("[Content_Types].xml").decode("utf-8")
    ct = _MAIN.sub(lambda m: m.group(1) + CT[kind] + m.group(3), ct)
    drop = set()
    if kind not in MACRO_KINDS:
        # the parts the content types call macros, by name or by ending
        for m in re.finditer(r'<Override\b[^>]*PartName="/([^"]+)"[^>]*ContentType="([^"]+)"', ct):
            if m.group(2) in VBA_TYPES:
                drop.add(m.group(1))
        for m in re.finditer(r'<Default\b[^>]*Extension="([^"]+)"[^>]*ContentType="([^"]+)"', ct):
            if m.group(2) in VBA_TYPES:
                drop.update(n for n in names if n.lower().endswith("." + m.group(1).lower()))
        drop.update(n for n in names if os.path.basename(n).lower() in ("vbaproject.bin", "vbadata.xml"))
        drop &= set(names)
        drop.update(n for n in names if any(n == os.path.dirname(d) + "/_rels/" + os.path.basename(d) + ".rels" for d in drop))
        if drop:
            ct = re.sub(r'<Override\b[^>]*PartName="/(?:%s)"[^>]*/>' % "|".join(re.escape(d) for d in drop), "", ct)
            ct = re.sub(r'<Default\b[^>]*ContentType="(?:%s)"[^>]*/>' % "|".join(re.escape(v) for v in VBA_TYPES), "", ct)
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for it in src.infolist():
            if it.filename in drop:
                continue
            b = src.read(it.filename)
            if it.filename == "[Content_Types].xml":
                b = ct.encode("utf-8")
            elif drop and it.filename.endswith(".rels"):
                b = re.sub(rb'<Relationship\b[^>]*Type="[^"]*/(?:vbaProject|vbaProjectSignature|wordVbaData|vbaData)"[^>]*/>', b"", b)
            z.writestr(it, b)
    return out.getvalue(), bool(drop)


def write_atomic(path, data):
    """Put data in the file at path: written beside it and then put in its place, so a failed save
    leaves the old file as it was. A link is followed (the file it points at is replaced, the link
    stays), and the file keeps its permissions."""
    real = os.path.realpath(path)
    tmp = os.path.join(os.path.dirname(real), ".%s.folio-tmp" % os.path.basename(real))
    try:
        mode = os.stat(real).st_mode & 0o7777
    except OSError:
        mode = None
    try:
        with open(tmp, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        if mode is not None:
            os.chmod(tmp, mode)
        os.replace(tmp, real)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def stamp(path):
    """What the file on disk is now (to notice another program saving it, S12-07), or None."""
    try:
        st = os.stat(path)
    except OSError:
        return None
    return (st.st_mtime_ns, st.st_size)


def plain_error(e):
    """An error from opening or saving, in words a person can act on (S12-12)."""
    import errno
    if isinstance(e, OSError) and e.errno is not None:
        return {errno.ENOENT: "The folder isn't there any more.",
                errno.EACCES: "You don't have permission to write there.",
                errno.EPERM: "You don't have permission to write there.",
                errno.EROFS: "That drive can only be read.",
                errno.ENOSPC: "The disk is full.",
                errno.EDQUOT: "The disk is full.",
                errno.ENAMETOOLONG: "The file name is too long.",
                errno.EISDIR: "That name belongs to a folder."}.get(e.errno, e.strerror or str(e))
    s = str(e)
    low = s.lower()
    if "os error 2)" in low or "no such file" in low:
        return "The folder isn't there any more."
    if "os error 13)" in low or "permission denied" in low:
        return "You don't have permission to write there."
    if "os error 28)" in low or "no space" in low:
        return "The disk is full."
    if "os error 30)" in low or "read-only file system" in low:
        return "That drive can only be read."
    if "zip" in low or "eocd" in low or "not a valid document package" in low:
        return "It isn't a PowerPoint presentation, or it's damaged."
    if "no presentation in it" in low:
        return "It's a package, but there's no presentation in it."
    if "write error" in low:
        return "The file couldn't be written there."
    return s[:1].upper() + s[1:] if s else "Something went wrong."

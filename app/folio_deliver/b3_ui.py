"""Backlog 3 commands: Merge Shapes, the Eyedropper, Action Settings, Zoom, Protect Presentation,
Compare, Compress Media, embedded fonts and Options, 3-D models and Cameo (a mixin of the
window)."""
import io
import math
import os
import re
import subprocess
import tempfile
import uuid
import wave
import struct

import cairo
from gi.repository import Gdk, GLib, Gtk

from . import APP_NAME
from .core import EMU_PT, surface_from

NS_MC = "http://schemas.openxmlformats.org/markup-compatibility/2006"
NS_PSLZ = "http://schemas.microsoft.com/office/powerpoint/2016/slidezoom"
NS_PSEZ = "http://schemas.microsoft.com/office/powerpoint/2016/sectionzoom"
NS_P166 = "http://schemas.microsoft.com/office/powerpoint/2016/6/main"
NS_AM3D = "http://schemas.microsoft.com/office/drawing/2017/model3d"
REL_MODEL = "http://schemas.microsoft.com/office/2017/06/relationships/model3d"
CAMEO_URI = "{9C2B8A1E-4D7F-4A3B-9E61-F01C0D0CA4E0}"


def emu(pt):
    return int(round(pt * EMU_PT))


def xesc(s):
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def png_bytes(surface):
    b = io.BytesIO()
    surface.write_to_png(b)
    return b.getvalue()


def slide_png(deck, i, width=640):
    sw, sh = deck.size()
    scale = width / sw
    pw, ph, stride, data, _ = deck.render(i, scale, False)
    return png_bytes(surface_from(pw, ph, stride, data))


# ---------------------------------------------------------------- sounds for actions
SOUNDS = ["Applause", "Arrow", "Bomb", "Breeze", "Camera", "Cash Register", "Chime", "Click", "Coin", "Drum Roll", "Explosion",
          "Hammer", "Laser", "Push", "Suction", "Typewriter", "Voltage", "Whoosh", "Wind"]


def synth_sound(name, rate=22050):
    """A short sound for an action, made here (WAV bytes)."""
    import random
    rnd = random.Random(name)
    n = int(rate * (1.4 if name in ("Applause", "Drum Roll", "Breeze", "Wind") else 0.5))
    out = []
    for k in range(n):
        t = k / rate
        env = math.exp(-t * (2.5 if name in ("Applause", "Drum Roll", "Breeze", "Wind") else 9))
        if name in ("Chime", "Cash Register", "Coin"):
            f = {"Chime": 880, "Cash Register": 1320, "Coin": 1760}[name]
            v = math.sin(2 * math.pi * f * t) * 0.6 + math.sin(2 * math.pi * f * 1.5 * t) * 0.3
        elif name in ("Laser", "Voltage"):
            v = math.sin(2 * math.pi * (1800 - 2400 * t) * t) * 0.7
        elif name in ("Drum Roll", "Typewriter", "Hammer", "Camera", "Click", "Arrow"):
            period = {"Drum Roll": 0.04, "Typewriter": 0.09, "Hammer": 0.2, "Camera": 0.25, "Click": 1.0, "Arrow": 1.0}[name]
            v = (rnd.random() * 2 - 1) * math.exp(-((t % period) * 60))
        else:   # noise: applause, whoosh, wind, explosion, suction, push, bomb, breeze
            v = rnd.random() * 2 - 1
        out.append(int(max(-1, min(1, v * env)) * 20000))
    b = io.BytesIO()
    w = wave.open(b, "wb")
    w.setnchannels(1)
    w.setsampwidth(2)
    w.setframerate(rate)
    w.writeframes(struct.pack("<%dh" % len(out), *out))
    w.close()
    return b.getvalue()


_playing = []


def play_action_sound(deck, part):
    data = deck.part_bytes(part)
    if not data:
        return
    path = os.path.join(tempfile.gettempdir(), "folio-action-%s" % os.path.basename(part))
    with open(path, "wb") as f:
        f.write(bytes(data))
    for player in (["paplay", path], ["aplay", "-q", path], ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", path]):
        try:
            _playing.append(subprocess.Popen(player, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
            return
        except OSError:
            continue


def stop_action_sound():
    while _playing:
        p = _playing.pop()
        try:
            p.terminate()
        except Exception:
            pass


def run_program(parent, path):
    """Run Program (Insert > Action): asks first, as PowerPoint does, since it starts a program."""
    d = Gtk.MessageDialog(transient_for=parent, modal=True, message_type=Gtk.MessageType.WARNING,
                          buttons=Gtk.ButtonsType.OK_CANCEL,
                          text="This presentation wants to start a program:\n\n%s\n\nStart it?" % path)
    r = d.run()
    d.destroy()
    if r != Gtk.ResponseType.OK:
        return
    try:
        import shlex
        subprocess.Popen(shlex.split(path), start_new_session=True)
    except Exception as e:
        parent.st.win.dialogs.message("%s couldn't start it.\n\n%s" % (APP_NAME, e)) if hasattr(parent, "st") else None


# ---------------------------------------------------------------- zoom
def _pres(deck):
    """(slide ids by index, sections [(name, id, [slide indexes])]) from presentation.xml."""
    pres = deck.part_xml("ppt/presentation.xml") or ""
    rels = deck.part_xml("ppt/_rels/presentation.xml.rels") or ""
    rid_target = dict(re.findall(r'Id="([^"]+)"[^>]*Target="([^"]+)"', rels))
    rid_target.update({a: b for b, a in re.findall(r'Target="([^"]+)"[^>]*Id="([^"]+)"', rels)})
    parts = deck.slide_parts()
    ids = {}
    for sid, rid in re.findall(r'<p:sldId id="(\d+)" r:id="([^"]+)"', pres):
        t = rid_target.get(rid, "")
        name = "ppt/" + t if not t.startswith("/") else t[1:]
        if name in parts:
            ids[parts.index(name)] = int(sid)
    by_sid = {v: k for k, v in ids.items()}
    sections = []
    for name, gid, body in re.findall(r'<p14:section name="([^"]*)" id="([^"]+)"><p14:sldIdLst>(.*?)</p14:sldIdLst>', pres):
        sl = [by_sid[int(x)] for x in re.findall(r'id="(\d+)"', body) if int(x) in by_sid]
        sections.append((name, gid, sl))
    return ids, sections


def zoom_info(deck, i, sid):
    """For a Zoom object: (slides it goes to, come back after them), else None."""
    xml = deck.object_xml(i, sid) or ""
    if "sldZmObj" not in xml and "sectionZmObj" not in xml:
        return None
    back = 'returnToParent="0"' not in xml
    if "sectionZmObj" in xml:
        m = re.search(r'sectionZmObj sectionId="([^"]+)"', xml)
        if not m:
            return None
        for _n, gid, sl in _pres(deck)[1]:
            if gid == m.group(1):
                return (sl, back) if sl else None
        return None
    t = deck.shape_link(i, sid) or ""
    if t.startswith("slide:"):
        return ([int(t[6:])], back)
    return None


def zoom_xml(kind, name, target_rel, x, y, w, h, back=True, slide_id=None, section_id=None):
    """A Slide or Section Zoom as PowerPoint writes it, with a picture with a link behind it."""
    guid = "{%s}" % str(uuid.uuid4()).upper()
    zm = ('<pslz:zmPr id="%s" returnToParent="%d" transitionDur="1000"><p166:blipFill xmlns:p166="%s"><a:blip r:embed="{rImg}"/>'
          '<a:stretch><a:fillRect/></a:stretch></p166:blipFill><p166:spPr xmlns:p166="%s"><a:xfrm><a:off x="0" y="0"/>'
          '<a:ext cx="%d" cy="%d"/></a:xfrm><a:prstGeom prst="rect"><a:avLst/></a:prstGeom><a:ln w="3175">'
          '<a:solidFill><a:prstClr val="ltGray"/></a:solidFill></a:ln></p166:spPr></pslz:zmPr>') % (guid, 1 if back else 0, NS_P166, NS_P166, emu(w), emu(h))
    if kind == "section":
        zm = zm.replace("pslz:zmPr", "psez:zmPr")
        obj = '<psez:sectionZm><psez:sectionZmObj sectionId="%s">%s</psez:sectionZmObj></psez:sectionZm>' % (section_id, zm)
        uri, ns, req = NS_PSEZ, 'xmlns:psez="%s"' % NS_PSEZ, "psez"
    else:
        obj = '<pslz:sldZm><pslz:sldZmObj sldId="%d" cId="0">%s</pslz:sldZmObj></pslz:sldZm>' % (slide_id or 256, zm)
        uri, ns, req = NS_PSLZ, 'xmlns:pslz="%s"' % NS_PSLZ, "pslz"
    link = '<a:hlinkClick r:id="{rSl}" action="ppaction://hlinksldjump"/>'
    xf = '<a:off x="%d" y="%d"/><a:ext cx="%d" cy="%d"/>' % (emu(x), emu(y), emu(w), emu(h))
    return ('<mc:AlternateContent xmlns:mc="%s"><mc:Choice %s Requires="%s"><p:graphicFrame><p:nvGraphicFramePr>'
            '<p:cNvPr id="{ID}" name="%s">%s</p:cNvPr><p:cNvGraphicFramePr><a:graphicFrameLocks noChangeAspect="1"/></p:cNvGraphicFramePr>'
            '<p:nvPr/></p:nvGraphicFramePr><p:xfrm>%s</p:xfrm><a:graphic><a:graphicData uri="%s">%s</a:graphicData></a:graphic>'
            '</p:graphicFrame></mc:Choice><mc:Fallback><p:pic><p:nvPicPr><p:cNvPr id="{ID}" name="%s">%s</p:cNvPr>'
            '<p:cNvPicPr><a:picLocks noGrp="1" noRot="1" noChangeAspect="1"/></p:cNvPicPr><p:nvPr/></p:nvPicPr><p:blipFill>'
            '<a:blip r:embed="{rImg}"/><a:stretch><a:fillRect/></a:stretch></p:blipFill><p:spPr><a:xfrm>%s</a:xfrm>'
            '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom><a:ln w="3175"><a:solidFill><a:prstClr val="ltGray"/></a:solidFill>'
            '</a:ln></p:spPr></p:pic></mc:Fallback></mc:AlternateContent>') % (
        NS_MC, ns, req, xesc(name), link, xf, uri, obj, xesc(name), link, xf)


# ---------------------------------------------------------------- 3-D models
def model_xml(name, x, y, w, h, rx, ry, rz, descr=""):
    """A 3-D model as PowerPoint 2019 writes it (am3d), with its picture for older readers."""
    xf = '<a:off x="%d" y="%d"/><a:ext cx="%d" cy="%d"/>' % (emu(x), emu(y), emu(w), emu(h))
    rot = '<am3d:rot ax="%d" ay="%d" az="%d"/>' % (int(rx * 60000), int(ry * 60000), int(rz * 60000))
    return ('<mc:AlternateContent xmlns:mc="%s"><mc:Choice xmlns:am3d="%s" Requires="am3d"><p:graphicFrame>'
            '<p:nvGraphicFramePr><p:cNvPr id="{ID}" name="%s" descr="%s"/><p:cNvGraphicFramePr><a:graphicFrameLocks noChangeAspect="1"/>'
            '</p:cNvGraphicFramePr><p:nvPr/></p:nvGraphicFramePr><p:xfrm>%s</p:xfrm><a:graphic><a:graphicData uri="%s">'
            '<am3d:model3d r:embed="{rModel}"><am3d:spPr><a:xfrm>%s</a:xfrm><a:prstGeom prst="rect"><a:avLst/></a:prstGeom></am3d:spPr>'
            '<am3d:camera><am3d:pos x="0" y="0" z="51581090"/><am3d:up dx="0" dy="36000000" dz="0"/><am3d:lookAt x="0" y="0" z="0"/>'
            '<am3d:perspective fov="2700000"/></am3d:camera><am3d:trans><am3d:meterPerModelUnit n="1" d="1"/>'
            '<am3d:preTrans dx="0" dy="0" dz="0"/><am3d:scale><am3d:sx n="1000000" d="1000000"/><am3d:sy n="1000000" d="1000000"/>'
            '<am3d:sz n="1000000" d="1000000"/></am3d:scale>%s<am3d:postTrans dx="0" dy="0" dz="0"/></am3d:trans>'
            '<am3d:raster rName="Office3DRenderer" rVer="16.0.8326"><am3d:blip r:embed="{rImg}"/></am3d:raster>'
            '<am3d:objViewport viewportSz="%d"/><am3d:ambientLight><am3d:clr><a:scrgbClr r="50000" g="50000" b="50000"/></am3d:clr>'
            '<am3d:illuminance n="500000" d="1000000"/></am3d:ambientLight></am3d:model3d></a:graphicData></a:graphic>'
            '</p:graphicFrame></mc:Choice><mc:Fallback><p:pic><p:nvPicPr><p:cNvPr id="{ID}" name="%s" descr="%s"/>'
            '<p:cNvPicPr><a:picLocks noGrp="1" noRot="1" noChangeAspect="1"/></p:cNvPicPr><p:nvPr/></p:nvPicPr><p:blipFill>'
            '<a:blip r:embed="{rImg}"/><a:stretch><a:fillRect/></a:stretch></p:blipFill><p:spPr><a:xfrm>%s</a:xfrm>'
            '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom></p:spPr></p:pic></mc:Fallback></mc:AlternateContent>') % (
        NS_MC, NS_AM3D, xesc(name), xesc(descr), xf, NS_AM3D, xf, rot, emu(max(w, h)), xesc(name), xesc(descr), xf)


def model_info(deck, i, sid):
    """For a 3-D model: (model part, (rx, ry, rz) degrees), else None."""
    xml = deck.object_xml(i, sid) or ""
    if "am3d:model3d" not in xml:
        return None
    m = re.search(r'am3d:model3d r:embed="([^"]+)"', xml)
    r = re.search(r'am3d:rot ax="(-?\d+)" ay="(-?\d+)" az="(-?\d+)"', xml)
    rot = tuple(int(v) / 60000.0 for v in r.groups()) if r else (0.0, 0.0, 0.0)
    part = deck.slide_rel_part(i, m.group(1)) if m else None
    return (part, rot) if part else None


def cameo_xml(name, x, y, w, h):
    """A Cameo: a rounded frame the camera's picture fills during the show."""
    return ('<p:sp><p:nvSpPr><p:cNvPr id="{ID}" name="%s" descr="Camera"><a:extLst><a:ext uri="%s"/></a:extLst></p:cNvPr>'
            '<p:cNvSpPr/><p:nvPr/></p:nvSpPr><p:spPr><a:xfrm><a:off x="%d" y="%d"/><a:ext cx="%d" cy="%d"/></a:xfrm>'
            '<a:prstGeom prst="roundRect"><a:avLst/></a:prstGeom><a:solidFill><a:srgbClr val="404040"/></a:solidFill>'
            '<a:ln w="19050"><a:solidFill><a:srgbClr val="FF8200"/></a:solidFill></a:ln></p:spPr><p:txBody>'
            '<a:bodyPr anchor="ctr"/><a:lstStyle/><a:p><a:pPr algn="ctr"/><a:r><a:rPr lang="en-US" sz="1400">'
            '<a:solidFill><a:srgbClr val="FFFFFF"/></a:solidFill></a:rPr><a:t>Camera</a:t></a:r></a:p></p:txBody></p:sp>') % (
        xesc(name), CAMEO_URI, emu(x), emu(y), emu(w), emu(h))


def is_cameo(deck, i, sid):
    return CAMEO_URI in (deck.object_xml(i, sid) or "")


# ---------------------------------------------------------------- the commands
class Backlog3Commands:
    # ------------------------------------------------------------ Merge Shapes (P3-02)
    def act_merge_shapes(self, how):
        """Shape Format > Merge Shapes: union, combine, fragment, intersect, subtract."""
        ids = [s for s in self._targets()]
        shapes = [self.canvas.shape(s) for s in ids]
        if len(ids) < 2 or any(s is None or s["kind"] not in ("sp", "cxnSp") for s in shapes):
            self.dialogs.info("Select two or more shapes to merge.", "Merge Shapes")
            return None
        try:
            from shapely.geometry import Polygon, MultiPolygon
            from shapely.geometry.polygon import orient
            from shapely.ops import unary_union, polygonize
        except ImportError:
            self.dialogs.message("Merge Shapes needs the geometry library (package python3-shapely).")
            return None
        geoms = []
        for sid in ids:
            polys = []
            for ring in self.deck.shape_outline(self.current, sid):
                if len(ring) >= 3:
                    p = Polygon(ring)
                    if not p.is_valid:
                        p = p.buffer(0)
                    polys.append(p)
            g = None
            for p in polys:       # rings inside one shape: holes are where they overlap an odd number of times
                g = p if g is None else g.symmetric_difference(p)
            geoms.append(g)
        if any(g is None or g.is_empty for g in geoms):
            return None
        if how == "union":
            parts = [unary_union(geoms)]
        elif how == "combine":
            g = geoms[0]
            for o in geoms[1:]:
                g = g.symmetric_difference(o)
            parts = [g]
        elif how == "intersect":
            g = geoms[0]
            for o in geoms[1:]:
                g = g.intersection(o)
            parts = [g]
        elif how == "subtract":
            parts = [geoms[0].difference(unary_union(geoms[1:]))]
        elif how == "fragment":
            lines = unary_union([g.boundary for g in geoms])
            whole = unary_union(geoms)
            parts = [p for p in polygonize(lines) if p.area > 0.01 and whole.contains(p.representative_point())]
        else:
            return None
        polys = []
        for g in parts:
            if g.is_empty:
                continue
            if isinstance(g, MultiPolygon):
                polys.append([orient(p, 1.0) for p in g.geoms])
            elif g.geom_type == "Polygon":
                polys.append([orient(g, 1.0)])
            elif hasattr(g, "geoms"):
                polys.append([orient(p, 1.0) for p in g.geoms if p.geom_type == "Polygon"])
        polys = [p for p in polys if p]
        if not polys:
            self.dialogs.info("The shapes don't overlap, so there is nothing to keep.", "Merge Shapes")
            return None
        style = self.deck.shapes_xml(self.current, [ids[0]])
        m = re.search(r"<p:sp\b.*</p:sp>", style, re.S)
        base = m.group(0) if m else None
        if base is None:
            return None
        made = []
        steps = 0
        for k, pl in enumerate(polys):
            xml = self._freeform_from(base, pl, "Freeform %d" % (k + 1), keep_text=(k == 0))
            if k == 0:
                self.deck.replace_object_xml(self.current, ids[0], "Merge Shapes", xml.replace('id="__ID__"', 'id="{ID}"'))
                made.append(ids[0])
            else:
                made.append(self.deck.insert_object_xml(self.current, "Merge Shapes", xml.replace('id="__ID__"', 'id="{ID}"')))
            steps += 1
        self.deck.delete_shapes(self.current, ids[1:])
        steps += 1
        self.deck.merge_undo(steps, "Merge Shapes")
        self.changed(slide=True)
        self.canvas.select(made)
        return made

    @staticmethod
    def _freeform_from(base, polys, name, keep_text=True):
        xs = [x for p in polys for ring in [p.exterior] + list(p.interiors) for x, _y in ring.coords]
        ys = [y for p in polys for ring in [p.exterior] + list(p.interiors) for _x, y in ring.coords]
        x0, y0, x1, y1 = min(xs), min(ys), max(xs), max(ys)
        w, h = max(0.01, x1 - x0), max(0.01, y1 - y0)
        path = []
        for p in polys:
            for ring in [p.exterior] + list(p.interiors):
                pts = list(ring.coords)
                if len(pts) < 3:
                    continue
                path.append('<a:moveTo><a:pt x="%d" y="%d"/></a:moveTo>' % (emu(pts[0][0] - x0), emu(pts[0][1] - y0)))
                for px, py in pts[1:]:
                    path.append('<a:lnTo><a:pt x="%d" y="%d"/></a:lnTo>' % (emu(px - x0), emu(py - y0)))
                path.append("<a:close/>")
        geom = ('<a:custGeom><a:avLst/><a:gdLst/><a:ahLst/><a:cxnLst/><a:rect l="0" t="0" r="r" b="b"/><a:pathLst>'
                '<a:path w="%d" h="%d">%s</a:path></a:pathLst></a:custGeom>') % (emu(w), emu(h), "".join(path))
        xml = re.sub(r"<a:prstGeom\b.*?</a:prstGeom>|<a:prstGeom\b[^>]*/>|<a:custGeom\b.*?</a:custGeom>", geom, base, count=1, flags=re.S)
        xml = re.sub(r"<a:xfrm\b[^>]*>.*?</a:xfrm>",
                     '<a:xfrm><a:off x="%d" y="%d"/><a:ext cx="%d" cy="%d"/></a:xfrm>' % (emu(x0), emu(y0), emu(w), emu(h)),
                     xml, count=1, flags=re.S)
        xml = re.sub(r'(<p:cNvPr\b[^>]*?)\bid="\d+"', r'\1id="__ID__"', xml, count=1)
        xml = re.sub(r'(<p:cNvPr\b[^>]*?)\bname="[^"]*"', r'\1name="%s"' % xesc(name), xml, count=1)
        if not keep_text:
            xml = re.sub(r"<p:txBody>.*?</p:txBody>", '<p:txBody><a:bodyPr/><a:lstStyle/><a:p><a:endParaRPr lang="en-US"/></a:p></p:txBody>',
                         xml, count=1, flags=re.S)
        if "<p:spPr>" not in xml and "<p:spPr " not in xml:
            return xml
        return xml

    # ------------------------------------------------------------ Eyedropper (P3-05)
    def act_eyedropper(self, which="shape-fill"):
        """Pick a colour from anywhere on the slide for the fill, outline or text."""
        c = self.canvas
        c.eyedropper = which
        w = c.area.get_window()
        if w is not None:
            w.set_cursor(Gdk.Cursor.new_from_name(w.get_display(), "crosshair"))
        self.status.flash("Eyedropper: click a colour on the slide (Esc cancels).") if hasattr(self.status, "flash") else None

    def eyedropper_pick(self, rgb):
        which = self.canvas.eyedropper
        self.eyedropper_cancel()
        if rgb is None:
            return
        v = "%02X%02X%02X" % rgb
        self.run("%s:%s" % (which, v))
        return v

    def eyedropper_cancel(self):
        c = self.canvas
        c.eyedropper = None
        w = c.area.get_window()
        if w is not None:
            w.set_cursor(None)

    # ------------------------------------------------------------ Action Settings (P3-03)
    def act_action_settings(self):
        """Insert > Action: what clicking or pointing at the selected object does in the show."""
        ids = self._targets()
        if not ids:
            self.dialogs.info("Select an object first.", "Action Settings")
            return None
        sid = ids[0]
        d = Gtk.Dialog(title="Action Settings", transient_for=self, modal=True)
        d.get_style_context().add_class("folio-dialog")
        d.add_button("Cancel", Gtk.ResponseType.CANCEL)
        d.add_button("OK", Gtk.ResponseType.OK)
        d.set_default_response(Gtk.ResponseType.OK)
        nb = Gtk.Notebook()
        d.get_content_area().pack_start(nb, True, True, 0)
        d.get_content_area().set_border_width(8)
        pages = {}
        shows = self.deck.custom_shows()
        n = self.deck.slide_count()
        targets = [("Next Slide", "next"), ("Previous Slide", "prev"), ("First Slide", "first"), ("Last Slide", "last"),
                   ("End Show", "end")] + [("Custom Show: %s" % name, "show:%d" % k) for k, (name, _s) in enumerate(shows)] + \
                  [("Slide %d" % (k + 1), "slide:%d" % k) for k in range(n)] + [("URL...", "url"), ("Other File...", "file")]
        for which, title in (("click", "Mouse Click"), ("hover", "Mouse Over")):
            cur = self.deck.shape_action(self.current, sid, which)
            g = Gtk.Grid(row_spacing=6, column_spacing=8, margin=10)
            heading = Gtk.Label(label="Action on " + ("click" if which == "click" else "mouse over"), xalign=0)
            g.attach(heading, 0, 0, 2, 1)
            none = Gtk.RadioButton.new_with_label(None, "None")
            link = Gtk.RadioButton.new_with_label_from_widget(none, "Hyperlink to:")
            prog = Gtk.RadioButton.new_with_label_from_widget(none, "Run program:")
            combo = Gtk.ComboBoxText()
            for label, _v in targets:
                combo.append_text(label)
            combo.set_active(0)
            url = Gtk.Entry(placeholder_text="Address or file")
            prog_e = Gtk.Entry(placeholder_text="Program")
            snd_check = Gtk.CheckButton(label="Play sound:")
            snd = Gtk.ComboBoxText()
            snd.append_text("[Stop Previous Sound]")
            for s in SOUNDS:
                snd.append_text(s)
            snd.append_text("Other Sound...")
            snd.set_active(7)
            hl = Gtk.CheckButton(label="Highlight click" if which == "click" else "Highlight when mouse over")
            g.attach(none, 0, 1, 2, 1)
            g.attach(link, 0, 2, 1, 1)
            g.attach(combo, 1, 2, 1, 1)
            g.attach(url, 1, 3, 1, 1)
            g.attach(prog, 0, 4, 1, 1)
            g.attach(prog_e, 1, 4, 1, 1)
            g.attach(snd_check, 0, 5, 1, 1)
            g.attach(snd, 1, 5, 1, 1)
            g.attach(hl, 0, 6, 2, 1)
            if cur is not None:
                tgt, sound, stop, high = cur
                if tgt.startswith("program:"):
                    prog.set_active(True)
                    prog_e.set_text(tgt[8:])
                elif tgt:
                    link.set_active(True)
                    vals = [v for _l, v in targets]
                    if tgt in vals:
                        combo.set_active(vals.index(tgt))
                    else:
                        combo.set_active(vals.index("url"))
                        url.set_text(tgt)
                snd_check.set_active(bool(sound or stop))
                if stop:
                    snd.set_active(0)
                hl.set_active(high)
            pages[which] = (none, link, prog, combo, url, prog_e, snd_check, snd, hl)
            nb.append_page(g, Gtk.Label(label=title))
        d.show_all()
        result = d.run()
        if result == Gtk.ResponseType.OK:
            for which, (none, link, prog, combo, url, prog_e, snd_check, snd, hl) in pages.items():
                target = ""
                if link.get_active():
                    v = targets[combo.get_active()][1]
                    target = url.get_text().strip() if v in ("url", "file") else v
                elif prog.get_active():
                    target = "program:" + prog_e.get_text().strip()
                sound, stop = None, False
                if snd_check.get_active():
                    k = snd.get_active()
                    if k == 0:
                        stop = True
                    elif k == len(SOUNDS) + 1:
                        fc = Gtk.FileChooserNative(title="Add Audio", transient_for=self, action=Gtk.FileChooserAction.OPEN)
                        if fc.run() == Gtk.ResponseType.ACCEPT:
                            p = fc.get_filename()
                            sound = (open(p, "rb").read(), os.path.basename(p))
                    else:
                        name = SOUNDS[k - 1]
                        sound = (synth_sound(name), name.lower().replace(" ", "") + ".wav")
                self.deck.set_shape_action(self.current, sid, which, target, sound, stop, hl.get_active())
            self.changed(slide=True)
        d.destroy()
        return result == Gtk.ResponseType.OK

    # ------------------------------------------------------------ Zoom (P3-04)
    def _pick_slides(self, title, multi=True):
        d = Gtk.Dialog(title=title, transient_for=self, modal=True)
        d.get_style_context().add_class("folio-dialog")
        d.add_button("Cancel", Gtk.ResponseType.CANCEL)
        d.add_button("Insert", Gtk.ResponseType.OK)
        flow = Gtk.FlowBox(max_children_per_line=4, selection_mode=Gtk.SelectionMode.MULTIPLE if multi else Gtk.SelectionMode.SINGLE)
        for k in range(self.deck.slide_count()):
            b = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            try:
                sw, sh = self.deck.size()
                pw, ph, stride, data, _ = self.deck.render(k, 150 / sw, False)
                img = Gtk.Image.new_from_surface(surface_from(pw, ph, stride, data))
            except Exception:
                img = Gtk.Label(label="")
            b.pack_start(img, False, False, 0)
            b.pack_start(Gtk.Label(label="%d" % (k + 1)), False, False, 0)
            b.index = k
            flow.add(b)
        sw_ = Gtk.ScrolledWindow()
        sw_.set_size_request(680, 420)
        sw_.add(flow)
        d.get_content_area().pack_start(sw_, True, True, 0)
        d.show_all()
        r = d.run()
        picks = [ch.get_child().index for ch in flow.get_selected_children()] if r == Gtk.ResponseType.OK else []
        d.destroy()
        return sorted(picks)

    def act_insert_zoom(self, kind="slide", slides=None):
        """Insert > Zoom: Summary Zoom, Section Zoom or Slide Zoom."""
        deck = self.deck
        if self.current is None:
            return None
        ids, sections = _pres(deck)
        sw, sh = deck.size()
        if kind == "slide":
            picks = slides if slides is not None else self._pick_slides("Insert Slide Zoom")
            if not picks:
                return None
            made = []
            w, h = sw / 4.5, sh / 4.5
            for k, t in enumerate(picks):
                x, y = 40 + (k % 4) * (w + 20), 60 + (k // 4) * (h + 20)
                xml = zoom_xml("slide", "Slide Zoom %d" % (k + 1), None, x, y, w, h, slide_id=ids.get(t))
                made.append(deck.insert_object_xml(self.current, "Insert Zoom", xml,
                                                   [("rImg", "image", "image", "png", "image/png", slide_png(deck, t), ""),
                                                    ("rSl", "slide", "", "", "", b"", "slide:%d" % t)]))
            deck.merge_undo(len(made), "Insert Slide Zoom")
            self.changed(slide=True)
            self.canvas.select(made)
            return made
        if kind in ("section", "summary"):
            if kind == "summary":
                # a new summary slide before the first chosen slide; each chosen slide starts a section
                picks = slides if slides is not None else self._pick_slides("Insert Summary Zoom")
                if not picks:
                    return None
                picks = sorted(set(picks))
                lay = ""
                for _m, ls in deck.layouts():
                    for part, nm in ls:
                        if nm.lower() == "title only":
                            lay = part
                    if not lay and ls:
                        lay = ls[0][0]
                summary = deck.new_slide(picks[0] - 1 if picks[0] > 0 else None, lay)
                steps = 1
                secs = ([("Default Section", 0)] if summary > 0 else []) + [("Summary Section", summary)] + \
                    [(self._slide_title(p + 1) or "Section %d" % (k + 1), p + 1) for k, p in enumerate(picks)]
                deck.write_sections(secs, "Summary Zoom")
                steps += 1
                for shp in deck.shapes(summary):
                    if shp.get("ph") in ("title", "ctrTitle"):
                        deck.set_text(summary, shp["id"], "Summary")
                        steps += 1
                        break
                ids, sections = _pres(deck)
                self.current = summary
                targets = [(gid, sl) for (_n, gid, sl) in sections if sl and sl[0] > summary]
                steps += self._insert_section_zooms(targets, sw, sh)
                deck.merge_undo(steps, "Insert Summary Zoom")
                self.changed(structure=True)
                self.go_slide(summary)
                return summary
            targets = [(gid, sl) for (_n, gid, sl) in sections if sl]
            if not targets:
                self.dialogs.info("This presentation has no sections. Add sections (Home > Section) first, or use Summary Zoom.",
                                  "Insert Section Zoom")
                return None
            n = self._insert_section_zooms(targets, sw, sh)
            deck.merge_undo(n, "Insert Section Zoom")
            self.changed(slide=True)
            return n
        return None

    def _slide_title(self, i):
        for _id, ph, paras in self.deck.slide_text(i):
            if ph in ("title", "ctrTitle") and paras and paras[0].strip():
                return paras[0].strip()
        return ""

    def _insert_section_zooms(self, targets, sw, sh):
        deck = self.deck
        w, h = sw / 4.2, sh / 4.2
        k = 0
        for gid, sl in targets:
            x, y = 40 + (k % 3) * (w + 30), 140 + (k // 3) * (h + 30)
            xml = zoom_xml("section", "Section Zoom %d" % (k + 1), None, x, y, w, h, section_id=gid)
            deck.insert_object_xml(self.current, "Insert Zoom", xml,
                                   [("rImg", "image", "image", "png", "image/png", slide_png(deck, sl[0]), ""),
                                    ("rSl", "slide", "", "", "", b"", "slide:%d" % sl[0])])
            k += 1
        return k

    # ------------------------------------------------------------ Protect Presentation (P3-06)
    def act_protect(self, how):
        if how == "password":
            pw = self.dialogs.ask_password("Encrypt Document", "Encrypt the contents of this file\n\nPassword:")
            if pw is None:
                return None
            if pw == "":
                self.password = None
                self.deck.modified = True
                self.update_title()
                return ""
            again = self.dialogs.ask_password("Confirm Password", "Reenter password:")
            if again != pw:
                self.dialogs.info("The passwords don't match.", "Confirm Password")
                return None
            self.password = pw
            self.deck.modified = True
            self.update_title()
            return pw
        if how == "final":
            self.deck.set_custom_prop("_MarkAsFinal", "bool", "true")
            self.changed(structure=True)
            if self.path:
                self.act_save()
            self.enter_final()
            return True
        if how == "readonly":
            on = not self.read_only_recommended()
            self.deck.set_custom_prop("_AlwaysOpenReadOnly", "bool" if on else "", "true")
            self.changed(structure=True)
            return on
        return None

    def read_only_recommended(self):
        return ("_AlwaysOpenReadOnly", "true") in self.deck.custom_props()

    def is_final(self):
        return ("_MarkAsFinal", "true") in self.deck.custom_props()

    def message_bar(self, text, button=None, action=None):
        bar = getattr(self, "_msgbar", None)
        if bar is not None:
            bar.destroy()
        bar = Gtk.Box(spacing=10)
        bar.get_style_context().add_class("folio-msgbar")
        lab = Gtk.Label(label=text, xalign=0)
        lab.set_margin_start(12)
        bar.pack_start(lab, True, True, 0)
        if button:
            b = Gtk.Button(label=button)
            b.connect("clicked", lambda *_: action())
            bar.pack_end(b, False, False, 6)
        self.outer.pack_start(bar, False, False, 0)
        self.outer.reorder_child(bar, 1)
        bar.show_all()
        self._msgbar = bar
        return bar

    def close_message_bar(self):
        bar = getattr(self, "_msgbar", None)
        if bar is not None:
            bar.destroy()
            self._msgbar = None

    def enter_final(self):
        self.final_mode = True
        self.canvas.leave_text()
        self.canvas.sel = []
        self.canvas.set_sensitive(False)
        self.ribbon.set_sensitive(False)
        self.message_bar("MARKED AS FINAL  An author has marked this presentation as final to discourage editing.",
                         "Edit Anyway", self.leave_final)

    def leave_final(self):
        self.final_mode = False
        self.canvas.set_sensitive(True)
        self.ribbon.set_sensitive(True)
        self.close_message_bar()
        if self.is_final():
            self.deck.set_custom_prop("_MarkAsFinal", "", "")
            self.changed(structure=True)

    def after_open_checks(self):
        """Embedded fonts, Mark as Final and Always Open Read-Only, when a presentation opens."""
        self.install_embedded_fonts()
        if self.is_final():
            self.enter_final()
        elif self.read_only_recommended():
            self.read_only_mode = True
            self.message_bar("READ-ONLY  The author would like you to open this as read-only, unless you need to make changes.",
                             "Edit Anyway", lambda: (setattr(self, "read_only_mode", False), self.close_message_bar()))

    # encryption on open / save
    def open_encrypted(self, path):
        """The decrypted package of a password-protected file (asks for the password), or None."""
        from . import crypt
        data = open(path, "rb").read()
        if not crypt.is_encrypted(data):
            return None
        tries = 0
        while True:
            pw = self.dialogs.ask_password("Password", "Enter password to open file\n%s" % os.path.basename(path))
            if pw is None:
                raise RuntimeError("The password was not given.")
            try:
                pkg = crypt.decrypt(data, pw)
            except crypt.WrongPassword:
                tries += 1
                self.dialogs.info("The password you supplied is not correct. Verify that the CAPS LOCK key is off and be sure "
                                  "to use the correct capitalization.", "Password")
                continue
            self.password = pw
            return pkg

    def write_protected(self, path):
        """Save the presentation encrypted with its password."""
        from . import crypt
        tmp = path + ".folio-tmp"
        self.deck.save(tmp)
        try:
            data = open(tmp, "rb").read()
        finally:
            os.remove(tmp)
        out = crypt.encrypt(data, self.password)
        with open(path, "wb") as f:
            f.write(out)
        self.deck.modified = False

    # ------------------------------------------------------------ embedded fonts and Options (P3-08)
    def fonts_used(self):
        fonts = set()
        for i in range(self.deck.slide_count()):
            try:
                xml = self.deck.shapes_xml(i, [s["id"] for s in self.deck.shapes(i)])
            except Exception:
                continue
            fonts.update(re.findall(r'<a:latin typeface="([^"+][^"]*)"', xml))
        major, minor = self.deck.theme_info()[1:3]
        fonts.update(f for f in (major, minor) if f)
        return sorted(f for f in fonts if not f.startswith("+"))

    def embed_fonts_now(self):
        """Put the fonts the slides use into the file (those whose licence allows it)."""
        from . import eot
        out, refused = [], []
        for fam in self.fonts_used():
            styles = []
            for st, b, it in (("regular", False, False), ("bold", True, False), ("italic", False, True), ("boldItalic", True, True)):
                p = eot.find_font_file(fam, b, it)
                if p is None:
                    continue
                data = open(p, "rb").read()
                if not eot.can_embed(data):
                    refused.append(fam)
                    break
                if any(open(q, "rb").read() == data for _s, q in styles):
                    continue
                styles.append((st, p))
            if styles and fam not in refused:
                out.append((fam, [(st, eot.make(open(p, "rb").read())) for st, p in styles]))
        self.deck.set_embedded_fonts(out)
        return [f for f, _s in out], refused

    def install_embedded_fonts(self):
        from . import eot
        try:
            fonts = self.deck.embedded_fonts()
        except Exception:
            return 0
        n = 0
        for face, st, part in fonts:
            data = self.deck.part_bytes(part)
            ttf = eot.font_of(bytes(data)) if data else None
            if ttf is None:
                continue
            fam, _style, _t = eot.info(ttf)
            if eot.find_font_file(fam or face) is not None:
                continue                   # installed already
            eot.install_for_show(ttf, "%s-%s.ttf" % (re.sub(r"\W", "", face), st))
            n += 1
        if n:
            subprocess.run(["fc-cache", eot.EMBED_DIR], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self.deck.reload_fonts()
            self.canvas.invalidate()
        return n

    def act_options(self):
        """File > Options: General, Proofing and Save."""
        d = Gtk.Dialog(title="%s Options" % APP_NAME, transient_for=self, modal=True)
        d.get_style_context().add_class("folio-dialog")
        d.add_button("Cancel", Gtk.ResponseType.CANCEL)
        d.add_button("OK", Gtk.ResponseType.OK)
        nb = Gtk.Notebook()
        d.get_content_area().pack_start(nb, True, True, 0)
        settings = getattr(self.app, "settings", {})
        g = Gtk.Grid(row_spacing=8, column_spacing=10, margin=12)
        g.attach(Gtk.Label(label="Personalize your copy of %s" % APP_NAME, xalign=0), 0, 0, 2, 1)
        name = Gtk.Entry(text=settings.get("user_name", os.environ.get("USER", "")))
        initials = Gtk.Entry(text=settings.get("user_initials", ""))
        g.attach(Gtk.Label(label="User name:", xalign=0), 0, 1, 1, 1)
        g.attach(name, 1, 1, 1, 1)
        g.attach(Gtk.Label(label="Initials:", xalign=0), 0, 2, 1, 1)
        g.attach(initials, 1, 2, 1, 1)
        nb.append_page(g, Gtk.Label(label="General"))
        p = Gtk.Grid(row_spacing=8, column_spacing=10, margin=12)
        spell = Gtk.CheckButton(label="Check spelling as you type")
        spell.set_active(settings.get("spell_as_you_type", True))
        p.attach(spell, 0, 0, 1, 1)
        nb.append_page(p, Gtk.Label(label="Proofing"))
        s = Gtk.Grid(row_spacing=8, column_spacing=10, margin=12)
        embed = Gtk.CheckButton(label="Embed fonts in the file")
        embed.set_active(self.deck.pres_attr("embedTrueTypeFonts") in ("1", "true"))
        subset = Gtk.RadioButton.new_with_label(None, "Embed only the characters used in the presentation (best for reducing file size)")
        allc = Gtk.RadioButton.new_with_label_from_widget(subset, "Embed all characters (best for editing by other people)")
        (subset if self.deck.pres_attr("saveSubsetFonts") in ("1", "true") else allc).set_active(True)
        note = Gtk.Label(label="Fonts are embedded whole either way; only fonts whose licence allows embedding are kept.", xalign=0)
        note.get_style_context().add_class("dim-label")
        s.attach(Gtk.Label(label="Preserve fidelity when sharing this presentation:", xalign=0), 0, 0, 1, 1)
        s.attach(embed, 0, 1, 1, 1)
        s.attach(subset, 0, 2, 1, 1)
        s.attach(allc, 0, 3, 1, 1)
        s.attach(note, 0, 4, 1, 1)
        nb.append_page(s, Gtk.Label(label="Save"))
        d.show_all()
        r = d.run()
        if r == Gtk.ResponseType.OK:
            settings["user_name"] = name.get_text()
            settings["user_initials"] = initials.get_text()
            settings["spell_as_you_type"] = spell.get_active()
            want = embed.get_active()
            if want != (self.deck.pres_attr("embedTrueTypeFonts") in ("1", "true")):
                self.deck.set_pres_attr("embedTrueTypeFonts", "1" if want else None)
                if not want:
                    self.deck.set_embedded_fonts([])
            self.deck.set_pres_attr("saveSubsetFonts", "1" if subset.get_active() and want else None)
            try:
                self.app.save_settings()
            except Exception:
                pass
        d.destroy()
        return r == Gtk.ResponseType.OK

    # ------------------------------------------------------------ Compress Media (P3-08)
    def act_compress_media(self, quality="hd"):
        """File > Info > Compress Media: Full HD (1080p), HD (720p) or Standard (480p); pictures too."""
        lines = {"full": 1080, "hd": 720, "standard": 480}.get(quality, 720)
        saved = 0
        done = 0
        import shutil
        ff = shutil.which("ffmpeg")
        for part, size in self.deck.media_parts():
            ext = os.path.splitext(part)[1].lower()
            data = bytes(self.deck.part_bytes(part) or b"")
            new = None
            if ext in (".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".gif"):
                new = self._shrink_picture(data, ext, lines * 2)
            elif ext in (".mp4", ".m4v", ".mov", ".avi", ".wmv", ".mkv", ".webm") and ff:
                new = self._transcode(ff, data, ext, ["-vf", "scale=-2:'min(%d,ih)'" % lines, "-c:v", "libx264", "-preset", "veryfast",
                                                      "-crf", "26", "-c:a", "aac", "-b:a", "128k"], ".mp4" if ext in (".mp4", ".m4v") else ext)
            elif ext in (".wav", ".m4a", ".mp3") and ff and size > 1000000:
                new = self._transcode(ff, data, ext, ["-b:a", "128k"], ext)
            if new and len(new) < len(data):
                self.deck.set_part(part, new, "Compress Media")
                saved += len(data) - len(new)
                done += 1
        if done > 1:
            self.deck.merge_undo(done, "Compress Media")
        self.changed(structure=True)
        msg = ("Compressed %d media file%s, saving %.1f MB." % (done, "" if done == 1 else "s", saved / 1e6)) if done else \
            "The media in this presentation is already as small as this quality allows."
        if not ff:
            msg += "\n\nVideo and audio need ffmpeg, which isn't installed; pictures were compressed."
        self.dialogs.info(msg, "Compress Media")
        return saved

    @staticmethod
    def _shrink_picture(data, ext, max_px):
        from gi.repository import GdkPixbuf
        try:
            ld = GdkPixbuf.PixbufLoader()
            ld.write(data)
            ld.close()
            pb = ld.get_pixbuf()
        except Exception:
            return None
        w, h = pb.get_width(), pb.get_height()
        k = max_px / max(w, h)
        if k < 1:
            pb = pb.scale_simple(max(1, int(w * k)), max(1, int(h * k)), GdkPixbuf.InterpType.BILINEAR)
        ok, buf = pb.save_to_bufferv("jpeg" if ext in (".jpg", ".jpeg") else "png",
                                     ["quality"] if ext in (".jpg", ".jpeg") else ["compression"],
                                     ["85"] if ext in (".jpg", ".jpeg") else ["9"])
        return bytes(buf) if ok else None

    @staticmethod
    def _transcode(ff, data, ext, args, out_ext):
        d = tempfile.mkdtemp(prefix="folio-compress-")
        src, dst = os.path.join(d, "in" + ext), os.path.join(d, "out" + out_ext)
        with open(src, "wb") as f:
            f.write(data)
        try:
            subprocess.run([ff, "-y", "-loglevel", "error", "-i", src] + args + [dst], timeout=600,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return open(dst, "rb").read() if os.path.exists(dst) else None
        except Exception:
            return None
        finally:
            import shutil
            shutil.rmtree(d, ignore_errors=True)

    # ------------------------------------------------------------ Compare (P3-07)
    def act_compare(self, path=None):
        """Review > Compare: the differences of another version, to accept or reject one by one."""
        if path is None:
            fc = Gtk.FileChooserNative(title="Choose File to Merge with Current Presentation", transient_for=self,
                                       action=Gtk.FileChooserAction.OPEN)
            flt = Gtk.FileFilter()
            flt.set_name("PowerPoint Presentations")
            flt.add_pattern("*.pptx")
            fc.add_filter(flt)
            if fc.run() != Gtk.ResponseType.ACCEPT:
                return None
            path = fc.get_filename()
        from .compare import compare, RevisionsPane
        changes = compare(self.deck, path)
        if not changes:
            self.dialogs.info("The presentations are the same.", "Compare")
            return []
        RevisionsPane(self, path, changes).show_all()
        return changes

    # ------------------------------------------------------------ 3-D Models (P3-09)
    def act_insert_model(self, path=None):
        """Insert > 3D Models > This Device: a glTF model (.glb, .gltf), turned with the mouse."""
        if path is None:
            fc = Gtk.FileChooserNative(title="Insert 3D Model", transient_for=self, action=Gtk.FileChooserAction.OPEN)
            flt = Gtk.FileFilter()
            flt.set_name("3D Models (*.glb, *.gltf)")
            flt.add_pattern("*.glb")
            flt.add_pattern("*.gltf")
            fc.add_filter(flt)
            if fc.run() != Gtk.ResponseType.ACCEPT:
                return None
            path = fc.get_filename()
        from . import model3d
        try:
            data, glb = model3d.load_file(path)
            mesh = model3d.Mesh(glb)
        except Exception as e:
            self.dialogs.message("%s can't read this 3D model.\n\n%s" % (APP_NAME, e))
            return None
        sw, sh = self.deck.size()
        w = sw * 0.4
        h = w
        x, y = (sw - w) / 2, (sh - h) / 2
        rot = (15.0, -30.0, 0.0)
        png = mesh.png(int(w * 2), int(h * 2), rot)
        name = os.path.splitext(os.path.basename(path))[0]
        sid = self.deck.insert_object_xml(self.current, "Insert 3D Model", model_xml("3D Model %s" % name, x, y, w, h, *rot, descr=name),
                                          [("rModel", REL_MODEL, "model3d", "glb", "model/gltf.binary", glb, ""),
                                           ("rImg", "image", "image", "png", "image/png", png, "")])
        self.changed(slide=True)
        self.canvas.select([sid])
        return sid

    def act_model_view(self, view):
        """3D Model > 3D Model Views: Front, Back, Left, Right, Top, Bottom, Above Front Left..."""
        views = {"front": (0, 0, 0), "back": (0, 180, 0), "left": (0, 90, 0), "right": (0, -90, 0), "top": (90, 0, 0),
                 "bottom": (-90, 0, 0), "above-front-left": (25, 35, 0), "above-front-right": (25, -35, 0),
                 "below-front-left": (-25, 35, 0), "below-front-right": (-25, -35, 0)}
        if view in views:
            return self.turn_model(views[view], absolute=True)
        return None

    def turn_model(self, rot, absolute=False, sid=None):
        from . import model3d
        ids = [sid] if sid is not None else self._targets()
        if not ids:
            return None
        sid = ids[0]
        info = model_info(self.deck, self.current, sid)
        if info is None:
            return None
        part, cur = info
        new = tuple(rot) if absolute else tuple((a + b) % 360 for a, b in zip(cur, rot))
        s = self.canvas.shape(sid) or {}
        glb = bytes(self.deck.part_bytes(part) or b"")
        mesh = model3d.Mesh(glb)
        png = mesh.png(int(s.get("w", 200) * 2), int(s.get("h", 200) * 2), new)
        xml = self.deck.object_xml(self.current, sid)
        xml = re.sub(r'am3d:rot ax="-?\d+" ay="-?\d+" az="-?\d+"',
                     'am3d:rot ax="%d" ay="%d" az="%d"' % tuple(int(v * 60000) for v in new), xml)
        rid_m = re.search(r'am3d:model3d r:embed="([^"]+)"', xml).group(1)
        xml = re.sub(r'(<p:cNvPr id=")\d+(")', r'\g<1>{ID}\2', xml)
        xml = xml.replace('r:embed="%s"' % rid_m, 'r:embed="{rModel}"')
        xml = re.sub(r'(<am3d:blip|<a:blip) r:embed="[^"]+"', r'\1 r:embed="{rImg}"', xml)
        self.deck.replace_object_xml(self.current, sid, "Rotate 3D Model", xml,
                                     [("rModel", REL_MODEL, "model3d", "glb", "model/gltf.binary", glb, ""),
                                      ("rImg", "image", "image", "png", "image/png", png, "")])
        self.changed(slide=True)
        return new

    # ------------------------------------------------------------ Cameo (P3-10)
    def act_insert_cameo(self):
        """Insert > Cameo: the computer's camera, live on the slide during the show."""
        sw, sh = self.deck.size()
        w = sw * 0.25
        h = w * 0.75
        sid = self.deck.insert_object_xml(self.current, "Insert Cameo", cameo_xml("Camera", sw - w - 30, sh - h - 30, w, h))
        self.changed(slide=True)
        self.canvas.select([sid])
        return sid

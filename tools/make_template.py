"""Writes Folio Show's blank presentation (share/templates/Blank.pptx) from scratch:
16:9 slides, the default Office colours and fonts, a slide master with the usual eleven
layouts, and one Title Slide."""
import os
import sys
import zipfile

P = "http://schemas.openxmlformats.org/presentationml/2006/main"
A = "http://schemas.openxmlformats.org/drawingml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
NS = 'xmlns:a="%s" xmlns:r="%s" xmlns:p="%s"' % (A, R, P)
RT = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/"
CX, CY = 12192000, 6858000
HDR = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'


def rels(items):
    out = [HDR, '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">']
    for i, (kind, target) in enumerate(items, 1):
        out.append('<Relationship Id="rId%d" Type="%s%s" Target="%s"/>' % (i, RT, kind, target))
    out.append("</Relationships>")
    return "".join(out)


def xfrm(x, y, w, h):
    return '<a:xfrm><a:off x="%d" y="%d"/><a:ext cx="%d" cy="%d"/></a:xfrm>' % (x, y, w, h)


def ph_sp(sid, name, ph, geom=None, body="", text=None, txbody_extra=""):
    """A placeholder shape: ph = attributes of p:ph; geom = (x, y, w, h) or None to inherit."""
    sppr = "<p:spPr>%s</p:spPr>" % (xfrm(*geom) if geom else "")
    paras = []
    for t in (text or [""]):
        if t:
            paras.append('<a:p><a:r><a:rPr lang="en-US"/><a:t>%s</a:t></a:r></a:p>' % t)
        else:
            paras.append('<a:p><a:endParaRPr lang="en-US"/></a:p>')
    return ('<p:sp><p:nvSpPr><p:cNvPr id="%d" name="%s"/><p:cNvSpPr><a:spLocks noGrp="1"/></p:cNvSpPr>'
            '<p:nvPr><p:ph %s/></p:nvPr></p:nvSpPr>%s<p:txBody><a:bodyPr%s/><a:lstStyle/>%s%s</p:txBody></p:sp>'
            % (sid, name, ph, sppr, body, txbody_extra, "".join(paras)))


GROUP = ('<p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr><p:grpSpPr>'
         '<a:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/><a:chOff x="0" y="0"/><a:chExt cx="0" cy="0"/>'
         '</a:xfrm></p:grpSpPr>')

THEME = HDR + ('<a:theme xmlns:a="%s" name="Office Theme"><a:themeElements>'
  '<a:clrScheme name="Office"><a:dk1><a:sysClr val="windowText" lastClr="000000"/></a:dk1>'
  '<a:lt1><a:sysClr val="window" lastClr="FFFFFF"/></a:lt1><a:dk2><a:srgbClr val="44546A"/></a:dk2>'
  '<a:lt2><a:srgbClr val="E7E6E6"/></a:lt2><a:accent1><a:srgbClr val="4472C4"/></a:accent1>'
  '<a:accent2><a:srgbClr val="ED7D31"/></a:accent2><a:accent3><a:srgbClr val="A5A5A5"/></a:accent3>'
  '<a:accent4><a:srgbClr val="FFC000"/></a:accent4><a:accent5><a:srgbClr val="5B9BD5"/></a:accent5>'
  '<a:accent6><a:srgbClr val="70AD47"/></a:accent6><a:hlink><a:srgbClr val="0563C1"/></a:hlink>'
  '<a:folHlink><a:srgbClr val="954F72"/></a:folHlink></a:clrScheme>'
  '<a:fontScheme name="Office"><a:majorFont><a:latin typeface="Calibri Light" panose="020F0302020204030204"/>'
  '<a:ea typeface=""/><a:cs typeface=""/></a:majorFont><a:minorFont><a:latin typeface="Calibri" '
  'panose="020F0502020204030204"/><a:ea typeface=""/><a:cs typeface=""/></a:minorFont></a:fontScheme>'
  '<a:fmtScheme name="Office"><a:fillStyleLst><a:solidFill><a:schemeClr val="phClr"/></a:solidFill>'
  '<a:gradFill rotWithShape="1"><a:gsLst><a:gs pos="0"><a:schemeClr val="phClr"><a:lumMod val="110000"/>'
  '<a:satMod val="105000"/><a:tint val="67000"/></a:schemeClr></a:gs><a:gs pos="50000"><a:schemeClr val="phClr">'
  '<a:lumMod val="105000"/><a:satMod val="103000"/><a:tint val="73000"/></a:schemeClr></a:gs><a:gs pos="100000">'
  '<a:schemeClr val="phClr"><a:lumMod val="105000"/><a:satMod val="109000"/><a:tint val="81000"/></a:schemeClr>'
  '</a:gs></a:gsLst><a:lin ang="5400000" scaled="0"/></a:gradFill><a:gradFill rotWithShape="1"><a:gsLst>'
  '<a:gs pos="0"><a:schemeClr val="phClr"><a:satMod val="103000"/><a:lumMod val="102000"/><a:tint val="94000"/>'
  '</a:schemeClr></a:gs><a:gs pos="50000"><a:schemeClr val="phClr"><a:satMod val="110000"/><a:lumMod val="100000"/>'
  '<a:shade val="100000"/></a:schemeClr></a:gs><a:gs pos="100000"><a:schemeClr val="phClr"><a:lumMod val="99000"/>'
  '<a:satMod val="120000"/><a:shade val="78000"/></a:schemeClr></a:gs></a:gsLst><a:lin ang="5400000" scaled="0"/>'
  '</a:gradFill></a:fillStyleLst><a:lnStyleLst><a:ln w="6350" cap="flat" cmpd="sng" algn="ctr"><a:solidFill>'
  '<a:schemeClr val="phClr"/></a:solidFill><a:prstDash val="solid"/><a:miter lim="800000"/></a:ln>'
  '<a:ln w="12700" cap="flat" cmpd="sng" algn="ctr"><a:solidFill><a:schemeClr val="phClr"/></a:solidFill>'
  '<a:prstDash val="solid"/><a:miter lim="800000"/></a:ln><a:ln w="19050" cap="flat" cmpd="sng" algn="ctr">'
  '<a:solidFill><a:schemeClr val="phClr"/></a:solidFill><a:prstDash val="solid"/><a:miter lim="800000"/></a:ln>'
  '</a:lnStyleLst><a:effectStyleLst><a:effectStyle><a:effectLst/></a:effectStyle><a:effectStyle><a:effectLst/>'
  '</a:effectStyle><a:effectStyle><a:effectLst><a:outerShdw blurRad="57150" dist="19050" dir="5400000" '
  'algn="ctr" rotWithShape="0"><a:srgbClr val="000000"><a:alpha val="63000"/></a:srgbClr></a:outerShdw>'
  '</a:effectLst></a:effectStyle></a:effectStyleLst><a:bgFillStyleLst><a:solidFill><a:schemeClr val="phClr"/>'
  '</a:solidFill><a:solidFill><a:schemeClr val="phClr"><a:tint val="95000"/><a:satMod val="170000"/></a:schemeClr>'
  '</a:solidFill><a:gradFill rotWithShape="1"><a:gsLst><a:gs pos="0"><a:schemeClr val="phClr"><a:tint val="93000"/>'
  '<a:satMod val="150000"/><a:shade val="98000"/><a:lumMod val="102000"/></a:schemeClr></a:gs><a:gs pos="50000">'
  '<a:schemeClr val="phClr"><a:tint val="98000"/><a:satMod val="130000"/><a:shade val="90000"/><a:lumMod val="103000"/>'
  '</a:schemeClr></a:gs><a:gs pos="100000"><a:schemeClr val="phClr"><a:shade val="63000"/><a:satMod val="120000"/>'
  '</a:schemeClr></a:gs></a:gsLst><a:lin ang="5400000" scaled="0"/></a:gradFill></a:bgFillStyleLst>'
  '</a:fmtScheme></a:themeElements><a:objectDefaults/><a:extraClrSchemeLst/></a:theme>' % A)


def lvl(n, sz, marl, indent, bullet=True, spcbef=1000):
    bu = ('<a:buFont typeface="Arial" panose="020B0604020202020204" pitchFamily="34" charset="0"/>'
          '<a:buChar char="&#8226;"/>') if bullet else '<a:buNone/>'
    return ('<a:lvl%dpPr marL="%d" indent="%d" algn="l" defTabSz="914400" rtl="0" eaLnBrk="1" latinLnBrk="0" '
            'hangingPunct="1"><a:lnSpc><a:spcPct val="90000"/></a:lnSpc><a:spcBef><a:spcPts val="%d"/></a:spcBef>'
            '%s<a:defRPr sz="%d" kern="1200"><a:solidFill><a:schemeClr val="tx1"/></a:solidFill>'
            '<a:latin typeface="+mn-lt"/><a:ea typeface="+mn-ea"/><a:cs typeface="+mn-cs"/></a:defRPr></a:lvl%dpPr>'
            % (n, marl, indent, spcbef, bu, sz, n))


def other_lvl(n):
    return ('<a:lvl%dpPr marL="%d" algn="l" defTabSz="914400" rtl="0" eaLnBrk="1" latinLnBrk="0" hangingPunct="1">'
            '<a:defRPr sz="1800" kern="1200"><a:solidFill><a:schemeClr val="tx1"/></a:solidFill>'
            '<a:latin typeface="+mn-lt"/><a:ea typeface="+mn-ea"/><a:cs typeface="+mn-cs"/></a:defRPr></a:lvl%dpPr>'
            % (n, (n - 1) * 457200, n))


BODY_LEVELS = [(2800, 228600), (2400, 685800), (2000, 1143000), (1800, 1600200), (1800, 2057400),
               (1800, 2514600), (1800, 2971800), (1800, 3429000), (1800, 3886200)]


def master():
    body_lv = "".join(lvl(i + 1, sz, ml, -228600, True, 1000 if i == 0 else 500) for i, (sz, ml) in enumerate(BODY_LEVELS))
    tree = (ph_sp(2, "Title Placeholder 1", 'type="title"', (838200, 365125, 10515600, 1325563),
                  ' vert="horz" lIns="91440" tIns="45720" rIns="91440" bIns="45720" rtlCol="0" anchor="ctr"',
                  ["Click to edit Master title style"])
            + ph_sp(3, "Text Placeholder 2", 'type="body" idx="1"', (838200, 1825625, 10515600, 4351338),
                    ' vert="horz" lIns="91440" tIns="45720" rIns="91440" bIns="45720" rtlCol="0"',
                    ["Click to edit Master text styles"])
            + ph_sp(4, "Date Placeholder 3", 'type="dt" sz="half" idx="2"', (838200, 6356350, 2743200, 365125),
                    ' vert="horz" lIns="91440" tIns="45720" rIns="91440" bIns="45720" rtlCol="0" anchor="ctr"',
                    txbody_extra="")
            + ph_sp(5, "Footer Placeholder 4", 'type="ftr" sz="quarter" idx="3"', (4038600, 6356350, 4114800, 365125),
                    ' vert="horz" lIns="91440" tIns="45720" rIns="91440" bIns="45720" rtlCol="0" anchor="ctr"')
            + ph_sp(6, "Slide Number Placeholder 5", 'type="sldNum" sz="quarter" idx="4"',
                    (8610600, 6356350, 2743200, 365125),
                    ' vert="horz" lIns="91440" tIns="45720" rIns="91440" bIns="45720" rtlCol="0" anchor="ctr"'))
    # small grey right/centre aligned text for the footer placeholders
    tree = tree.replace('<p:txBody><a:bodyPr vert="horz" lIns="91440" tIns="45720" rIns="91440" bIns="45720" rtlCol="0" anchor="ctr"/><a:lstStyle/><a:p><a:endParaRPr lang="en-US"/></a:p></p:txBody>',
                        '<p:txBody><a:bodyPr vert="horz" lIns="91440" tIns="45720" rIns="91440" bIns="45720" rtlCol="0" anchor="ctr"/>'
                        '<a:lstStyle><a:lvl1pPr algn="l"><a:defRPr sz="1200"><a:solidFill><a:schemeClr val="tx1">'
                        '<a:tint val="75000"/></a:schemeClr></a:solidFill></a:defRPr></a:lvl1pPr></a:lstStyle>'
                        '<a:p><a:endParaRPr lang="en-US"/></a:p></p:txBody>')
    title_style = ('<p:titleStyle><a:lvl1pPr algn="l" defTabSz="914400" rtl="0" eaLnBrk="1" latinLnBrk="0" hangingPunct="1">'
                   '<a:lnSpc><a:spcPct val="90000"/></a:lnSpc><a:spcBef><a:spcPct val="0"/></a:spcBef><a:buNone/>'
                   '<a:defRPr sz="4400" kern="1200"><a:solidFill><a:schemeClr val="tx1"/></a:solidFill>'
                   '<a:latin typeface="+mj-lt"/><a:ea typeface="+mj-ea"/><a:cs typeface="+mj-cs"/></a:defRPr>'
                   '</a:lvl1pPr></p:titleStyle>')
    other = "<p:otherStyle><a:defPPr><a:defRPr lang=\"en-US\"/></a:defPPr>%s</p:otherStyle>" % "".join(other_lvl(i) for i in range(1, 10))
    lays = "".join('<p:sldLayoutId id="%d" r:id="rId%d"/>' % (2147483649 + i, i + 1) for i in range(11))
    return (HDR + '<p:sldMaster %s><p:cSld><p:bg><p:bgRef idx="1001"><a:schemeClr val="bg1"/></p:bgRef></p:bg>'
            '<p:spTree>%s%s</p:spTree></p:cSld><p:clrMap bg1="lt1" tx1="dk1" bg2="lt2" tx2="dk2" accent1="accent1" '
            'accent2="accent2" accent3="accent3" accent4="accent4" accent5="accent5" accent6="accent6" hlink="hlink" '
            'folHlink="folHlink"/><p:sldLayoutIdLst>%s</p:sldLayoutIdLst><p:txStyles>%s<p:bodyStyle>%s</p:bodyStyle>%s'
            '</p:txStyles></p:sldMaster>' % (NS, GROUP, tree, lays, title_style, body_lv, other))


FOOTERS = (ph_sp(4, "Date Placeholder 3", 'type="dt" sz="half" idx="10"')
           + ph_sp(5, "Footer Placeholder 4", 'type="ftr" sz="quarter" idx="11"')
           + ph_sp(6, "Slide Number Placeholder 5", 'type="sldNum" sz="quarter" idx="12"'))


def layout(name, kind, shapes, footers=True, extra=""):
    return (HDR + '<p:sldLayout %s type="%s" preserve="1"><p:cSld name="%s"><p:spTree>%s%s%s</p:spTree></p:cSld>'
            '<p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr>%s</p:sldLayout>'
            % (NS, kind, name, GROUP, shapes, FOOTERS if footers else "", extra))


def big(sz):
    return '<a:lstStyle><a:lvl1pPr algn="ctr"><a:defRPr sz="%d"/></a:lvl1pPr></a:lstStyle>' % sz


def centred_title():
    s = ph_sp(2, "Title 1", 'type="ctrTitle"', (1524000, 1122363, 9144000, 2387600), ' anchor="b"', ["Click to edit Master title style"])
    s = s.replace("<a:lstStyle/>", big(6000))
    sub = ph_sp(3, "Subtitle 2", 'type="subTitle" idx="1"', (1524000, 3602038, 9144000, 1655762), "", ["Click to edit Master subtitle style"])
    sub = sub.replace("<a:lstStyle/>", '<a:lstStyle><a:lvl1pPr marL="0" indent="0" algn="ctr"><a:buNone/><a:defRPr sz="2400"/></a:lvl1pPr>'
                      '<a:lvl2pPr marL="457200" indent="0" algn="ctr"><a:buNone/><a:defRPr sz="2000"/></a:lvl2pPr></a:lstStyle>')
    return s + sub


def title_ph(geom=None):
    return ph_sp(2, "Title 1", 'type="title"', geom, "", ["Click to edit Master title style"])


def body_ph(sid, name, idx, geom=None, text="Click to edit Master text styles", extra_ph=""):
    return ph_sp(sid, name, 'idx="%d"%s' % (idx, extra_ph), geom, "", [text])


LAYOUTS = [
    ("Title Slide", "title", centred_title()),
    ("Title and Content", "obj", title_ph() + body_ph(3, "Content Placeholder 2", 1)),
    ("Section Header", "secHead",
     ph_sp(2, "Title 1", 'type="title"', (831850, 1709738, 10515600, 2852737), ' anchor="b"', ["Click to edit Master title style"]).replace("<a:lstStyle/>", '<a:lstStyle><a:lvl1pPr><a:defRPr sz="6000"/></a:lvl1pPr></a:lstStyle>')
     + ph_sp(3, "Text Placeholder 2", 'type="body" idx="1"', (831850, 4589463, 10515600, 1500187), "", ["Click to edit Master text styles"]).replace("<a:lstStyle/>", '<a:lstStyle><a:lvl1pPr marL="0" indent="0"><a:buNone/><a:defRPr sz="2400"><a:solidFill><a:schemeClr val="tx1"><a:tint val="75000"/></a:schemeClr></a:solidFill></a:defRPr></a:lvl1pPr></a:lstStyle>')),
    ("Two Content", "twoObj", title_ph() + body_ph(3, "Content Placeholder 2", 1, (838200, 1825625, 5181600, 4351338), extra_ph=' sz="half"')
     + body_ph(4, "Content Placeholder 3", 2, (6172200, 1825625, 5181600, 4351338), extra_ph=' sz="half"')),
    ("Comparison", "twoTxTwoObj", title_ph((839788, 365125, 10515600, 1325563))
     + ph_sp(3, "Text Placeholder 2", 'type="body" idx="1"', (839788, 1681163, 5157787, 823912), ' anchor="b"', ["Click to edit Master text styles"]).replace("<a:lstStyle/>", '<a:lstStyle><a:lvl1pPr marL="0" indent="0"><a:buNone/><a:defRPr sz="2400" b="1"/></a:lvl1pPr></a:lstStyle>')
     + body_ph(4, "Content Placeholder 3", 2, (839788, 2505075, 5157787, 3684588), extra_ph=' sz="half"')
     + ph_sp(5, "Text Placeholder 4", 'type="body" sz="quarter" idx="3"', (6172200, 1681163, 5183188, 823912), ' anchor="b"', ["Click to edit Master text styles"]).replace("<a:lstStyle/>", '<a:lstStyle><a:lvl1pPr marL="0" indent="0"><a:buNone/><a:defRPr sz="2400" b="1"/></a:lvl1pPr></a:lstStyle>')
     + body_ph(6, "Content Placeholder 5", 4, (6172200, 2505075, 5183188, 3684588), extra_ph=' sz="quarter"')),
    ("Title Only", "titleOnly", title_ph()),
    ("Blank", "blank", ""),
    ("Content with Caption", "objTx",
     ph_sp(2, "Title 1", 'type="title"', (839788, 457200, 3932237, 1600200), ' anchor="b"', ["Click to edit Master title style"]).replace("<a:lstStyle/>", '<a:lstStyle><a:lvl1pPr><a:defRPr sz="3200"/></a:lvl1pPr></a:lstStyle>')
     + body_ph(3, "Content Placeholder 2", 1, (5183188, 987425, 6172200, 4873625))
     + ph_sp(4, "Text Placeholder 3", 'type="body" sz="half" idx="2"', (839788, 2057400, 3932237, 3811588), "", ["Click to edit Master text styles"]).replace("<a:lstStyle/>", '<a:lstStyle><a:lvl1pPr marL="0" indent="0"><a:buNone/><a:defRPr sz="1600"/></a:lvl1pPr></a:lstStyle>')),
    ("Picture with Caption", "picTx",
     ph_sp(2, "Title 1", 'type="title"', (839788, 457200, 3932237, 1600200), ' anchor="b"', ["Click to edit Master title style"]).replace("<a:lstStyle/>", '<a:lstStyle><a:lvl1pPr><a:defRPr sz="3200"/></a:lvl1pPr></a:lstStyle>')
     + ph_sp(3, "Picture Placeholder 2", 'type="pic" idx="1"', (5183188, 987425, 6172200, 4873625), "", [""]).replace("<a:lstStyle/>", '<a:lstStyle><a:lvl1pPr marL="0" indent="0"><a:buNone/><a:defRPr sz="3200"/></a:lvl1pPr></a:lstStyle>')
     + ph_sp(4, "Text Placeholder 3", 'type="body" sz="half" idx="2"', (839788, 2057400, 3932237, 3811588), "", ["Click to edit Master text styles"]).replace("<a:lstStyle/>", '<a:lstStyle><a:lvl1pPr marL="0" indent="0"><a:buNone/><a:defRPr sz="1600"/></a:lvl1pPr></a:lstStyle>')),
    ("Title and Vertical Text", "vertTx", title_ph()
     + ph_sp(3, "Vertical Text Placeholder 2", 'type="body" orient="vert" idx="1"', None, ' vert="eaVert"', ["Click to edit Master text styles"])),
    ("Vertical Title and Text", "vertTitleAndTx",
     ph_sp(2, "Vertical Title 1", 'type="title" orient="vert"', (8724900, 365125, 2628900, 5811838), ' vert="eaVert"', ["Click to edit Master title style"])
     + ph_sp(3, "Vertical Text Placeholder 2", 'type="body" orient="vert" idx="1"', (838200, 365125, 7734300, 5811838), ' vert="eaVert"', ["Click to edit Master text styles"])),
]

CT = HDR + ('<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Default Extension="png" ContentType="image/png"/><Default Extension="jpeg" ContentType="image/jpeg"/>'
            '<Override PartName="/ppt/presentation.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml"/>'
            '<Override PartName="/ppt/slideMasters/slideMaster1.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slideMaster+xml"/>'
            '%s'
            '<Override PartName="/ppt/slides/slide1.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slide+xml"/>'
            '<Override PartName="/ppt/presProps.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.presProps+xml"/>'
            '<Override PartName="/ppt/viewProps.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.viewProps+xml"/>'
            '<Override PartName="/ppt/theme/theme1.xml" ContentType="application/vnd.openxmlformats-officedocument.theme+xml"/>'
            '<Override PartName="/ppt/tableStyles.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.tableStyles+xml"/>'
            '<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>'
            '<Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>'
            '</Types>') % "".join(
    '<Override PartName="/ppt/slideLayouts/slideLayout%d.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slideLayout+xml"/>' % (i + 1)
    for i in range(len(LAYOUTS)))

PRES = HDR + ('<p:presentation %s saveSubsetFonts="1"><p:sldMasterIdLst><p:sldMasterId id="2147483648" r:id="rId1"/>'
              '</p:sldMasterIdLst><p:sldIdLst><p:sldId id="256" r:id="rId2"/></p:sldIdLst>'
              '<p:sldSz cx="%d" cy="%d"/><p:notesSz cx="6858000" cy="9144000"/><p:defaultTextStyle>'
              '<a:defPPr><a:defRPr lang="en-US"/></a:defPPr>%s</p:defaultTextStyle></p:presentation>'
              % (NS, CX, CY, "".join(other_lvl(i) for i in range(1, 10))))

SLIDE1 = HDR + ('<p:sld %s><p:cSld><p:spTree>%s%s%s</p:spTree></p:cSld><p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr></p:sld>'
                % (NS, GROUP,
                   '<p:sp><p:nvSpPr><p:cNvPr id="2" name="Title 1"/><p:cNvSpPr><a:spLocks noGrp="1"/></p:cNvSpPr>'
                   '<p:nvPr><p:ph type="ctrTitle"/></p:nvPr></p:nvSpPr><p:spPr/><p:txBody><a:bodyPr/><a:lstStyle/>'
                   '<a:p><a:endParaRPr lang="en-US"/></a:p></p:txBody></p:sp>',
                   '<p:sp><p:nvSpPr><p:cNvPr id="3" name="Subtitle 2"/><p:cNvSpPr><a:spLocks noGrp="1"/></p:cNvSpPr>'
                   '<p:nvPr><p:ph type="subTitle" idx="1"/></p:nvPr></p:nvSpPr><p:spPr/><p:txBody><a:bodyPr/><a:lstStyle/>'
                   '<a:p><a:endParaRPr lang="en-US"/></a:p></p:txBody></p:sp>'))

CORE = HDR + ('<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
              'xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" '
              'xmlns:dcmitype="http://purl.org/dc/dcmitype/" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
              '<dc:title>PowerPoint Presentation</dc:title><cp:revision>1</cp:revision></cp:coreProperties>').replace(
    "PowerPoint Presentation", "Presentation")
APP = HDR + ('<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties" '
             'xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes">'
             '<Application>Folio Show</Application><PresentationFormat>Widescreen</PresentationFormat>'
             '<Slides>1</Slides></Properties>')
PRESPROPS = HDR + '<p:presentationPr %s/>' % NS
VIEWPROPS = HDR + ('<p:viewPr %s><p:normalViewPr><p:restoredLeft sz="15000"/><p:restoredTop sz="94660"/></p:normalViewPr>'
                   '<p:gridSpacing cx="76200" cy="76200"/></p:viewPr>' % NS)
TABLESTYLES = HDR + ('<a:tblStyleLst xmlns:a="%s" def="{5C22544A-7EE6-4342-B048-85BDC9FD1C3A}"/>' % A)


def build(path):
    files = {
        "[Content_Types].xml": CT,
        "_rels/.rels": rels([("officeDocument", "ppt/presentation.xml")]).replace(
            "</Relationships>",
            '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>'
            '<Relationship Id="rId3" Type="%sextended-properties" Target="docProps/app.xml"/></Relationships>' % RT),
        "docProps/core.xml": CORE,
        "docProps/app.xml": APP,
        "ppt/presentation.xml": PRES,
        "ppt/_rels/presentation.xml.rels": rels([("slideMaster", "slideMasters/slideMaster1.xml"),
                                                 ("slide", "slides/slide1.xml"), ("presProps", "presProps.xml"),
                                                 ("viewProps", "viewProps.xml"), ("theme", "theme/theme1.xml"),
                                                 ("tableStyles", "tableStyles.xml")]),
        "ppt/presProps.xml": PRESPROPS, "ppt/viewProps.xml": VIEWPROPS, "ppt/tableStyles.xml": TABLESTYLES,
        "ppt/theme/theme1.xml": THEME,
        "ppt/slideMasters/slideMaster1.xml": master(),
        "ppt/slideMasters/_rels/slideMaster1.xml.rels": rels(
            [("slideLayout", "../slideLayouts/slideLayout%d.xml" % (i + 1)) for i in range(len(LAYOUTS))]
            + [("theme", "../theme/theme1.xml")]),
        "ppt/slides/slide1.xml": SLIDE1,
        "ppt/slides/_rels/slide1.xml.rels": rels([("slideLayout", "../slideLayouts/slideLayout1.xml")]),
    }
    for i, (name, kind, shapes) in enumerate(LAYOUTS):
        files["ppt/slideLayouts/slideLayout%d.xml" % (i + 1)] = layout(name, kind, shapes, footers=True)
        files["ppt/slideLayouts/_rels/slideLayout%d.xml.rels" % (i + 1)] = rels([("slideMaster", "../slideMasters/slideMaster1.xml")])
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", files.pop("[Content_Types].xml"))
        z.writestr("_rels/.rels", files.pop("_rels/.rels"))
        for k, v in files.items():
            z.writestr(k, v)


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(__file__), "..", "share", "templates", "Blank.pptx")
    build(out)
    print(out)

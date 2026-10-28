//! Ink (freeform strokes), video and audio, embedded documents.

use crate::edit::{fragment, next_shape_id, rel_path};
use crate::model::{path, Deck, RT};
use folio_core::package::Package;

const CT: &str = "[Content_Types].xml";
const REL_MEDIA: &str = "http://schemas.microsoft.com/office/2007/relationships/media";
const NS_P14: &str = "http://schemas.microsoft.com/office/powerpoint/2010/main";

fn media_ctype(ext: &str) -> &'static str {
    match ext {
        "mp4" | "m4v" => "video/mp4",
        "mov" => "video/quicktime",
        "webm" => "video/webm",
        "avi" => "video/x-msvideo",
        "wmv" => "video/x-ms-wmv",
        "mkv" => "video/x-matroska",
        "mp3" => "audio/mpeg",
        "m4a" => "audio/mp4",
        "wav" => "audio/wav",
        "ogg" | "oga" => "audio/ogg",
        "flac" => "audio/flac",
        "wma" => "audio/x-ms-wma",
        _ => "application/octet-stream",
    }
}

impl Deck {
    /// A pen or highlighter stroke as a freeform: points in slide points, colour RRGGBB,
    /// width in points, alpha in percent (100 = opaque).
    pub fn add_ink(&mut self, i: usize, pts: &[(f64, f64)], color: u32, width: f64, alpha: f64, name: &str) -> Result<u32, String> {
        if pts.len() < 2 {
            return Err("too short".into());
        }
        let part = self.slide_part(i)?;
        self.begin("Ink", &[part.clone()]);
        let (mut x0, mut y0, mut x1, mut y1) = (f64::MAX, f64::MAX, f64::MIN, f64::MIN);
        for &(x, y) in pts {
            x0 = x0.min(x);
            y0 = y0.min(y);
            x1 = x1.max(x);
            y1 = y1.max(y);
        }
        let (w, h) = ((x1 - x0).max(0.5), (y1 - y0).max(0.5));
        let e = |v: f64| (v * 12700.0).round() as i64;
        let mut p = format!(r#"<a:moveTo><a:pt x="{}" y="{}"/></a:moveTo>"#, e(pts[0].0 - x0), e(pts[0].1 - y0));
        for &(x, y) in &pts[1..] {
            p.push_str(&format!(r#"<a:lnTo><a:pt x="{}" y="{}"/></a:lnTo>"#, e(x - x0), e(y - y0)));
        }
        let alpha_xml = if alpha < 99.5 { format!(r#"<a:alpha val="{}"/>"#, (alpha * 1000.0).round() as i64) } else { String::new() };
        let d = self.pkg.xml_mut(&part).map_err(|e| e.to_string())?;
        let id = next_shape_id(d);
        let xml = format!(
            r#"<p:sp><p:nvSpPr><p:cNvPr id="{id}" name="{name} {n}"/><p:cNvSpPr/><p:nvPr/></p:nvSpPr><p:spPr><a:xfrm><a:off x="{}" y="{}"/><a:ext cx="{}" cy="{}"/></a:xfrm><a:custGeom><a:avLst/><a:gdLst/><a:ahLst/><a:cxnLst/><a:rect l="0" t="0" r="r" b="b"/><a:pathLst><a:path w="{}" h="{}" fill="none">{p}</a:path></a:pathLst></a:custGeom><a:noFill/><a:ln w="{}" cap="rnd"><a:solidFill><a:srgbClr val="{:06X}">{alpha_xml}</a:srgbClr></a:solidFill><a:round/></a:ln></p:spPr></p:sp>"#,
            e(x0), e(y0), e(w), e(h), e(w), e(h), e(width), color, n = id - 1);
        let tree = path(d, d.root, &["p:cSld", "p:spTree"]).ok_or("no tree")?;
        let node = fragment(d, &xml).ok_or("bad ink")?;
        d.append(tree, node);
        self.commit();
        Ok(id)
    }

    /// Insert a video or audio file (kind "video" | "audio") shown by `poster` (a PNG).
    #[allow(clippy::too_many_arguments)]
    pub fn add_media(&mut self, i: usize, kind: &str, data: Vec<u8>, ext: &str, poster: Vec<u8>, name: &str,
                     x: f64, y: f64, w: f64, h: f64) -> Result<u32, String> {
        let slide = self.slide_part(i)?;
        let ext = ext.to_lowercase();
        let media = self.free_name("ppt/media", "media", &ext);
        let img = self.free_name("ppt/media", "image", "png");
        self.begin(if kind == "audio" { "Insert Audio" } else { "Insert Video" },
                   &[slide.clone(), Package::rels_name(&slide), CT.to_string(), media.clone(), img.clone()]);
        self.pkg.put_raw(&media, data);
        self.pkg.ensure_default(&ext, media_ctype(&ext));
        self.pkg.put_raw(&img, poster);
        self.pkg.ensure_default("png", "image/png");
        let target = rel_path(&slide, &media);
        let link = self.pkg.add_rel(&slide, &format!("{RT}{kind}"), &target);
        let embed = self.pkg.add_rel(&slide, REL_MEDIA, &target);
        let pic = self.pkg.add_rel(&slide, &format!("{RT}image"), &rel_path(&slide, &img));
        let d = self.pkg.xml_mut(&slide).map_err(|e| e.to_string())?;
        let id = next_shape_id(d);
        let e = |v: f64| (v * 12700.0).round() as i64;
        let file = if kind == "audio" { "a:audioFile" } else { "a:videoFile" };
        let xml = format!(
            r#"<p:pic><p:nvPicPr><p:cNvPr id="{id}" name="{}"><a:hlinkClick r:id="" action="ppaction://media"/></p:cNvPr><p:cNvPicPr><a:picLocks noChangeAspect="1"/></p:cNvPicPr><p:nvPr><{file} r:link="{link}"/><p:extLst><p:ext uri="{{DAA4B4D4-6D71-4841-9C94-3DE7FCFB9230}}"><p14:media xmlns:p14="{NS_P14}" r:embed="{embed}"/></p:ext></p:extLst></p:nvPr></p:nvPicPr><p:blipFill><a:blip r:embed="{pic}"/><a:stretch><a:fillRect/></a:stretch></p:blipFill><p:spPr><a:xfrm><a:off x="{}" y="{}"/><a:ext cx="{}" cy="{}"/></a:xfrm><a:prstGeom prst="rect"><a:avLst/></a:prstGeom></p:spPr></p:pic>"#,
            esc(name), e(x), e(y), e(w), e(h));
        let tree = path(d, d.root, &["p:cSld", "p:spTree"]).ok_or("no tree")?;
        let node = fragment(d, &xml).ok_or("bad media")?;
        d.append(tree, node);
        self.commit();
        Ok(id)
    }

    /// A media shape's (kind, part, extension), or None.
    pub fn media_info(&mut self, i: usize, id: u32) -> Option<(String, String, String)> {
        let slide = self.slide_part(i).ok()?;
        let n = self.find_shape(&slide, id)?;
        let d = self.pkg.xml(&slide).ok()?;
        let nv = path(d, n, &["p:nvPicPr", "p:nvPr"])?;
        let (kind, f) = if let Some(f) = d.child(nv, "a:videoFile") { ("video", f) } else { ("audio", d.child(nv, "a:audioFile")?) };
        // the embedded copy first (p14:media), else the link
        let mut rid = d.attr(f, "r:link").unwrap_or("").to_string();
        fn find_media(d: &folio_core::xml::XmlDoc, n: folio_core::xml::NodeId) -> Option<String> {
            for c in d.elements(n) {
                if d.name(c) == "p14:media" {
                    return d.attr(c, "r:embed").map(|s| s.to_string());
                }
                if let Some(x) = find_media(d, c) {
                    return Some(x);
                }
            }
            None
        }
        if let Some(e) = find_media(d, nv) {
            rid = e;
        }
        let t = self.pkg.rel_target(&slide, &rid)?;
        let part = Package::resolve(&slide, &t);
        let ext = part.rsplit('.').next().unwrap_or("").to_string();
        Some((kind.to_string(), part, ext))
    }

    /// Embed a document (an Office Open XML file) shown by `icon` (a PNG).
    #[allow(clippy::too_many_arguments)]
    pub fn add_embedded(&mut self, i: usize, data: Vec<u8>, ext: &str, prog_id: &str, icon: Vec<u8>, name: &str,
                        x: f64, y: f64, w: f64, h: f64) -> Result<u32, String> {
        let slide = self.slide_part(i)?;
        let ext = ext.to_lowercase();
        let stem = match ext.as_str() { "xlsx" => "Microsoft_Excel_Worksheet", "docx" => "Microsoft_Word_Document", "pptx" => "Microsoft_PowerPoint_Presentation", _ => "Package" };
        let part = self.free_name("ppt/embeddings", stem, &ext);
        let img = self.free_name("ppt/media", "image", "png");
        self.begin("Insert Object", &[slide.clone(), Package::rels_name(&slide), CT.to_string(), part.clone(), img.clone()]);
        self.pkg.put_raw(&part, data);
        let ct = match ext.as_str() {
            "xlsx" => "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "docx" => "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "pptx" => "application/vnd.openxmlformats-officedocument.presentationml.presentation",
            _ => "application/octet-stream",
        };
        self.pkg.ensure_default(&ext, ct);
        self.pkg.put_raw(&img, icon);
        self.pkg.ensure_default("png", "image/png");
        let rid = self.pkg.add_rel(&slide, &format!("{RT}package"), &rel_path(&slide, &part));
        let pic = self.pkg.add_rel(&slide, &format!("{RT}image"), &rel_path(&slide, &img));
        let d = self.pkg.xml_mut(&slide).map_err(|e| e.to_string())?;
        let id = next_shape_id(d);
        let e = |v: f64| (v * 12700.0).round() as i64;
        let xml = format!(
            r#"<p:graphicFrame><p:nvGraphicFramePr><p:cNvPr id="{id}" name="{}"/><p:cNvGraphicFramePr><a:graphicFrameLocks noChangeAspect="1"/></p:cNvGraphicFramePr><p:nvPr/></p:nvGraphicFramePr><p:xfrm><a:off x="{x0}" y="{y0}"/><a:ext cx="{cx}" cy="{cy}"/></p:xfrm><a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/presentationml/2006/ole"><p:oleObj showAsIcon="1" name="{}" r:id="{rid}" imgW="{cx}" imgH="{cy}" progId="{prog_id}"><p:embed/><p:pic><p:nvPicPr><p:cNvPr id="0" name=""/><p:cNvPicPr/><p:nvPr/></p:nvPicPr><p:blipFill><a:blip r:embed="{pic}"/><a:stretch><a:fillRect/></a:stretch></p:blipFill><p:spPr><a:xfrm><a:off x="{x0}" y="{y0}"/><a:ext cx="{cx}" cy="{cy}"/></a:xfrm><a:prstGeom prst="rect"><a:avLst/></a:prstGeom></p:spPr></p:pic></p:oleObj></a:graphicData></a:graphic></p:graphicFrame>"#,
            esc(name), esc(name), x0 = e(x), y0 = e(y), cx = e(w), cy = e(h));
        let tree = path(d, d.root, &["p:cSld", "p:spTree"]).ok_or("no tree")?;
        let node = fragment(d, &xml).ok_or("bad object")?;
        d.append(tree, node);
        self.commit();
        Ok(id)
    }

    /// An embedded object's (prog id, part), or None.
    pub fn embedded_info(&mut self, i: usize, id: u32) -> Option<(String, String)> {
        let slide = self.slide_part(i).ok()?;
        let n = self.find_shape(&slide, id)?;
        let d = self.pkg.xml(&slide).ok()?;
        let gd = path(d, n, &["a:graphic", "a:graphicData"])?;
        let ole = {
            fn find(d: &folio_core::xml::XmlDoc, n: folio_core::xml::NodeId) -> Option<folio_core::xml::NodeId> {
                for c in d.elements(n) {
                    if d.name(c) == "p:oleObj" {
                        return Some(c);
                    }
                    if let Some(x) = find(d, c) {
                        return Some(x);
                    }
                }
                None
            }
            find(d, gd)?
        };
        let prog = d.attr(ole, "progId").unwrap_or("").to_string();
        let rid = d.attr(ole, "r:id")?.to_string();
        let t = self.pkg.rel_target(&slide, &rid)?;
        Some((prog, Package::resolve(&slide, &t)))
    }

    pub fn part_bytes(&self, part: &str) -> Option<Vec<u8>> {
        self.pkg.bytes(part)
    }
}

fn esc(s: &str) -> String {
    let mut o = String::new();
    folio_core::xml::escape_text(s, &mut o);
    o.replace('"', "&quot;")
}

const NS_M: &str = "http://schemas.openxmlformats.org/officeDocument/2006/math";
const NS_A14: &str = "http://schemas.microsoft.com/office/drawing/2010/main";

impl Deck {
    /// An equation: `omml` is its m:oMath; `png` the picture shown by programs without math.
    #[allow(clippy::too_many_arguments)]
    pub fn insert_equation(&mut self, i: usize, omml: &str, png: Vec<u8>, x: f64, y: f64, w: f64, h: f64) -> Result<u32, String> {
        let slide = self.slide_part(i)?;
        let img = self.free_name("ppt/media", "image", "png");
        self.begin("Insert Equation", &[slide.clone(), Package::rels_name(&slide), CT.to_string(), img.clone()]);
        self.pkg.put_raw(&img, png);
        self.pkg.ensure_default("png", "image/png");
        let pic = self.pkg.add_rel(&slide, &format!("{RT}image"), &rel_path(&slide, &img));
        let d = self.pkg.xml_mut(&slide).map_err(|e| e.to_string())?;
        let id = next_shape_id(d);
        let xml = equation_xml(id, omml, &pic, x, y, w, h);
        let tree = path(d, d.root, &["p:cSld", "p:spTree"]).ok_or("no tree")?;
        let node = fragment(d, &xml).ok_or("bad equation")?;
        d.append(tree, node);
        self.commit();
        Ok(id)
    }

    /// The m:oMath of an equation shape (None: it isn't one).
    pub fn equation(&mut self, i: usize, id: u32) -> Option<String> {
        let slide = self.slide_part(i).ok()?;
        let n = self.find_shape(&slide, id)?;
        let d = self.pkg.xml(&slide).ok()?;
        fn find(d: &folio_core::xml::XmlDoc, n: folio_core::xml::NodeId) -> Option<folio_core::xml::NodeId> {
            for c in d.elements(n) {
                if d.name(c) == "m:oMath" {
                    return Some(c);
                }
                if let Some(x) = find(d, c) {
                    return Some(x);
                }
            }
            None
        }
        let m = find(d, n)?;
        Some(d.serialize_node(m))
    }

    /// Change an equation (and its picture), keeping its place.
    #[allow(clippy::too_many_arguments)]
    pub fn set_equation(&mut self, i: usize, id: u32, omml: &str, png: Vec<u8>, w: f64, h: f64) -> Result<(), String> {
        let slide = self.slide_part(i)?;
        let n = self.find_shape(&slide, id).ok_or("no such equation")?;
        let (x, y) = {
            let d = self.pkg.xml(&slide).map_err(|e| e.to_string())?;
            let off = path(d, n, &["p:spPr", "a:xfrm", "a:off"]);
            (off.and_then(|o| crate::model::emu(d, o, "x")).unwrap_or(0.0) / 12700.0,
             off.and_then(|o| crate::model::emu(d, o, "y")).unwrap_or(0.0) / 12700.0)
        };
        let img = self.free_name("ppt/media", "image", "png");
        self.begin("Equation", &[slide.clone(), Package::rels_name(&slide), CT.to_string(), img.clone()]);
        self.pkg.put_raw(&img, png);
        let pic = self.pkg.add_rel(&slide, &format!("{RT}image"), &rel_path(&slide, &img));
        let d = self.pkg.xml_mut(&slide).map_err(|e| e.to_string())?;
        let (ac, _t) = crate::edit::alt_twins(d, n);
        let old = ac.unwrap_or(n);
        let parent = d.parent(old).ok_or("bad equation")?;
        let at = d.index_in_parent(old).unwrap_or(0);
        d.detach(old);
        let node = fragment(d, &equation_xml(id, omml, &pic, x, y, w, h)).ok_or("bad equation")?;
        d.insert(parent, at, node);
        self.commit();
        Ok(())
    }
}

fn equation_xml(id: u32, omml: &str, pic: &str, x: f64, y: f64, w: f64, h: f64) -> String {
    let e = |v: f64| (v * 12700.0).round() as i64;
    let sppr = |fill: &str| format!(r#"<p:spPr><a:xfrm><a:off x="{}" y="{}"/><a:ext cx="{}" cy="{}"/></a:xfrm><a:prstGeom prst="rect"><a:avLst/></a:prstGeom>{fill}</p:spPr>"#,
                                    e(x), e(y), e(w), e(h));
    let nv = format!(r#"<p:nvSpPr><p:cNvPr id="{id}" name="TextBox {}"/><p:cNvSpPr txBox="1"/><p:nvPr/></p:nvSpPr>"#, id - 1);
    // the oMath with the math namespace declared on it
    let omml = if omml.contains("xmlns:m=") { omml.to_string() } else { omml.replacen("<m:oMath", &format!(r#"<m:oMath xmlns:m="{NS_M}""#), 1) };
    format!(
        r#"<mc:AlternateContent xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006"><mc:Choice xmlns:a14="{NS_A14}" Requires="a14"><p:sp>{nv}{}<p:txBody><a:bodyPr wrap="none" lIns="0" tIns="0" rIns="0" bIns="0"><a:spAutoFit/></a:bodyPr><a:lstStyle/><a:p><a:pPr algn="ctr"/><a14:m><m:oMathPara xmlns:m="{NS_M}"><m:oMathParaPr><m:jc m:val="centerGroup"/></m:oMathParaPr>{omml}</m:oMathPara></a14:m><a:endParaRPr lang="en-US"/></a:p></p:txBody></p:sp></mc:Choice><mc:Fallback><p:sp>{nv}{}<p:txBody><a:bodyPr/><a:lstStyle/><a:p><a:r><a:rPr lang="en-US"><a:noFill/></a:rPr><a:t> </a:t></a:r></a:p></p:txBody></p:sp></mc:Fallback></mc:AlternateContent>"#,
        sppr("<a:noFill/>"),
        sppr(&format!(r#"<a:blipFill><a:blip r:embed="{pic}"/><a:stretch><a:fillRect/></a:stretch></a:blipFill>"#)))
}

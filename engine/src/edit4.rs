//! Reusing slides from another presentation, changing a picture, slide show settings.

use crate::edit::{fragment, rel_path};
use crate::model::{path, Deck, RT};
use folio_core::package::Package;
use folio_core::xml::XmlDoc;
use std::collections::HashMap;

const CT: &str = "[Content_Types].xml";

pub fn image_ctype(ext: &str) -> &'static str {
    match ext {
        "png" => "image/png",
        "jpeg" | "jpg" => "image/jpeg",
        "gif" => "image/gif",
        "bmp" => "image/bmp",
        "tif" | "tiff" => "image/tiff",
        "svg" => "image/svg+xml",
        "emf" => "image/x-emf",
        "wmf" => "image/x-wmf",
        _ => "application/octet-stream",
    }
}

/// A part's content type from a package's [Content_Types].xml.
fn content_type(pkg: &mut Package, name: &str) -> Option<String> {
    let d = pkg.xml(CT).ok()?;
    let pname = format!("/{name}");
    for o in d.children_named(d.root, "Override") {
        if d.attr(o, "PartName").map(|p| p.eq_ignore_ascii_case(&pname)).unwrap_or(false) {
            return d.attr(o, "ContentType").map(|s| s.to_string());
        }
    }
    let ext = name.rsplit('.').next()?.to_lowercase();
    for o in d.children_named(d.root, "Default") {
        if d.attr(o, "Extension").map(|e| e.eq_ignore_ascii_case(&ext)).unwrap_or(false) {
            return d.attr(o, "ContentType").map(|s| s.to_string());
        }
    }
    None
}

fn split_name(name: &str) -> (String, String, String) {
    let (dir, file) = name.rsplit_once('/').unwrap_or(("", name));
    let (stem, ext) = file.rsplit_once('.').unwrap_or((file, ""));
    let stem = stem.trim_end_matches(|c: char| c.is_ascii_digit()).to_string();
    (dir.to_string(), stem, ext.to_string())
}

impl Deck {
    /// Copy part `name` of `src` (and what it relates to) into this package; returns its new name.
    fn copy_part(&mut self, src: &mut Package, name: &str, done: &mut HashMap<String, String>) -> Option<String> {
        if let Some(n) = done.get(name) {
            return Some(n.clone());
        }
        let data = src.bytes(name)?;
        let (dir, stem, ext) = split_name(name);
        let new = self.free_name(&dir, if stem.is_empty() { "part" } else { &stem }, &ext);
        done.insert(name.to_string(), new.clone());
        self.touch(&[new.clone(), Package::rels_name(&new)]);
        self.pkg.put_raw(&new, data);
        if let Some(ct) = content_type(src, name) {
            if content_type(&mut self.pkg, &new).as_deref() != Some(ct.as_str()) {
                self.pkg.set_content_type(&new, &ct);
            }
        }
        self.copy_rels(src, name, &new, done, None);
        Some(new)
    }

    /// Copy the relationships of src part `from` to our part `to`, with the same ids.
    fn copy_rels(&mut self, src: &mut Package, from: &str, to: &str, done: &mut HashMap<String, String>,
                 layout: Option<&str>) {
        let rels = src.rels(from);
        if rels.is_empty() {
            return;
        }
        let mut doc = XmlDoc::with_root("Relationships", &[("xmlns", "http://schemas.openxmlformats.org/package/2006/relationships")]);
        for r in rels {
            let kind = r.kind.rsplit('/').next().unwrap_or("").to_string();
            let target = if r.external {
                Some(r.target.clone())
            } else {
                match kind.as_str() {
                    "slideLayout" => layout.map(|l| rel_path(to, l)),
                    "notesSlide" | "comments" => None,
                    // a jump to another slide of the source: to this slide instead
                    "slide" => Some(rel_path(to, to)),
                    _ => {
                        let sp = Package::resolve(from, &r.target);
                        self.copy_part(src, &sp, done).map(|n| rel_path(to, &n))
                    }
                }
            };
            let Some(t) = target else { continue };
            let el = doc.new_element("Relationship", &[("Id", &r.id), ("Type", &r.kind), ("Target", &t)]);
            if r.external {
                doc.set_attr(el, "TargetMode", "External");
            }
            let root = doc.root;
            doc.append(root, el);
        }
        self.touch(&[Package::rels_name(to)]);
        self.pkg.put_xml(&Package::rels_name(to), doc);
    }

    /// The layouts of a presentation file's slides: [(slide index, title text, layout name)].
    pub fn file_slides(bytes: &[u8]) -> Result<Vec<(usize, String)>, String> {
        let mut src = Deck::open(bytes)?;
        let n = src.slides.len();
        Ok((0..n).map(|i| {
            let p = src.slides[i].clone();
            let lay = src.pkg.related(&p, "/slideLayout").unwrap_or_default();
            (i, src.layout_name(&lay))
        }).collect())
    }

    /// Insert slides `which` of another presentation (its bytes) after slide `after` (None: first),
    /// in this presentation's theme: each takes the layout with the same name, else `fallback`.
    pub fn reuse_slides(&mut self, bytes: &[u8], which: &[usize], after: Option<usize>, fallback: &str) -> Result<usize, String> {
        let mut src = Deck::open(bytes)?;
        let secs = self.section_parts();
        let mut by_name: HashMap<String, String> = HashMap::new();
        for m in self.masters() {
            for l in self.layouts_of(&m) {
                let n = self.layout_name(&l);
                by_name.entry(n).or_insert(l);
            }
        }
        self.begin("Reuse Slides", &self.structure_parts(&[]));
        let mut at = after.map(|a| (a + 1).min(self.slides.len())).unwrap_or(0);
        let first = at;
        let mut done: HashMap<String, String> = HashMap::new();
        let mut new_parts = Vec::new();
        for &k in which {
            let Some(sp) = src.slides.get(k).cloned() else { continue };
            let lay_src = src.pkg.related(&sp, "/slideLayout").unwrap_or_default();
            let lname = src.layout_name(&lay_src);
            let layout = by_name.get(&lname).cloned().unwrap_or_else(|| fallback.to_string());
            let part = self.free_name("ppt/slides", "slide", "xml");
            self.touch(&[part.clone(), Package::rels_name(&part)]);
            let data = src.pkg.bytes(&sp).ok_or("no slide")?;
            self.pkg.put_raw(&part, data);
            self.pkg.set_content_type(&part, crate::model::CT_SLIDE);
            self.copy_rels(&mut src.pkg, &sp, &part, &mut done, Some(&layout));
            self.slides.insert(at, part.clone());
            new_parts.push(part);
            at += 1;
        }
        self.write_slide_list()?;
        self.fix_sections(secs, &new_parts)?;
        self.commit();
        Ok(first)
    }

    /// Put a new picture file into a picture shape (its box stays).
    pub fn replace_picture(&mut self, i: usize, id: u32, data: Vec<u8>, ext: &str) -> Result<(), String> {
        let part = self.slide_part(i)?;
        let n = self.find_shape(&part, id).ok_or("no such picture")?;
        let ext = ext.to_lowercase().replace("jpg", "jpeg");
        let media = self.free_name("ppt/media", "image", &ext);
        self.begin("Change Picture", &[part.clone(), Package::rels_name(&part), CT.to_string(), media.clone()]);
        self.pkg.put_raw(&media, data);
        self.pkg.ensure_default(&ext, image_ctype(&ext));
        let rid = self.pkg.add_rel(&part, &format!("{RT}image"), &rel_path(&part, &media));
        let d = self.pkg.xml_mut(&part).map_err(|e| e.to_string())?;
        let blip = path(d, n, &["p:blipFill", "a:blip"]).ok_or("not a picture")?;
        d.set_attr(blip, "r:embed", &rid);
        if let Some(bf) = d.child(n, "p:blipFill") {
            if let Some(sr) = d.child(bf, "a:srcRect") {
                d.detach(sr);
            }
        }
        self.commit();
        Ok(())
    }

    // ------------------------------------------------------------ Set Up Show
    fn pres_props(&mut self) -> Option<String> {
        let pres = self.pres.clone();
        self.pkg.related(&pres, "/presProps")
    }

    /// Show settings: kind (presented | browsed | kiosk), loop, no narration, no animation,
    /// from, to (1-based, 0 = all), use timings, pen colour (RRGGBB).
    pub fn show_settings(&mut self) -> (String, bool, bool, i64, i64, bool, String) {
        let def = ("presented".to_string(), false, false, 0, 0, true, "FF0000".to_string());
        let Some(pp) = self.pres_props() else { return def };
        let Ok(d) = self.pkg.xml(&pp) else { return def };
        let Some(s) = d.child(d.root, "p:showPr") else { return def };
        let on = |k: &str| matches!(d.attr(s, k), Some("1") | Some("true"));
        let kind = if d.child(s, "p:kiosk").is_some() { "kiosk" } else if d.child(s, "p:browse").is_some() { "browsed" } else { "presented" };
        let (from, to) = d.child(s, "p:sldRg").map(|r| (crate::model::emu(d, r, "st").unwrap_or(0.0) as i64, crate::model::emu(d, r, "end").unwrap_or(0.0) as i64)).unwrap_or((0, 0));
        let pen = path(d, s, &["p:penClr", "a:srgbClr"]).and_then(|c| d.attr(c, "val")).unwrap_or("FF0000").to_string();
        (kind.to_string(), on("loop") || kind == "kiosk", on("showAnimation") == false && d.attr(s, "showAnimation").is_some(),
         from, to, d.attr(s, "useTimings") != Some("0"), pen)
    }

    #[allow(clippy::too_many_arguments)]
    pub fn set_show_settings(&mut self, kind: &str, looped: bool, no_anim: bool, from: i64, to: i64, timings: bool, pen: &str) -> Result<(), String> {
        let pres = self.pres.clone();
        let pp = match self.pres_props() { Some(p) => p, None => "ppt/presProps.xml".to_string() };
        self.begin("Set Up Show", &[pp.clone(), pres.clone(), Package::rels_name(&pres), CT.to_string()]);
        if !self.pkg.has(&pp) {
            let doc = XmlDoc::parse(br#"<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:presentationPr xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"/>"#).map_err(|e| e.to_string())?;
            self.pkg.put_xml(&pp, doc);
            self.pkg.set_content_type(&pp, "application/vnd.openxmlformats-officedocument.presentationml.presProps+xml");
            self.pkg.add_rel(&pres, &format!("{RT}presProps"), "presProps.xml");
        }
        let d = self.pkg.xml_mut(&pp).map_err(|e| e.to_string())?;
        if let Some(s) = d.child(d.root, "p:showPr") {
            d.detach(s);
        }
        let mut attrs = String::new();
        if looped || kind == "kiosk" {
            attrs.push_str(r#" loop="1""#);
        }
        if no_anim {
            attrs.push_str(r#" showAnimation="0""#);
        } else {
            attrs.push_str(r#" showAnimation="1""#);
        }
        if !timings {
            attrs.push_str(r#" useTimings="0""#);
        }
        let mode = match kind { "kiosk" => "<p:kiosk/>", "browsed" => r#"<p:browse showScrollbar="1"/>"#, _ => "<p:present/>" };
        let rg = if from > 0 || to > 0 { format!(r#"<p:sldRg st="{}" end="{}"/>"#, from.max(1), if to > 0 { to } else { self.slides.len() as i64 }) } else { "<p:sldAll/>".to_string() };
        let xml = format!(r#"<p:showPr{attrs}>{mode}{rg}<p:penClr><a:srgbClr val="{pen}"/></p:penClr></p:showPr>"#);
        let el = fragment(d, &xml).ok_or("bad settings")?;
        let root = d.root;
        // showPr comes first in presentationPr
        d.insert(root, 0, el);
        self.commit();
        Ok(())
    }
}

/// Relationship ids an XML fragment refers to (r:embed, r:link, r:id, ...).
fn rids_in(xml: &str) -> Vec<String> {
    let mut out = Vec::new();
    let mut rest = xml;
    while let Some(k) = rest.find(" r:") {
        rest = &rest[k + 3..];
        let Some(eq) = rest.find("=\"") else { break };
        let name = &rest[..eq];
        if name.chars().all(|c| c.is_ascii_alphanumeric()) {
            let v = &rest[eq + 2..];
            if let Some(end) = v.find('"') {
                let id = v[..end].to_string();
                if !id.is_empty() && !out.contains(&id) {
                    out.push(id);
                }
            }
        }
    }
    out
}

impl Deck {
    /// What shapes copied from slide i refer to: (rid, relationship type, target or "", bytes, content type, external).
    pub fn shape_media(&mut self, i: usize, xml: &str) -> Vec<(String, String, String, Vec<u8>, String, bool)> {
        let Ok(part) = self.slide_part(i) else { return Vec::new() };
        let rels = self.pkg.rels(&part);
        let mut out = Vec::new();
        for rid in rids_in(xml) {
            let Some(r) = rels.iter().find(|r| r.id == rid) else { continue };
            if r.external {
                out.push((rid, r.kind.clone(), r.target.clone(), Vec::new(), String::new(), true));
                continue;
            }
            let t = Package::resolve(&part, &r.target);
            if r.kind.ends_with("/slide") || r.kind.ends_with("/slideLayout") || r.kind.ends_with("/notesSlide") {
                continue;
            }
            let Some(b) = self.pkg.bytes(&t) else { continue };
            let ct = content_type(&mut self.pkg, &t).unwrap_or_default();
            out.push((rid, r.kind.clone(), t, b, ct, false));
        }
        out
    }

    /// Paste shapes with what they refer to (from shape_media), from any presentation.
    pub fn paste_shapes_media(&mut self, i: usize, xml: &str, media: &[(String, String, String, Vec<u8>, String, bool)], dx: f64, dy: f64) -> Result<Vec<u32>, String> {
        let part = self.slide_part(i)?;
        self.begin("Paste", &[part.clone(), Package::rels_name(&part), CT.to_string()]);
        let mut xml = xml.to_string();
        // placeholders while ids are swapped, so rId2 -> rId5 and rId5 -> rId7 don't collide
        let mut swaps = Vec::new();
        for (k, (rid, kind, target, bytes, ct, external)) in media.iter().enumerate() {
            let new_rid = if *external {
                let r = self.pkg.add_rel(&part, kind, target);
                if let Ok(rd) = self.pkg.xml_mut(&Package::rels_name(&part)) {
                    let found = rd.elements(rd.root).find(|&x| rd.attr(x, "Id") == Some(r.as_str()));
                    if let Some(x) = found {
                        rd.set_attr(x, "TargetMode", "External");
                    }
                }
                r
            } else {
                let (dir, file) = target.rsplit_once('/').unwrap_or(("ppt/media", target.as_str()));
                let (stem, ext) = file.rsplit_once('.').unwrap_or((file, "bin"));
                let stem = stem.trim_end_matches(|c: char| c.is_ascii_digit());
                // the same picture already here: reuse it
                let existing = self.pkg.part_names().into_iter().find(|n| n.starts_with(dir) && self.pkg.raw(n).map(|r| r == bytes.as_slice()).unwrap_or(false));
                let name = match existing {
                    Some(n) => n,
                    None => {
                        let n = self.free_name(dir, if stem.is_empty() { "image" } else { stem }, ext);
                        self.touch(&[n.clone()]);
                        self.pkg.put_raw(&n, bytes.clone());
                        if !ct.is_empty() && content_type(&mut self.pkg, &n).as_deref() != Some(ct.as_str()) {
                            self.pkg.set_content_type(&n, ct);
                        }
                        n
                    }
                };
                self.pkg.add_rel(&part, kind, &rel_path(&part, &name))
            };
            let ph = format!("\u{1}{k}\u{1}");
            xml = xml.replace(&format!("=\"{rid}\""), &format!("=\"{ph}\""));
            swaps.push((ph, new_rid));
        }
        for (ph, new_rid) in swaps {
            xml = xml.replace(&ph, &new_rid);
        }
        // paste_shapes joins this undo step
        self.paste_shapes(i, &xml, dx, dy)
    }
}

impl Deck {
    /// Custom slide shows: [(name, [slide indexes])].
    pub fn custom_shows(&mut self) -> Vec<(String, Vec<usize>)> {
        let pres = self.pres.clone();
        let rels = self.pkg.rels(&pres);
        let slides = self.slides.clone();
        let Ok(d) = self.pkg.xml(&pres) else { return Vec::new() };
        let Some(lst) = d.child(d.root, "p:custShowLst") else { return Vec::new() };
        d.children_named(lst, "p:custShow").map(|cs| {
            let name = d.attr(cs, "name").unwrap_or("").to_string();
            let idx = d.child(cs, "p:sldLst").map(|sl| d.children_named(sl, "p:sld").filter_map(|s| {
                let rid = d.attr(s, "r:id")?;
                let r = rels.iter().find(|r| r.id == rid)?;
                let t = Package::resolve(&pres, &r.target);
                slides.iter().position(|p| *p == t)
            }).collect()).unwrap_or_default();
            (name, idx)
        }).collect()
    }

    pub fn set_custom_shows(&mut self, shows: &[(String, Vec<usize>)]) -> Result<(), String> {
        let pres = self.pres.clone();
        self.begin("Custom Shows", &[pres.clone()]);
        let rels = self.pkg.rels(&pres);
        let slides = self.slides.clone();
        let rid_of = |k: usize| -> Option<String> {
            let p = slides.get(k)?;
            rels.iter().find(|r| Package::resolve(&pres, &r.target) == *p).map(|r| r.id.clone())
        };
        let mut xml = String::from("<p:custShowLst>");
        for (n, (name, idx)) in shows.iter().enumerate() {
            let mut e = String::new();
            folio_core::xml::escape_text(name, &mut e);
            xml.push_str(&format!(r#"<p:custShow name="{}" id="{n}"><p:sldLst>"#, e.replace('"', "&quot;")));
            for &k in idx {
                if let Some(r) = rid_of(k) {
                    xml.push_str(&format!(r#"<p:sld r:id="{r}"/>"#));
                }
            }
            xml.push_str("</p:sldLst></p:custShow>");
        }
        xml.push_str("</p:custShowLst>");
        let d = self.pkg.xml_mut(&pres).map_err(|e| e.to_string())?;
        let root = d.root;
        if let Some(old) = d.child(root, "p:custShowLst") {
            d.detach(old);
        }
        if !shows.is_empty() {
            let el = fragment(d, &xml).ok_or("bad shows")?;
            // after notesSz / smartTags / embeddedFontLst, before photoAlbum / custDataLst / kinsoku / defaultTextStyle
            let at = d.children(root).iter().position(|&c| matches!(d.name(c), "p:photoAlbum" | "p:custDataLst" | "p:kinsoku" | "p:defaultTextStyle" | "p:modifyVerifier" | "p:extLst"))
                .unwrap_or(d.children(root).len());
            d.insert(root, at, el);
        }
        self.commit();
        Ok(())
    }
}

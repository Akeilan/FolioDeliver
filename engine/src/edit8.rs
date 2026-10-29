//! Backlog 3: shape outlines (Merge Shapes), objects written as XML with their own parts
//! (Zoom, 3-D models, Cameo, actions with sounds), replacing parts (Compress Media), custom
//! document properties (Mark as Final), and embedded fonts.

use std::collections::HashMap;

use crate::edit::{fragment, next_shape_id, rel_path};
use crate::model::{path, Deck, EMU_PT, RT};
use crate::scene;
use folio_core::package::Package;
use folio_core::shapes::Shape;
use folio_core::xml::NodeId;

const CT: &str = "[Content_Types].xml";
const CUSTOM: &str = "docProps/custom.xml";
const RT_CUSTOM: &str = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/custom-properties";
const RT_FONT: &str = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/font";

/// A part a new object brings with it: placeholder in the XML ("{rImg}"), relationship type
/// (full URI, or a short name under the officeDocument namespace), file stem, extension,
/// content type and bytes. An empty `stem` means `target` is a link (another slide's index as
/// "slide:N", or an external address).
pub struct NewPart {
    pub key: String,
    pub rel: String,
    pub stem: String,
    pub ext: String,
    pub ctype: String,
    pub data: Vec<u8>,
    pub target: String,
}

fn rel_uri(r: &str) -> String {
    if r.contains("://") { r.to_string() } else { format!("{RT}{r}") }
}

impl Deck {
    /// A shape's outline as polygons in slide points (its rotation and flips applied).
    pub fn shape_outline(&mut self, i: usize, id: u32) -> Result<Vec<Vec<(f64, f64)>>, String> {
        let part = self.slide_part(i)?;
        let n = self.find_shape(&part, id).ok_or("no such shape")?;
        let ctx = scene::context(self, &part);
        let (x, y, w, h, rot, fh, fv) = scene::shape_box(self, &ctx, &part, n);
        let d = self.pkg.xml(&part).map_err(|e| e.to_string())?;
        let sh = match d.child(n, "p:spPr") {
            Some(sp) => Shape::parse_sppr(d, sp, &HashMap::new()),
            None => return Err("not a shape".into()),
        };
        let (c, s) = (rot.to_radians().cos(), rot.to_radians().sin());
        let (cx, cy) = (x + w / 2.0, y + h / 2.0);
        Ok(sh.polygons(w, h).into_iter().map(|poly| {
            poly.into_iter().map(|(px, py)| {
                let px = if fh { w - px } else { px } - w / 2.0;
                let py = if fv { h - py } else { py } - h / 2.0;
                (cx + px * c - py * s, cy + px * s + py * c)
            }).collect()
        }).collect())
    }

    fn add_new_parts(&mut self, part: &str, parts: &[NewPart]) -> Result<Vec<(String, String)>, String> {
        let mut subs = Vec::new();
        for np in parts {
            let rel = rel_uri(&np.rel);
            let rid = if np.stem.is_empty() {
                if let Some(k) = np.target.strip_prefix("slide:") {
                    let k: usize = k.parse().unwrap_or(0);
                    let to = self.slides.get(k).cloned().ok_or("no such slide")?;
                    self.pkg.add_rel(part, &rel, &rel_path(part, &to))
                } else {
                    let rid = self.pkg.add_rel(part, &rel, &np.target);
                    let rels_name = Package::rels_name(part);
                    if let Ok(rd) = self.pkg.xml_mut(&rels_name) {
                        let found = rd.elements(rd.root).find(|&r| rd.attr(r, "Id") == Some(rid.as_str()));
                        if let Some(r) = found {
                            rd.set_attr(r, "TargetMode", "External");
                        }
                    }
                    rid
                }
            } else {
                let dir = if np.ext == "fntdata" { "ppt/fonts" } else { "ppt/media" };
                let name = self.free_name(dir, &np.stem, &np.ext);
                self.pkg.put_raw(&name, np.data.clone());
                self.pkg.ensure_default(&np.ext, &np.ctype);
                self.pkg.add_rel(part, &rel, &rel_path(part, &name))
            };
            subs.push((format!("{{{}}}", np.key), rid));
        }
        Ok(subs)
    }

    fn touched(&self, part: &str, parts: &[NewPart]) -> Vec<String> {
        let mut t = vec![part.to_string(), Package::rels_name(part), CT.to_string()];
        for np in parts {
            if !np.stem.is_empty() {
                t.push(self.free_name("ppt/media", &np.stem, &np.ext));
            }
        }
        t
    }

    /// Add an object written as XML to slide i: "{ID}" becomes its new shape id, "{key}" each
    /// part's relationship id. The XML may be a p:sp, p:pic, p:graphicFrame or an
    /// mc:AlternateContent holding them. Returns the new id.
    pub fn insert_object_xml(&mut self, i: usize, label: &str, xml: &str, parts: Vec<NewPart>) -> Result<u32, String> {
        let part = self.slide_part(i)?;
        let touched = self.touched(&part, &parts);
        self.begin(label, &touched);
        let subs = self.add_new_parts(&part, &parts)?;
        let d = self.pkg.xml_mut(&part).map_err(|e| e.to_string())?;
        let id = next_shape_id(d);
        let mut x = xml.replace("{ID}", &id.to_string());
        for (k, v) in &subs {
            x = x.replace(k, v);
        }
        let tree = path(d, d.root, &["p:cSld", "p:spTree"]).ok_or("slide has no shape tree")?;
        let n = fragment(d, &x).ok_or("bad object")?;
        d.append(tree, n);
        self.commit();
        Ok(id)
    }

    /// Replace object `id` (with all its alternate-content branches) by new XML, keeping its
    /// id and place in the drawing order.
    pub fn replace_object_xml(&mut self, i: usize, id: u32, label: &str, xml: &str, parts: Vec<NewPart>) -> Result<(), String> {
        let part = self.slide_part(i)?;
        let n = self.find_shape(&part, id).ok_or("no such shape")?;
        let touched = self.touched(&part, &parts);
        self.begin(label, &touched);
        let subs = self.add_new_parts(&part, &parts)?;
        let d = self.pkg.xml_mut(&part).map_err(|e| e.to_string())?;
        let (ac, _) = crate::edit::alt_twins(d, n);
        let old = ac.unwrap_or(n);
        let parent = d.parent(old).ok_or("bad shape")?;
        let at = d.index_in_parent(old).unwrap_or(0);
        let mut x = xml.replace("{ID}", &id.to_string());
        for (k, v) in &subs {
            x = x.replace(k, v);
        }
        let el = fragment(d, &x).ok_or("bad object")?;
        d.detach(old);
        d.insert(parent, at, el);
        self.commit();
        Ok(())
    }

    /// The XML of object `id` including its alternate content, if any.
    pub fn object_xml(&mut self, i: usize, id: u32) -> Option<String> {
        let part = self.slide_part(i).ok()?;
        let n = self.find_shape(&part, id)?;
        let d = self.pkg.xml(&part).ok()?;
        let (ac, _) = crate::edit::alt_twins(d, n);
        Some(d.serialize_node(ac.unwrap_or(n)))
    }

    /// The part a relationship of slide i points at.
    pub fn slide_rel_part(&mut self, i: usize, rid: &str) -> Option<String> {
        let part = self.slide_part(i).ok()?;
        let t = self.pkg.rel_target(&part, rid)?;
        Some(Package::resolve(&part, &t))
    }

    /// Put new bytes into an existing part (undoable), optionally renaming its extension's
    /// content type default.
    pub fn set_part(&mut self, name: &str, data: Vec<u8>, label: &str) -> Result<(), String> {
        if !self.pkg.has(name) {
            return Err("no such part".into());
        }
        self.begin(label, &[name.to_string()]);
        self.pkg.put_raw(name, data);
        self.commit();
        Ok(())
    }

    /// Every media and picture part with its size in bytes.
    pub fn media_parts(&self) -> Vec<(String, usize)> {
        self.pkg.part_names().into_iter().filter(|n| n.starts_with("ppt/media/"))
            .map(|n| { let l = self.pkg.raw(&n).map(|b| b.len()).unwrap_or(0); (n, l) }).collect()
    }

    // ------------------------------------------------------------ custom properties
    pub fn custom_props(&mut self) -> Vec<(String, String)> {
        let Ok(d) = self.pkg.xml(CUSTOM) else { return Vec::new() };
        d.elements(d.root).map(|p| {
            let name = d.attr(p, "name").unwrap_or("").to_string();
            let v = d.elements(p).next().map(|v| d.text(v)).unwrap_or_default();
            (name, v)
        }).collect()
    }

    /// Set (or with an empty kind, remove) a custom property: kind "bool", "lpwstr", "i4".
    pub fn set_custom_prop(&mut self, name: &str, kind: &str, value: &str) -> Result<(), String> {
        let mut props: Vec<(String, String, String)> = Vec::new();
        if let Ok(d) = self.pkg.xml(CUSTOM) {
            for p in d.elements(d.root) {
                let n = d.attr(p, "name").unwrap_or("").to_string();
                if let Some(v) = d.elements(p).next() {
                    let k = d.name(v).trim_start_matches("vt:").to_string();
                    props.push((n, k, d.text(v)));
                }
            }
        }
        props.retain(|(n, _, _)| n != name);
        if !kind.is_empty() {
            props.push((name.to_string(), kind.to_string(), value.to_string()));
        }
        self.begin("Properties", &[CUSTOM.to_string(), "_rels/.rels".to_string(), CT.to_string()]);
        let mut xml = String::from(r#"<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/custom-properties" xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes">"#);
        for (k, (n, t, v)) in props.iter().enumerate() {
            let mut val = String::new();
            folio_core::xml::escape_text(v, &mut val);
            xml.push_str(&format!(r#"<property fmtid="{{D5CDD505-2E9C-101B-9397-08002B2CF9AE}}" pid="{}" name="{}"><vt:{t}>{val}</vt:{t}></property>"#,
                                  k + 2, folio_core::xml::attr_escaped(n)));
        }
        xml.push_str("</Properties>");
        let had = self.pkg.has(CUSTOM);
        self.pkg.put_raw(CUSTOM, xml.into_bytes());
        if !had {
            self.pkg.set_content_type(CUSTOM, "application/vnd.openxmlformats-officedocument.custom-properties+xml");
            self.pkg.add_rel("", RT_CUSTOM, CUSTOM);
        }
        self.commit();
        Ok(())
    }

    // ------------------------------------------------------------ embedded fonts
    /// Fonts embedded in the presentation: (typeface, style, font part).
    pub fn embedded_fonts(&mut self) -> Vec<(String, String, String)> {
        let main = self.pres.clone();
        let mut out = Vec::new();
        let Ok(d) = self.pkg.xml(&main) else { return out };
        let Some(lst) = d.child(d.root, "p:embeddedFontLst") else { return out };
        let mut refs = Vec::new();
        for ef in d.children_named(lst, "p:embeddedFont") {
            let face = d.child(ef, "p:font").and_then(|f| d.attr(f, "typeface")).unwrap_or("").to_string();
            for st in ["p:regular", "p:bold", "p:italic", "p:boldItalic"] {
                if let Some(r) = d.child(ef, st).and_then(|e| d.attr(e, "r:id")) {
                    refs.push((face.clone(), st.trim_start_matches("p:").to_string(), r.to_string()));
                }
            }
        }
        for (face, st, rid) in refs {
            if let Some(t) = self.pkg.rel_target(&main, &rid) {
                out.push((face, st, Package::resolve(&main, &t)));
            }
        }
        out
    }

    /// Replace the embedded font list: [(typeface, [(style, EOT bytes)])]. Empty: none.
    pub fn set_embedded_fonts(&mut self, fonts: Vec<(String, Vec<(String, Vec<u8>)>)>) -> Result<(), String> {
        let main = self.pres.clone();
        let old: Vec<String> = self.embedded_fonts().into_iter().map(|(_, _, p)| p).collect();
        let mut touched = vec![main.clone(), Package::rels_name(&main), CT.to_string()];
        touched.extend(old.iter().cloned());
        self.begin("Embed Fonts", &touched);
        // drop the old list, its relationships and parts
        let rels_name = Package::rels_name(&main);
        for p in &old {
            self.pkg.remove(p);
        }
        if let Ok(rd) = self.pkg.xml_mut(&rels_name) {
            for r in rd.elements(rd.root).collect::<Vec<_>>() {
                if rd.attr(r, "Type") == Some(RT_FONT) {
                    rd.detach(r);
                }
            }
        }
        let mut xml = String::from("<p:embeddedFontLst>");
        let mut k = 1;
        for (face, styles) in &fonts {
            xml.push_str(&format!(r#"<p:embeddedFont><p:font typeface="{}"/>"#, folio_core::xml::attr_escaped(face)));
            for (st, data) in styles {
                let mut name = format!("ppt/fonts/font{k}.fntdata");
                while self.pkg.has(&name) {
                    k += 1;
                    name = format!("ppt/fonts/font{k}.fntdata");
                }
                k += 1;
                self.pkg.put_raw(&name, data.clone());
                self.pkg.ensure_default("fntdata", "application/x-fontdata");
                let rid = self.pkg.add_rel(&main, RT_FONT, &rel_path(&main, &name));
                xml.push_str(&format!(r#"<p:{st} r:id="{rid}"/>"#));
            }
            xml.push_str("</p:embeddedFont>");
        }
        xml.push_str("</p:embeddedFontLst>");
        let d = self.pkg.xml_mut(&main).map_err(|e| e.to_string())?;
        let root = d.root;
        if let Some(l) = d.child(root, "p:embeddedFontLst") {
            d.detach(l);
        }
        if !fonts.is_empty() {
            let el = fragment(d, &xml).ok_or("bad font list")?;
            // after notesSz, before custShowLst / photoAlbum / custDataLst / kinsoku / defaultTextStyle
            let after: Vec<NodeId> = d.elements(root).filter(|&c| matches!(d.name(c), "p:sldMasterIdLst" | "p:notesMasterIdLst"
                | "p:handoutMasterIdLst" | "p:sldIdLst" | "p:sldSz" | "p:notesSz" | "p:smartTags")).collect();
            let at = after.last().and_then(|&n| d.index_in_parent(n)).map(|k| k + 1).unwrap_or(0);
            d.insert(root, at, el);
        }
        self.commit();
        Ok(())
    }

    /// The size of the slide in points (for objects placed on it).
    pub fn slide_points(&self) -> (f64, f64) {
        (self.cx / EMU_PT, self.cy / EMU_PT)
    }
}

impl Deck {
    /// What clicking or pointing at a shape does in the show (Insert > Action). `which` is
    /// "click" or "hover"; `target` as for links ("slide:N", "next", "prev", "first", "last",
    /// "end", an address or file), plus "show:N" (custom show N, returning after it) and
    /// "program:PATH"; `sound` a sound to play (bytes and file name) or none; `stop_sound`
    /// stops a playing sound. An empty target with no sound removes the action.
    #[allow(clippy::too_many_arguments)]
    pub fn set_shape_action(&mut self, i: usize, id: u32, which: &str, target: &str, sound: Option<(Vec<u8>, String)>,
                            stop_sound: bool, highlight: bool) -> Result<(), String> {
        let part = self.slide_part(i)?;
        let n = self.find_shape(&part, id).ok_or("no such shape")?;
        let el_name = if which == "hover" { "a:hlinkHover" } else { "a:hlinkClick" };
        let mut touched = vec![part.clone(), Package::rels_name(&part), CT.to_string()];
        if let Some((_, nm)) = &sound {
            let ext = nm.rsplit('.').next().unwrap_or("wav").to_lowercase();
            touched.push(self.free_name("ppt/media", "audio", &ext));
        }
        self.begin("Action Settings", &touched);
        let (rid, action) = if let Some(k) = target.strip_prefix("show:") {
            (String::new(), format!("ppaction://customshow?id={k}&return=true"))
        } else if let Some(p) = target.strip_prefix("program:") {
            let rid = self.pkg.add_rel(&part, &format!("{RT}hyperlink"), p);
            let rels_name = Package::rels_name(&part);
            if let Ok(rd) = self.pkg.xml_mut(&rels_name) {
                let found = rd.elements(rd.root).find(|&r| rd.attr(r, "Id") == Some(rid.as_str()));
                if let Some(r) = found {
                    rd.set_attr(r, "TargetMode", "External");
                }
            }
            (rid, "ppaction://program".to_string())
        } else if target.is_empty() {
            (String::new(), if sound.is_some() || stop_sound { "ppaction://noaction".to_string() } else { String::new() })
        } else {
            self.link_rel(&part, target)?
        };
        let snd = match &sound {
            Some((data, nm)) => {
                let ext = nm.rsplit('.').next().unwrap_or("wav").to_lowercase();
                let media = self.free_name("ppt/media", "audio", &ext);
                self.pkg.put_raw(&media, data.clone());
                self.pkg.ensure_default(&ext, if ext == "wav" { "audio/wav" } else if ext == "mp3" { "audio/mpeg" } else { "audio/unknown" });
                Some((self.pkg.add_rel(&part, &format!("{RT}audio"), &rel_path(&part, &media)), nm.clone()))
            }
            None => None,
        };
        let d = self.pkg.xml_mut(&part).map_err(|e| e.to_string())?;
        let nv = d.elements(n).next().ok_or("bad shape")?;
        let c = d.child(nv, "p:cNvPr").ok_or("bad shape")?;
        if let Some(h) = d.child(c, el_name) {
            d.detach(h);
        }
        if !target.is_empty() || sound.is_some() || stop_sound {
            let mut attrs: Vec<(&str, &str)> = vec![("r:id", rid.as_str())];
            if !action.is_empty() {
                attrs.push(("action", action.as_str()));
            }
            if highlight {
                attrs.push(("highlightClick", "1"));
            }
            if stop_sound {
                attrs.push(("endSnd", "1"));
            }
            let h = d.new_element(el_name, &attrs);
            if let Some((srid, nm)) = &snd {
                let s = d.new_element("a:snd", &[("r:embed", srid.as_str()), ("name", nm.as_str())]);
                d.append(h, s);
            }
            let at = if el_name == "a:hlinkHover" { d.child(c, "a:hlinkClick").and_then(|x| d.index_in_parent(x)).map(|k| k + 1).unwrap_or(0) } else { 0 };
            d.insert(c, at, h);
        }
        self.commit();
        Ok(())
    }

    /// A shape's click or hover action: (target as set_shape_action takes it, sound part or "",
    /// stops sound, highlight).
    pub fn shape_action(&mut self, i: usize, id: u32, which: &str) -> Option<(String, String, bool, bool)> {
        let part = self.slide_part(i).ok()?;
        let n = self.find_shape(&part, id)?;
        let d = self.pkg.xml(&part).ok()?;
        let nv = d.elements(n).next()?;
        let h = path(d, nv, &["p:cNvPr", if which == "hover" { "a:hlinkHover" } else { "a:hlinkClick" }])?;
        let rid = d.attr(h, "r:id").unwrap_or("").to_string();
        let act = d.attr(h, "action").unwrap_or("").to_string();
        let hl = d.attr(h, "highlightClick").is_some_and(|v| v == "1" || v == "true");
        let srid = d.child(h, "a:snd").and_then(|s| d.attr(s, "r:embed")).map(|s| s.to_string());
        let stop = d.attr(h, "endSnd").is_some_and(|v| v == "1" || v == "true");
        let target = if let Some(rest) = act.strip_prefix("ppaction://customshow?id=") {
            format!("show:{}", rest.split('&').next().unwrap_or("0"))
        } else if act == "ppaction://program" {
            format!("program:{}", self.pkg.rel_target(&part, &rid).unwrap_or_default())
        } else if act == "ppaction://noaction" {
            String::new()
        } else {
            self.link_target(&part, &rid, &act)
        };
        let sound = srid.and_then(|r| self.pkg.rel_target(&part, &r).map(|t| Package::resolve(&part, &t))).unwrap_or_default();
        Some((target, sound, stop, hl))
    }
}

impl Deck {
    /// An attribute of presentation.xml's root (embedTrueTypeFonts, saveSubsetFonts...).
    pub fn pres_attr(&mut self, name: &str) -> Option<String> {
        let main = self.pres.clone();
        let d = self.pkg.xml(&main).ok()?;
        d.attr(d.root, name).map(|s| s.to_string())
    }

    pub fn set_pres_attr(&mut self, name: &str, value: Option<&str>) -> Result<(), String> {
        let main = self.pres.clone();
        self.begin("Options", &[main.clone()]);
        let d = self.pkg.xml_mut(&main).map_err(|e| e.to_string())?;
        let root = d.root;
        match value {
            Some(v) => d.set_attr(root, name, v),
            None => {
                d.remove_attr(root, name);
            }
        }
        self.commit();
        Ok(())
    }
}

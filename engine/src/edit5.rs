//! Slide Master view: masters and layouts (add, duplicate, delete, rename, preserve, the
//! placeholders they show), and the handout master.

use crate::edit::{fragment, rel_path};
use crate::model::{emu, path, Deck, RT};
use folio_core::package::Package;
use folio_core::xml::{NodeId, XmlDoc};

const CT: &str = "[Content_Types].xml";
const CT_LAYOUT: &str = "application/vnd.openxmlformats-officedocument.presentationml.slideLayout+xml";
const CT_MASTER: &str = "application/vnd.openxmlformats-officedocument.presentationml.slideMaster+xml";
const CT_THEME: &str = "application/vnd.openxmlformats-officedocument.theme+xml";
const CT_HANDOUT: &str = "application/vnd.openxmlformats-officedocument.presentationml.handoutMaster+xml";
const NS: &str = r#"xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main""#;

fn remove_override(pkg: &mut Package, part: &str) {
    let Ok(d) = pkg.xml_mut(CT) else { return };
    let pname = format!("/{part}");
    for o in d.children_named(d.root, "Override").collect::<Vec<_>>() {
        if d.attr(o, "PartName") == Some(pname.as_str()) {
            d.detach(o);
        }
    }
}

fn tree(d: &XmlDoc) -> Option<NodeId> {
    path(d, d.root, &["p:cSld", "p:spTree"])
}

/// The placeholders of a part: (node, type, idx).
fn placeholders(d: &XmlDoc) -> Vec<(NodeId, String, Option<u32>)> {
    let Some(t) = tree(d) else { return Vec::new() };
    d.elements(t).filter_map(|n| {
        let nv = d.elements(n).next()?;
        let ph = path(d, nv, &["p:nvPr", "p:ph"])?;
        Some((n, d.attr(ph, "type").unwrap_or("obj").to_string(), d.attr(ph, "idx").and_then(|v| v.parse().ok())))
    }).collect()
}

fn max_shape_id(d: &XmlDoc) -> u32 {
    crate::edit::next_shape_id(d)
}

impl Deck {
    /// Design parts: (index into the design list, part, kind, name, slides using it).
    pub fn design_parts(&mut self) -> Vec<(usize, String, String, String, usize)> {
        self.refresh_design();
        let parts = self.design.clone();
        let slides = self.slides.clone();
        let mut uses: std::collections::HashMap<String, usize> = std::collections::HashMap::new();
        for s in &slides {
            if let Some(l) = self.layout_of(s) {
                *uses.entry(l.clone()).or_default() += 1;
                if let Some(m) = self.master_of(&l) {
                    *uses.entry(m).or_default() += 1;
                }
            }
        }
        parts.iter().enumerate().map(|(k, p)| {
            let kind = if p.contains("slideMasters/") { "master" } else if p.contains("slideLayouts/") { "layout" }
                       else if p.contains("notesMaster") { "notesMaster" } else { "handoutMaster" };
            let name = if kind == "master" {
                let n = self.pkg.xml(p).ok().and_then(|d| d.child(d.root, "p:cSld").and_then(|c| d.attr(c, "name")).map(|s| s.to_string())).unwrap_or_default();
                if n.is_empty() { self.theme_of(p).and_then(|t| self.pkg.xml(&t).ok().and_then(|d| d.attr(d.root, "name").map(|s| s.to_string()))).unwrap_or_else(|| "Office Theme".into()) } else { n }
            } else if kind == "layout" { self.layout_name(p) } else if kind == "notesMaster" { "Notes Master".into() } else { "Handout Master".into() };
            (k, p.clone(), kind.to_string(), name, uses.get(p).copied().unwrap_or(0))
        }).collect()
    }

    fn next_master_id(&mut self) -> u64 {
        let mut max = 2147483647u64;
        let pres = self.pres.clone();
        if let Ok(d) = self.pkg.xml(&pres) {
            if let Some(l) = d.child(d.root, "p:sldMasterIdLst") {
                for m in d.elements(l) {
                    max = max.max(emu(d, m, "id").unwrap_or(0.0) as u64);
                }
            }
        }
        for m in self.masters() {
            if let Ok(d) = self.pkg.xml(&m) {
                if let Some(l) = d.child(d.root, "p:sldLayoutIdLst") {
                    for x in d.elements(l) {
                        max = max.max(emu(d, x, "id").unwrap_or(0.0) as u64);
                    }
                }
            }
        }
        max + 1
    }

    /// Put a layout part into a master's list after `after` (or at the end).
    fn attach_layout(&mut self, master: &str, layout: &str, after: Option<&str>) -> Result<(), String> {
        let id = self.next_master_id();
        let rid = self.pkg.add_rel(master, &format!("{RT}slideLayout"), &rel_path(master, layout));
        let rels = self.pkg.rels(master);
        let d = self.pkg.xml_mut(master).map_err(|e| e.to_string())?;
        let root = d.root;
        let lst = match d.child(root, "p:sldLayoutIdLst") {
            Some(l) => l,
            None => {
                let l = d.new_element("p:sldLayoutIdLst", &[]);
                let at = d.child(root, "p:clrMap").and_then(|c| d.index_in_parent(c)).map(|k| k + 1).unwrap_or(1);
                d.insert(root, at, l);
                l
            }
        };
        let el = d.new_element("p:sldLayoutId", &[("id", &id.to_string()), ("r:id", &rid)]);
        let pos = after.and_then(|a| {
            d.elements(lst).position(|x| {
                let r = d.attr(x, "r:id").unwrap_or("");
                rels.iter().any(|rr| rr.id == r && Package::resolve(master, &rr.target) == a)
            })
        }).map(|k| k + 1).unwrap_or(d.elements(lst).count());
        d.insert(lst, pos, el);
        Ok(())
    }

    /// A new layout in `master` (title and footers, like PowerPoint's Insert Layout) after `after`.
    pub fn add_layout(&mut self, master: &str, after: Option<&str>, name: &str) -> Result<String, String> {
        let part = self.free_name("ppt/slideLayouts", "slideLayout", "xml");
        self.begin("Insert Layout", &[master.to_string(), Package::rels_name(master), part.clone(), Package::rels_name(&part), CT.to_string()]);
        let xml = format!(r#"<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:sldLayout {NS} preserve="1" userDrawn="1"><p:cSld name="{}"><p:spTree><p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr><p:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/><a:chOff x="0" y="0"/><a:chExt cx="0" cy="0"/></a:xfrm></p:grpSpPr>{}</p:spTree></p:cSld><p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr></p:sldLayout>"#,
            esc(name), [Self::ph_xml(2, "title", None), Self::ph_xml(3, "dt", Some(10)), Self::ph_xml(4, "ftr", Some(11)), Self::ph_xml(5, "sldNum", Some(12))].concat());
        let doc = XmlDoc::parse(xml.as_bytes()).map_err(|e| e.to_string())?;
        self.pkg.put_xml(&part, doc);
        self.pkg.set_content_type(&part, CT_LAYOUT);
        self.pkg.add_rel(&part, &format!("{RT}slideMaster"), &rel_path(&part, master));
        self.attach_layout(master, &part, after)?;
        self.commit();
        self.refresh_design();
        Ok(part)
    }

    fn ph_xml(id: u32, kind: &str, idx: Option<u32>) -> String {
        let (label, sz) = match kind {
            "title" => ("Title", ""),
            "dt" => ("Date Placeholder", r#" sz="half""#),
            "ftr" => ("Footer Placeholder", r#" sz="quarter""#),
            "sldNum" => ("Slide Number Placeholder", r#" sz="quarter""#),
            "body" => ("Text Placeholder", ""),
            "hdr" => ("Header Placeholder", r#" sz="quarter""#),
            "sldImg" => ("Slide Image Placeholder", ""),
            _ => ("Placeholder", ""),
        };
        let ty = if kind == "obj" { String::new() } else { format!(r#" type="{kind}""#) };
        let ix = idx.map(|i| format!(r#" idx="{i}""#)).unwrap_or_default();
        let text = match kind {
            "title" => r#"<a:p><a:r><a:rPr lang="en-US"/><a:t>Click to edit Master title style</a:t></a:r></a:p>"#,
            "hdr" => r#"<a:p><a:r><a:rPr lang="en-US"/><a:t>Header</a:t></a:r></a:p>"#,
            "dt" => r#"<a:p><a:fld id="{B7B1A5D1-1C0E-4F35-9E8E-2A6C3C1F0D11}" type="datetimeFigureOut"><a:rPr lang="en-US"/><a:t>‹date›</a:t></a:fld><a:endParaRPr lang="en-US"/></a:p>"#,
            "sldNum" => r#"<a:p><a:fld id="{3C3E7F2A-5B1D-4C6E-8F0A-9D2B4E6A8C13}" type="slidenum"><a:rPr lang="en-US"/><a:t>‹#›</a:t></a:fld><a:endParaRPr lang="en-US"/></a:p>"#,
            _ => r#"<a:p><a:endParaRPr lang="en-US"/></a:p>"#,
        };
        format!(r#"<p:sp><p:nvSpPr><p:cNvPr id="{id}" name="{label} {}"/><p:cNvSpPr><a:spLocks noGrp="1"/></p:cNvSpPr><p:nvPr><p:ph{ty}{sz}{ix}/></p:nvPr></p:nvSpPr><p:spPr/><p:txBody><a:bodyPr/><a:lstStyle/>{text}</p:txBody></p:sp>"#, id - 1)
    }

    /// A copy of a layout (or, given a master, of the master with all its layouts and theme).
    pub fn duplicate_design(&mut self, part: &str) -> Result<String, String> {
        if part.contains("slideMasters/") {
            return self.duplicate_master(part);
        }
        let master = self.master_of(part).ok_or("no master")?;
        let new = self.free_name("ppt/slideLayouts", "slideLayout", "xml");
        self.begin("Duplicate Layout", &[master.clone(), Package::rels_name(&master), new.clone(), Package::rels_name(&new), CT.to_string()]);
        let data = self.pkg.bytes(part).ok_or("no layout")?;
        self.pkg.put_raw(&new, data);
        self.pkg.set_content_type(&new, CT_LAYOUT);
        self.copy_rels_same_ids(part, &new);
        let name = format!("1_{}", self.layout_name(part));
        if let Ok(d) = self.pkg.xml_mut(&new) {
            if let Some(c) = d.child(d.root, "p:cSld") {
                d.set_attr(c, "name", &name);
            }
            d.set_attr(d.root, "preserve", "1");
            d.set_attr(d.root, "userDrawn", "1");
        }
        self.attach_layout(&master, &new, Some(part))?;
        self.commit();
        self.refresh_design();
        Ok(new)
    }

    fn copy_rels_same_ids(&mut self, from: &str, to: &str) {
        let rels = self.pkg.rels(from);
        let mut doc = XmlDoc::with_root("Relationships", &[("xmlns", "http://schemas.openxmlformats.org/package/2006/relationships")]);
        for r in rels {
            let t = if r.external { r.target.clone() } else { rel_path(to, &Package::resolve(from, &r.target)) };
            let el = doc.new_element("Relationship", &[("Id", &r.id), ("Type", &r.kind), ("Target", &t)]);
            if r.external {
                doc.set_attr(el, "TargetMode", "External");
            }
            let root = doc.root;
            doc.append(root, el);
        }
        self.pkg.put_xml(&Package::rels_name(to), doc);
    }

    fn duplicate_master(&mut self, master: &str) -> Result<String, String> {
        let pres = self.pres.clone();
        let layouts = self.layouts_of(master);
        let theme = self.theme_of(master).ok_or("no theme")?;
        let new_m = self.free_name("ppt/slideMasters", "slideMaster", "xml");
        let new_t = self.free_name("ppt/theme", "theme", "xml");
        let mut touch = vec![pres.clone(), Package::rels_name(&pres), CT.to_string(), new_m.clone(), Package::rels_name(&new_m), new_t.clone()];
        self.begin("Insert Slide Master", &touch);
        self.pkg.put_raw(&new_t, self.pkg.bytes(&theme).ok_or("no theme")?);
        self.pkg.set_content_type(&new_t, CT_THEME);
        self.pkg.put_raw(&new_m, self.pkg.bytes(master).ok_or("no master")?);
        self.pkg.set_content_type(&new_m, CT_MASTER);
        // the master's relationships, the same ids, its layouts and theme replaced below
        self.copy_rels_same_ids(master, &new_m);
        let mut map = Vec::new();
        for l in &layouts {
            let nl = self.free_name("ppt/slideLayouts", "slideLayout", "xml");
            touch = vec![nl.clone(), Package::rels_name(&nl)];
            self.touch(&touch);
            self.pkg.put_raw(&nl, self.pkg.bytes(l).ok_or("no layout")?);
            self.pkg.set_content_type(&nl, CT_LAYOUT);
            self.copy_rels_same_ids(l, &nl);
            // its master is the new one
            if let Ok(rd) = self.pkg.xml_mut(&Package::rels_name(&nl)) {
                for r in rd.elements(rd.root).collect::<Vec<_>>() {
                    if rd.attr(r, "Type").map(|t| t.ends_with("/slideMaster")).unwrap_or(false) {
                        rd.set_attr(r, "Target", &rel_path(&nl, &new_m));
                    }
                }
            }
            map.push((l.clone(), nl));
        }
        if let Ok(rd) = self.pkg.xml_mut(&Package::rels_name(&new_m)) {
            for r in rd.elements(rd.root).collect::<Vec<_>>() {
                let ty = rd.attr(r, "Type").unwrap_or("").to_string();
                let tg = Package::resolve(master, rd.attr(r, "Target").unwrap_or(""));
                if ty.ends_with("/theme") {
                    rd.set_attr(r, "Target", &rel_path(&new_m, &new_t));
                } else if ty.ends_with("/slideLayout") {
                    if let Some((_, nl)) = map.iter().find(|(o, _)| *o == tg) {
                        rd.set_attr(r, "Target", &rel_path(&new_m, nl));
                    }
                }
            }
        }
        // new ids for the copied layouts
        let mut id = self.next_master_id();
        let master_id = id;
        id += 1;
        if let Ok(d) = self.pkg.xml_mut(&new_m) {
            if let Some(l) = d.child(d.root, "p:sldLayoutIdLst") {
                for x in d.elements(l).collect::<Vec<_>>() {
                    d.set_attr(x, "id", &id.to_string());
                    id += 1;
                }
            }
            if let Some(c) = d.child(d.root, "p:cSld") {
                d.set_attr(c, "name", "Custom Design");
            }
            d.set_attr(d.root, "preserve", "1");
        }
        if let Ok(d) = self.pkg.xml_mut(&new_t) {
            d.set_attr(d.root, "name", "Custom Design");
        }
        let rid = self.pkg.add_rel(&pres, &format!("{RT}slideMaster"), &rel_path(&pres, &new_m));
        let d = self.pkg.xml_mut(&pres).map_err(|e| e.to_string())?;
        let lst = d.child(d.root, "p:sldMasterIdLst").ok_or("no master list")?;
        let el = d.new_element("p:sldMasterId", &[("id", &master_id.to_string()), ("r:id", &rid)]);
        d.append(lst, el);
        self.commit();
        self.refresh_design();
        Ok(new_m)
    }

    /// Delete a layout or master nobody uses (PowerPoint keeps used ones).
    pub fn delete_design(&mut self, part: &str) -> Result<(), String> {
        let uses = self.design_parts().into_iter().find(|d| d.1 == part).map(|d| d.4).unwrap_or(0);
        if uses > 0 {
            return Err("in use by slides".into());
        }
        if part.contains("slideMasters/") {
            if self.masters().len() <= 1 {
                return Err("the only master".into());
            }
            let pres = self.pres.clone();
            let layouts = self.layouts_of(part);
            let theme = self.theme_of(part);
            let mut touch = vec![pres.clone(), Package::rels_name(&pres), CT.to_string(), part.to_string(), Package::rels_name(part)];
            for l in &layouts {
                touch.push(l.clone());
                touch.push(Package::rels_name(l));
            }
            if let Some(t) = &theme {
                touch.push(t.clone());
            }
            self.begin("Delete Master", &touch);
            let rid = self.pkg.rels(&pres).into_iter().find(|r| Package::resolve(&pres, &r.target) == part).map(|r| r.id);
            if let Some(rid) = rid {
                Self::drop_rel(&mut self.pkg, &pres, &rid);
                if let Ok(d) = self.pkg.xml_mut(&pres) {
                    if let Some(l) = d.child(d.root, "p:sldMasterIdLst") {
                        for m in d.elements(l).collect::<Vec<_>>() {
                            if d.attr(m, "r:id") == Some(rid.as_str()) {
                                d.detach(m);
                            }
                        }
                    }
                }
            }
            for p in layouts.iter().chain(std::iter::once(&part.to_string())).chain(theme.iter()) {
                self.pkg.remove(p);
                self.pkg.remove(&Package::rels_name(p));
                remove_override(&mut self.pkg, p);
            }
        } else {
            let master = self.master_of(part).ok_or("no master")?;
            self.begin("Delete Layout", &[master.clone(), Package::rels_name(&master), part.to_string(), Package::rels_name(part), CT.to_string()]);
            let rid = self.pkg.rels(&master).into_iter().find(|r| Package::resolve(&master, &r.target) == part).map(|r| r.id);
            if let Some(rid) = rid {
                Self::drop_rel(&mut self.pkg, &master, &rid);
                if let Ok(d) = self.pkg.xml_mut(&master) {
                    if let Some(l) = d.child(d.root, "p:sldLayoutIdLst") {
                        for m in d.elements(l).collect::<Vec<_>>() {
                            if d.attr(m, "r:id") == Some(rid.as_str()) {
                                d.detach(m);
                            }
                        }
                    }
                }
            }
            self.pkg.remove(part);
            self.pkg.remove(&Package::rels_name(part));
            remove_override(&mut self.pkg, part);
        }
        self.commit();
        self.refresh_design();
        Ok(())
    }

    fn drop_rel(pkg: &mut Package, part: &str, rid: &str) {
        if let Ok(d) = pkg.xml_mut(&Package::rels_name(part)) {
            for r in d.elements(d.root).collect::<Vec<_>>() {
                if d.attr(r, "Id") == Some(rid) {
                    d.detach(r);
                }
            }
        }
    }

    pub fn rename_design(&mut self, part: &str, name: &str) -> Result<(), String> {
        let theme = if part.contains("slideMasters/") { self.theme_of(part) } else { None };
        let mut touch = vec![part.to_string()];
        if let Some(t) = &theme {
            touch.push(t.clone());
        }
        self.begin("Rename", &touch);
        let d = self.pkg.xml_mut(part).map_err(|e| e.to_string())?;
        let root = d.root;
        let c = d.child(root, "p:cSld").ok_or("bad part")?;
        d.set_attr(c, "name", name);
        if let Some(t) = theme {
            if let Ok(td) = self.pkg.xml_mut(&t) {
                let r = td.root;
                td.set_attr(r, "name", name);
            }
        }
        self.commit();
        Ok(())
    }

    /// Whether a slide or layout shows its master's (and layout's) graphics.
    pub fn shows_master_shapes(&mut self, part: &str) -> bool {
        self.pkg.xml(part).ok().map(|d| !matches!(d.attr(d.root, "showMasterSp"), Some("0") | Some("false"))).unwrap_or(true)
    }

    /// Hide Background Graphics (off) or show them (on).
    pub fn set_show_master_shapes(&mut self, part: &str, on: bool) -> Result<(), String> {
        self.begin("Hide Background Graphics", &[part.to_string()]);
        let d = self.pkg.xml_mut(part).map_err(|e| e.to_string())?;
        let r = d.root;
        if on {
            d.remove_attr(r, "showMasterSp");
        } else {
            d.set_attr(r, "showMasterSp", "0");
        }
        self.commit();
        Ok(())
    }

    pub fn preserved(&mut self, part: &str) -> bool {
        self.pkg.xml(part).ok().map(|d| matches!(d.attr(d.root, "preserve"), Some("1") | Some("true"))).unwrap_or(false)
    }

    pub fn set_preserved(&mut self, part: &str, on: bool) -> Result<(), String> {
        self.begin("Preserve", &[part.to_string()]);
        let d = self.pkg.xml_mut(part).map_err(|e| e.to_string())?;
        let r = d.root;
        d.set_attr(r, "preserve", if on { "1" } else { "0" });
        self.commit();
        Ok(())
    }

    /// Which placeholder kinds a layout or master shows: title, body, dt, ftr, sldNum, others.
    pub fn design_placeholders(&mut self, part: &str) -> Vec<String> {
        self.pkg.xml(part).map(|d| placeholders(d).into_iter().map(|p| p.1).collect()).unwrap_or_default()
    }

    /// Show or hide placeholders of these kinds on a layout or master ("title", "footers" =
    /// dt + ftr + sldNum, "body", "dt", "ftr", "sldNum").
    pub fn design_toggle(&mut self, part: &str, which: &str, on: bool) -> Result<(), String> {
        let kinds: Vec<&str> = match which { "footers" => vec!["dt", "ftr", "sldNum"], k => vec![k] };
        self.begin(if on { "Show Placeholder" } else { "Hide Placeholder" }, &[part.to_string()]);
        let is_master = part.contains("slideMasters/");
        let is_page = part.contains("notesMaster") || part.contains("handoutMaster");
        // where PowerPoint keeps them (EMU), for parts whose placeholders need their own box
        let defaults = if is_page {
            "hdr:0,0,2971800,458788|dt:3884613,0,2971800,458788|sldImg:685800,1143000,5486400,3086100|body:685800,4400550,5486400,3600450|ftr:0,8685213,2971800,458787|sldNum:3884613,8685213,2971800,458787"
        } else {
            "title:838200,365125,10515600,1325563|body:838200,1825625,10515600,4351338|dt:838200,6356350,2743200,365125|ftr:4038600,6356350,4114800,365125|sldNum:8610600,6356350,2743200,365125"
        };
        let scale = if is_page { 1.0 } else { self.cx / 12192000.0 };
        let notes = part.contains("notesMaster");
        let d = self.pkg.xml_mut(part).map_err(|e| e.to_string())?;
        let t = tree(d).ok_or("no shapes")?;
        let have = placeholders(d);
        for k in kinds {
            let found: Vec<NodeId> = have.iter().filter(|p| p.1 == k).map(|p| p.0).collect();
            if !on {
                for n in found {
                    d.detach(n);
                }
            } else if found.is_empty() {
                let id = max_shape_id(d);
                let idx = if is_page {
                    match (k, notes) { ("hdr", _) => None, ("dt", _) => Some(1), ("sldImg", _) => Some(2), ("body", _) => Some(3),
                                       ("ftr", true) => Some(4), ("sldNum", true) => Some(5), ("ftr", false) => Some(2), ("sldNum", false) => Some(3), _ => None }
                } else if is_master {
                    match k { "dt" => Some(2), "ftr" => Some(3), "sldNum" => Some(4), "body" => Some(1), _ => None }
                } else {
                    match k { "dt" => Some(10), "ftr" => Some(11), "sldNum" => Some(12), "body" => Some(1), _ => None }
                };
                let mut xml = Self::ph_xml(id, k, idx);
                if is_master || is_page {
                    if let Some(dflt) = defaults.split('|').find(|s| s.starts_with(&format!("{k}:"))) {
                        let v: Vec<f64> = dflt[k.len() + 1..].split(',').filter_map(|x| x.parse().ok()).collect();
                        let line = if k == "sldImg" { r#"<a:noFill/><a:ln w="12700"><a:solidFill><a:prstClr val="black"/></a:solidFill></a:ln>"# } else { "" };
                        let x = format!(r#"<p:spPr><a:xfrm><a:off x="{}" y="{}"/><a:ext cx="{}" cy="{}"/></a:xfrm><a:prstGeom prst="rect"><a:avLst/></a:prstGeom>{line}</p:spPr>"#,
                                        (v[0] * scale) as i64, (v[1] * scale) as i64, (v[2] * scale) as i64, (v[3] * scale) as i64);
                        xml = xml.replace("<p:spPr/>", &x);
                    }
                    if k == "sldImg" {
                        if let (Some(a), Some(b)) = (xml.find("<p:txBody>"), xml.find("</p:txBody>")) {
                            xml.replace_range(a..b + "</p:txBody>".len(), "");
                        }
                    }
                    if k == "body" {
                        xml = xml.replace(r#"<a:p><a:endParaRPr lang="en-US"/></a:p>"#, if is_page {
                            r#"<a:p><a:pPr lvl="0"/><a:r><a:rPr lang="en-US"/><a:t>Click to edit Master text styles</a:t></a:r></a:p>"#
                        } else {
                            r#"<a:p><a:pPr lvl="0"/><a:r><a:rPr lang="en-US"/><a:t>Click to edit Master text styles</a:t></a:r></a:p><a:p><a:pPr lvl="1"/><a:r><a:rPr lang="en-US"/><a:t>Second level</a:t></a:r></a:p><a:p><a:pPr lvl="2"/><a:r><a:rPr lang="en-US"/><a:t>Third level</a:t></a:r></a:p><a:p><a:pPr lvl="3"/><a:r><a:rPr lang="en-US"/><a:t>Fourth level</a:t></a:r></a:p><a:p><a:pPr lvl="4"/><a:r><a:rPr lang="en-US"/><a:t>Fifth level</a:t></a:r></a:p>"#
                        });
                    }
                }
                if let Some(n) = fragment(d, &xml) {
                    if k == "title" {
                        // the title goes first, like PowerPoint's
                        let at = d.children(t).iter().position(|&c| d.name(c) != "p:nvGrpSpPr" && d.name(c) != "p:grpSpPr").unwrap_or(d.children(t).len());
                        d.insert(t, at, n);
                    } else {
                        d.append(t, n);
                    }
                }
            }
        }
        self.commit();
        Ok(())
    }

    /// Draw a new placeholder on a layout: kind obj (Content), body (Text), pic, chart, tbl,
    /// media, clipArt; box in points. Returns its shape id.
    #[allow(clippy::too_many_arguments)]
    pub fn add_layout_placeholder(&mut self, part: &str, kind: &str, x: f64, y: f64, w: f64, h: f64) -> Result<u32, String> {
        self.begin("Insert Placeholder", &[part.to_string()]);
        let d = self.pkg.xml_mut(part).map_err(|e| e.to_string())?;
        let t = tree(d).ok_or("no shapes")?;
        let idx = placeholders(d).iter().filter_map(|p| p.2).max().unwrap_or(12).max(12) + 1;
        let id = max_shape_id(d);
        let (label, prompt) = match kind {
            "body" => ("Text Placeholder", "Click to edit Master text styles"),
            "pic" => ("Picture Placeholder", "Picture"),
            "chart" => ("Chart Placeholder", "Chart"),
            "tbl" => ("Table Placeholder", "Table"),
            "media" => ("Media Placeholder", "Media"),
            "clipArt" => ("Online Image Placeholder", "Online Image"),
            _ => ("Content Placeholder", "Click to edit Master text styles"),
        };
        let ty = if kind == "obj" { String::new() } else { format!(r#" type="{kind}""#) };
        let e = |v: f64| (v * 12700.0).round() as i64;
        let xml = format!(r#"<p:sp><p:nvSpPr><p:cNvPr id="{id}" name="{label} {}"/><p:cNvSpPr><a:spLocks noGrp="1"/></p:cNvSpPr><p:nvPr><p:ph{ty} sz="quarter" idx="{idx}"/></p:nvPr></p:nvSpPr><p:spPr><a:xfrm><a:off x="{}" y="{}"/><a:ext cx="{}" cy="{}"/></a:xfrm></p:spPr><p:txBody><a:bodyPr/><a:lstStyle/><a:p><a:pPr lvl="0"/><a:r><a:rPr lang="en-US"/><a:t>{prompt}</a:t></a:r></a:p></p:txBody></p:sp>"#,
                          id - 1, e(x), e(y), e(w), e(h));
        let n = fragment(d, &xml).ok_or("bad placeholder")?;
        d.append(t, n);
        self.commit();
        Ok(id)
    }

    /// The handout master, made when there is none.
    pub fn ensure_handout_master(&mut self) -> Result<String, String> {
        let pres = self.pres.clone();
        if let Some(h) = self.pkg.related(&pres, "/handoutMaster") {
            return Ok(h);
        }
        let part = "ppt/handoutMasters/handoutMaster1.xml".to_string();
        let theme = self.free_name("ppt/theme", "theme", "xml");
        self.begin("Handout Master", &[pres.clone(), Package::rels_name(&pres), CT.to_string(), part.clone(), Package::rels_name(&part), theme.clone()]);
        let src_theme = self.masters().first().and_then(|m| self.theme_of(m)).ok_or("no theme")?;
        self.pkg.put_raw(&theme, self.pkg.bytes(&src_theme).ok_or("no theme")?);
        self.pkg.set_content_type(&theme, CT_THEME);
        let (w, h) = (6858000i64, 9144000i64);
        let ph = |id: u32, ty: &str, idx: u32, x: i64, y: i64, label: &str, algn: &str| format!(
            r#"<p:sp><p:nvSpPr><p:cNvPr id="{id}" name="{label}"/><p:cNvSpPr><a:spLocks noGrp="1"/></p:cNvSpPr><p:nvPr><p:ph type="{ty}" sz="quarter" idx="{idx}"/></p:nvPr></p:nvSpPr><p:spPr><a:xfrm><a:off x="{x}" y="{y}"/><a:ext cx="2971800" cy="458788"/></a:xfrm><a:prstGeom prst="rect"><a:avLst/></a:prstGeom></p:spPr><p:txBody><a:bodyPr vert="horz" lIns="91440" tIns="45720" rIns="91440" bIns="45720" rtlCol="0"/><a:lstStyle><a:lvl1pPr algn="{algn}"><a:defRPr sz="1200"/></a:lvl1pPr></a:lstStyle>{}</p:txBody></p:sp>"#,
            match ty {
                "hdr" => r#"<a:p><a:r><a:rPr lang="en-US"/><a:t>Header</a:t></a:r></a:p>"#,
                "dt" => r#"<a:p><a:fld id="{B7B1A5D1-1C0E-4F35-9E8E-2A6C3C1F0D11}" type="datetimeFigureOut"><a:rPr lang="en-US"/><a:t>‹date›</a:t></a:fld><a:endParaRPr lang="en-US"/></a:p>"#,
                "sldNum" => r#"<a:p><a:fld id="{3C3E7F2A-5B1D-4C6E-8F0A-9D2B4E6A8C13}" type="slidenum"><a:rPr lang="en-US"/><a:t>‹#›</a:t></a:fld><a:endParaRPr lang="en-US"/></a:p>"#,
                _ => r#"<a:p><a:endParaRPr lang="en-US"/></a:p>"#,
            });
        let shapes = [ph(2, "hdr", 0, 0, 0, "Header Placeholder 1", "l"), ph(3, "dt", 1, w - 2971800, 0, "Date Placeholder 2", "r"),
                      ph(4, "ftr", 2, 0, h - 458788, "Footer Placeholder 3", "l"), ph(5, "sldNum", 3, w - 2971800, h - 458788, "Slide Number Placeholder 4", "r")].concat();
        let xml = format!(r#"<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:handoutMaster {NS}><p:cSld><p:bg><p:bgRef idx="1001"><a:schemeClr val="bg1"/></p:bgRef></p:bg><p:spTree><p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr><p:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/><a:chOff x="0" y="0"/><a:chExt cx="0" cy="0"/></a:xfrm></p:grpSpPr>{shapes}</p:spTree></p:cSld><p:clrMap bg1="lt1" tx1="dk1" bg2="lt2" tx2="dk2" accent1="accent1" accent2="accent2" accent3="accent3" accent4="accent4" accent5="accent5" accent6="accent6" hlink="hlink" folHlink="folHlink"/></p:handoutMaster>"#);
        self.pkg.put_xml(&part, XmlDoc::parse(xml.as_bytes()).map_err(|e| e.to_string())?);
        self.pkg.set_content_type(&part, CT_HANDOUT);
        self.pkg.add_rel(&part, &format!("{RT}theme"), &rel_path(&part, &theme));
        let rid = self.pkg.add_rel(&pres, &format!("{RT}handoutMaster"), &rel_path(&pres, &part));
        let d = self.pkg.xml_mut(&pres).map_err(|e| e.to_string())?;
        let root = d.root;
        let el = fragment(d, &format!(r#"<p:handoutMasterIdLst><p:handoutMasterId r:id="{rid}"/></p:handoutMasterIdLst>"#)).ok_or("bad list")?;
        // after notesMasterIdLst / sldMasterIdLst, before sldIdLst
        let at = ["p:notesMasterIdLst", "p:sldMasterIdLst"].iter().find_map(|k| d.child(root, k)).and_then(|c| d.index_in_parent(c)).map(|k| k + 1).unwrap_or(0);
        d.insert(root, at, el);
        self.commit();
        self.refresh_design();
        Ok(part)
    }

    /// The notes master, made when there is none.
    pub fn notes_master_part(&mut self) -> Result<String, String> {
        if let Some(m) = self.notes_master() {
            return Ok(m);
        }
        let pres = self.pres.clone();
        self.begin("Notes Master", &[pres.clone(), Package::rels_name(&pres), CT.to_string()]);
        let r = self.ensure_notes_master();
        self.commit();
        self.refresh_design();
        r
    }
}

fn esc(s: &str) -> String {
    let mut o = String::new();
    folio_core::xml::escape_text(s, &mut o);
    o.replace('"', "&quot;")
}

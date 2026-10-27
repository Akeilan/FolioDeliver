//! Changing a presentation: slides (new, duplicate, delete, move, hide, layout),
//! shapes (insert, move, resize, rotate, order, delete) and text (typing, deleting,
//! splitting paragraphs, run and paragraph formatting). Every change is undoable.

use crate::model::{emu, path, Deck, CT_SLIDE, EMU_PT, RT};
use crate::scene;
use folio_core::package::Package;
use folio_core::xml::{NodeId, XmlDoc};

const NS_DECL: &str = r#"xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main""#;
const CT: &str = "[Content_Types].xml";

fn rel_path(from: &str, to: &str) -> String {
    let fd: Vec<&str> = from.split('/').collect();
    let td: Vec<&str> = to.split('/').collect();
    let fdir = &fd[..fd.len() - 1];
    let mut common = 0;
    while common < fdir.len() && common < td.len() - 1 && fdir[common] == td[common] {
        common += 1;
    }
    let mut out: Vec<String> = std::iter::repeat("..".to_string()).take(fdir.len() - common).collect();
    out.extend(td[common..].iter().map(|s| s.to_string()));
    out.join("/")
}

fn esc(s: &str) -> String {
    folio_core::xml::attr_escaped(s)
}

fn emu_s(pt: f64) -> String {
    format!("{}", (pt * EMU_PT).round() as i64)
}

/// Parse an XML fragment (with the presentation namespaces) and bring it into `dom`.
pub fn fragment(dom: &mut XmlDoc, xml: &str) -> Option<NodeId> {
    let wrapped = format!("<w {NS_DECL}>{xml}</w>");
    let f = XmlDoc::parse(wrapped.as_bytes()).ok()?;
    let first = f.elements(f.root).next()?;
    Some(dom.import_node(&f, first))
}

fn set_t(dom: &mut XmlDoc, t: NodeId, s: &str) {
    let kids: Vec<NodeId> = dom.children(t).to_vec();
    if let Some(&k) = kids.iter().find(|&&k| dom.text_of_node(k).is_some()) {
        dom.set_text(k, s);
        for &o in kids.iter().filter(|&&o| o != k) {
            dom.detach(o);
        }
    } else {
        let n = dom.new_text(s);
        dom.append(t, n);
    }
}

fn char_len(s: &str) -> usize {
    s.chars().count()
}

fn split_at_char(s: &str, k: usize) -> (String, String) {
    let b = s.char_indices().nth(k).map(|(i, _)| i).unwrap_or(s.len());
    (s[..b].to_string(), s[b..].to_string())
}

impl Deck {
    pub fn slide_part(&self, i: usize) -> Result<String, String> {
        self.slides.get(i).cloned().ok_or_else(|| "no such slide".to_string())
    }

    fn structure_parts(&self, extra: &[String]) -> Vec<String> {
        let mut v = vec![self.pres.clone(), Package::rels_name(&self.pres), CT.to_string()];
        for e in extra {
            v.push(e.clone());
            v.push(Package::rels_name(e));
        }
        v
    }

    fn write_slide_list(&mut self) -> Result<(), String> {
        let pres = self.pres.clone();
        let rels = self.pkg.rels(&pres);
        let slides = self.slides.clone();
        let dom = self.pkg.xml_mut(&pres).map_err(|e| e.to_string())?;
        let root = dom.root;
        let lst = match dom.child(root, "p:sldIdLst") {
            Some(l) => l,
            None => {
                let l = dom.new_element("p:sldIdLst", &[]);
                // after the masters (and notes/handout master lists)
                let after = ["p:sldMasterIdLst", "p:notesMasterIdLst", "p:handoutMasterIdLst"].iter()
                    .filter_map(|n| dom.child(root, n)).filter_map(|n| dom.index_in_parent(n)).max();
                dom.insert(root, after.map(|i| i + 1).unwrap_or(0), l);
                l
            }
        };
        let old: Vec<NodeId> = dom.elements(lst).collect();
        let mut by_target: Vec<(String, NodeId)> = Vec::new();
        for o in &old {
            let rid = dom.attr(*o, "r:id").unwrap_or("");
            if let Some(r) = rels.iter().find(|r| r.id == rid) {
                by_target.push((Package::resolve(&pres, &r.target), *o));
            }
            dom.detach(*o);
        }
        let mut next_id = old.iter().filter_map(|o| dom.attr(*o, "id").and_then(|v| v.parse::<u32>().ok())).max().unwrap_or(255) + 1;
        let mut need_rel = Vec::new();
        for s in &slides {
            if let Some((_, n)) = by_target.iter().find(|(t, _)| t == s) {
                dom.append(lst, *n);
            } else {
                need_rel.push(s.clone());
            }
        }
        // new slides: relationship and id, then put everything in order again
        for s in need_rel {
            let target = rel_path(&pres, &s);
            let rid = self.pkg.add_rel(&pres, &format!("{RT}slide"), &target);
            let dom = self.pkg.xml_mut(&pres).map_err(|e| e.to_string())?;
            let lst = dom.child(dom.root, "p:sldIdLst").unwrap();
            let el = dom.new_element("p:sldId", &[("id", &next_id.to_string()), ("r:id", &rid)]);
            next_id += 1;
            dom.append(lst, el);
            by_target.push((s, el));
        }
        let dom = self.pkg.xml_mut(&pres).map_err(|e| e.to_string())?;
        let lst = dom.child(dom.root, "p:sldIdLst").unwrap();
        let rels = by_target;
        for n in dom.elements(lst).collect::<Vec<_>>() {
            dom.detach(n);
        }
        for s in &slides {
            if let Some((_, n)) = rels.iter().find(|(t, _)| t == s) {
                dom.append(lst, *n);
            }
        }
        // drop relationships to slides no longer listed
        let rname = Package::rels_name(&pres);
        if let Ok(rd) = self.pkg.xml_mut(&rname) {
            for r in rd.elements(rd.root).collect::<Vec<_>>() {
                let ty = rd.attr(r, "Type").unwrap_or("");
                if ty.ends_with("/slide") {
                    let t = Package::resolve(&pres, rd.attr(r, "Target").unwrap_or(""));
                    if !slides.contains(&t) {
                        rd.detach(r);
                    }
                }
            }
        }
        Ok(())
    }

    /// A new slide after slide `after` (None: at the start) with `layout`.
    pub fn new_slide(&mut self, after: Option<usize>, layout: &str) -> Result<usize, String> {
        let part = self.free_name("ppt/slides", "slide", "xml");
        self.begin("New Slide", &self.structure_parts(&[part.clone()]));
        let mut shapes = String::new();
        let mut id = 2;
        if let Ok(ld) = self.pkg.xml(layout) {
            let ld = ld.clone();
            if let Some(tree) = path(&ld, ld.root, &["p:cSld", "p:spTree"]) {
                for n in ld.elements(tree) {
                    let Some(ph) = scene::ph_of(&ld, n) else { continue };
                    if matches!(ph.kind.as_str(), "dt" | "ftr" | "sldNum" | "hdr") {
                        continue;
                    }
                    let (_, name) = scene::shape_id(&ld, n);
                    let mut attrs = String::new();
                    if ph.kind != "body" || ph.idx.is_none() {
                        attrs.push_str(&format!(r#" type="{}""#, ph.kind));
                    }
                    if let Some(i) = ph.idx {
                        attrs.push_str(&format!(r#" idx="{i}""#));
                    }
                    if ph.kind == "body" && ph.idx.is_some() {
                        // a body placeholder with an index: no type attribute needed
                        attrs = attrs.replace(r#" type="body""#, "");
                    }
                    let orient = ld.elements(n).find(|&c| ld.name(c) == "p:nvSpPr")
                        .and_then(|nv| path(&ld, nv, &["p:nvPr", "p:ph"])).and_then(|p| ld.attr(p, "orient"))
                        .map(|o| format!(r#" orient="{o}""#)).unwrap_or_default();
                    let sz = ld.elements(n).find(|&c| ld.name(c) == "p:nvSpPr")
                        .and_then(|nv| path(&ld, nv, &["p:nvPr", "p:ph"])).and_then(|p| ld.attr(p, "sz"))
                        .map(|o| format!(r#" sz="{o}""#)).unwrap_or_default();
                    let body = if ld.name(n) == "p:sp" {
                        r#"<p:txBody><a:bodyPr/><a:lstStyle/><a:p><a:endParaRPr lang="en-US" dirty="0"/></a:p></p:txBody>"#
                    } else {
                        ""
                    };
                    shapes.push_str(&format!(
                        r#"<p:sp><p:nvSpPr><p:cNvPr id="{id}" name="{}"/><p:cNvSpPr><a:spLocks noGrp="1"/></p:cNvSpPr><p:nvPr><p:ph{attrs}{orient}{sz}/></p:nvPr></p:nvSpPr><p:spPr/>{body}</p:sp>"#,
                        esc(&name)));
                    id += 1;
                }
            }
        }
        let xml = format!(
            r#"<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:sld {NS_DECL}><p:cSld><p:spTree><p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr><p:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/><a:chOff x="0" y="0"/><a:chExt cx="0" cy="0"/></a:xfrm></p:grpSpPr>{shapes}</p:spTree></p:cSld><p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr></p:sld>"#);
        let doc = XmlDoc::parse(xml.as_bytes()).map_err(|e| e.to_string())?;
        self.pkg.put_xml(&part, doc);
        self.pkg.set_content_type(&part, CT_SLIDE);
        self.pkg.add_rel(&part, &format!("{RT}slideLayout"), &rel_path(&part, layout));
        let at = after.map(|a| (a + 1).min(self.slides.len())).unwrap_or(0);
        self.slides.insert(at, part);
        self.write_slide_list()?;
        self.commit();
        Ok(at)
    }

    /// Copy slides (in order) to just after the last of them; returns the first copy's index.
    pub fn duplicate_slides(&mut self, idx: &[usize]) -> Result<usize, String> {
        let mut idx: Vec<usize> = idx.iter().copied().filter(|i| *i < self.slides.len()).collect();
        idx.sort();
        idx.dedup();
        let Some(&last) = idx.last() else { return Err("no slide".into()) };
        let mut news = Vec::new();
        let mut taken: Vec<String> = Vec::new();
        for _ in &idx {
            let mut n = 1;
            loop {
                let name = format!("ppt/slides/slide{n}.xml");
                if !self.pkg.has(&name) && !taken.contains(&name) {
                    taken.push(name);
                    break;
                }
                n += 1;
            }
        }
        self.begin("Duplicate Slide", &self.structure_parts(&taken));
        for (k, i) in idx.iter().enumerate() {
            let src = self.slides[*i].clone();
            let dst = taken[k].clone();
            let data = self.pkg.bytes(&src).ok_or("slide missing")?;
            self.pkg.put_raw(&dst, data);
            self.pkg.set_content_type(&dst, CT_SLIDE);
            // relationships: the same targets (notes are not shared)
            for r in self.pkg.rels(&src) {
                if r.kind.ends_with("/notesSlide") {
                    continue;
                }
                let target = if r.external { r.target.clone() } else { rel_path(&dst, &Package::resolve(&src, &r.target)) };
                let rels_name = Package::rels_name(&dst);
                if !self.pkg.has(&rels_name) {
                    let doc = XmlDoc::with_root("Relationships", &[("xmlns", "http://schemas.openxmlformats.org/package/2006/relationships")]);
                    self.pkg.put_xml(&rels_name, doc);
                }
                let rd = self.pkg.xml_mut(&rels_name).map_err(|e| e.to_string())?;
                let mut attrs = vec![("Id", r.id.as_str()), ("Type", r.kind.as_str()), ("Target", target.as_str())];
                if r.external {
                    attrs.push(("TargetMode", "External"));
                }
                let el = rd.new_element("Relationship", &attrs);
                let root = rd.root;
                rd.append(root, el);
            }
            news.push(dst);
        }
        let at = last + 1;
        for (k, n) in news.into_iter().enumerate() {
            self.slides.insert(at + k, n);
        }
        self.write_slide_list()?;
        self.commit();
        Ok(at)
    }

    pub fn delete_slides(&mut self, idx: &[usize]) -> Result<(), String> {
        let parts: Vec<String> = idx.iter().filter_map(|i| self.slides.get(*i).cloned()).collect();
        if parts.is_empty() {
            return Ok(());
        }
        let mut touched = parts.clone();
        for p in &parts {
            if let Some(n) = self.notes_of(p) {
                touched.push(n);
            }
        }
        self.begin(if parts.len() > 1 { "Delete Slides" } else { "Delete Slide" }, &self.structure_parts(&touched));
        for p in &touched {
            self.pkg.remove(p);
            self.pkg.remove(&Package::rels_name(p));
            if let Ok(ct) = self.pkg.xml_mut(CT) {
                let pname = format!("/{p}");
                for o in ct.children_named(ct.root, "Override").collect::<Vec<_>>() {
                    if ct.attr(o, "PartName") == Some(&pname) {
                        ct.detach(o);
                    }
                }
            }
        }
        self.slides.retain(|s| !parts.contains(s));
        self.write_slide_list()?;
        self.commit();
        Ok(())
    }

    /// Move slides `idx` so they sit before the slide now at `to` (len: at the end).
    pub fn move_slides(&mut self, idx: &[usize], to: usize) -> Result<usize, String> {
        let mut idx: Vec<usize> = idx.iter().copied().filter(|i| *i < self.slides.len()).collect();
        idx.sort();
        idx.dedup();
        if idx.is_empty() {
            return Ok(to);
        }
        self.begin("Move Slide", &self.structure_parts(&[]));
        let moving: Vec<String> = idx.iter().map(|i| self.slides[*i].clone()).collect();
        let before = idx.iter().filter(|i| **i < to).count();
        self.slides.retain(|s| !moving.contains(s));
        let at = (to - before).min(self.slides.len());
        for (k, m) in moving.into_iter().enumerate() {
            self.slides.insert(at + k, m);
        }
        self.write_slide_list()?;
        self.commit();
        Ok(at)
    }

    pub fn is_hidden(&mut self, i: usize) -> bool {
        let Ok(p) = self.slide_part(i) else { return false };
        self.pkg.xml(&p).ok().and_then(|d| d.attr(d.root, "show")).map(|v| v == "0" || v == "false").unwrap_or(false)
    }

    pub fn set_hidden(&mut self, idx: &[usize], hidden: bool) -> Result<(), String> {
        let parts: Vec<String> = idx.iter().filter_map(|i| self.slides.get(*i).cloned()).collect();
        self.begin("Hide Slide", &parts);
        for p in &parts {
            let d = self.pkg.xml_mut(p).map_err(|e| e.to_string())?;
            let r = d.root;
            if hidden {
                d.set_attr(r, "show", "0");
            } else {
                d.remove_attr(r, "show");
            }
        }
        self.commit();
        Ok(())
    }

    /// Give slides another layout: placeholders keep their content and follow the new
    /// layout's positions, as PowerPoint does.
    pub fn set_layout(&mut self, idx: &[usize], layout: &str) -> Result<(), String> {
        let parts: Vec<String> = idx.iter().filter_map(|i| self.slides.get(*i).cloned()).collect();
        let mut touched = Vec::new();
        for p in &parts {
            touched.push(p.clone());
            touched.push(Package::rels_name(p));
        }
        self.begin("Layout", &touched);
        for p in &parts {
            let rels_name = Package::rels_name(p);
            let target = rel_path(p, layout);
            if let Ok(rd) = self.pkg.xml_mut(&rels_name) {
                for r in rd.elements(rd.root).collect::<Vec<_>>() {
                    if rd.attr(r, "Type").unwrap_or("").ends_with("/slideLayout") {
                        rd.set_attr(r, "Target", &target);
                    }
                }
            }
            // drop positions so placeholders follow the new layout
            let d = self.pkg.xml_mut(p).map_err(|e| e.to_string())?;
            if let Some(tree) = path(d, d.root, &["p:cSld", "p:spTree"]) {
                for n in d.elements(tree).collect::<Vec<_>>() {
                    if scene::ph_of(d, n).is_some() {
                        if let Some(x) = path(d, n, &["p:spPr", "a:xfrm"]) {
                            d.detach(x);
                        }
                    }
                }
            }
        }
        // placeholders the new layout has and the slide lacks
        for p in &parts {
            let ld = self.pkg.xml(layout).map_err(|e| e.to_string())?.clone();
            let Some(ltree) = path(&ld, ld.root, &["p:cSld", "p:spTree"]) else { continue };
            let want: Vec<(scene::Ph, String, bool)> = ld.elements(ltree)
                .filter_map(|n| scene::ph_of(&ld, n).map(|ph| (ph, scene::shape_id(&ld, n).1, ld.name(n) == "p:sp")))
                .filter(|(ph, _, _)| !matches!(ph.kind.as_str(), "dt" | "ftr" | "sldNum" | "hdr")).collect();
            let d = self.pkg.xml_mut(p).map_err(|e| e.to_string())?;
            let Some(tree) = path(d, d.root, &["p:cSld", "p:spTree"]) else { continue };
            let have: Vec<scene::Ph> = d.elements(tree).filter_map(|n| scene::ph_of(d, n)).collect();
            let mut next = next_shape_id(d);
            for (ph, name, is_sp) in want {
                let found = have.iter().any(|h| (h.idx.is_some() && h.idx == ph.idx) || (h.idx.is_none() && ph.idx.is_none() && h.kind == ph.kind)
                    || (matches!(h.kind.as_str(), "title" | "ctrTitle") && matches!(ph.kind.as_str(), "title" | "ctrTitle")));
                if found {
                    continue;
                }
                let mut attrs = format!(r#" type="{}""#, ph.kind);
                if let Some(i) = ph.idx {
                    attrs = if ph.kind == "body" { format!(r#" idx="{i}""#) } else { format!(r#"{attrs} idx="{i}""#) };
                }
                let body = if is_sp { r#"<p:txBody><a:bodyPr/><a:lstStyle/><a:p><a:endParaRPr lang="en-US"/></a:p></p:txBody>"# } else { "" };
                let xml = format!(r#"<p:sp><p:nvSpPr><p:cNvPr id="{next}" name="{}"/><p:cNvSpPr><a:spLocks noGrp="1"/></p:cNvSpPr><p:nvPr><p:ph{attrs}/></p:nvPr></p:nvSpPr><p:spPr/>{body}</p:sp>"#, esc(&name));
                next += 1;
                if let Some(n) = fragment(d, &xml) {
                    d.append(tree, n);
                }
            }
            // empty placeholders the new layout doesn't have go away
            let lphs: Vec<scene::Ph> = ld.elements(ltree).filter_map(|n| scene::ph_of(&ld, n)).collect();
            for n in d.elements(tree).collect::<Vec<_>>() {
                let Some(ph) = scene::ph_of(d, n) else { continue };
                let matched = lphs.iter().any(|l| (ph.idx.is_some() && l.idx == ph.idx) || l.kind == ph.kind
                    || (matches!(l.kind.as_str(), "title" | "ctrTitle") && matches!(ph.kind.as_str(), "title" | "ctrTitle")));
                let empty = d.child(n, "p:txBody").map(|tb| crate::text::plain_text(d, tb).iter().all(|s| s.is_empty())).unwrap_or(true)
                    && d.name(n) == "p:sp";
                if !matched && empty {
                    d.detach(n);
                }
            }
        }
        self.commit();
        Ok(())
    }

    // ------------------------------------------------------------ shapes
    pub fn find_shape(&mut self, part: &str, id: u32) -> Option<NodeId> {
        let d = self.pkg.xml(part).ok()?;
        let tree = path(d, d.root, &["p:cSld", "p:spTree"])?;
        let mut all = Vec::new();
        scene::collect_shapes(d, tree, &mut all);
        all.into_iter().find(|n| scene::shape_id(d, *n).0 == id)
    }

    fn insert_shape_xml(&mut self, i: usize, label: &str, build: &dyn Fn(u32) -> String) -> Result<u32, String> {
        let part = self.slide_part(i)?;
        self.begin(label, &[part.clone()]);
        let d = self.pkg.xml_mut(&part).map_err(|e| e.to_string())?;
        let id = next_shape_id(d);
        let tree = path(d, d.root, &["p:cSld", "p:spTree"]).ok_or("slide has no shape tree")?;
        let n = fragment(d, &build(id)).ok_or("bad shape")?;
        // before any extension list at the end of the tree
        let at = d.elements(tree).position(|c| d.name(c) == "p:extLst").map(|p| {
            d.children(tree).iter().position(|&c| c == d.elements(tree).nth(p).unwrap()).unwrap()
        });
        match at {
            Some(k) => d.insert(tree, k, n),
            None => d.append(tree, n),
        }
        self.commit();
        Ok(id)
    }

    pub fn add_textbox(&mut self, i: usize, x: f64, y: f64, w: f64, h: f64, text: &str) -> Result<u32, String> {
        let t = esc_text(text);
        let run = if text.is_empty() { r#"<a:endParaRPr lang="en-US" dirty="0"/>"#.to_string() } else {
            format!(r#"<a:r><a:rPr lang="en-US" dirty="0"/><a:t>{t}</a:t></a:r><a:endParaRPr lang="en-US" dirty="0"/>"#)
        };
        self.insert_shape_xml(i, "Insert Text Box", &|id| format!(
            r#"<p:sp><p:nvSpPr><p:cNvPr id="{id}" name="TextBox {n}"/><p:cNvSpPr txBox="1"/><p:nvPr/></p:nvSpPr><p:spPr><a:xfrm><a:off x="{}" y="{}"/><a:ext cx="{}" cy="{}"/></a:xfrm><a:prstGeom prst="rect"><a:avLst/></a:prstGeom><a:noFill/></p:spPr><p:txBody><a:bodyPr wrap="square" rtlCol="0"><a:spAutoFit/></a:bodyPr><a:lstStyle/><a:p>{run}</a:p></p:txBody></p:sp>"#,
            emu_s(x), emu_s(y), emu_s(w), emu_s(h), n = id - 1))
    }

    /// A preset shape styled as PowerPoint's default (accent 1 fill, darker outline, white text).
    pub fn add_shape(&mut self, i: usize, prst: &str, x: f64, y: f64, w: f64, h: f64) -> Result<u32, String> {
        let line_like = matches!(prst, "line" | "straightConnector1" | "bentConnector3" | "curvedConnector3");
        let label = nice_shape_name(prst);
        if line_like {
            let arrow = if prst == "straightConnector1" { r#"<a:ln><a:tailEnd type="triangle"/></a:ln>"# } else { "" };
            return self.insert_shape_xml(i, "Insert Shape", &|id| format!(
                r#"<p:cxnSp><p:nvCxnSpPr><p:cNvPr id="{id}" name="{label} {n}"/><p:cNvCxnSpPr/><p:nvPr/></p:nvCxnSpPr><p:spPr><a:xfrm><a:off x="{}" y="{}"/><a:ext cx="{}" cy="{}"/></a:xfrm><a:prstGeom prst="{prst}"><a:avLst/></a:prstGeom>{arrow}</p:spPr><p:style><a:lnRef idx="1"><a:schemeClr val="accent1"/></a:lnRef><a:fillRef idx="0"><a:schemeClr val="accent1"/></a:fillRef><a:effectRef idx="0"><a:schemeClr val="accent1"/></a:effectRef><a:fontRef idx="minor"><a:schemeClr val="tx1"/></a:fontRef></p:style></p:cxnSp>"#,
                emu_s(x), emu_s(y), emu_s(w), emu_s(h), n = id - 1));
        }
        self.insert_shape_xml(i, "Insert Shape", &|id| format!(
            r#"<p:sp><p:nvSpPr><p:cNvPr id="{id}" name="{label} {n}"/><p:cNvSpPr/><p:nvPr/></p:nvSpPr><p:spPr><a:xfrm><a:off x="{}" y="{}"/><a:ext cx="{}" cy="{}"/></a:xfrm><a:prstGeom prst="{prst}"><a:avLst/></a:prstGeom></p:spPr><p:style><a:lnRef idx="2"><a:schemeClr val="accent1"><a:shade val="50000"/></a:schemeClr></a:lnRef><a:fillRef idx="1"><a:schemeClr val="accent1"/></a:fillRef><a:effectRef idx="0"><a:schemeClr val="accent1"/></a:effectRef><a:fontRef idx="minor"><a:schemeClr val="lt1"/></a:fontRef></p:style><p:txBody><a:bodyPr rtlCol="0" anchor="ctr"/><a:lstStyle/><a:p><a:pPr algn="ctr"/><a:endParaRPr lang="en-US" dirty="0"/></a:p></p:txBody></p:sp>"#,
            emu_s(x), emu_s(y), emu_s(w), emu_s(h), n = id - 1))
    }

    /// A picture from file bytes; `ext` is its extension ("png", "jpeg"...).
    pub fn add_picture(&mut self, i: usize, data: Vec<u8>, ext: &str, name: &str, x: f64, y: f64, w: f64, h: f64) -> Result<u32, String> {
        let part = self.slide_part(i)?;
        let ext = ext.to_lowercase().replace("jpg", "jpeg");
        let media = self.free_name("ppt/media", "image", &ext);
        let ctype = match ext.as_str() {
            "png" => "image/png",
            "jpeg" => "image/jpeg",
            "gif" => "image/gif",
            "bmp" => "image/bmp",
            "tif" | "tiff" => "image/tiff",
            "svg" => "image/svg+xml",
            "emf" => "image/x-emf",
            "wmf" => "image/x-wmf",
            _ => "application/octet-stream",
        };
        self.begin("Insert Picture", &[part.clone(), Package::rels_name(&part), CT.to_string(), media.clone()]);
        self.pkg.put_raw(&media, data);
        self.pkg.ensure_default(&ext, ctype);
        let rid = self.pkg.add_rel(&part, &format!("{RT}image"), &rel_path(&part, &media));
        let d = self.pkg.xml_mut(&part).map_err(|e| e.to_string())?;
        let id = next_shape_id(d);
        let xml = format!(
            r#"<p:pic><p:nvPicPr><p:cNvPr id="{id}" name="Picture {n}" descr="{}"/><p:cNvPicPr><a:picLocks noChangeAspect="1"/></p:cNvPicPr><p:nvPr/></p:nvPicPr><p:blipFill><a:blip r:embed="{rid}"/><a:stretch><a:fillRect/></a:stretch></p:blipFill><p:spPr><a:xfrm><a:off x="{}" y="{}"/><a:ext cx="{}" cy="{}"/></a:xfrm><a:prstGeom prst="rect"><a:avLst/></a:prstGeom></p:spPr></p:pic>"#,
            esc(name), emu_s(x), emu_s(y), emu_s(w), emu_s(h), n = id - 1);
        let tree = path(d, d.root, &["p:cSld", "p:spTree"]).ok_or("no tree")?;
        let n = fragment(d, &xml).ok_or("bad picture")?;
        d.append(tree, n);
        self.commit();
        Ok(id)
    }

    /// Move/resize shapes: (id, x, y, w, h) in points; rotation in degrees when given.
    pub fn set_boxes(&mut self, i: usize, boxes: &[(u32, f64, f64, f64, f64, Option<f64>)], label: &str) -> Result<(), String> {
        let part = self.slide_part(i)?;
        let ctx = scene::context(self, &part);
        // placeholders without a box of their own get the inherited one first
        let mut inherited = Vec::new();
        for b in boxes {
            if let Some(n) = self.find_shape(&part, b.0) {
                let bx = scene::shape_box(self, &ctx, &part, n);
                inherited.push((b.0, bx));
            }
        }
        self.begin(label, &[part.clone()]);
        for (id, x, y, w, h, rot) in boxes {
            let Some(n) = self.find_shape(&part, *id) else { continue };
            let d = self.pkg.xml_mut(&part).map_err(|e| e.to_string())?;
            let xf = ensure_xfrm(d, n);
            let off = d.child(xf, "a:off").unwrap();
            let ext = d.child(xf, "a:ext").unwrap();
            let (ox, oy, ow, oh) = (emu(d, off, "x").unwrap_or(0.0), emu(d, off, "y").unwrap_or(0.0),
                                    emu(d, ext, "cx").unwrap_or(0.0), emu(d, ext, "cy").unwrap_or(0.0));
            let (ox, oy, ow, oh) = if ow == 0.0 && oh == 0.0 {
                inherited.iter().find(|(k, _)| k == id).map(|(_, b)| (b.0 * EMU_PT, b.1 * EMU_PT, b.2 * EMU_PT, b.3 * EMU_PT)).unwrap_or((ox, oy, ow, oh))
            } else {
                (ox, oy, ow, oh)
            };
            d.set_attr(off, "x", &emu_s(*x));
            d.set_attr(off, "y", &emu_s(*y));
            d.set_attr(ext, "cx", &emu_s(w.abs().max(0.0)));
            d.set_attr(ext, "cy", &emu_s(h.abs().max(0.0)));
            if let Some(r) = rot {
                let r = r.rem_euclid(360.0);
                if r.abs() < 1e-6 {
                    d.remove_attr(xf, "rot");
                } else {
                    d.set_attr(xf, "rot", &format!("{}", (r * 60000.0).round() as i64));
                }
            }
            // a group's children move and scale with it
            if d.name(n) == "p:grpSp" && ow > 0.0 && oh > 0.0 {
                let _ = (ox, oy);
                // chOff/chExt stay: the group maps its child space onto the new box
            }
        }
        self.commit();
        Ok(())
    }

    pub fn flip(&mut self, i: usize, ids: &[u32], horizontal: bool) -> Result<(), String> {
        let part = self.slide_part(i)?;
        let ctx = scene::context(self, &part);
        let mut boxes = Vec::new();
        for id in ids {
            if let Some(n) = self.find_shape(&part, *id) {
                boxes.push((*id, scene::shape_box(self, &ctx, &part, n)));
            }
        }
        self.begin(if horizontal { "Flip Horizontal" } else { "Flip Vertical" }, &[part.clone()]);
        for (id, b) in boxes {
            let Some(n) = self.find_shape(&part, id) else { continue };
            let d = self.pkg.xml_mut(&part).map_err(|e| e.to_string())?;
            let xf = ensure_xfrm(d, n);
            let off = d.child(xf, "a:off").unwrap();
            if emu(d, d.child(xf, "a:ext").unwrap(), "cx").unwrap_or(0.0) == 0.0 {
                d.set_attr(off, "x", &emu_s(b.0));
                d.set_attr(off, "y", &emu_s(b.1));
                let ext = d.child(xf, "a:ext").unwrap();
                d.set_attr(ext, "cx", &emu_s(b.2));
                d.set_attr(ext, "cy", &emu_s(b.3));
            }
            let key = if horizontal { "flipH" } else { "flipV" };
            let on = d.attr(xf, key).map(|v| v == "1" || v == "true").unwrap_or(false);
            if on {
                d.remove_attr(xf, key);
            } else {
                d.set_attr(xf, key, "1");
            }
        }
        self.commit();
        Ok(())
    }

    pub fn delete_shapes(&mut self, i: usize, ids: &[u32]) -> Result<(), String> {
        let part = self.slide_part(i)?;
        self.begin("Delete", &[part.clone()]);
        for id in ids {
            if let Some(n) = self.find_shape(&part, *id) {
                let d = self.pkg.xml_mut(&part).map_err(|e| e.to_string())?;
                d.detach(n);
            }
        }
        self.commit();
        Ok(())
    }

    /// Order: "front", "back", "forward", "backward".
    pub fn reorder(&mut self, i: usize, ids: &[u32], how: &str) -> Result<(), String> {
        let part = self.slide_part(i)?;
        let label = match how {
            "front" => "Bring to Front",
            "back" => "Send to Back",
            "forward" => "Bring Forward",
            _ => "Send Backward",
        };
        self.begin(label, &[part.clone()]);
        let nodes: Vec<NodeId> = ids.iter().filter_map(|id| self.find_shape(&part, *id)).collect();
        let d = self.pkg.xml_mut(&part).map_err(|e| e.to_string())?;
        let mut nodes = nodes;
        if matches!(how, "front" | "backward") {
            nodes.reverse();
        }
        for n in nodes {
            let Some(parent) = d.parent(n) else { continue };
            let sibs: Vec<NodeId> = d.children(parent).iter().copied()
                .filter(|&c| matches!(d.name(c), "p:sp" | "p:pic" | "p:graphicFrame" | "p:cxnSp" | "p:grpSp" | "mc:AlternateContent")).collect();
            let pos = sibs.iter().position(|&c| c == n).unwrap_or(0);
            let target = match how {
                "front" => sibs.len() - 1,
                "back" => 0,
                "forward" => (pos + 1).min(sibs.len() - 1),
                _ => pos.saturating_sub(1),
            };
            if target == pos {
                continue;
            }
            let anchor = sibs[target];
            d.detach(n);
            let ai = d.index_in_parent(anchor).unwrap_or(0);
            let at = if target > pos { ai + 1 } else { ai };
            d.insert(parent, at, n);
        }
        self.commit();
        Ok(())
    }

    /// Copies of shapes, offset; returns the new ids.
    pub fn duplicate_shapes(&mut self, i: usize, ids: &[u32], dx: f64, dy: f64) -> Result<Vec<u32>, String> {
        let part = self.slide_part(i)?;
        self.begin("Duplicate", &[part.clone()]);
        let nodes: Vec<NodeId> = ids.iter().filter_map(|id| self.find_shape(&part, *id)).collect();
        let d = self.pkg.xml_mut(&part).map_err(|e| e.to_string())?;
        let tree = path(d, d.root, &["p:cSld", "p:spTree"]).ok_or("no tree")?;
        let mut next = next_shape_id(d);
        let mut out = Vec::new();
        for n in nodes {
            let c = d.clone_node(n);
            renumber(d, c, &mut next, &mut out);
            if let Some(xf) = xfrm_of(d, c) {
                if let Some(off) = d.child(xf, "a:off") {
                    let x = emu(d, off, "x").unwrap_or(0.0) + dx * EMU_PT;
                    let y = emu(d, off, "y").unwrap_or(0.0) + dy * EMU_PT;
                    d.set_attr(off, "x", &format!("{}", x.round() as i64));
                    d.set_attr(off, "y", &format!("{}", y.round() as i64));
                }
            }
            d.append(tree, c);
        }
        self.commit();
        Ok(out)
    }

    /// The XML of shapes (for the clipboard), wrapped in a p:spTree.
    pub fn shapes_xml(&mut self, i: usize, ids: &[u32]) -> Result<String, String> {
        let part = self.slide_part(i)?;
        let nodes: Vec<NodeId> = ids.iter().filter_map(|id| self.find_shape(&part, *id)).collect();
        let d = self.pkg.xml(&part).map_err(|e| e.to_string())?;
        let mut s = format!("<p:spTree {NS_DECL}>");
        for n in nodes {
            s.push_str(&d.serialize_node(n));
        }
        s.push_str("</p:spTree>");
        Ok(s)
    }

    /// Paste shapes from `shapes_xml` (pictures need the same package).
    pub fn paste_shapes(&mut self, i: usize, xml: &str, dx: f64, dy: f64) -> Result<Vec<u32>, String> {
        let part = self.slide_part(i)?;
        let src = XmlDoc::parse(xml.as_bytes()).map_err(|e| e.to_string())?;
        self.begin("Paste", &[part.clone()]);
        let d = self.pkg.xml_mut(&part).map_err(|e| e.to_string())?;
        let tree = path(d, d.root, &["p:cSld", "p:spTree"]).ok_or("no tree")?;
        let mut next = next_shape_id(d);
        let mut out = Vec::new();
        for n in src.elements(src.root).collect::<Vec<_>>() {
            let c = d.import_node(&src, n);
            renumber(d, c, &mut next, &mut out);
            if let Some(xf) = xfrm_of(d, c) {
                if let Some(off) = d.child(xf, "a:off") {
                    let x = emu(d, off, "x").unwrap_or(0.0) + dx * EMU_PT;
                    let y = emu(d, off, "y").unwrap_or(0.0) + dy * EMU_PT;
                    d.set_attr(off, "x", &format!("{}", x.round() as i64));
                    d.set_attr(off, "y", &format!("{}", y.round() as i64));
                }
            }
            d.append(tree, c);
        }
        self.commit();
        Ok(out)
    }

    pub fn group(&mut self, i: usize, ids: &[u32]) -> Result<u32, String> {
        let part = self.slide_part(i)?;
        let ctx = scene::context(self, &part);
        let mut boxes = Vec::new();
        for id in ids {
            if let Some(n) = self.find_shape(&part, *id) {
                boxes.push((n, scene::shape_box(self, &ctx, &part, n)));
            }
        }
        if boxes.len() < 2 {
            return Err("select two or more objects to group".into());
        }
        let x0 = boxes.iter().map(|b| b.1 .0).fold(f64::INFINITY, f64::min);
        let y0 = boxes.iter().map(|b| b.1 .1).fold(f64::INFINITY, f64::min);
        let x1 = boxes.iter().map(|b| b.1 .0 + b.1 .2).fold(f64::NEG_INFINITY, f64::max);
        let y1 = boxes.iter().map(|b| b.1 .1 + b.1 .3).fold(f64::NEG_INFINITY, f64::max);
        self.begin("Group", &[part.clone()]);
        let d = self.pkg.xml_mut(&part).map_err(|e| e.to_string())?;
        let id = next_shape_id(d);
        let (ox, oy, w, h) = (emu_s(x0), emu_s(y0), emu_s(x1 - x0), emu_s(y1 - y0));
        let xml = format!(r#"<p:grpSp><p:nvGrpSpPr><p:cNvPr id="{id}" name="Group {n}"/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr><p:grpSpPr><a:xfrm><a:off x="{ox}" y="{oy}"/><a:ext cx="{w}" cy="{h}"/><a:chOff x="{ox}" y="{oy}"/><a:chExt cx="{w}" cy="{h}"/></a:xfrm></p:grpSpPr></p:grpSp>"#, n = id - 1);
        let g = fragment(d, &xml).ok_or("bad group")?;
        // where the topmost member was
        let last = boxes.iter().map(|b| b.0).max_by_key(|n| d.index_in_parent(*n).unwrap_or(0)).unwrap();
        let parent = d.parent(last).ok_or("no parent")?;
        let at = d.index_in_parent(last).unwrap_or(0) + 1;
        d.insert(parent, at, g);
        let mut members: Vec<NodeId> = boxes.iter().map(|b| b.0).collect();
        members.sort_by_key(|n| d.index_in_parent(*n).unwrap_or(0));
        for (k, (n, b)) in members.iter().map(|n| (*n, boxes.iter().find(|x| x.0 == *n).unwrap().1)).enumerate() {
            let _ = k;
            // placeholders keep their box explicitly inside the group
            let xf = ensure_xfrm(d, n);
            let off = d.child(xf, "a:off").unwrap();
            let ext = d.child(xf, "a:ext").unwrap();
            if emu(d, ext, "cx").unwrap_or(0.0) == 0.0 {
                d.set_attr(off, "x", &emu_s(b.0));
                d.set_attr(off, "y", &emu_s(b.1));
                d.set_attr(ext, "cx", &emu_s(b.2));
                d.set_attr(ext, "cy", &emu_s(b.3));
            }
            d.detach(n);
            d.append(g, n);
        }
        self.commit();
        Ok(id)
    }

    pub fn ungroup(&mut self, i: usize, id: u32) -> Result<Vec<u32>, String> {
        let part = self.slide_part(i)?;
        let g = self.find_shape(&part, id).ok_or("no such group")?;
        self.begin("Ungroup", &[part.clone()]);
        let d = self.pkg.xml_mut(&part).map_err(|e| e.to_string())?;
        if d.name(g) != "p:grpSp" {
            self.cancel();
            return Err("not a group".into());
        }
        let xf = path(d, g, &["p:grpSpPr", "a:xfrm"]);
        let get = |d: &XmlDoc, n: &str, a: &str| xf.and_then(|x| d.child(x, n)).and_then(|c| emu(d, c, a)).unwrap_or(0.0);
        let (ox, oy, ow, oh) = (get(d, "a:off", "x"), get(d, "a:off", "y"), get(d, "a:ext", "cx"), get(d, "a:ext", "cy"));
        let (cx, cy, cw, ch) = (get(d, "a:chOff", "x"), get(d, "a:chOff", "y"), get(d, "a:chExt", "cx"), get(d, "a:chExt", "cy"));
        let sx = if cw > 0.0 { ow / cw } else { 1.0 };
        let sy = if ch > 0.0 { oh / ch } else { 1.0 };
        let parent = d.parent(g).ok_or("no parent")?;
        let mut at = d.index_in_parent(g).unwrap_or(0);
        let mut out = Vec::new();
        for c in d.elements(g).collect::<Vec<_>>() {
            if !matches!(d.name(c), "p:sp" | "p:pic" | "p:graphicFrame" | "p:cxnSp" | "p:grpSp" | "mc:AlternateContent") {
                continue;
            }
            if let Some(x) = xfrm_of(d, c) {
                if let (Some(off), Some(ext)) = (d.child(x, "a:off"), d.child(x, "a:ext")) {
                    let nx = ox + (emu(d, off, "x").unwrap_or(0.0) - cx) * sx;
                    let ny = oy + (emu(d, off, "y").unwrap_or(0.0) - cy) * sy;
                    let nw = emu(d, ext, "cx").unwrap_or(0.0) * sx;
                    let nh = emu(d, ext, "cy").unwrap_or(0.0) * sy;
                    d.set_attr(off, "x", &format!("{}", nx.round() as i64));
                    d.set_attr(off, "y", &format!("{}", ny.round() as i64));
                    d.set_attr(ext, "cx", &format!("{}", nw.round() as i64));
                    d.set_attr(ext, "cy", &format!("{}", nh.round() as i64));
                }
            }
            out.push(scene::shape_id(d, c).0);
            d.detach(c);
            at += 1;
            d.insert(parent, at, c);
        }
        d.detach(g);
        self.commit();
        Ok(out)
    }

    // ------------------------------------------------------------ text
    /// The txBody of a shape, made if it has none.
    fn body_of(&mut self, part: &str, id: u32, make: bool) -> Result<NodeId, String> {
        let n = self.find_shape(part, id).ok_or("no such shape")?;
        let d = self.pkg.xml_mut(part).map_err(|e| e.to_string())?;
        if let Some(tb) = d.child(n, "p:txBody") {
            return Ok(tb);
        }
        if !make || !matches!(d.name(n), "p:sp") {
            return Err("this object has no text".into());
        }
        let tb = fragment(d, r#"<p:txBody><a:bodyPr rtlCol="0" anchor="ctr"/><a:lstStyle/><a:p><a:pPr algn="ctr"/><a:endParaRPr lang="en-US"/></a:p></p:txBody>"#).unwrap();
        d.append(n, tb);
        Ok(tb)
    }

    pub fn paragraphs(&mut self, i: usize, id: u32) -> Vec<String> {
        let Ok(part) = self.slide_part(i) else { return Vec::new() };
        let Some(n) = self.find_shape(&part, id) else { return Vec::new() };
        let Ok(d) = self.pkg.xml(&part) else { return Vec::new() };
        match d.child(n, "p:txBody") {
            Some(tb) => crate::text::plain_text(d, tb),
            None => Vec::new(),
        }
    }

    /// Type `text` at (para, off). Newlines start new paragraphs; '\u{b}' is a line break.
    pub fn insert_text(&mut self, i: usize, id: u32, para: usize, off: usize, text: &str, label: &str) -> Result<(usize, usize), String> {
        let part = self.slide_part(i)?;
        self.begin(label, &[part.clone()]);
        let tb = self.body_of(&part, id, true)?;
        let d = self.pkg.xml_mut(&part).map_err(|e| e.to_string())?;
        let mut pos = (para, off);
        for (k, chunk) in text.split('\n').enumerate() {
            if k > 0 {
                pos = split_para(d, tb, pos.0, pos.1);
            }
            for (j, piece) in chunk.split('\u{b}').enumerate() {
                if j > 0 {
                    pos = insert_break(d, tb, pos.0, pos.1);
                }
                if !piece.is_empty() {
                    pos = insert_in_para(d, tb, pos.0, pos.1, piece);
                }
            }
        }
        self.commit();
        Ok(pos)
    }

    pub fn delete_text(&mut self, i: usize, id: u32, a: (usize, usize), b: (usize, usize), label: &str) -> Result<(usize, usize), String> {
        let part = self.slide_part(i)?;
        let (a, b) = if a <= b { (a, b) } else { (b, a) };
        if a == b {
            return Ok(a);
        }
        self.begin(label, &[part.clone()]);
        let tb = self.body_of(&part, id, false)?;
        let d = self.pkg.xml_mut(&part).map_err(|e| e.to_string())?;
        delete_range(d, tb, a, b);
        self.commit();
        Ok(a)
    }

    /// Replace all text of a shape.
    pub fn set_text(&mut self, i: usize, id: u32, text: &str) -> Result<(), String> {
        let paras = self.paragraphs(i, id);
        let last = paras.len().saturating_sub(1);
        let end = (last, paras.last().map(|s| char_len(s)).unwrap_or(0));
        let part = self.slide_part(i)?;
        self.begin("Typing", &[part.clone()]);
        let tb = self.body_of(&part, id, true)?;
        let d = self.pkg.xml_mut(&part).map_err(|e| e.to_string())?;
        delete_range(d, tb, (0, 0), end);
        let mut pos = (0, 0);
        for (k, chunk) in text.split('\n').enumerate() {
            if k > 0 {
                pos = split_para(d, tb, pos.0, pos.1);
            }
            if !chunk.is_empty() {
                pos = insert_in_para(d, tb, pos.0, pos.1, chunk);
            }
        }
        self.commit();
        Ok(())
    }

    /// Run formatting over a range (empty range: the whole shape's text when `whole`).
    /// keys: b, i, u, strike, sz (points), baseline (percent), cap, color (RRGGBB or ""), font, highlight, spc.
    pub fn format_runs(&mut self, i: usize, id: u32, a: (usize, usize), b: (usize, usize), key: &str, value: &str) -> Result<(), String> {
        let part = self.slide_part(i)?;
        self.begin(&format_label(key), &[part.clone()]);
        let tb = self.body_of(&part, id, false)?;
        let d = self.pkg.xml_mut(&part).map_err(|e| e.to_string())?;
        let (a, b) = if a <= b { (a, b) } else { (b, a) };
        let paras: Vec<NodeId> = d.children_named(tb, "a:p").collect();
        for (pi, p) in paras.iter().enumerate() {
            if pi < a.0 || pi > b.0 {
                continue;
            }
            let plen = para_len(d, *p);
            let s = if pi == a.0 { a.1 } else { 0 };
            let e = if pi == b.0 { b.1 } else { plen };
            let whole_para = s == 0 && e >= plen;
            if s < e {
                split_runs_at(d, *p, e);
                split_runs_at(d, *p, s);
                let mut at = 0;
                for c in d.elements(*p).collect::<Vec<_>>() {
                    let l = piece_len(d, c);
                    if matches!(d.name(c), "a:r" | "a:fld") && at >= s && at + l <= e && l > 0 {
                        let rpr = ensure_rpr(d, c);
                        set_rpr(d, rpr, key, value);
                    }
                    at += l;
                }
            }
            if whole_para || plen == 0 || (a == b) {
                let e = ensure_end_rpr(d, *p);
                set_rpr(d, e, key, value);
            }
        }
        self.commit();
        Ok(())
    }

    /// Paragraph formatting for paragraphs p0..=p1.
    /// keys: algn, lvl, marL, indent (points), bullet ("none", "char:•", "auto:arabicPeriod", "" = inherit),
    /// lnSpc (multiple, e.g. 1.5), spcBef / spcAft (points), anchor (shape), numCol (shape).
    pub fn format_paras(&mut self, i: usize, id: u32, p0: usize, p1: usize, key: &str, value: &str) -> Result<(), String> {
        let part = self.slide_part(i)?;
        self.begin(&format_label(key), &[part.clone()]);
        let tb = self.body_of(&part, id, true)?;
        let d = self.pkg.xml_mut(&part).map_err(|e| e.to_string())?;
        if matches!(key, "anchor" | "numCol" | "wrap" | "vert" | "autofit") {
            let bp = match d.child(tb, "a:bodyPr") {
                Some(b) => b,
                None => {
                    let b = d.new_element("a:bodyPr", &[]);
                    d.insert(tb, 0, b);
                    b
                }
            };
            if key == "autofit" {
                for c in d.elements(bp).collect::<Vec<_>>() {
                    if matches!(d.name(c), "a:normAutofit" | "a:spAutoFit" | "a:noAutofit") {
                        d.detach(c);
                    }
                }
                let name = match value { "shrink" => "a:normAutofit", "resize" => "a:spAutoFit", _ => "a:noAutofit" };
                let el = d.new_element(name, &[]);
                d.insert(bp, 0, el);
            } else if value.is_empty() {
                d.remove_attr(bp, key);
            } else {
                d.set_attr(bp, key, value);
            }
            self.commit();
            return Ok(());
        }
        let paras: Vec<NodeId> = d.children_named(tb, "a:p").collect();
        for (pi, p) in paras.iter().enumerate() {
            if pi < p0 || pi > p1 {
                continue;
            }
            let ppr = ensure_ppr(d, *p);
            match key {
                "algn" | "lvl" => {
                    if value.is_empty() || (key == "lvl" && value == "0") {
                        d.remove_attr(ppr, key);
                    } else {
                        d.set_attr(ppr, key, value);
                    }
                }
                "marL" | "indent" => {
                    let v: f64 = value.parse().unwrap_or(0.0);
                    d.set_attr(ppr, key, &emu_s(v));
                }
                "bullet" => {
                    for c in d.elements(ppr).collect::<Vec<_>>() {
                        if matches!(d.name(c), "a:buNone" | "a:buChar" | "a:buAutoNum" | "a:buBlip" | "a:buFont" | "a:buFontTx") {
                            d.detach(c);
                        }
                    }
                    let el = if value == "none" {
                        Some(d.new_element("a:buNone", &[]))
                    } else if let Some(ch) = value.strip_prefix("char:") {
                        let (font, ch) = match ch.split_once('|') { Some((c, f)) => (Some(f.to_string()), c.to_string()), None => (None, ch.to_string()) };
                        if let Some(f) = font {
                            let fe = d.new_element("a:buFont", &[("typeface", &f)]);
                            insert_bullet_child(d, ppr, fe);
                        }
                        Some(d.new_element("a:buChar", &[("char", &ch)]))
                    } else if let Some(t) = value.strip_prefix("auto:") {
                        let (t, start) = t.split_once('@').map(|(a, b)| (a.to_string(), Some(b.to_string()))).unwrap_or((t.to_string(), None));
                        let el = d.new_element("a:buAutoNum", &[("type", &t)]);
                        if let Some(s) = start.filter(|s| s != "1") {
                            d.set_attr(el, "startAt", &s);
                        }
                        Some(el)
                    } else {
                        None
                    };
                    if let Some(el) = el {
                        insert_bullet_child(d, ppr, el);
                    }
                }
                "lnSpc" | "spcBef" | "spcAft" => {
                    let name = format!("a:{key}");
                    if let Some(c) = d.child(ppr, &name) {
                        d.detach(c);
                    }
                    if !value.is_empty() {
                        let inner = if key == "lnSpc" {
                            let v: f64 = value.parse().unwrap_or(1.0);
                            format!(r#"<a:spcPct val="{}"/>"#, (v * 100000.0).round() as i64)
                        } else {
                            let v: f64 = value.parse().unwrap_or(0.0);
                            format!(r#"<a:spcPts val="{}"/>"#, (v * 100.0).round() as i64)
                        };
                        let el = fragment(d, &format!("<{name}>{inner}</{name}>")).unwrap();
                        // a:lnSpc, a:spcBef, a:spcAft come first, in that order
                        let order = ["a:lnSpc", "a:spcBef", "a:spcAft"];
                        let mine = order.iter().position(|o| *o == name).unwrap();
                        let at = d.children(ppr).iter().position(|&c| {
                            let nm = d.name(c);
                            !order[..mine].contains(&nm)
                        }).unwrap_or(d.children(ppr).len());
                        d.insert(ppr, at, el);
                    }
                }
                _ => {}
            }
        }
        self.commit();
        Ok(())
    }

    /// The run properties at a position (what the ribbon shows).
    pub fn run_props_at(&mut self, i: usize, id: u32, para: usize, off: usize) -> Option<crate::scene::RunP> {
        let part = self.slide_part(i).ok()?;
        let ctx = scene::context(self, &part);
        let n = self.find_shape(&part, id)?;
        let levels = scene::text_levels(self, &ctx, &part, n);
        let d = self.pkg.xml(&part).ok()?;
        let tb = d.child(n, "p:txBody")?;
        let paras = crate::text::read_paras(d, tb, &levels, &ctx.scheme, &crate::text::Env::default());
        let p = paras.get(para)?;
        let mut at = 0;
        let mut last = None;
        for pc in &p.pieces {
            let l = char_len(&pc.text);
            if off > at && off <= at + l || (off == 0 && at == 0 && l > 0) {
                let mut r = pc.props.clone();
                if r.latin.is_none() {
                    r.latin = Some(ctx.minor.clone());
                } else if let Some(f) = r.latin.clone() {
                    r.latin = Some(ctx.font(&f));
                }
                return Some(r);
            }
            at += l;
            last = Some(pc.props.clone());
        }
        let mut r = last.unwrap_or_else(|| p.end.clone());
        r.latin = Some(ctx.font(r.latin.as_deref().unwrap_or("+mn-lt")));
        Some(r)
    }
}

fn format_label(key: &str) -> String {
    match key {
        "b" => "Bold",
        "i" => "Italic",
        "u" => "Underline",
        "strike" => "Strikethrough",
        "sz" => "Font Size",
        "font" => "Font",
        "color" => "Font Color",
        "highlight" => "Highlight",
        "algn" => "Align",
        "bullet" => "Bullets",
        "lvl" => "Indent",
        "lnSpc" => "Line Spacing",
        _ => "Format",
    }
    .to_string()
}

fn esc_text(s: &str) -> String {
    let mut o = String::new();
    folio_core::xml::escape_text(s, &mut o);
    o
}

pub fn nice_shape_name(prst: &str) -> String {
    match prst {
        "rect" => "Rectangle".into(),
        "roundRect" => "Rectangle: Rounded Corners".into(),
        "ellipse" => "Oval".into(),
        "triangle" => "Isosceles Triangle".into(),
        "rightArrow" => "Arrow: Right".into(),
        "line" | "straightConnector1" => "Straight Connector".into(),
        p => {
            let mut s = String::new();
            for (i, c) in p.chars().enumerate() {
                if i == 0 {
                    s.extend(c.to_uppercase());
                } else if c.is_uppercase() {
                    s.push(' ');
                    s.push(c);
                } else {
                    s.push(c);
                }
            }
            s
        }
    }
}

pub fn next_shape_id(d: &XmlDoc) -> u32 {
    let mut max = 1;
    fn walk(d: &XmlDoc, n: NodeId, max: &mut u32) {
        for c in d.elements(n) {
            if d.name(c) == "p:cNvPr" {
                if let Some(v) = d.attr(c, "id").and_then(|v| v.parse::<u32>().ok()) {
                    *max = (*max).max(v);
                }
            }
            walk(d, c, max);
        }
    }
    walk(d, d.root, &mut max);
    max + 1
}

fn renumber(d: &mut XmlDoc, n: NodeId, next: &mut u32, out: &mut Vec<u32>) {
    let mut stack = vec![n];
    let mut first = true;
    while let Some(c) = stack.pop() {
        if d.name(c) == "p:cNvPr" {
            d.set_attr(c, "id", &next.to_string());
            if first {
                out.push(*next);
                first = false;
            }
            *next += 1;
        }
        let kids: Vec<NodeId> = d.elements(c).collect();
        for k in kids.into_iter().rev() {
            stack.push(k);
        }
    }
}

fn xfrm_of(d: &XmlDoc, n: NodeId) -> Option<NodeId> {
    match d.name(n) {
        "p:graphicFrame" => d.child(n, "p:xfrm"),
        "p:grpSp" => path(d, n, &["p:grpSpPr", "a:xfrm"]),
        _ => path(d, n, &["p:spPr", "a:xfrm"]),
    }
}

/// The shape's xfrm, made (empty, 0 size) if missing.
fn ensure_xfrm(d: &mut XmlDoc, n: NodeId) -> NodeId {
    if let Some(x) = xfrm_of(d, n) {
        if d.child(x, "a:off").is_none() {
            let o = d.new_element("a:off", &[("x", "0"), ("y", "0")]);
            d.insert(x, 0, o);
        }
        if d.child(x, "a:ext").is_none() {
            let e = d.new_element("a:ext", &[("cx", "0"), ("cy", "0")]);
            let at = d.index_in_parent(d.child(x, "a:off").unwrap()).map(|i| i + 1).unwrap_or(0);
            d.insert(x, at, e);
        }
        return x;
    }
    let (holder_name, xf_name) = match d.name(n) {
        "p:graphicFrame" => ("", "p:xfrm"),
        "p:grpSp" => ("p:grpSpPr", "a:xfrm"),
        _ => ("p:spPr", "a:xfrm"),
    };
    let holder = if holder_name.is_empty() {
        n
    } else {
        match d.child(n, holder_name) {
            Some(h) => h,
            None => {
                let h = d.new_element(holder_name, &[]);
                let at = d.elements(n).position(|c| d.name(c).starts_with("p:nv")).map(|i| i + 1).unwrap_or(0);
                d.insert(n, at, h);
                h
            }
        }
    };
    let x = fragment(d, &format!(r#"<{xf_name}><a:off x="0" y="0"/><a:ext cx="0" cy="0"/></{xf_name}>"#)).unwrap();
    if holder == n {
        let at = d.elements(n).position(|c| d.name(c).starts_with("p:nv")).map(|i| i + 1).unwrap_or(0);
        d.insert(n, at, x);
    } else {
        d.insert(holder, 0, x);
    }
    x
}

fn piece_len(d: &XmlDoc, c: NodeId) -> usize {
    match d.name(c) {
        "a:r" | "a:fld" => d.child(c, "a:t").map(|t| char_len(&d.text(t))).unwrap_or(0),
        "a:br" => 1,
        _ => 0,
    }
}

fn para_len(d: &XmlDoc, p: NodeId) -> usize {
    d.elements(p).map(|c| piece_len(d, c)).sum()
}

fn ensure_rpr(d: &mut XmlDoc, r: NodeId) -> NodeId {
    if let Some(x) = d.child(r, "a:rPr") {
        return x;
    }
    let x = d.new_element("a:rPr", &[("lang", "en-US"), ("dirty", "0")]);
    d.insert(r, 0, x);
    x
}

fn ensure_end_rpr(d: &mut XmlDoc, p: NodeId) -> NodeId {
    if let Some(x) = d.child(p, "a:endParaRPr") {
        return x;
    }
    let x = d.new_element("a:endParaRPr", &[("lang", "en-US"), ("dirty", "0")]);
    d.append(p, x);
    x
}

fn ensure_ppr(d: &mut XmlDoc, p: NodeId) -> NodeId {
    if let Some(x) = d.child(p, "a:pPr") {
        return x;
    }
    let x = d.new_element("a:pPr", &[]);
    d.insert(p, 0, x);
    x
}

/// Bullet elements go after the spacing and before tabs/defRPr.
fn insert_bullet_child(d: &mut XmlDoc, ppr: NodeId, el: NodeId) {
    let order = ["a:lnSpc", "a:spcBef", "a:spcAft", "a:buClrTx", "a:buClr", "a:buSzTx", "a:buSzPct", "a:buSzPts", "a:buFontTx", "a:buFont"];
    let at = d.children(ppr).iter().position(|&c| !order.contains(&d.name(c))).unwrap_or(d.children(ppr).len());
    d.insert(ppr, at, el);
}

/// rPr children in schema order.
const RPR_ORDER: [&str; 11] = ["a:ln", "a:noFill", "a:solidFill", "a:gradFill", "a:blipFill", "a:pattFill", "a:grpFill",
                               "a:effectLst", "a:highlight", "a:latin", "a:ea"];

fn put_rpr_child(d: &mut XmlDoc, rpr: NodeId, el: NodeId) {
    let name = d.name(el).to_string();
    let rank = |n: &str| RPR_ORDER.iter().position(|o| *o == n).unwrap_or(99);
    let mine = rank(&name);
    let at = d.children(rpr).iter().position(|&c| rank(d.name(c)) > mine).unwrap_or(d.children(rpr).len());
    d.insert(rpr, at, el);
}

fn set_rpr(d: &mut XmlDoc, rpr: NodeId, key: &str, value: &str) {
    match key {
        "b" | "i" => {
            if value.is_empty() { d.remove_attr(rpr, key); } else { d.set_attr(rpr, key, if value == "1" || value == "true" { "1" } else { "0" }); }
        }
        "u" => {
            if value.is_empty() { d.remove_attr(rpr, "u"); } else { d.set_attr(rpr, "u", value); }
        }
        "strike" => {
            if value.is_empty() { d.remove_attr(rpr, "strike"); } else { d.set_attr(rpr, "strike", value); }
        }
        "sz" => {
            match value.parse::<f64>() {
                Ok(v) => d.set_attr(rpr, "sz", &format!("{}", (v * 100.0).round() as i64)),
                Err(_) => { d.remove_attr(rpr, "sz"); }
            }
        }
        "baseline" => {
            match value.parse::<f64>() {
                Ok(v) if v != 0.0 => d.set_attr(rpr, "baseline", &format!("{}", (v * 1000.0).round() as i64)),
                _ => { d.remove_attr(rpr, "baseline"); }
            }
        }
        "cap" => {
            if value.is_empty() || value == "none" { d.remove_attr(rpr, "cap"); } else { d.set_attr(rpr, "cap", value); }
        }
        "spc" => {
            match value.parse::<f64>() {
                Ok(v) if v != 0.0 => d.set_attr(rpr, "spc", &format!("{}", (v * 100.0).round() as i64)),
                _ => { d.remove_attr(rpr, "spc"); }
            }
        }
        "color" | "highlight" => {
            let names: &[&str] = if key == "color" { &["a:solidFill", "a:noFill", "a:gradFill", "a:pattFill", "a:blipFill", "a:grpFill"] } else { &["a:highlight"] };
            for c in d.elements(rpr).collect::<Vec<_>>() {
                if names.contains(&d.name(c)) {
                    d.detach(c);
                }
            }
            if !value.is_empty() {
                let inner = if let Some(s) = value.strip_prefix("scheme:") {
                    format!(r#"<a:schemeClr val="{s}"/>"#)
                } else {
                    format!(r#"<a:srgbClr val="{}"/>"#, value.trim_start_matches('#').to_uppercase())
                };
                let el_name = if key == "color" { "a:solidFill" } else { "a:highlight" };
                let el = fragment(d, &format!("<{el_name}>{inner}</{el_name}>")).unwrap();
                put_rpr_child(d, rpr, el);
            }
        }
        "clear" => {
            let keep: Vec<(String, String)> = ["lang", "altLang", "dirty", "err", "noProof"].iter()
                .filter_map(|k| d.attr(rpr, k).map(|v| (k.to_string(), v.to_string()))).collect();
            let attrs: Vec<String> = match &d.node(rpr).kind { folio_core::xml::Kind::Element { attrs, .. } => attrs.iter().map(|a| a.0.clone()).collect(), _ => Vec::new() };
            for a in attrs {
                if !keep.iter().any(|(k, _)| *k == a) {
                    d.remove_attr(rpr, &a);
                }
            }
            for c in d.elements(rpr).collect::<Vec<_>>() {
                if d.name(c) != "a:hlinkClick" && d.name(c) != "a:extLst" {
                    d.detach(c);
                }
            }
        }
        "shadow" => {
            if let Some(e) = d.child(rpr, "a:effectLst") {
                d.detach(e);
            }
            if value == "1" {
                let el = fragment(d, r#"<a:effectLst><a:outerShdw blurRad="38100" dist="38100" dir="2700000" algn="tl"><a:srgbClr val="000000"><a:alpha val="43137"/></a:srgbClr></a:outerShdw></a:effectLst>"#).unwrap();
                put_rpr_child(d, rpr, el);
            }
        }
        "font" => {
            for c in d.elements(rpr).collect::<Vec<_>>() {
                if matches!(d.name(c), "a:latin" | "a:ea" | "a:cs") {
                    d.detach(c);
                }
            }
            if !value.is_empty() {
                let el = d.new_element("a:latin", &[("typeface", value)]);
                put_rpr_child(d, rpr, el);
                let cs = d.new_element("a:cs", &[("typeface", value)]);
                let at = d.index_in_parent(el).unwrap() + 1;
                d.insert(rpr, at, cs);
            }
        }
        _ => {}
    }
}

/// Split the run that straddles char offset `off` of paragraph `p`.
fn split_runs_at(d: &mut XmlDoc, p: NodeId, off: usize) {
    let mut at = 0;
    for c in d.elements(p).collect::<Vec<_>>() {
        let l = piece_len(d, c);
        if d.name(c) == "a:r" && off > at && off < at + l {
            let t = d.child(c, "a:t").unwrap();
            let (a, b) = split_at_char(&d.text(t), off - at);
            let copy = d.clone_node(c);
            set_t(d, t, &a);
            let t2 = d.child(copy, "a:t").unwrap();
            set_t(d, t2, &b);
            let i = d.index_in_parent(c).unwrap();
            d.insert(p, i + 1, copy);
            return;
        }
        at += l;
    }
}

fn nth_para(d: &XmlDoc, tb: NodeId, k: usize) -> Option<NodeId> {
    d.children_named(tb, "a:p").nth(k)
}

/// Insert plain text (no newlines) into a paragraph; returns the position after it.
fn insert_in_para(d: &mut XmlDoc, tb: NodeId, para: usize, off: usize, s: &str) -> (usize, usize) {
    let p = match nth_para(d, tb, para) {
        Some(p) => p,
        None => {
            let p = fragment(d, r#"<a:p><a:endParaRPr lang="en-US"/></a:p>"#).unwrap();
            d.append(tb, p);
            p
        }
    };
    let n = char_len(s);
    let mut at = 0;
    let kids: Vec<NodeId> = d.elements(p).collect();
    // the run the caret is in (at a boundary: the run before it)
    let mut target: Option<(NodeId, usize)> = None;
    let mut before_idx: Option<usize> = None;
    for (k, c) in kids.iter().enumerate() {
        let l = piece_len(d, *c);
        let is_run = d.name(*c) == "a:r";
        if is_run && off >= at && off <= at + l && (off > at || l == 0 || target.is_none()) {
            if off > at || target.is_none() {
                target = Some((*c, off - at));
            }
            if off < at + l {
                break;
            }
        }
        if off <= at && before_idx.is_none() && l > 0 {
            before_idx = Some(k);
        }
        at += l;
    }
    if let Some((r, k)) = target {
        let t = match d.child(r, "a:t") {
            Some(t) => t,
            None => {
                let t = d.new_element("a:t", &[]);
                d.append(r, t);
                t
            }
        };
        let (a, b) = split_at_char(&d.text(t), k);
        set_t(d, t, &format!("{a}{s}{b}"));
        return (para, off + n);
    }
    // no run here: a new one with the paragraph mark's (or the next run's) formatting
    let rpr_src = d.child(p, "a:endParaRPr");
    let r = d.new_element("a:r", &[]);
    if let Some(e) = rpr_src {
        let c = d.clone_node(e);
        d.rename(c, "a:rPr");
        d.append(r, c);
    } else {
        let c = d.new_element("a:rPr", &[("lang", "en-US"), ("dirty", "0")]);
        d.append(r, c);
    }
    let t = d.new_element("a:t", &[]);
    let tx = d.new_text(s);
    d.append(t, tx);
    d.append(r, t);
    let idx = match before_idx {
        Some(k) => d.index_in_parent(kids[k]).unwrap(),
        None => {
            // before endParaRPr
            match d.child(p, "a:endParaRPr") {
                Some(e) => d.index_in_parent(e).unwrap(),
                None => d.children(p).len(),
            }
        }
    };
    let idx = if before_idx.is_none() { idx } else { idx };
    // never before the pPr
    let min = d.child(p, "a:pPr").and_then(|x| d.index_in_parent(x)).map(|i| i + 1).unwrap_or(0);
    d.insert(p, idx.max(min), r);
    (para, off + n)
}

fn insert_break(d: &mut XmlDoc, tb: NodeId, para: usize, off: usize) -> (usize, usize) {
    let Some(p) = nth_para(d, tb, para) else { return (para, off) };
    split_runs_at(d, p, off);
    let mut at = 0;
    let mut idx = None;
    for c in d.elements(p).collect::<Vec<_>>() {
        if at >= off && piece_len(d, c) > 0 {
            idx = d.index_in_parent(c);
            break;
        }
        at += piece_len(d, c);
    }
    let br = fragment(d, r#"<a:br><a:rPr lang="en-US" dirty="0"/></a:br>"#).unwrap();
    let idx = idx.unwrap_or_else(|| d.child(p, "a:endParaRPr").and_then(|e| d.index_in_parent(e)).unwrap_or(d.children(p).len()));
    let min = d.child(p, "a:pPr").and_then(|x| d.index_in_parent(x)).map(|i| i + 1).unwrap_or(0);
    d.insert(p, idx.max(min), br);
    (para, off + 1)
}

/// Split paragraph `para` at `off`: the rest moves to a new paragraph with the same pPr.
fn split_para(d: &mut XmlDoc, tb: NodeId, para: usize, off: usize) -> (usize, usize) {
    let Some(p) = nth_para(d, tb, para) else { return (para, off) };
    split_runs_at(d, p, off);
    let np = d.new_element("a:p", &[]);
    if let Some(ppr) = d.child(p, "a:pPr") {
        let c = d.clone_node(ppr);
        d.append(np, c);
    }
    let mut at = 0;
    let mut moving = Vec::new();
    // the formatting the new paragraph's mark takes: the run before the split
    let mut last_rpr: Option<NodeId> = None;
    for c in d.elements(p).collect::<Vec<_>>() {
        let nm = d.name(c).to_string();
        if nm == "a:pPr" {
            continue;
        }
        if nm == "a:endParaRPr" {
            continue;
        }
        let l = piece_len(d, c);
        if at >= off {
            moving.push(c);
        } else if nm == "a:r" {
            last_rpr = d.child(c, "a:rPr");
        }
        at += l;
    }
    for c in moving {
        d.detach(c);
        d.append(np, c);
    }
    // both paragraphs keep a paragraph mark
    if let Some(e) = d.child(p, "a:endParaRPr") {
        let c = d.clone_node(e);
        d.detach(e);
        d.append(np, c);
        if let Some(r) = last_rpr {
            let m = d.clone_node(r);
            d.rename(m, "a:endParaRPr");
            d.append(p, m);
        } else {
            d.append(p, e);
        }
    } else if let Some(r) = last_rpr {
        let m = d.clone_node(r);
        d.rename(m, "a:endParaRPr");
        d.append(np, m);
    }
    let i = d.index_in_parent(p).unwrap();
    d.insert(tb, i + 1, np);
    (para + 1, 0)
}

fn delete_range(d: &mut XmlDoc, tb: NodeId, a: (usize, usize), b: (usize, usize)) {
    let paras: Vec<NodeId> = d.children_named(tb, "a:p").collect();
    if a.0 >= paras.len() {
        return;
    }
    let bp = b.0.min(paras.len() - 1);
    for (pi, p) in paras.iter().enumerate() {
        if pi < a.0 || pi > bp {
            continue;
        }
        let plen = para_len(d, *p);
        let s = if pi == a.0 { a.1 } else { 0 };
        let e = if pi == bp { b.1.min(plen) } else { plen };
        if s >= e {
            continue;
        }
        split_runs_at(d, *p, e);
        split_runs_at(d, *p, s);
        let mut at = 0;
        for c in d.elements(*p).collect::<Vec<_>>() {
            let l = piece_len(d, c);
            if l > 0 && at >= s && at + l <= e {
                // keep the formatting of the paragraph's last run for its mark
                if d.name(c) == "a:r" && s == 0 && e >= plen && d.child(*p, "a:endParaRPr").is_none() {
                    if let Some(r) = d.child(c, "a:rPr") {
                        let m = d.clone_node(r);
                        d.rename(m, "a:endParaRPr");
                        d.append(*p, m);
                    }
                }
                d.detach(c);
            }
            at += l;
        }
    }
    // join the paragraphs a..=b
    if bp > a.0 {
        let first = paras[a.0];
        let first_end = d.child(first, "a:endParaRPr");
        for p in &paras[a.0 + 1..=bp] {
            let kids: Vec<NodeId> = d.elements(*p).filter(|&c| d.name(c) != "a:pPr").collect();
            for c in kids {
                d.detach(c);
                if d.name(c) == "a:endParaRPr" {
                    if let Some(fe) = first_end {
                        d.detach(fe);
                    }
                    d.append(first, c);
                } else {
                    let at = d.child(first, "a:endParaRPr").and_then(|e| d.index_in_parent(e)).unwrap_or(d.children(first).len());
                    d.insert(first, at, c);
                }
            }
            d.detach(*p);
        }
    }
    // empty runs left behind
    if let Some(p) = nth_para(d, tb, a.0) {
        for c in d.elements(p).collect::<Vec<_>>() {
            if d.name(c) == "a:r" && piece_len(d, c) == 0 && para_len(d, p) > 0 {
                d.detach(c);
            }
        }
    }
}

const CT_NOTES_MASTER: &str = "application/vnd.openxmlformats-officedocument.presentationml.notesMaster+xml";
const CT_THEME: &str = "application/vnd.openxmlformats-officedocument.theme+xml";

impl Deck {
    pub fn notes_master(&mut self) -> Option<String> {
        let pres = self.pres.clone();
        self.pkg.related(&pres, "/notesMaster")
    }

    /// A notes master (with its own copy of the first theme) when the file has none.
    fn ensure_notes_master(&mut self) -> Result<String, String> {
        if let Some(m) = self.notes_master() {
            return Ok(m);
        }
        let part = self.free_name("ppt/notesMasters", "notesMaster", "xml");
        let theme = self.free_name("ppt/theme", "theme", "xml");
        let src_theme = self.masters().first().cloned().and_then(|m| self.theme_of(&m));
        let tb = src_theme.and_then(|t| self.pkg.bytes(&t)).ok_or("no theme to copy")?;
        self.touch(&[part.clone(), Package::rels_name(&part), theme.clone()]);
        self.pkg.put_raw(&theme, tb);
        self.pkg.set_content_type(&theme, CT_THEME);
        let (cx, cy) = (6858000i64, 9144000i64);
        let xml = format!(r#"<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:notesMaster {NS_DECL}><p:cSld><p:bg><p:bgRef idx="1001"><a:schemeClr val="bg1"/></p:bgRef></p:bg><p:spTree><p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr><p:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/><a:chOff x="0" y="0"/><a:chExt cx="0" cy="0"/></a:xfrm></p:grpSpPr><p:sp><p:nvSpPr><p:cNvPr id="2" name="Slide Image Placeholder 1"/><p:cNvSpPr><a:spLocks noGrp="1" noRot="1" noChangeAspect="1"/></p:cNvSpPr><p:nvPr><p:ph type="sldImg" idx="2"/></p:nvPr></p:nvSpPr><p:spPr><a:xfrm><a:off x="685800" y="1143000"/><a:ext cx="5486400" cy="3086100"/></a:xfrm><a:prstGeom prst="rect"><a:avLst/></a:prstGeom><a:noFill/><a:ln w="12700"><a:solidFill><a:prstClr val="black"/></a:solidFill></a:ln></p:spPr></p:sp><p:sp><p:nvSpPr><p:cNvPr id="3" name="Notes Placeholder 2"/><p:cNvSpPr><a:spLocks noGrp="1"/></p:cNvSpPr><p:nvPr><p:ph type="body" sz="quarter" idx="3"/></p:nvPr></p:nvSpPr><p:spPr><a:xfrm><a:off x="685800" y="4400550"/><a:ext cx="5486400" cy="3600450"/></a:xfrm><a:prstGeom prst="rect"><a:avLst/></a:prstGeom></p:spPr><p:txBody><a:bodyPr vert="horz" lIns="91440" tIns="45720" rIns="91440" bIns="45720" rtlCol="0"/><a:lstStyle/><a:p><a:pPr lvl="0"/><a:r><a:rPr lang="en-US"/><a:t>Click to edit Master text styles</a:t></a:r></a:p></p:txBody></p:sp></p:spTree></p:cSld><p:clrMap bg1="lt1" tx1="dk1" bg2="lt2" tx2="dk2" accent1="accent1" accent2="accent2" accent3="accent3" accent4="accent4" accent5="accent5" accent6="accent6" hlink="hlink" folHlink="folHlink"/><p:notesStyle><a:lvl1pPr marL="0" algn="l" defTabSz="914400" rtl="0" eaLnBrk="1" latinLnBrk="0" hangingPunct="1"><a:defRPr sz="1200" kern="1200"><a:solidFill><a:schemeClr val="tx1"/></a:solidFill><a:latin typeface="+mn-lt"/><a:ea typeface="+mn-ea"/><a:cs typeface="+mn-cs"/></a:defRPr></a:lvl1pPr></p:notesStyle></p:notesMaster>"#);
        let _ = (cx, cy);
        let doc = XmlDoc::parse(xml.as_bytes()).map_err(|e| e.to_string())?;
        self.pkg.put_xml(&part, doc);
        self.pkg.set_content_type(&part, CT_NOTES_MASTER);
        self.pkg.add_rel(&part, &format!("{RT}theme"), &rel_path(&part, &theme));
        let pres = self.pres.clone();
        let rid = self.pkg.add_rel(&pres, &format!("{RT}notesMaster"), &rel_path(&pres, &part));
        let d = self.pkg.xml_mut(&pres).map_err(|e| e.to_string())?;
        let root = d.root;
        let lst = d.new_element("p:notesMasterIdLst", &[]);
        let id = d.new_element("p:notesMasterId", &[("r:id", &rid)]);
        d.append(lst, id);
        let at = d.child(root, "p:sldMasterIdLst").and_then(|n| d.index_in_parent(n)).map(|i| i + 1).unwrap_or(0);
        d.insert(root, at, lst);
        if d.child(root, "p:notesSz").is_none() {
            let ns = d.new_element("p:notesSz", &[("cx", "6858000"), ("cy", "9144000")]);
            let at = d.child(root, "p:sldSz").and_then(|n| d.index_in_parent(n)).map(|i| i + 1).unwrap_or(d.children(root).len());
            d.insert(root, at, ns);
        }
        Ok(part)
    }

    /// Set the speaker notes of slide i (a notes page is made when it has none).
    pub fn set_notes(&mut self, i: usize, text: &str) -> Result<(), String> {
        let slide = self.slide_part(i)?;
        let existing = self.notes_of(&slide);
        let mut parts = vec![self.pres.clone(), Package::rels_name(&self.pres), CT.to_string(), slide.clone(), Package::rels_name(&slide)];
        let notes = match &existing {
            Some(n) => n.clone(),
            None => self.free_name("ppt/notesSlides", "notesSlide", "xml"),
        };
        parts.push(notes.clone());
        parts.push(Package::rels_name(&notes));
        self.begin("Notes", &parts);
        if existing.is_none() {
            let master = self.ensure_notes_master()?;
            let xml = format!(r#"<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:notes {NS_DECL}><p:cSld><p:spTree><p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr><p:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/><a:chOff x="0" y="0"/><a:chExt cx="0" cy="0"/></a:xfrm></p:grpSpPr><p:sp><p:nvSpPr><p:cNvPr id="2" name="Slide Image Placeholder 1"/><p:cNvSpPr><a:spLocks noGrp="1" noRot="1" noChangeAspect="1"/></p:cNvSpPr><p:nvPr><p:ph type="sldImg"/></p:nvPr></p:nvSpPr><p:spPr/></p:sp><p:sp><p:nvSpPr><p:cNvPr id="3" name="Notes Placeholder 2"/><p:cNvSpPr><a:spLocks noGrp="1"/></p:cNvSpPr><p:nvPr><p:ph type="body" idx="1"/></p:nvPr></p:nvSpPr><p:spPr/><p:txBody><a:bodyPr/><a:lstStyle/><a:p><a:endParaRPr lang="en-US" dirty="0"/></a:p></p:txBody></p:sp></p:spTree></p:cSld><p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr></p:notes>"#);
            let doc = XmlDoc::parse(xml.as_bytes()).map_err(|e| e.to_string())?;
            self.pkg.put_xml(&notes, doc);
            self.pkg.set_content_type(&notes, crate::model::CT_NOTES);
            self.pkg.add_rel(&notes, &format!("{RT}notesMaster"), &rel_path(&notes, &master));
            self.pkg.add_rel(&notes, &format!("{RT}slide"), &rel_path(&notes, &slide));
            self.pkg.add_rel(&slide, &format!("{RT}notesSlide"), &rel_path(&slide, &notes));
        }
        // the body placeholder's text
        let d = self.pkg.xml_mut(&notes).map_err(|e| e.to_string())?;
        let tree = path(d, d.root, &["p:cSld", "p:spTree"]).ok_or("notes page has no shapes")?;
        let body = d.elements(tree).find(|&n| scene::ph_of(d, n).is_some_and(|p| p.kind == "body"));
        let body = match body {
            Some(b) => b,
            None => {
                let id = next_shape_id(d);
                let n = fragment(d, &format!(r#"<p:sp><p:nvSpPr><p:cNvPr id="{id}" name="Notes Placeholder"/><p:cNvSpPr><a:spLocks noGrp="1"/></p:cNvSpPr><p:nvPr><p:ph type="body" idx="1"/></p:nvPr></p:nvSpPr><p:spPr/><p:txBody><a:bodyPr/><a:lstStyle/><a:p><a:endParaRPr lang="en-US"/></a:p></p:txBody></p:sp>"#)).unwrap();
                d.append(tree, n);
                n
            }
        };
        let tb = match d.child(body, "p:txBody") {
            Some(t) => t,
            None => {
                let t = fragment(d, r#"<p:txBody><a:bodyPr/><a:lstStyle/><a:p><a:endParaRPr lang="en-US"/></a:p></p:txBody>"#).unwrap();
                d.append(body, t);
                t
            }
        };
        for p in d.children_named(tb, "a:p").collect::<Vec<_>>() {
            d.detach(p);
        }
        for line in text.split('\n') {
            let run = if line.is_empty() { String::new() } else {
                format!(r#"<a:r><a:rPr lang="en-US" dirty="0"/><a:t>{}</a:t></a:r>"#, esc_text(line))
            };
            let p = fragment(d, &format!(r#"<a:p>{run}<a:endParaRPr lang="en-US" dirty="0"/></a:p>"#)).unwrap();
            d.append(tb, p);
        }
        self.commit();
        Ok(())
    }
}

impl Deck {
    /// Shrink-on-overflow text: the font scale and line spacing reduction PowerPoint stores.
    pub fn set_font_scale(&mut self, i: usize, id: u32, scale: f64, reduction: f64, label: &str) -> Result<(), String> {
        let part = self.slide_part(i)?;
        let n = self.find_shape(&part, id).ok_or("no such shape")?;
        self.begin(label, &[part.clone()]);
        let d = self.pkg.xml_mut(&part).map_err(|e| e.to_string())?;
        let Some(bp) = path(d, n, &["p:txBody", "a:bodyPr"]) else { self.cancel(); return Ok(()) };
        let na = match d.child(bp, "a:normAutofit") {
            Some(x) => x,
            None => {
                let x = d.new_element("a:normAutofit", &[]);
                d.insert(bp, 0, x);
                x
            }
        };
        if scale >= 0.999 {
            d.remove_attr(na, "fontScale");
        } else {
            d.set_attr(na, "fontScale", &format!("{}", (scale * 100000.0).round() as i64));
        }
        if reduction <= 0.0001 {
            d.remove_attr(na, "lnSpcReduction");
        } else {
            d.set_attr(na, "lnSpcReduction", &format!("{}", (reduction * 100000.0).round() as i64));
        }
        self.commit();
        Ok(())
    }
}

fn fill_xml(spec: &str) -> String {
    if spec == "none" {
        "<a:noFill/>".into()
    } else if let Some(s) = spec.strip_prefix("scheme:") {
        format!(r#"<a:solidFill><a:schemeClr val="{s}"/></a:solidFill>"#)
    } else {
        format!(r#"<a:solidFill><a:srgbClr val="{}"/></a:solidFill>"#, spec.trim_start_matches('#').to_uppercase())
    }
}

const FILLS: [&str; 6] = ["a:noFill", "a:solidFill", "a:gradFill", "a:blipFill", "a:pattFill", "a:grpFill"];

/// spPr children in schema order.
const SPPR_ORDER: [&str; 13] = ["a:xfrm", "a:custGeom", "a:prstGeom", "a:noFill", "a:solidFill", "a:gradFill", "a:blipFill",
                                "a:pattFill", "a:grpFill", "a:ln", "a:effectLst", "a:scene3d", "a:sp3d"];

fn put_sppr_child(d: &mut XmlDoc, sppr: NodeId, el: NodeId) {
    let rank = |n: &str| SPPR_ORDER.iter().position(|o| *o == n).unwrap_or(99);
    let mine = rank(d.name(el));
    let at = d.children(sppr).iter().position(|&c| d.text_of_node(c).is_none() && rank(d.name(c)) > mine).unwrap_or(d.children(sppr).len());
    d.insert(sppr, at, el);
}

fn sppr_of(d: &mut XmlDoc, n: NodeId) -> NodeId {
    let name = if d.name(n) == "p:grpSp" { "p:grpSpPr" } else { "p:spPr" };
    if let Some(s) = d.child(n, name) {
        return s;
    }
    let s = d.new_element(name, &[]);
    let at = d.elements(n).position(|c| d.name(c).starts_with("p:nv")).map(|i| i + 1).unwrap_or(0);
    let at = if d.name(n) == "p:pic" { d.child(n, "p:blipFill").and_then(|b| d.index_in_parent(b)).map(|i| i + 1).unwrap_or(at) } else { at };
    d.insert(n, at, s);
    s
}

impl Deck {
    pub fn set_background(&mut self, idx: &[usize], spec: &str) -> Result<(), String> {
        let parts: Vec<String> = idx.iter().filter_map(|i| self.slides.get(*i).cloned()).collect();
        self.begin("Format Background", &parts);
        for p in &parts {
            let d = self.pkg.xml_mut(p).map_err(|e| e.to_string())?;
            let csld = d.child(d.root, "p:cSld").ok_or("no cSld")?;
            if let Some(bg) = d.child(csld, "p:bg") {
                d.detach(bg);
            }
            if !spec.is_empty() {
                let bg = fragment(d, &format!("<p:bg><p:bgPr>{}<a:effectLst/></p:bgPr></p:bg>", fill_xml(spec))).unwrap();
                d.insert(csld, 0, bg);
            }
        }
        self.commit();
        Ok(())
    }

    pub fn set_shape_fill(&mut self, i: usize, ids: &[u32], spec: &str) -> Result<(), String> {
        let part = self.slide_part(i)?;
        let nodes: Vec<NodeId> = ids.iter().filter_map(|id| self.find_shape(&part, *id)).collect();
        self.begin("Shape Fill", &[part.clone()]);
        let d = self.pkg.xml_mut(&part).map_err(|e| e.to_string())?;
        for n in nodes {
            if d.name(n) == "p:graphicFrame" {
                continue;
            }
            let sp = sppr_of(d, n);
            for c in d.elements(sp).collect::<Vec<_>>() {
                if FILLS.contains(&d.name(c)) {
                    d.detach(c);
                }
            }
            let el = fragment(d, &fill_xml(spec)).unwrap();
            put_sppr_child(d, sp, el);
        }
        self.commit();
        Ok(())
    }

    /// Outline colour (None: keep), width in points, dash preset.
    pub fn set_shape_line(&mut self, i: usize, ids: &[u32], spec: Option<&str>, width: Option<f64>, dash: Option<&str>) -> Result<(), String> {
        let part = self.slide_part(i)?;
        let nodes: Vec<NodeId> = ids.iter().filter_map(|id| self.find_shape(&part, *id)).collect();
        self.begin("Shape Outline", &[part.clone()]);
        let d = self.pkg.xml_mut(&part).map_err(|e| e.to_string())?;
        for n in nodes {
            if d.name(n) == "p:graphicFrame" {
                continue;
            }
            let sp = sppr_of(d, n);
            let ln = match d.child(sp, "a:ln") {
                Some(l) => l,
                None => {
                    let l = d.new_element("a:ln", &[]);
                    put_sppr_child(d, sp, l);
                    l
                }
            };
            if let Some(w) = width {
                d.set_attr(ln, "w", &emu_s(w));
            }
            if let Some(spec) = spec {
                for c in d.elements(ln).collect::<Vec<_>>() {
                    if FILLS.contains(&d.name(c)) {
                        d.detach(c);
                    }
                }
                let el = fragment(d, &fill_xml(spec)).unwrap();
                d.insert(ln, 0, el);
            }
            if let Some(ds) = dash {
                if let Some(c) = d.child(ln, "a:prstDash") {
                    d.detach(c);
                }
                let el = d.new_element("a:prstDash", &[("val", ds)]);
                let at = d.elements(ln).position(|c| FILLS.contains(&d.name(c))).map(|k| k + 1).unwrap_or(0);
                let kids: Vec<NodeId> = d.children(ln).to_vec();
                let at = kids.iter().position(|&c| d.text_of_node(c).is_none() && !FILLS.contains(&d.name(c))).unwrap_or(kids.len()).max(at.min(kids.len()));
                d.insert(ln, at, el);
            }
        }
        self.commit();
        Ok(())
    }

    pub fn set_shape_shadow(&mut self, i: usize, ids: &[u32], on: bool) -> Result<(), String> {
        let part = self.slide_part(i)?;
        let nodes: Vec<NodeId> = ids.iter().filter_map(|id| self.find_shape(&part, *id)).collect();
        self.begin("Shape Effects", &[part.clone()]);
        let d = self.pkg.xml_mut(&part).map_err(|e| e.to_string())?;
        for n in nodes {
            let sp = sppr_of(d, n);
            if let Some(e) = d.child(sp, "a:effectLst") {
                d.detach(e);
            }
            let xml = if on {
                r#"<a:effectLst><a:outerShdw blurRad="50800" dist="38100" dir="2700000" algn="tl" rotWithShape="0"><a:prstClr val="black"><a:alpha val="40000"/></a:prstClr></a:outerShdw></a:effectLst>"#
            } else {
                "<a:effectLst/>"
            };
            let el = fragment(d, xml).unwrap();
            put_sppr_child(d, sp, el);
        }
        self.commit();
        Ok(())
    }

    fn cnvpr(&mut self, part: &str, id: u32) -> Option<(NodeId,)> {
        let n = self.find_shape(part, id)?;
        let d = self.pkg.xml(part).ok()?;
        let nv = d.elements(n).find(|&c| d.name(c).starts_with("p:nv"))?;
        Some((d.child(nv, "p:cNvPr")?,))
    }

    pub fn set_alt_text(&mut self, i: usize, id: u32, text: &str) -> Result<(), String> {
        let part = self.slide_part(i)?;
        let (c,) = self.cnvpr(&part, id).ok_or("no such shape")?;
        self.begin("Alt Text", &[part.clone()]);
        let d = self.pkg.xml_mut(&part).map_err(|e| e.to_string())?;
        if text.is_empty() { d.remove_attr(c, "descr"); } else { d.set_attr(c, "descr", text); }
        self.commit();
        Ok(())
    }

    pub fn rename_shape(&mut self, i: usize, id: u32, name: &str) -> Result<(), String> {
        let part = self.slide_part(i)?;
        let (c,) = self.cnvpr(&part, id).ok_or("no such shape")?;
        self.begin("Rename", &[part.clone()]);
        let d = self.pkg.xml_mut(&part).map_err(|e| e.to_string())?;
        d.set_attr(c, "name", name);
        self.commit();
        Ok(())
    }
}

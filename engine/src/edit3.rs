//! Links, picture cropping and comments.

use crate::edit::{cell_node, fragment, split_tid};
use crate::model::{emu, path, Deck, RT};
use folio_core::package::Package;
use folio_core::xml::{NodeId, XmlDoc};

const CT_COMMENTS: &str = "application/vnd.openxmlformats-officedocument.presentationml.comments+xml";
const CT_AUTHORS: &str = "application/vnd.openxmlformats-officedocument.presentationml.commentAuthors+xml";

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

fn esc_text(s: &str) -> String {
    let mut o = String::new();
    folio_core::xml::escape_text(s, &mut o);
    o
}

impl Deck {
    fn text_body_node(d: &XmlDoc, n: NodeId, cell: Option<usize>) -> Option<NodeId> {
        match cell {
            Some(k) => d.child(cell_node(d, n, k)?, "a:txBody"),
            None => d.child(n, "p:txBody"),
        }
    }

    fn link_rel(&mut self, part: &str, target: &str) -> Result<(String, String), String> {
        Ok(if target.is_empty() {
            (String::new(), String::new())
        } else if let Some(k) = target.strip_prefix("slide:") {
            let k: usize = k.parse().unwrap_or(0);
            let to = self.slides.get(k).cloned().ok_or("no such slide")?;
            let rid = self.pkg.add_rel(part, &format!("{RT}slide"), &rel_path(part, &to));
            (rid, "ppaction://hlinksldjump".to_string())
        } else if let Some(j) = match target { "next" => Some("nextslide"), "prev" => Some("previousslide"), "first" => Some("firstslide"), "last" => Some("lastslide"), "end" => Some("endshow"), _ => None } {
            (String::new(), format!("ppaction://hlinkshowjump?jump={j}"))
        } else {
            let rels_name = Package::rels_name(part);
            let rid = self.pkg.add_rel(part, &format!("{RT}hyperlink"), target);
            if let Ok(rd) = self.pkg.xml_mut(&rels_name) {
                let found = rd.elements(rd.root).find(|&r| rd.attr(r, "Id") == Some(rid.as_str()));
                if let Some(r) = found {
                    rd.set_attr(r, "TargetMode", "External");
                }
            }
            (rid, String::new())
        })
    }

    /// A click action on a whole shape (same targets as set_link).
    pub fn set_shape_link(&mut self, i: usize, id: u32, target: &str) -> Result<(), String> {
        let part = self.slide_part(i)?;
        let n = self.find_shape(&part, id).ok_or("no such shape")?;
        self.begin(if target.is_empty() { "Remove Link" } else { "Insert Link" }, &[part.clone(), Package::rels_name(&part)]);
        let (rid, action) = self.link_rel(&part, target)?;
        let d = self.pkg.xml_mut(&part).map_err(|e| e.to_string())?;
        let nv = d.elements(n).next().ok_or("bad shape")?;
        let c = d.child(nv, "p:cNvPr").ok_or("bad shape")?;
        if let Some(h) = d.child(c, "a:hlinkClick") {
            d.detach(h);
        }
        if !target.is_empty() {
            let mut attrs: Vec<(&str, &str)> = vec![("r:id", rid.as_str())];
            if !action.is_empty() {
                attrs.push(("action", action.as_str()));
            }
            let h = d.new_element("a:hlinkClick", &attrs);
            d.insert(c, 0, h);
        }
        self.commit();
        Ok(())
    }

    pub fn shape_link(&mut self, i: usize, id: u32) -> Option<String> {
        let part = self.slide_part(i).ok()?;
        let n = self.find_shape(&part, id)?;
        let d = self.pkg.xml(&part).ok()?;
        let nv = d.elements(n).next()?;
        let h = path(d, nv, &["p:cNvPr", "a:hlinkClick"])?;
        let (rid, act) = (d.attr(h, "r:id").unwrap_or("").to_string(), d.attr(h, "action").unwrap_or("").to_string());
        Some(self.link_target(&part, &rid, &act))
    }

    /// Link (para, char) a..b: an address ("https://..."), "slide:N" (0-based), "next",
    /// "prev", "first", "last", or "" to remove the link.
    pub fn set_link(&mut self, i: usize, tid: u32, a: (usize, usize), b: (usize, usize), target: &str) -> Result<(), String> {
        let part = self.slide_part(i)?;
        let (sid, cell) = split_tid(tid);
        let n = self.find_shape(&part, sid).ok_or("no such shape")?;
        self.begin(if target.is_empty() { "Remove Link" } else { "Insert Link" }, &[part.clone(), Package::rels_name(&part)]);
        let (rid, action) = self.link_rel(&part, target)?;
        let d = self.pkg.xml_mut(&part).map_err(|e| e.to_string())?;
        let tb = Self::text_body_node(d, n, cell).ok_or("no text")?;
        let paras: Vec<NodeId> = d.children_named(tb, "a:p").collect();
        let (a, b) = if a <= b { (a, b) } else { (b, a) };
        for (pi, p) in paras.iter().enumerate() {
            if pi < a.0 || pi > b.0 {
                continue;
            }
            let plen = crate::edit::para_len(d, *p);
            let s = if pi == a.0 { a.1 } else { 0 };
            let e = if pi == b.0 { b.1 } else { plen };
            if s >= e {
                continue;
            }
            crate::edit::split_runs_at(d, *p, e);
            crate::edit::split_runs_at(d, *p, s);
            let mut at = 0;
            for c in d.elements(*p).collect::<Vec<_>>() {
                let l = crate::edit::piece_len(d, c);
                if d.name(c) == "a:r" && at >= s && at + l <= e && l > 0 {
                    let rpr = crate::edit::ensure_rpr(d, c);
                    if let Some(h) = d.child(rpr, "a:hlinkClick") {
                        d.detach(h);
                    }
                    if !target.is_empty() {
                        let mut attrs: Vec<(&str, &str)> = vec![("r:id", rid.as_str())];
                        if !action.is_empty() {
                            attrs.push(("action", action.as_str()));
                        }
                        let h = d.new_element("a:hlinkClick", &attrs);
                        let at2 = d.children(rpr).iter().position(|&x| d.text_of_node(x).is_none() && matches!(d.name(x), "a:hlinkMouseOver" | "a:rtl" | "a:extLst"))
                            .unwrap_or(d.children(rpr).len());
                        d.insert(rpr, at2, h);
                    }
                }
                at += l;
            }
        }
        self.commit();
        Ok(())
    }

    /// What a link (relationship id + action) on slide part `part` goes to.
    pub fn link_target(&mut self, part: &str, rid: &str, action: &str) -> String {
        if let Some(j) = action.strip_prefix("ppaction://hlinkshowjump?jump=") {
            return match j { "nextslide" => "next", "previousslide" => "prev", "firstslide" => "first", "lastslide" => "last", "endshow" => "end", _ => "next" }.to_string();
        }
        let Some(t) = self.pkg.rel_target(part, rid) else { return String::new() };
        if action.contains("hlinksldjump") {
            let to = Package::resolve(part, &t);
            return self.slides.iter().position(|s| *s == to).map(|k| format!("slide:{k}")).unwrap_or_default();
        }
        t
    }

    /// The link under text position (para, off) of a text target.
    pub fn link_at_pos(&mut self, i: usize, tid: u32, para: usize, off: usize) -> Option<String> {
        let part = self.slide_part(i).ok()?;
        let (sid, cell) = split_tid(tid);
        let n = self.find_shape(&part, sid)?;
        let d = self.pkg.xml(&part).ok()?;
        let tb = Self::text_body_node(d, n, cell)?;
        let p = d.children_named(tb, "a:p").nth(para)?;
        let mut at = 0;
        let mut found = None;
        for c in d.elements(p) {
            let l = crate::edit::piece_len(d, c);
            if d.name(c) == "a:r" && off >= at && off < at + l.max(1) {
                if let Some(h) = path(d, c, &["a:rPr", "a:hlinkClick"]) {
                    found = Some((d.attr(h, "r:id").unwrap_or("").to_string(), d.attr(h, "action").unwrap_or("").to_string()));
                }
                break;
            }
            at += l;
        }
        let (rid, action) = found?;
        Some(self.link_target(&part, &rid, &action))
    }

    // ------------------------------------------------------------ crop
    /// The picture file of a picture shape.
    pub fn picture_data(&mut self, i: usize, id: u32) -> Option<Vec<u8>> {
        let part = self.slide_part(i).ok()?;
        let n = self.find_shape(&part, id)?;
        let d = self.pkg.xml(&part).ok()?;
        let blip = path(d, n, &["p:blipFill", "a:blip"])?;
        let rid = d.attr(blip, "r:embed")?.to_string();
        let t = self.pkg.rel_target(&part, &rid)?;
        self.pkg.bytes(&Package::resolve(&part, &t))
    }

    pub fn crop(&mut self, i: usize, id: u32) -> Option<(f64, f64, f64, f64)> {
        let part = self.slide_part(i).ok()?;
        let n = self.find_shape(&part, id)?;
        let d = self.pkg.xml(&part).ok()?;
        let bf = d.child(n, "p:blipFill")?;
        let Some(sr) = d.child(bf, "a:srcRect") else { return Some((0.0, 0.0, 0.0, 0.0)) };
        let g = |k: &str| emu(d, sr, k).unwrap_or(0.0) / 100000.0;
        Some((g("l"), g("t"), g("r"), g("b")))
    }

    /// Crop a picture (fractions of the picture cut from each side) and set its box (points).
    #[allow(clippy::too_many_arguments)]
    pub fn set_crop(&mut self, i: usize, id: u32, l: f64, t: f64, r: f64, b: f64, x: f64, y: f64, w: f64, h: f64) -> Result<(), String> {
        let part = self.slide_part(i)?;
        let n = self.find_shape(&part, id).ok_or("no such picture")?;
        self.begin("Crop", &[part.clone()]);
        {
            let d = self.pkg.xml_mut(&part).map_err(|e| e.to_string())?;
            let bf = d.child(n, "p:blipFill").ok_or("not a picture")?;
            if let Some(sr) = d.child(bf, "a:srcRect") {
                d.detach(sr);
            }
            if l.abs() + t.abs() + r.abs() + b.abs() > 1e-6 {
                let pc = |v: f64| format!("{}", (v * 100000.0).round() as i64);
                let sr = d.new_element("a:srcRect", &[]);
                for (k, v) in [("l", l), ("t", t), ("r", r), ("b", b)] {
                    if v.abs() > 1e-6 {
                        d.set_attr(sr, k, &pc(v));
                    }
                }
                let at = d.child(bf, "a:blip").and_then(|bl| d.index_in_parent(bl)).map(|k| k + 1).unwrap_or(0);
                d.insert(bf, at, sr);
            }
        }
        self.commit();
        self.set_boxes(i, &[(id, x, y, w, h, None)], "Crop")?;
        Ok(())
    }

    // ------------------------------------------------------------ comments
    fn authors_part(&mut self) -> Option<String> {
        let pres = self.pres.clone();
        self.pkg.related(&pres, "/commentAuthors")
    }

    fn comments_part(&mut self, slide: &str) -> Option<String> {
        self.pkg.rels(slide).into_iter().find(|r| r.kind.ends_with("/comments") && !r.external)
            .map(|r| Package::resolve(slide, &r.target))
    }

    /// Slide i's comments: (index, author, initials, date, text, x, y).
    pub fn comments(&mut self, i: usize) -> Vec<(u32, String, String, String, String, f64, f64)> {
        let Ok(slide) = self.slide_part(i) else { return Vec::new() };
        let Some(cp) = self.comments_part(&slide) else { return Vec::new() };
        let authors: Vec<(String, String, String)> = self.authors_part().and_then(|a| self.pkg.xml(&a).ok().map(|d| {
            d.elements(d.root).map(|c| (d.attr(c, "id").unwrap_or("").to_string(), d.attr(c, "name").unwrap_or("").to_string(),
                                        d.attr(c, "initials").unwrap_or("").to_string())).collect()
        })).unwrap_or_default();
        let Ok(d) = self.pkg.xml(&cp) else { return Vec::new() };
        d.elements(d.root).filter(|&c| d.name(c) == "p:cm").map(|c| {
            let aid = d.attr(c, "authorId").unwrap_or("");
            let (name, ini) = authors.iter().find(|a| a.0 == aid).map(|a| (a.1.clone(), a.2.clone())).unwrap_or_default();
            let pos = d.child(c, "p:pos");
            (emu(d, c, "idx").unwrap_or(0.0) as u32, name, ini, d.attr(c, "dt").unwrap_or("").to_string(),
             d.child(c, "p:text").map(|t| d.text(t)).unwrap_or_default(),
             pos.and_then(|p| emu(d, p, "x")).unwrap_or(0.0) / 8.0, pos.and_then(|p| emu(d, p, "y")).unwrap_or(0.0) / 8.0)
        }).collect()
    }

    pub fn add_comment(&mut self, i: usize, text: &str, author: &str, initials: &str, x: f64, y: f64) -> Result<u32, String> {
        let slide = self.slide_part(i)?;
        let pres = self.pres.clone();
        let authors = match self.authors_part() { Some(a) => a, None => "ppt/commentAuthors.xml".to_string() };
        let cp = match self.comments_part(&slide) { Some(c) => c, None => self.free_name("ppt/comments", "comment", "xml") };
        self.begin("New Comment", &[pres.clone(), Package::rels_name(&pres), "[Content_Types].xml".to_string(), authors.clone(),
                                    slide.clone(), Package::rels_name(&slide), cp.clone()]);
        if !self.pkg.has(&authors) {
            let doc = XmlDoc::parse(br#"<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:cmAuthorLst xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"/>"#).map_err(|e| e.to_string())?;
            self.pkg.put_xml(&authors, doc);
            self.pkg.set_content_type(&authors, CT_AUTHORS);
            self.pkg.add_rel(&pres, &format!("{RT}commentAuthors"), &rel_path(&pres, &authors));
        }
        // the author and the comment's number
        let (aid, idx) = {
            let d = self.pkg.xml_mut(&authors).map_err(|e| e.to_string())?;
            let root = d.root;
            let existing = d.elements(root).find(|&c| d.attr(c, "name") == Some(author));
            let a = match existing {
                Some(a) => a,
                None => {
                    let id = d.elements(root).filter_map(|c| emu(d, c, "id")).fold(-1.0f64, f64::max) + 1.0;
                    let a = d.new_element("p:cmAuthor", &[("id", &format!("{}", id as i64)), ("name", author), ("initials", initials),
                                                          ("lastIdx", "0"), ("clrIdx", &format!("{}", id as i64 % 8))]);
                    d.append(root, a);
                    a
                }
            };
            let idx = emu(d, a, "lastIdx").unwrap_or(0.0) as u32 + 1;
            d.set_attr(a, "lastIdx", &idx.to_string());
            (d.attr(a, "id").unwrap_or("0").to_string(), idx)
        };
        if !self.pkg.has(&cp) {
            let doc = XmlDoc::parse(br#"<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:cmLst xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"/>"#).map_err(|e| e.to_string())?;
            self.pkg.put_xml(&cp, doc);
            self.pkg.set_content_type(&cp, CT_COMMENTS);
            self.pkg.add_rel(&slide, &format!("{RT}comments"), &rel_path(&slide, &cp));
        }
        let dt = chrono::Local::now().format("%Y-%m-%dT%H:%M:%S%.3f").to_string();
        let d = self.pkg.xml_mut(&cp).map_err(|e| e.to_string())?;
        let xml = format!(r#"<p:cm authorId="{aid}" dt="{dt}" idx="{idx}"><p:pos x="{}" y="{}"/><p:text>{}</p:text></p:cm>"#,
                          (x * 8.0).round() as i64, (y * 8.0).round() as i64, esc_text(text));
        let el = fragment(d, &xml).ok_or("bad comment")?;
        let root = d.root;
        d.append(root, el);
        self.commit();
        Ok(idx)
    }

    fn comment_node(d: &XmlDoc, author_ids: &[String], idx: u32, author: Option<&str>) -> Option<NodeId> {
        let _ = (author_ids, author);
        d.elements(d.root).find(|&c| emu(d, c, "idx").map(|v| v as u32) == Some(idx))
    }

    pub fn edit_comment(&mut self, i: usize, idx: u32, text: &str) -> Result<(), String> {
        let slide = self.slide_part(i)?;
        let cp = self.comments_part(&slide).ok_or("no comments")?;
        self.begin("Edit Comment", &[cp.clone()]);
        let d = self.pkg.xml_mut(&cp).map_err(|e| e.to_string())?;
        let c = Self::comment_node(d, &[], idx, None).ok_or("no such comment")?;
        if let Some(t) = d.child(c, "p:text") {
            d.detach(t);
        }
        let t = fragment(d, &format!("<p:text>{}</p:text>", esc_text(text))).unwrap();
        d.append(c, t);
        self.commit();
        Ok(())
    }

    pub fn delete_comment(&mut self, i: usize, idx: Option<u32>) -> Result<(), String> {
        let slide = self.slide_part(i)?;
        let Some(cp) = self.comments_part(&slide) else { return Ok(()) };
        self.begin("Delete Comment", &[cp.clone()]);
        let d = self.pkg.xml_mut(&cp).map_err(|e| e.to_string())?;
        for c in d.elements(d.root).collect::<Vec<_>>() {
            if idx.is_none() || emu(d, c, "idx").map(|v| v as u32) == idx {
                d.detach(c);
            }
        }
        self.commit();
        Ok(())
    }
}

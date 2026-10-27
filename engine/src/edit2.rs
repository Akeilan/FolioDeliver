//! More changes: tables, headers and footers, slide size, sections, transitions and the
//! theme's colours and fonts.

use crate::edit::{fragment, next_shape_id};
use crate::model::{emu, path, Deck, EMU_PT};
use crate::scene;
use folio_core::package::Package;
use folio_core::xml::{NodeId, XmlDoc};

const P14: &str = "http://schemas.microsoft.com/office/powerpoint/2010/main";
const SECTION_EXT: &str = "{521415D9-36F7-43E2-AB2F-B90AF26B5E84}";

fn emu_s(pt: f64) -> String {
    format!("{}", (pt * EMU_PT).round() as i64)
}

fn esc(s: &str) -> String {
    folio_core::xml::attr_escaped(s)
}

fn esc_text(s: &str) -> String {
    let mut o = String::new();
    folio_core::xml::escape_text(s, &mut o);
    o
}

fn tbl_of(d: &XmlDoc, frame: NodeId) -> Option<NodeId> {
    path(d, frame, &["a:graphic", "a:graphicData", "a:tbl"])
}

fn empty_cell() -> &'static str {
    r#"<a:tc><a:txBody><a:bodyPr/><a:lstStyle/><a:p><a:endParaRPr lang="en-US" dirty="0"/></a:p></a:txBody><a:tcPr/></a:tc>"#
}

/// The 32-bit guid PowerPoint gives each section.
fn guid(n: u64) -> String {
    let t = std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).map(|d| d.as_nanos() as u64).unwrap_or(0) ^ (n * 0x9E3779B97F4A7C15);
    format!("{{{:08X}-{:04X}-{:04X}-{:04X}-{:012X}}}", (t >> 32) as u32, (t >> 16) as u16, t as u16 | 0x4000, (t >> 48) as u16 | 0x8000, t & 0xFFFF_FFFF_FFFF)
}

impl Deck {
    // ------------------------------------------------------------ tables
    pub fn add_table(&mut self, i: usize, rows: usize, cols: usize, x: f64, y: f64, w: f64) -> Result<u32, String> {
        let part = self.slide_part(i)?;
        let rows = rows.clamp(1, 75);
        let cols = cols.clamp(1, 75);
        let cw = (w / cols as f64 * EMU_PT).round() as i64;
        let rh = 370840i64;
        self.begin("Insert Table", &[part.clone()]);
        let d = self.pkg.xml_mut(&part).map_err(|e| e.to_string())?;
        let id = next_shape_id(d);
        let mut grid = String::new();
        for _ in 0..cols {
            grid.push_str(&format!(r#"<a:gridCol w="{cw}"/>"#));
        }
        let mut body = String::new();
        for _ in 0..rows {
            body.push_str(&format!(r#"<a:tr h="{rh}">"#));
            for _ in 0..cols {
                body.push_str(empty_cell());
            }
            body.push_str("</a:tr>");
        }
        let xml = format!(
            r#"<p:graphicFrame><p:nvGraphicFramePr><p:cNvPr id="{id}" name="Table {n}"/><p:cNvGraphicFramePr><a:graphicFrameLocks noGrp="1"/></p:cNvGraphicFramePr><p:nvPr/></p:nvGraphicFramePr><p:xfrm><a:off x="{}" y="{}"/><a:ext cx="{}" cy="{}"/></p:xfrm><a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/table"><a:tbl><a:tblPr firstRow="1" bandRow="1"><a:tableStyleId>{{5C22544A-7EE6-4342-B048-85BDC9FD1C3A}}</a:tableStyleId></a:tblPr><a:tblGrid>{grid}</a:tblGrid>{body}</a:tbl></a:graphicData></a:graphic></p:graphicFrame>"#,
            emu_s(x), emu_s(y), cw * cols as i64, rh * rows as i64, n = id - 1);
        let tree = path(d, d.root, &["p:cSld", "p:spTree"]).ok_or("no tree")?;
        let n = fragment(d, &xml).ok_or("bad table")?;
        d.append(tree, n);
        self.commit();
        Ok(id)
    }

    /// (rows, cols) of a table.
    pub fn table_size(&mut self, i: usize, id: u32) -> Option<(usize, usize)> {
        let part = self.slide_part(i).ok()?;
        let n = self.find_shape(&part, id)?;
        let d = self.pkg.xml(&part).ok()?;
        let t = tbl_of(d, n)?;
        let rows = d.children_named(t, "a:tr").count();
        let cols = d.child(t, "a:tblGrid").map(|g| d.children_named(g, "a:gridCol").count()).unwrap_or(0);
        Some((rows, cols))
    }

    fn table_frame_height(d: &mut XmlDoc, frame: NodeId) {
        let Some(t) = tbl_of(d, frame) else { return };
        let h: f64 = d.children_named(t, "a:tr").map(|r| emu(d, r, "h").unwrap_or(0.0)).sum();
        let w: f64 = d.child(t, "a:tblGrid").map(|g| d.children_named(g, "a:gridCol").map(|c| emu(d, c, "w").unwrap_or(0.0)).sum()).unwrap_or(0.0);
        if let Some(ext) = path(d, frame, &["p:xfrm", "a:ext"]) {
            d.set_attr(ext, "cy", &format!("{}", h.round() as i64));
            d.set_attr(ext, "cx", &format!("{}", w.round() as i64));
        }
    }

    /// Insert a row before row `at` (rows: copy of row `like`'s look).
    pub fn table_insert_row(&mut self, i: usize, id: u32, at: usize) -> Result<(), String> {
        let part = self.slide_part(i)?;
        let n = self.find_shape(&part, id).ok_or("no such table")?;
        self.begin("Insert Row", &[part.clone()]);
        let d = self.pkg.xml_mut(&part).map_err(|e| e.to_string())?;
        let t = tbl_of(d, n).ok_or("not a table")?;
        let rows: Vec<NodeId> = d.children_named(t, "a:tr").collect();
        let like = rows[at.min(rows.len() - 1).min(rows.len().saturating_sub(1))];
        let new = d.clone_node(like);
        for tc in d.children_named(new, "a:tc").collect::<Vec<_>>() {
            // empty text, no merges
            if let Some(tb) = d.child(tc, "a:txBody") {
                for p in d.children_named(tb, "a:p").collect::<Vec<_>>() {
                    d.detach(p);
                }
                let p = fragment(d, r#"<a:p><a:endParaRPr lang="en-US" dirty="0"/></a:p>"#).unwrap();
                d.append(tb, p);
            }
            for a in ["rowSpan", "vMerge"] {
                d.remove_attr(tc, a);
            }
        }
        let idx = if at >= rows.len() { d.index_in_parent(rows[rows.len() - 1]).unwrap() + 1 } else { d.index_in_parent(rows[at]).unwrap() };
        d.insert(t, idx, new);
        Self::table_frame_height(d, n);
        self.commit();
        Ok(())
    }

    pub fn table_insert_col(&mut self, i: usize, id: u32, at: usize) -> Result<(), String> {
        let part = self.slide_part(i)?;
        let n = self.find_shape(&part, id).ok_or("no such table")?;
        self.begin("Insert Column", &[part.clone()]);
        let d = self.pkg.xml_mut(&part).map_err(|e| e.to_string())?;
        let t = tbl_of(d, n).ok_or("not a table")?;
        let grid = d.child(t, "a:tblGrid").ok_or("no grid")?;
        let gcols: Vec<NodeId> = d.children_named(grid, "a:gridCol").collect();
        let like = gcols[at.min(gcols.len() - 1)];
        let gc = d.clone_node(like);
        for c in d.elements(gc).collect::<Vec<_>>() {
            d.detach(c);
        }
        let gidx = if at >= gcols.len() { d.index_in_parent(gcols[gcols.len() - 1]).unwrap() + 1 } else { d.index_in_parent(gcols[at]).unwrap() };
        d.insert(grid, gidx, gc);
        for r in d.children_named(t, "a:tr").collect::<Vec<_>>() {
            let tcs: Vec<NodeId> = d.children_named(r, "a:tc").collect();
            let cell = fragment(d, empty_cell()).unwrap();
            let idx = if at >= tcs.len() { tcs.last().and_then(|c| d.index_in_parent(*c)).map(|k| k + 1).unwrap_or(0) } else { d.index_in_parent(tcs[at]).unwrap() };
            d.insert(r, idx, cell);
        }
        Self::table_frame_height(d, n);
        self.commit();
        Ok(())
    }

    pub fn table_delete_row(&mut self, i: usize, id: u32, row: usize) -> Result<bool, String> {
        let part = self.slide_part(i)?;
        let n = self.find_shape(&part, id).ok_or("no such table")?;
        self.begin("Delete Rows", &[part.clone()]);
        let d = self.pkg.xml_mut(&part).map_err(|e| e.to_string())?;
        let t = tbl_of(d, n).ok_or("not a table")?;
        let rows: Vec<NodeId> = d.children_named(t, "a:tr").collect();
        if rows.len() <= 1 {
            // the last row: the table goes
            d.detach(n);
            self.commit();
            return Ok(true);
        }
        if let Some(r) = rows.get(row) {
            d.detach(*r);
        }
        Self::table_frame_height(d, n);
        self.commit();
        Ok(false)
    }

    pub fn table_delete_col(&mut self, i: usize, id: u32, col: usize) -> Result<bool, String> {
        let part = self.slide_part(i)?;
        let n = self.find_shape(&part, id).ok_or("no such table")?;
        self.begin("Delete Columns", &[part.clone()]);
        let d = self.pkg.xml_mut(&part).map_err(|e| e.to_string())?;
        let t = tbl_of(d, n).ok_or("not a table")?;
        let grid = d.child(t, "a:tblGrid").ok_or("no grid")?;
        let gcols: Vec<NodeId> = d.children_named(grid, "a:gridCol").collect();
        if gcols.len() <= 1 {
            d.detach(n);
            self.commit();
            return Ok(true);
        }
        if let Some(g) = gcols.get(col) {
            d.detach(*g);
        }
        for r in d.children_named(t, "a:tr").collect::<Vec<_>>() {
            let tc = d.children_named(r, "a:tc").nth(col);
            if let Some(tc) = tc {
                d.detach(tc);
            }
        }
        Self::table_frame_height(d, n);
        self.commit();
        Ok(false)
    }

    /// Table style options: firstRow, lastRow, firstCol, lastCol, bandRow, bandCol.
    pub fn table_option(&mut self, i: usize, id: u32, key: &str, on: bool) -> Result<(), String> {
        let part = self.slide_part(i)?;
        let n = self.find_shape(&part, id).ok_or("no such table")?;
        self.begin("Table Style Options", &[part.clone()]);
        let d = self.pkg.xml_mut(&part).map_err(|e| e.to_string())?;
        let t = tbl_of(d, n).ok_or("not a table")?;
        let pr = match d.child(t, "a:tblPr") {
            Some(p) => p,
            None => {
                let p = d.new_element("a:tblPr", &[]);
                d.insert(t, 0, p);
                p
            }
        };
        if on { d.set_attr(pr, key, "1"); } else { d.remove_attr(pr, key); }
        self.commit();
        Ok(())
    }

    pub fn table_option_value(&mut self, i: usize, id: u32, key: &str) -> bool {
        let Ok(part) = self.slide_part(i) else { return false };
        let Some(n) = self.find_shape(&part, id) else { return false };
        let Ok(d) = self.pkg.xml(&part) else { return false };
        tbl_of(d, n).and_then(|t| d.child(t, "a:tblPr")).and_then(|p| d.attr(p, key)).map(|v| v == "1" || v == "true").unwrap_or(false)
    }

    /// Shade cells (indexes row by row): "RRGGBB", "scheme:x" or "none"; "" = the style's.
    pub fn table_shade(&mut self, i: usize, id: u32, cells: &[usize], spec: &str) -> Result<(), String> {
        let part = self.slide_part(i)?;
        let n = self.find_shape(&part, id).ok_or("no such table")?;
        self.begin("Shading", &[part.clone()]);
        let d = self.pkg.xml_mut(&part).map_err(|e| e.to_string())?;
        for k in cells {
            let Some(tc) = crate::edit::cell_node(d, n, *k) else { continue };
            let pr = match d.child(tc, "a:tcPr") {
                Some(p) => p,
                None => {
                    let p = d.new_element("a:tcPr", &[]);
                    d.append(tc, p);
                    p
                }
            };
            for c in d.elements(pr).collect::<Vec<_>>() {
                if matches!(d.name(c), "a:noFill" | "a:solidFill" | "a:gradFill" | "a:blipFill" | "a:pattFill" | "a:grpFill") {
                    d.detach(c);
                }
            }
            if !spec.is_empty() {
                let xml = if spec == "none" { "<a:noFill/>".to_string() } else if let Some(s) = spec.strip_prefix("scheme:") {
                    format!(r#"<a:solidFill><a:schemeClr val="{s}"/></a:solidFill>"#)
                } else {
                    format!(r#"<a:solidFill><a:srgbClr val="{}"/></a:solidFill>"#, spec.trim_start_matches('#').to_uppercase())
                };
                let el = fragment(d, &xml).unwrap();
                // fills come after the borders (lnL ... lnBlToTr), before extLst
                let at = d.children(pr).iter().position(|&c| d.text_of_node(c).is_none() && matches!(d.name(c), "a:headers" | "a:extLst")).unwrap_or(d.children(pr).len());
                d.insert(pr, at, el);
            }
        }
        self.commit();
        Ok(())
    }

    // ------------------------------------------------------------ header and footer
    /// Date (None: off; Some("") updates automatically; Some(text): fixed), slide number,
    /// footer (None: off), on slides `idx`; `skip_title` leaves Title Slide layouts out.
    pub fn set_header_footer(&mut self, idx: &[usize], date: Option<&str>, number: bool, footer: Option<&str>, skip_title: bool) -> Result<(), String> {
        let parts: Vec<String> = idx.iter().filter_map(|i| self.slides.get(*i).cloned()).collect();
        self.begin("Header and Footer", &parts);
        for p in &parts {
            let layout = self.layout_of(p);
            let is_title = layout.as_ref().map(|l| self.layout_name(l) == "Title Slide").unwrap_or(false)
                || layout.as_ref().and_then(|l| self.pkg.xml(l).ok()).map(|d| d.attr(d.root, "type") == Some("title")).unwrap_or(false);
            // the layout's placeholders (their idx), else the master's
            let mut lph: Vec<(String, Option<u32>, String)> = Vec::new();
            if let Some(l) = &layout {
                if let Ok(ld) = self.pkg.xml(l) {
                    if let Some(tree) = path(ld, ld.root, &["p:cSld", "p:spTree"]) {
                        for n in ld.elements(tree) {
                            if let Some(ph) = scene::ph_of(ld, n) {
                                if matches!(ph.kind.as_str(), "dt" | "ftr" | "sldNum") {
                                    lph.push((ph.kind.clone(), ph.idx, scene::shape_id(ld, n).1));
                                }
                            }
                        }
                    }
                }
            }
            let d = self.pkg.xml_mut(p).map_err(|e| e.to_string())?;
            let Some(tree) = path(d, d.root, &["p:cSld", "p:spTree"]) else { continue };
            for n in d.elements(tree).collect::<Vec<_>>() {
                if scene::ph_of(d, n).is_some_and(|ph| matches!(ph.kind.as_str(), "dt" | "ftr" | "sldNum")) {
                    d.detach(n);
                }
            }
            if skip_title && is_title {
                continue;
            }
            let mut next = next_shape_id(d);
            for (kind, name_default, on) in [("dt", "Date Placeholder", date.is_some()), ("ftr", "Footer Placeholder", footer.is_some()),
                                             ("sldNum", "Slide Number Placeholder", number)] {
                if !on {
                    continue;
                }
                let (idx_attr, name) = match lph.iter().find(|(k, _, _)| k == kind) {
                    Some((_, Some(i), nm)) => (format!(r#" idx="{i}""#), nm.clone()),
                    Some((_, None, nm)) => (String::new(), nm.clone()),
                    None => (String::new(), format!("{name_default} {}", next - 1)),
                };
                let sz = if kind == "ftr" { r#" sz="quarter""# } else { r#" sz="quarter""# };
                let body = match kind {
                    "dt" => match date {
                        Some(t) if !t.is_empty() => format!(r#"<a:p><a:r><a:rPr lang="en-US" dirty="0"/><a:t>{}</a:t></a:r><a:endParaRPr lang="en-US" dirty="0"/></a:p>"#, esc_text(t)),
                        _ => format!(r#"<a:p><a:fld id="{}" type="datetime1"><a:rPr lang="en-US"/><a:t>{}</a:t></a:fld><a:endParaRPr lang="en-US" dirty="0"/></a:p>"#,
                                     guid(next as u64), chrono::Local::now().format("%-m/%-d/%Y")),
                    },
                    "ftr" => {
                        let t = footer.unwrap_or("");
                        if t.is_empty() { r#"<a:p><a:endParaRPr lang="en-US" dirty="0"/></a:p>"#.to_string() } else {
                            format!(r#"<a:p><a:r><a:rPr lang="en-US" dirty="0"/><a:t>{}</a:t></a:r><a:endParaRPr lang="en-US" dirty="0"/></a:p>"#, esc_text(t))
                        }
                    }
                    _ => format!(r#"<a:p><a:fld id="{}" type="slidenum"><a:rPr lang="en-US"/><a:t>‹#›</a:t></a:fld><a:endParaRPr lang="en-US" dirty="0"/></a:p>"#, guid(next as u64 + 7)),
                };
                let xml = format!(r#"<p:sp><p:nvSpPr><p:cNvPr id="{next}" name="{}"/><p:cNvSpPr><a:spLocks noGrp="1"/></p:cNvSpPr><p:nvPr><p:ph type="{kind}"{sz}{idx_attr}/></p:nvPr></p:nvSpPr><p:spPr/><p:txBody><a:bodyPr/><a:lstStyle/>{body}</p:txBody></p:sp>"#, esc(&name));
                next += 1;
                if let Some(n) = fragment(d, &xml) {
                    d.append(tree, n);
                }
            }
        }
        self.commit();
        Ok(())
    }

    /// What slide i shows: (date shown, date fixed text or "", number shown, footer shown, footer text).
    pub fn header_footer(&mut self, i: usize) -> (bool, String, bool, bool, String) {
        let Ok(p) = self.slide_part(i) else { return (false, String::new(), false, false, String::new()) };
        let Ok(d) = self.pkg.xml(&p) else { return (false, String::new(), false, false, String::new()) };
        let mut out = (false, String::new(), false, false, String::new());
        if let Some(tree) = path(d, d.root, &["p:cSld", "p:spTree"]) {
            for n in d.elements(tree) {
                let Some(ph) = scene::ph_of(d, n) else { continue };
                let tb = d.child(n, "p:txBody");
                let text = tb.map(|t| crate::text::plain_text(d, t).join("\n")).unwrap_or_default();
                let has_field = tb.is_some_and(|t| d.children_named(t, "a:p").any(|p| d.child(p, "a:fld").is_some()));
                match ph.kind.as_str() {
                    "dt" => {
                        out.0 = true;
                        if !has_field {
                            out.1 = text;
                        }
                    }
                    "sldNum" => out.2 = true,
                    "ftr" => {
                        out.3 = true;
                        out.4 = text;
                    }
                    _ => {}
                }
            }
        }
        out
    }

    // ------------------------------------------------------------ slide size
    /// New slide size (points); content scaled to fit ("fit") or to fill ("max"), centred.
    pub fn set_slide_size(&mut self, w: f64, h: f64, mode: &str) -> Result<(), String> {
        let (ow, oh) = (self.cx / EMU_PT, self.cy / EMU_PT);
        let (sx, sy) = (w / ow, h / oh);
        let k = if mode == "max" { sx.max(sy) } else { sx.min(sy) };
        let (dx, dy) = ((w - ow * k) / 2.0, (h - oh * k) / 2.0);
        let mut parts = vec![self.pres.clone()];
        parts.extend(self.slides.clone());
        for m in self.masters() {
            parts.push(m.clone());
            parts.extend(self.layouts_of(&m));
        }
        self.begin("Slide Size", &parts);
        let pres = self.pres.clone();
        {
            let d = self.pkg.xml_mut(&pres).map_err(|e| e.to_string())?;
            let sz = d.child(d.root, "p:sldSz").ok_or("no slide size")?;
            d.set_attr(sz, "cx", &emu_s(w));
            d.set_attr(sz, "cy", &emu_s(h));
            d.remove_attr(sz, "type");
        }
        for p in parts.iter().skip(1) {
            let Ok(d) = self.pkg.xml_mut(p) else { continue };
            let Some(tree) = path(d, d.root, &["p:cSld", "p:spTree"]) else { continue };
            for n in d.elements(tree).collect::<Vec<_>>() {
                let xf = match d.name(n) {
                    "p:graphicFrame" => d.child(n, "p:xfrm"),
                    "p:grpSp" => path(d, n, &["p:grpSpPr", "a:xfrm"]),
                    "p:sp" | "p:pic" | "p:cxnSp" => path(d, n, &["p:spPr", "a:xfrm"]),
                    _ => None,
                };
                let Some(xf) = xf else { continue };
                if let Some(off) = d.child(xf, "a:off") {
                    let x = emu(d, off, "x").unwrap_or(0.0) / EMU_PT * k + dx;
                    let y = emu(d, off, "y").unwrap_or(0.0) / EMU_PT * k + dy;
                    d.set_attr(off, "x", &emu_s(x));
                    d.set_attr(off, "y", &emu_s(y));
                }
                if let Some(ext) = d.child(xf, "a:ext") {
                    let cx = emu(d, ext, "cx").unwrap_or(0.0) / EMU_PT * k;
                    let cy = emu(d, ext, "cy").unwrap_or(0.0) / EMU_PT * k;
                    d.set_attr(ext, "cx", &emu_s(cx));
                    d.set_attr(ext, "cy", &emu_s(cy));
                }
                // a table's grid and rows follow its frame
                if d.name(n) == "p:graphicFrame" {
                    if let Some(t) = tbl_of(d, n) {
                        if let Some(g) = d.child(t, "a:tblGrid") {
                            for c in d.children_named(g, "a:gridCol").collect::<Vec<_>>() {
                                let v = emu(d, c, "w").unwrap_or(0.0) * k;
                                d.set_attr(c, "w", &format!("{}", v.round() as i64));
                            }
                        }
                        for r in d.children_named(t, "a:tr").collect::<Vec<_>>() {
                            let v = emu(d, r, "h").unwrap_or(0.0) * k;
                            d.set_attr(r, "h", &format!("{}", v.round() as i64));
                        }
                    }
                }
            }
        }
        self.cx = w * EMU_PT;
        self.cy = h * EMU_PT;
        self.commit();
        Ok(())
    }

    // ------------------------------------------------------------ sections
    fn section_list(&mut self) -> Option<NodeId> {
        let pres = self.pres.clone();
        let d = self.pkg.xml(&pres).ok()?;
        let ext = d.child(d.root, "p:extLst")?;
        let e = d.children_named(ext, "p:ext").find(|&e| d.attr(e, "uri") == Some(SECTION_EXT))?;
        d.elements(e).find(|&c| d.name(c).ends_with(":sectionLst"))
    }

    /// Sections: (name, index of its first slide, number of slides).
    pub fn sections(&mut self) -> Vec<(String, usize, usize)> {
        let pres = self.pres.clone();
        let Some(lst) = self.section_list() else { return Vec::new() };
        let rels = self.pkg.rels(&pres);
        let Ok(d) = self.pkg.xml(&pres) else { return Vec::new() };
        // slide id -> slide index
        let mut ids: Vec<(String, usize)> = Vec::new();
        if let Some(sl) = d.child(d.root, "p:sldIdLst") {
            for s in d.children_named(sl, "p:sldId") {
                let rid = d.attr(s, "r:id").unwrap_or("");
                if let Some(r) = rels.iter().find(|r| r.id == rid) {
                    let part = Package::resolve(&pres, &r.target);
                    if let Some(k) = self.slides.iter().position(|p| *p == part) {
                        ids.push((d.attr(s, "id").unwrap_or("").to_string(), k));
                    }
                }
            }
        }
        let mut out = Vec::new();
        let mut at = 0;
        for sec in d.elements(lst) {
            if !d.name(sec).ends_with(":section") {
                continue;
            }
            let name = d.attr(sec, "name").unwrap_or("").to_string();
            let mine: Vec<usize> = d.elements(sec).filter(|c| d.name(*c).ends_with(":sldIdLst"))
                .flat_map(|l| d.elements(l).filter_map(|s| d.attr(s, "id").map(|v| v.to_string())).collect::<Vec<_>>())
                .filter_map(|id| ids.iter().find(|(i, _)| *i == id).map(|(_, k)| *k)).collect();
            let first = mine.iter().min().copied().unwrap_or(at);
            out.push((name, first, mine.len()));
            at = first + mine.len();
        }
        out
    }

    /// Rewrite the section list: (name, first slide index) in order; slides before the first
    /// section's start go in it.
    pub fn write_sections(&mut self, secs: &[(String, usize)], label: &str) -> Result<(), String> {
        let pres = self.pres.clone();
        self.begin(label, &[pres.clone()]);
        let rels = self.pkg.rels(&pres);
        let slides = self.slides.clone();
        let d = self.pkg.xml_mut(&pres).map_err(|e| e.to_string())?;
        let root = d.root;
        // slide ids in slide order
        let mut sid: Vec<String> = Vec::new();
        if let Some(sl) = d.child(root, "p:sldIdLst") {
            let mut pairs: Vec<(usize, String)> = Vec::new();
            for s in d.children_named(sl, "p:sldId") {
                let rid = d.attr(s, "r:id").unwrap_or("");
                if let Some(r) = rels.iter().find(|r| r.id == rid) {
                    let part = Package::resolve(&pres, &r.target);
                    if let Some(k) = slides.iter().position(|p| *p == part) {
                        pairs.push((k, d.attr(s, "id").unwrap_or("").to_string()));
                    }
                }
            }
            pairs.sort();
            sid = pairs.into_iter().map(|p| p.1).collect();
        }
        let ext_lst = match d.child(root, "p:extLst") {
            Some(e) => e,
            None => {
                let e = d.new_element("p:extLst", &[]);
                d.append(root, e);
                e
            }
        };
        let old = d.children_named(ext_lst, "p:ext").find(|&e| d.attr(e, "uri") == Some(SECTION_EXT));
        if let Some(old) = old {
            d.detach(old);
        }
        if !secs.is_empty() {
            let mut xml = format!(r#"<p:ext uri="{SECTION_EXT}"><p14:sectionLst xmlns:p14="{P14}">"#);
            for (k, (name, start)) in secs.iter().enumerate() {
                let start = if k == 0 { 0 } else { *start };
                let end = secs.get(k + 1).map(|s| s.1).unwrap_or(sid.len()).max(start);
                xml.push_str(&format!(r#"<p14:section name="{}" id="{}"><p14:sldIdLst>"#, esc(name), guid(k as u64)));
                for s in sid.iter().take(end).skip(start) {
                    xml.push_str(&format!(r#"<p14:sldId id="{s}"/>"#));
                }
                xml.push_str("</p14:sldIdLst></p14:section>");
            }
            xml.push_str("</p14:sectionLst></p:ext>");
            let el = fragment(d, &xml).ok_or("bad sections")?;
            d.insert(ext_lst, 0, el);
        }
        if d.elements(ext_lst).next().is_none() {
            d.detach(ext_lst);
        }
        self.commit();
        Ok(())
    }

    // ------------------------------------------------------------ transitions
    /// Slide i's transition: (kind, option, duration seconds, on click, after seconds or -1).
    pub fn transition(&mut self, i: usize) -> (String, String, f64, bool, f64) {
        let none = ("none".to_string(), String::new(), 0.0, true, -1.0);
        let Ok(p) = self.slide_part(i) else { return none };
        let Ok(d) = self.pkg.xml(&p) else { return none };
        let root = d.root;
        let tr = d.child(root, "p:transition").or_else(|| {
            d.children_named(root, "mc:AlternateContent").find_map(|ac| {
                let ch = d.child(ac, "mc:Choice").or_else(|| d.child(ac, "mc:Fallback"))?;
                d.child(ch, "p:transition")
            })
        });
        let Some(tr) = tr else { return none };
        let dur = d.attr(tr, "p14:dur").and_then(|v| v.parse::<f64>().ok()).map(|v| v / 1000.0).unwrap_or(
            match d.attr(tr, "spd") { Some("slow") => 1.0, Some("fast") => 0.5, _ => 0.75 });
        let click = d.attr(tr, "advClick").map(|v| v != "0" && v != "false").unwrap_or(true);
        let after = d.attr(tr, "advTm").and_then(|v| v.parse::<f64>().ok()).map(|v| v / 1000.0).unwrap_or(-1.0);
        let (kind, opt) = d.elements(tr).find(|&c| !d.name(c).ends_with("sndAc") && d.name(c) != "p:extLst")
            .map(|c| {
                let name = d.name(c).split(':').next_back().unwrap_or("").to_string();
                let opt = d.attr(c, "dir").or_else(|| d.attr(c, "orient")).or_else(|| d.attr(c, "thruBlk")).unwrap_or("").to_string();
                (name, opt)
            })
            .unwrap_or(("cut".into(), String::new()));
        (kind, opt, dur, click, after)
    }

    /// Set the transition of slides `idx`: kind "none", "fade", "push", "wipe", "split", "cover",
    /// "pull", "cut", "randomBar", "circle", "dissolve", "zoom"...; option: dir / orient.
    pub fn set_transition(&mut self, idx: &[usize], kind: &str, opt: &str, dur: f64, click: bool, after: f64) -> Result<(), String> {
        let parts: Vec<String> = idx.iter().filter_map(|i| self.slides.get(*i).cloned()).collect();
        self.begin("Transition", &parts);
        for p in &parts {
            let d = self.pkg.xml_mut(p).map_err(|e| e.to_string())?;
            let root = d.root;
            for n in d.elements(root).collect::<Vec<_>>() {
                let is_tr = d.name(n) == "p:transition"
                    || (d.name(n) == "mc:AlternateContent" && d.elements(n).any(|c| d.elements(c).any(|t| d.name(t) == "p:transition")));
                if is_tr {
                    d.detach(n);
                }
            }
            if kind == "none" && click && after < 0.0 {
                continue;
            }
            let spd = if dur >= 0.95 { "slow" } else if dur <= 0.55 { "fast" } else { "med" };
            let mut attrs = format!(r#" spd="{spd}""#);
            if !click {
                attrs.push_str(r#" advClick="0""#);
            }
            if after >= 0.0 {
                attrs.push_str(&format!(r#" advTm="{}""#, (after * 1000.0).round() as i64));
            }
            let child = match kind {
                "none" => String::new(),
                "push" | "wipe" | "cover" | "pull" => format!(r#"<p:{kind} dir="{}"/>"#, if opt.is_empty() { if kind == "wipe" { "d" } else { "u" } } else { opt }),
                "split" => format!(r#"<p:split orient="{}" dir="out"/>"#, if opt.is_empty() { "horz" } else { opt }),
                "randomBar" | "blinds" | "checker" | "comb" => format!(r#"<p:{kind} dir="{}"/>"#, if opt.is_empty() { "horz" } else { opt }),
                "fade" => if opt == "thruBlk" { r#"<p:fade thruBlk="1"/>"#.to_string() } else { "<p:fade/>".to_string() },
                k => format!("<p:{k}/>"),
            };
            let xml = format!("<p:transition{attrs}>{child}</p:transition>");
            let el = fragment(d, &xml).ok_or("bad transition")?;
            // after cSld / clrMapOvr, before timing and extLst
            let at = d.elements(root).position(|c| matches!(d.name(c), "p:timing" | "p:extLst"))
                .map(|k| d.index_in_parent(d.elements(root).nth(k).unwrap()).unwrap())
                .unwrap_or(d.children(root).len());
            d.insert(root, at, el);
        }
        self.commit();
        Ok(())
    }

    // ------------------------------------------------------------ theme
    /// The theme's colours (dk1 lt1 dk2 lt2 accent1..6 hlink folHlink) and fonts (major, minor).
    pub fn theme_info(&mut self) -> (Vec<(String, u32)>, String, String) {
        let master = self.masters().first().cloned();
        let Some(theme) = master.and_then(|m| self.theme_of(&m)) else { return (Vec::new(), String::new(), String::new()) };
        let ctx_scheme = {
            let mut s = crate::color::Scheme::office();
            if let Ok(d) = self.pkg.xml(&theme) {
                if let Some(cs) = path(d, d.root, &["a:themeElements", "a:clrScheme"]) {
                    s.read_theme(d, cs);
                }
            }
            s
        };
        let names = ["dk1", "lt1", "dk2", "lt2", "accent1", "accent2", "accent3", "accent4", "accent5", "accent6", "hlink", "folHlink"];
        let colors = names.iter().map(|n| (n.to_string(), ctx_scheme.colors.get(*n).copied().unwrap_or(0))).collect();
        let d = self.pkg.xml(&theme).ok();
        let font = |k: &str| d.and_then(|d| path(d, d.root, &["a:themeElements", "a:fontScheme", k, "a:latin"]).and_then(|l| d.attr(l, "typeface").map(|s| s.to_string()))).unwrap_or_default();
        (colors, font("a:majorFont"), font("a:minorFont"))
    }

    /// Change every master's theme colours (12, in theme order) and/or fonts.
    pub fn set_theme(&mut self, name: Option<&str>, colors: Option<&[u32]>, major: Option<&str>, minor: Option<&str>) -> Result<(), String> {
        let mut themes = Vec::new();
        for m in self.masters() {
            if let Some(t) = self.theme_of(&m) {
                if !themes.contains(&t) {
                    themes.push(t);
                }
            }
        }
        self.begin(if colors.is_some() && major.is_none() { "Theme Colors" } else if colors.is_none() { "Theme Fonts" } else { "Theme" }, &themes);
        let names = ["dk1", "lt1", "dk2", "lt2", "accent1", "accent2", "accent3", "accent4", "accent5", "accent6", "hlink", "folHlink"];
        for t in &themes {
            let d = self.pkg.xml_mut(t).map_err(|e| e.to_string())?;
            let Some(te) = d.child(d.root, "a:themeElements") else { continue };
            if let Some(cols) = colors {
                if let Some(cs) = d.child(te, "a:clrScheme") {
                    if let Some(nm) = name {
                        d.set_attr(cs, "name", nm);
                    }
                    for (k, nm) in names.iter().enumerate() {
                        let Some(&c) = cols.get(k) else { continue };
                        let Some(slot) = d.child(cs, &format!("a:{nm}")) else { continue };
                        for ch in d.elements(slot).collect::<Vec<_>>() {
                            d.detach(ch);
                        }
                        let el = d.new_element("a:srgbClr", &[("val", &format!("{:06X}", c & 0xFFFFFF))]);
                        d.append(slot, el);
                    }
                }
            }
            if let Some(fs) = d.child(te, "a:fontScheme") {
                for (k, v) in [("a:majorFont", major), ("a:minorFont", minor)] {
                    let Some(v) = v else { continue };
                    if let Some(l) = path(d, fs, &[k, "a:latin"]) {
                        d.set_attr(l, "typeface", v);
                    }
                }
            }
        }
        self.commit();
        Ok(())
    }
}

impl Deck {
    /// Sections as (name, slide parts), or empty when the file has none.
    pub fn section_parts(&mut self) -> Vec<(String, Vec<String>)> {
        let secs = self.sections();
        secs.into_iter().map(|(name, first, n)| (name, self.slides.iter().skip(first).take(n).cloned().collect())).collect()
    }

    /// After slides moved, were added or deleted: keep every slide in a section. Slides in `moved`
    /// (or not in any section: new ones) join the section of the slide before them (the first
    /// section at the start), as PowerPoint does.
    pub fn fix_sections(&mut self, old: Vec<(String, Vec<String>)>, moved: &[String]) -> Result<(), String> {
        if old.is_empty() {
            return Ok(());
        }
        let slides = self.slides.clone();
        let sec_of = |p: &String| old.iter().position(|(_, ps)| ps.contains(p));
        let mut member: Vec<usize> = Vec::with_capacity(slides.len());
        for (k, p) in slides.iter().enumerate() {
            let own = if moved.contains(p) { None } else { sec_of(p) };
            let s = match own {
                Some(s) => s,
                None => if k == 0 {
                    // at the start: the section of the next slide that stayed
                    slides.iter().skip(1).find(|q| !moved.contains(q)).and_then(sec_of).unwrap_or(0)
                } else {
                    member[k - 1]
                },
            };
            member.push(s);
        }
        // contiguous: a slide can't go back to an earlier section than the one before it
        for k in 1..member.len() {
            if member[k] < member[k - 1] {
                member[k] = member[k - 1];
            }
        }
        let mut out = Vec::new();
        let mut at = 0;
        for (si, (name, _)) in old.iter().enumerate() {
            let start = member.iter().position(|&m| m == si).unwrap_or(at);
            let n = member.iter().filter(|&&m| m == si).count();
            out.push((name.clone(), start));
            at = start + n;
        }
        self.write_sections(&out, "Section")
    }
}

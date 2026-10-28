//! Charts on slides: inserting one (its chart part and the workbook holding its data, in a
//! graphic frame), finding a chart's part, changing its XML and data (undoably).

use crate::edit::{fragment, next_shape_id, rel_path};
use crate::model::{path, Deck};
use folio_core::package::Package;

const CT: &str = "[Content_Types].xml";
const REL_CHART: &str = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/chart";
const REL_PACKAGE: &str = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/package";
const REL_CHARTEX: &str = "http://schemas.microsoft.com/office/2014/relationships/chartEx";
const CT_CHART: &str = "application/vnd.openxmlformats-officedocument.drawingml.chart+xml";
const CT_CHARTEX: &str = "application/vnd.ms-office.chartex+xml";
const CT_XLSX: &str = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet";
const NS_C: &str = "http://schemas.openxmlformats.org/drawingml/2006/chart";
const NS_CX: &str = "http://schemas.microsoft.com/office/drawing/2014/chartex";
const NS_R: &str = "http://schemas.openxmlformats.org/officeDocument/2006/relationships";

impl Deck {
    /// Insert a chart: `xml` is its chart part (its c:externalData points at rId1, the workbook
    /// `xlsx`); `ex` for a chartEx (treemap, sunburst...). Returns the new shape's id.
    #[allow(clippy::too_many_arguments)]
    pub fn insert_chart(&mut self, i: usize, xml: &str, xlsx: &[u8], x: f64, y: f64, w: f64, h: f64, ex: bool) -> Result<u32, String> {
        let slide = self.slide_part(i)?;
        let stem = if ex { "chartEx" } else { "chart" };
        let part = self.free_name("ppt/charts", stem, "xml");
        let book = self.free_name("ppt/embeddings", "Microsoft_Excel_Worksheet", "xlsx");
        self.begin("Insert Chart", &[slide.clone(), Package::rels_name(&slide), CT.to_string(), part.clone(),
                                     Package::rels_name(&part), book.clone()]);
        self.pkg.put_raw(&book, xlsx.to_vec());
        self.pkg.ensure_default("xlsx", CT_XLSX);
        let brid = self.pkg.add_rel(&part, REL_PACKAGE, &rel_path(&part, &book));
        let xml = xml.replace("r:id=\"rId1\"", &format!("r:id=\"{brid}\""));
        self.pkg.put_raw(&part, xml.into_bytes());
        self.pkg.set_content_type(&part, if ex { CT_CHARTEX } else { CT_CHART });
        let rid = self.pkg.add_rel(&slide, if ex { REL_CHARTEX } else { REL_CHART }, &rel_path(&slide, &part));
        let d = self.pkg.xml_mut(&slide).map_err(|e| e.to_string())?;
        let id = next_shape_id(d);
        let e = |v: f64| (v * 12700.0).round() as i64;
        let frame = |inner: &str, uri: &str| format!(
            r#"<p:graphicFrame><p:nvGraphicFramePr><p:cNvPr id="{id}" name="Chart {n}"/><p:cNvGraphicFramePr/><p:nvPr/></p:nvGraphicFramePr><p:xfrm><a:off x="{}" y="{}"/><a:ext cx="{}" cy="{}"/></p:xfrm><a:graphic><a:graphicData uri="{uri}">{inner}</a:graphicData></a:graphic></p:graphicFrame>"#,
            e(x), e(y), e(w), e(h), n = id - 1);
        let xml = if ex {
            format!(r#"<mc:AlternateContent xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006"><mc:Choice xmlns:cx1="http://schemas.microsoft.com/office/drawing/2015/9/8/chartex" Requires="cx1">{}</mc:Choice><mc:Fallback><p:sp><p:nvSpPr><p:cNvPr id="{id}" name="Chart {n}"/><p:cNvSpPr/><p:nvPr/></p:nvSpPr><p:spPr><a:xfrm><a:off x="{}" y="{}"/><a:ext cx="{}" cy="{}"/></a:xfrm><a:prstGeom prst="rect"><a:avLst/></a:prstGeom></p:spPr><p:txBody><a:bodyPr anchor="ctr"/><a:lstStyle/><a:p><a:pPr algn="ctr"/><a:r><a:rPr lang="en-US" sz="1100"/><a:t>This chart isn't available in your version of PowerPoint.</a:t></a:r></a:p></p:txBody></p:sp></mc:Fallback></mc:AlternateContent>"#,
                    frame(&format!(r#"<cx:chart xmlns:cx="{NS_CX}" xmlns:r="{NS_R}" r:id="{rid}"/>"#), NS_CX), e(x), e(y), e(w), e(h), n = id - 1)
        } else {
            frame(&format!(r#"<c:chart xmlns:c="{NS_C}" xmlns:r="{NS_R}" r:id="{rid}"/>"#), NS_C)
        };
        let tree = path(d, d.root, &["p:cSld", "p:spTree"]).ok_or("no tree")?;
        let n = fragment(d, &xml).ok_or("bad chart frame")?;
        d.append(tree, n);
        self.commit();
        Ok(id)
    }

    /// The chart part a graphic frame shows (None: it isn't a chart).
    pub fn chart_part(&mut self, i: usize, id: u32) -> Option<String> {
        let slide = self.slide_part(i).ok()?;
        let n = self.find_shape(&slide, id)?;
        let d = self.pkg.xml(&slide).ok()?;
        let gd = path(d, n, &["a:graphic", "a:graphicData"])?;
        let uri = d.attr(gd, "uri").unwrap_or("");
        if !(uri.ends_with("/chart") || uri.ends_with("/chartex")) {
            return None;
        }
        let c = d.elements(gd).next()?;
        let rid = d.attr(c, "r:id")?.to_string();
        let t = self.pkg.rel_target(&slide, &rid)?;
        Some(Package::resolve(&slide, &t))
    }

    pub fn chart_xml(&mut self, part: &str) -> Option<String> {
        self.pkg.bytes(part).map(|b| String::from_utf8_lossy(&b).into_owned())
    }

    pub fn set_chart_xml(&mut self, part: &str, xml: &str) -> Result<(), String> {
        if !self.pkg.has(part) {
            return Err("no such chart".into());
        }
        folio_core::xml::XmlDoc::parse(xml.as_bytes()).map_err(|e| e.to_string())?;
        self.begin("Chart", &[part.to_string()]);
        // keep the workbook relationship id the chart had
        let rid = self.pkg.rels(part).into_iter().find(|r| r.kind.ends_with("/package")).map(|r| r.id);
        let xml = match rid { Some(r) => xml.replace("r:id=\"rId1\"", &format!("r:id=\"{r}\"")), None => xml.to_string() };
        self.pkg.put_raw(part, xml.into_bytes());
        self.commit();
        Ok(())
    }

    pub fn chart_workbook(&mut self, part: &str) -> Option<Vec<u8>> {
        let r = self.pkg.rels(part).into_iter().find(|r| !r.external && (r.kind.ends_with("/package") || r.kind.ends_with("/oleObject")))?;
        self.pkg.bytes(&Package::resolve(part, &r.target))
    }

    pub fn set_chart_workbook(&mut self, part: &str, bytes: &[u8]) -> Result<(), String> {
        let r = self.pkg.rels(part).into_iter().find(|r| !r.external && (r.kind.ends_with("/package") || r.kind.ends_with("/oleObject")))
            .ok_or("no workbook")?;
        let name = Package::resolve(part, &r.target);
        self.begin("Chart Data", &[name.clone()]);
        self.pkg.put_raw(&name, bytes.to_vec());
        self.commit();
        Ok(())
    }
}

const RT_DGM: &str = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/";
const DIAGRAM_KINDS: [(&str, &str, &str, &str); 5] = [
    ("data", "diagramData", "data", "application/vnd.openxmlformats-officedocument.drawingml.diagramData+xml"),
    ("layout", "diagramLayout", "layout", "application/vnd.openxmlformats-officedocument.drawingml.diagramLayout+xml"),
    ("style", "diagramQuickStyle", "quickStyle", "application/vnd.openxmlformats-officedocument.drawingml.diagramStyle+xml"),
    ("colors", "diagramColors", "colors", "application/vnd.openxmlformats-officedocument.drawingml.diagramColors+xml"),
    ("drawing", "diagramDrawing", "drawing", "application/vnd.ms-office.drawingml.diagramDrawing+xml"),
];

impl Deck {
    /// Insert SmartArt from its five parts (data, layout, style, colors, drawing); the data
    /// part's "{DRAWING_RID}" becomes the drawing's relationship id. Returns the shape id.
    #[allow(clippy::too_many_arguments)]
    pub fn insert_diagram(&mut self, i: usize, xml: &[String; 5], x: f64, y: f64, w: f64, h: f64) -> Result<u32, String> {
        let slide = self.slide_part(i)?;
        let mut names = Vec::new();
        for (_k, _rel, stem, _ct) in DIAGRAM_KINDS {
            // the same number for all five, as PowerPoint does
            names.push(stem);
        }
        let mut n = 1;
        while DIAGRAM_KINDS.iter().any(|(_, _, stem, _)| self.pkg.has(&format!("ppt/diagrams/{stem}{n}.xml"))) {
            n += 1;
        }
        let parts: Vec<String> = DIAGRAM_KINDS.iter().map(|(_, _, stem, _)| format!("ppt/diagrams/{stem}{n}.xml")).collect();
        let mut touch = vec![slide.clone(), Package::rels_name(&slide), CT.to_string()];
        touch.extend(parts.iter().cloned());
        self.begin("Insert SmartArt", &touch);
        let mut rids = Vec::new();
        for (k, (_key, rel, _stem, ct)) in DIAGRAM_KINDS.iter().enumerate() {
            let kind = if *rel == "diagramDrawing" { "http://schemas.microsoft.com/office/2007/relationships/diagramDrawing".to_string() }
                       else { format!("{RT_DGM}{rel}") };
            let rid = self.pkg.add_rel(&slide, &kind, &rel_path(&slide, &parts[k]));
            self.pkg.set_content_type(&parts[k], ct);
            rids.push(rid);
        }
        for k in 0..5 {
            let body = if k == 0 { xml[0].replace("{DRAWING_RID}", &rids[4]) } else { xml[k].clone() };
            self.pkg.put_raw(&parts[k], body.into_bytes());
        }
        let d = self.pkg.xml_mut(&slide).map_err(|e| e.to_string())?;
        let id = next_shape_id(d);
        let e = |v: f64| (v * 12700.0).round() as i64;
        let frame = format!(
            r#"<p:graphicFrame><p:nvGraphicFramePr><p:cNvPr id="{id}" name="Diagram {nn}"/><p:cNvGraphicFramePr/><p:nvPr/></p:nvGraphicFramePr><p:xfrm><a:off x="{}" y="{}"/><a:ext cx="{}" cy="{}"/></p:xfrm><a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/diagram"><dgm:relIds xmlns:dgm="http://schemas.openxmlformats.org/drawingml/2006/diagram" xmlns:r="{NS_R}" r:dm="{}" r:lo="{}" r:qs="{}" r:cs="{}"/></a:graphicData></a:graphic></p:graphicFrame>"#,
            e(x), e(y), e(w), e(h), rids[0], rids[1], rids[2], rids[3], nn = id - 1);
        let tree = path(d, d.root, &["p:cSld", "p:spTree"]).ok_or("no tree")?;
        let node = fragment(d, &frame).ok_or("bad diagram frame")?;
        d.append(tree, node);
        self.commit();
        let _ = names;
        Ok(id)
    }

    /// A SmartArt frame's parts: [data, layout, style, colors, drawing] ("" when missing).
    pub fn diagram_parts(&mut self, i: usize, id: u32) -> Option<Vec<String>> {
        let slide = self.slide_part(i).ok()?;
        let n = self.find_shape(&slide, id)?;
        let d = self.pkg.xml(&slide).ok()?;
        let gd = path(d, n, &["a:graphic", "a:graphicData"])?;
        if !d.attr(gd, "uri").unwrap_or("").ends_with("/diagram") {
            return None;
        }
        let ri = d.child(gd, "dgm:relIds")?;
        let ids: Vec<String> = ["r:dm", "r:lo", "r:qs", "r:cs"].iter().map(|k| d.attr(ri, k).unwrap_or("").to_string()).collect();
        let rels = self.pkg.rels(&slide);
        let mut out: Vec<String> = ids.iter().map(|rid| rels.iter().find(|r| &r.id == rid).map(|r| Package::resolve(&slide, &r.target)).unwrap_or_default()).collect();
        // the drawing: named in the data part
        let data = out[0].clone();
        let drawing = self.pkg.xml(&data).ok().and_then(|dd| {
            let mut found = None;
            fn walk(dd: &folio_core::xml::XmlDoc, n: folio_core::xml::NodeId, out: &mut Option<String>) {
                for c in dd.elements(n) {
                    if dd.name(c).ends_with("dataModelExt") {
                        *out = dd.attr(c, "relId").map(|s| s.to_string());
                    }
                    walk(dd, c, out);
                }
            }
            walk(dd, dd.root, &mut found);
            found
        }).and_then(|rid| rels.iter().find(|r| r.id == rid).map(|r| Package::resolve(&slide, &r.target)))
            .or_else(|| rels.iter().find(|r| r.kind.ends_with("/diagramDrawing")).map(|r| Package::resolve(&slide, &r.target)))
            .unwrap_or_default();
        out.push(drawing);
        Some(out)
    }

    /// Replace a SmartArt's parts (empty strings leave a part as it is).
    pub fn set_diagram(&mut self, i: usize, id: u32, xml: &[String; 5]) -> Result<(), String> {
        let parts = self.diagram_parts(i, id).ok_or("not SmartArt")?;
        let slide = self.slide_part(i)?;
        self.begin("SmartArt", &parts.iter().filter(|p| !p.is_empty()).cloned().collect::<Vec<_>>());
        let drid = self.pkg.rels(&slide).into_iter().find(|r| Package::resolve(&slide, &r.target) == parts[4]).map(|r| r.id).unwrap_or_default();
        for k in 0..5 {
            if xml[k].is_empty() || parts[k].is_empty() {
                continue;
            }
            let body = if k == 0 { xml[0].replace("{DRAWING_RID}", &drid) } else { xml[k].clone() };
            self.pkg.put_raw(&parts[k], body.into_bytes());
        }
        self.commit();
        Ok(())
    }
}

//! Drawing slides: backgrounds, the master's and layout's own shapes, the slide's
//! shapes with fills, outlines, pictures, tables, charts and text.

use crate::color::{Rgba, Scheme};
use crate::model::{emu, path, Deck, EMU_PT};
use crate::scene::{self, Context, Ph};
use crate::text::{self, Env, Layout, Para, Seg};
use folio_core::fonts::{Font, FontCache};
use folio_core::package::Package;
use folio_core::shapes::Shape;
use folio_core::xml::{NodeId, XmlDoc};
use std::collections::HashMap;
use std::f64::consts::PI;
use std::sync::Arc;

#[derive(Clone, Debug)]
pub enum Fill {
    None,
    Solid(Rgba),
    /// stops (pos 0..1, colour), angle in degrees, path kind ("circle", "rect", "shape") when radial
    Grad(Vec<(f64, Rgba)>, f64, Option<String>),
    /// image part, crop (l, t, r, b fractions), tiled
    Pic(String, [f64; 4], bool, f64),
    Patt(Rgba, Rgba, String),
}

#[derive(Clone, Debug)]
pub struct Line {
    pub w: f64,
    pub fill: Fill,
    pub dash: String,
}

/// What the UI needs to know about each shape on a slide.
#[derive(Clone, Debug)]
pub struct ShapeInfo {
    pub id: u32,
    pub name: String,
    pub kind: String,
    pub x: f64,
    pub y: f64,
    pub w: f64,
    pub h: f64,
    pub rot: f64,
    pub flip_h: bool,
    pub flip_v: bool,
    pub ph: Option<String>,
    pub has_text: bool,
    pub empty: bool,
    pub group: u32,
    pub geom: String,
    pub descr: String,
}

#[derive(Clone, Debug, Default)]
pub struct Opts {
    /// draw empty placeholders with their prompt and dashed edge
    pub edit: bool,
    /// a shape whose text is being edited is still drawn; this skips nothing
    pub hide: Option<u32>,
}

pub struct Painter {
    pub fonts: FontCache,
    lib: Option<freetype::Library>,
    faces: HashMap<usize, cairo::FontFace>,
    pics: HashMap<String, Option<cairo::ImageSurface>>,
    pub max_px: u32,
}

impl Default for Painter {
    fn default() -> Self {
        Self::new()
    }
}

/// One shape found while drawing: where it is and how to draw it.
struct Item<'a> {
    part: &'a str,
    dom: &'a XmlDoc,
    node: NodeId,
}

pub fn prompt_for(kind: &str) -> &'static str {
    match kind {
        "title" | "ctrTitle" => "Click to add title",
        "subTitle" => "Click to add subtitle",
        "pic" => "Click icon to add picture",
        "tbl" => "Click icon to add table",
        "chart" => "Click icon to add chart",
        "media" => "Click icon to add media",
        "dt" | "ftr" | "sldNum" | "hdr" => "",
        _ => "Click to add text",
    }
}

impl Painter {
    pub fn new() -> Painter {
        Painter { fonts: FontCache::new(), lib: freetype::Library::init().ok(), faces: HashMap::new(), pics: HashMap::new(), max_px: 2400 }
    }

    fn face(&mut self, f: &Font) -> Option<cairo::FontFace> {
        if let Some(ff) = self.faces.get(&f.id) {
            return Some(ff.clone());
        }
        let lib = self.lib.as_ref()?;
        let face = if f.path.as_os_str().is_empty() {
            lib.new_memory_face(std::rc::Rc::new(f.data().to_vec()), f.index as isize).ok()?
        } else {
            lib.new_face(&f.path, f.index as isize).ok()?
        };
        let ff = cairo::FontFace::create_from_ft(&face).ok()?;
        self.faces.insert(f.id, ff.clone());
        Some(ff)
    }

    pub fn picture(&mut self, pkg: &Package, part: &str) -> Option<cairo::ImageSurface> {
        if let Some(p) = self.pics.get(part) {
            return p.clone();
        }
        let s = pkg.raw(part).and_then(|b| folio_core::pictures::decode(b, self.max_px));
        self.pics.insert(part.to_string(), s.clone());
        s
    }

    pub fn forget_pictures(&mut self) {
        self.pics.clear();
    }

    /// Draw slide `part` with its top-left at the origin, in points (scale the context first).
    pub fn draw(&mut self, deck: &mut Deck, part: &str, cr: &cairo::Context, opts: &Opts) -> Vec<ShapeInfo> {
        let ctx = scene::context(deck, part);
        let w = deck.cx / EMU_PT;
        let h = deck.cy / EMU_PT;
        let num = deck.slides.iter().position(|s| s == part).map(|i| i + 1).unwrap_or(0);
        let env = Env { slide_num: num, date: chrono::Local::now().format("%-m/%-d/%Y").to_string(), font_scale: 1.0, spc_reduction: 0.0 };
        let mut parts: Vec<(String, XmlDoc)> = Vec::new();
        for p in [ctx.master.clone(), ctx.layout.clone(), Some(part.to_string())].into_iter().flatten() {
            if parts.iter().any(|(n, _)| *n == p) {
                continue;
            }
            if let Ok(d) = deck.pkg.xml(&p) {
                parts.push((p, d.clone()));
            }
        }
        cr.save().ok();
        cr.rectangle(0.0, 0.0, w, h);
        cr.clip();
        // background: the slide's, the layout's or the master's
        cr.set_source_rgb(1.0, 1.0, 1.0);
        cr.paint().ok();
        for (p, dom) in parts.iter().rev() {
            if let Some(bg) = path(dom, dom.root, &["p:cSld", "p:bg"]) {
                let fill = self.background(deck, &ctx, p, dom, bg);
                cr.rectangle(0.0, 0.0, w, h);
                self.paint_fill(deck, cr, &fill, w, h, (0.0, 0.0, w, h));
                break;
            }
        }
        // the master's and the layout's own shapes
        let show = |dom: &XmlDoc| dom.attr(dom.root, "showMasterSp").map(|v| v != "0" && v != "false").unwrap_or(true);
        let slide_shows = parts.iter().find(|(n, _)| n == part).map(|(_, d)| show(d)).unwrap_or(true);
        let layout_shows = ctx.layout.as_ref().and_then(|l| parts.iter().find(|(n, _)| n == l)).map(|(_, d)| show(d)).unwrap_or(true);
        let mut infos = Vec::new();
        for (p, dom) in &parts {
            let is_slide = p == part;
            let is_master = p.contains("slideMasters/") && !part.contains("slideMasters/");
            let is_layout = p.contains("slideLayouts/") && !part.contains("slideLayouts/");
            if (is_master && (!slide_shows || !layout_shows)) || (is_layout && !slide_shows) {
                continue;
            }
            let Some(tree) = path(dom, dom.root, &["p:cSld", "p:spTree"]) else { continue };
            for n in kids(dom, tree) {
                if !is_slide && scene::ph_of(dom, n).is_some() {
                    continue;
                }
                let item = Item { part: p, dom, node: n };
                let info = self.draw_item(deck, &ctx, cr, &item, &env, opts, 0, is_slide);
                if is_slide {
                    infos.extend(info);
                }
            }
        }
        cr.restore().ok();
        infos
    }

    fn background(&mut self, deck: &mut Deck, ctx: &Context, part: &str, dom: &XmlDoc, bg: NodeId) -> Fill {
        if let Some(pr) = dom.child(bg, "p:bgPr") {
            return fill_of(deck, &ctx.scheme, part, dom, pr, None).unwrap_or(Fill::Solid(Rgba::new(0xFFFFFF)));
        }
        if let Some(r) = dom.child(bg, "p:bgRef") {
            let ph = ctx.scheme.color_in(dom, r, None);
            let idx = emu(dom, r, "idx").unwrap_or(0.0) as usize;
            if idx >= 1001 {
                if let Some(f) = theme_style(deck, ctx, "a:bgFillStyleLst", idx - 1000, ph) {
                    return f;
                }
            } else if idx > 0 {
                if let Some(f) = theme_style(deck, ctx, "a:fillStyleLst", idx, ph) {
                    return f;
                }
            }
            return ph.map(Fill::Solid).unwrap_or(Fill::Solid(Rgba::new(0xFFFFFF)));
        }
        Fill::Solid(Rgba::new(0xFFFFFF))
    }

    /// Fill the current path with `fill`; `bbox` is the shape's box for gradients and pictures.
    fn paint_fill(&mut self, deck: &mut Deck, cr: &cairo::Context, fill: &Fill, w: f64, h: f64, bbox: (f64, f64, f64, f64)) {
        let (bx, by, bw, bh) = bbox;
        match fill {
            Fill::None => {
                cr.new_path();
            }
            Fill::Solid(c) => {
                c.set(cr);
                cr.fill().ok();
            }
            Fill::Patt(fg, bg, prst) => {
                if let Some(tile) = pattern_tile(fg, bg, prst) {
                    let p = cairo::SurfacePattern::create(&tile);
                    p.set_extend(cairo::Extend::Repeat);
                    p.set_filter(cairo::Filter::Nearest);
                    cr.set_source(&p).ok();
                } else {
                    let mix = |a: f64, b: f64| (a * 0.5 + b * 0.5).clamp(0.0, 1.0);
                    cr.set_source_rgba(mix(fg.r(), bg.r()), mix(fg.g(), bg.g()), mix(fg.b(), bg.b()), (fg.a + bg.a) / 2.0);
                }
                cr.fill().ok();
            }
            Fill::Grad(stops, ang, kind) => {
                let stops_on = |g: &cairo::Gradient| {
                    for (pos, c) in stops {
                        g.add_color_stop_rgba(*pos, c.r(), c.g(), c.b(), c.a);
                    }
                };
                match kind {
                    Some(_) => {
                        let r = (bw * bw + bh * bh).sqrt() / 2.0;
                        let g = cairo::RadialGradient::new(bx + bw / 2.0, by + bh / 2.0, 0.0, bx + bw / 2.0, by + bh / 2.0, r);
                        stops_on(&g);
                        cr.set_source(&g).ok();
                    }
                    None => {
                        let a = ang.to_radians();
                        let (dx, dy) = (a.cos(), a.sin());
                        let half = (bw * dx.abs() + bh * dy.abs()) / 2.0;
                        let (cx, cy) = (bx + bw / 2.0, by + bh / 2.0);
                        let g = cairo::LinearGradient::new(cx - dx * half, cy - dy * half, cx + dx * half, cy + dy * half);
                        stops_on(&g);
                        cr.set_source(&g).ok();
                    }
                }
                cr.fill().ok();
            }
            Fill::Pic(name, crop, tile, alpha) => {
                let Some(img) = self.picture(&deck.pkg, name) else {
                    cr.set_source_rgb(0.85, 0.85, 0.85);
                    cr.fill().ok();
                    return;
                };
                cr.save().ok();
                cr.clip();
                let (iw, ih) = (img.width() as f64, img.height() as f64);
                if *tile {
                    let p = cairo::SurfacePattern::create(&img);
                    p.set_extend(cairo::Extend::Repeat);
                    let mut m = cairo::Matrix::identity();
                    m.translate(-bx, -by);
                    p.set_matrix(m);
                    cr.set_source(&p).ok();
                } else {
                    let (l, t, r, b) = (crop[0], crop[1], crop[2], crop[3]);
                    let sw = iw * (1.0 - l - r);
                    let shh = ih * (1.0 - t - b);
                    cr.translate(bx, by);
                    cr.scale(bw / sw.max(1e-6), bh / shh.max(1e-6));
                    cr.translate(-iw * l, -ih * t);
                    cr.set_source_surface(&img, 0.0, 0.0).ok();
                    let p = cr.source();
                    p.set_filter(cairo::Filter::Good);
                }
                cr.paint_with_alpha(*alpha).ok();
                cr.restore().ok();
                cr.new_path();
            }
        }
        let _ = (w, h);
    }

    #[allow(clippy::too_many_arguments)]
    fn draw_item(&mut self, deck: &mut Deck, ctx: &Context, cr: &cairo::Context, it: &Item, env: &Env, opts: &Opts,
                 group: u32, collect: bool) -> Vec<ShapeInfo> {
        let dom = it.dom;
        let n = it.node;
        if scene::hidden(dom, n) {
            return Vec::new();
        }
        let name = dom.name(n).to_string();
        let mut out = Vec::new();
        let (x, y, w, h, rot, fh, fv) = scene::shape_box(deck, ctx, it.part, n);
        let (id, sname) = scene::shape_id(dom, n);
        let ph = scene::ph_of(dom, n);
        cr.save().ok();
        cr.translate(x + w / 2.0, y + h / 2.0);
        cr.rotate(rot.to_radians());
        let mut geom = String::new();
        match name.as_str() {
            "p:grpSp" => {
                cr.translate(-w / 2.0, -h / 2.0);
                if fh {
                    cr.translate(w, 0.0);
                    cr.scale(-1.0, 1.0);
                }
                if fv {
                    cr.translate(0.0, h);
                    cr.scale(1.0, -1.0);
                }
                if let Some(xf) = path(dom, n, &["p:grpSpPr", "a:xfrm"]) {
                    let ch_off = dom.child(xf, "a:chOff");
                    let ch_ext = dom.child(xf, "a:chExt");
                    let cx = ch_off.and_then(|c| emu(dom, c, "x")).unwrap_or(0.0) / EMU_PT;
                    let cy = ch_off.and_then(|c| emu(dom, c, "y")).unwrap_or(0.0) / EMU_PT;
                    let cw = ch_ext.and_then(|c| emu(dom, c, "cx")).unwrap_or(w * EMU_PT) / EMU_PT;
                    let chh = ch_ext.and_then(|c| emu(dom, c, "cy")).unwrap_or(h * EMU_PT) / EMU_PT;
                    if cw > 0.0 && chh > 0.0 {
                        cr.scale(w / cw, h / chh);
                    }
                    cr.translate(-cx, -cy);
                }
                for c in kids(dom, n) {
                    let sub = Item { part: it.part, dom, node: c };
                    self.draw_item(deck, ctx, cr, &sub, env, opts, id, false);
                }
            }
            "p:pic" => {
                cr.translate(-w / 2.0, -h / 2.0);
                let sppr = dom.child(n, "p:spPr");
                let mut sh = sppr.map(|s| Shape::parse_sppr(dom, s, &HashMap::new())).unwrap_or_else(rect_shape);
                geom = sh.geom.clone();
                if let Some(bf) = dom.child(n, "p:blipFill") {
                    if let Some(f) = blip_fill(deck, it.part, dom, bf) {
                        cr.save().ok();
                        if fh {
                            cr.translate(w, 0.0);
                            cr.scale(-1.0, 1.0);
                        }
                        if fv {
                            cr.translate(0.0, h);
                            cr.scale(1.0, -1.0);
                        }
                        sh.outline(cr, w, h);
                        self.paint_fill(deck, cr, &f, w, h, (0.0, 0.0, w, h));
                        cr.restore().ok();
                    }
                }
                self.outline(deck, ctx, cr, it, &mut sh, w, h);
            }
            "p:graphicFrame" => {
                cr.translate(-w / 2.0, -h / 2.0);
                let gd = path(dom, n, &["a:graphic", "a:graphicData"]);
                let uri = gd.and_then(|g| dom.attr(g, "uri")).unwrap_or("");
                if uri.ends_with("/table") {
                    if let Some(tbl) = gd.and_then(|g| dom.child(g, "a:tbl")) {
                        self.draw_table(deck, ctx, cr, it, tbl, env);
                    }
                    geom = "table".into();
                } else if uri.ends_with("/chart") {
                    let rid = gd.and_then(|g| dom.child(g, "c:chart")).and_then(|c| dom.attr(c, "r:id")).unwrap_or("").to_string();
                    if let Some(target) = deck.pkg.rel_target(it.part, &rid).map(|t| Package::resolve(it.part, &t)) {
                        if let Some(b) = deck.pkg.raw(&target) {
                            let bytes = Arc::new(b.to_vec());
                            let theme = folio_core::pictures::theme_array(&ctx.scheme.colors);
                            folio_core::chart::draw(cr, &bytes, w, h, &theme, &ctx.minor);
                        }
                    }
                    geom = "chart".into();
                } else if uri.ends_with("/diagram") {
                    self.draw_diagram(deck, ctx, cr, it, w, h, env);
                    geom = "smartart".into();
                } else {
                    cr.rectangle(0.0, 0.0, w, h);
                    cr.set_source_rgba(0.5, 0.5, 0.5, 0.15);
                    cr.fill().ok();
                }
            }
            _ => {
                // p:sp, p:cxnSp
                cr.translate(-w / 2.0, -h / 2.0);
                let chain = scene::sppr_chain(deck, ctx, it.part, n);
                let mut sh = rect_shape();
                let mut docs: Vec<(String, XmlDoc)> = Vec::new();
                for (p, node) in &chain {
                    let d = if p == it.part { dom.clone() } else { deck.pkg.xml(p).map(|d| d.clone()).unwrap_or_else(|_| dom.clone()) };
                    docs.push((p.clone(), d));
                    let _ = node;
                }
                // geometry: the first spPr that names one
                for ((_, node), (_, d)) in chain.iter().zip(docs.iter()) {
                    if let Some(sp) = d.child(*node, "p:spPr") {
                        if d.child(sp, "a:prstGeom").is_some() || d.child(sp, "a:custGeom").is_some() {
                            sh = Shape::parse_sppr(d, sp, &HashMap::new());
                            break;
                        }
                    }
                }
                geom = sh.geom.clone();
                let fill = self.shape_fill(deck, ctx, &chain, &docs);
                if !matches!(fill, Fill::None) {
                    cr.save().ok();
                    if fh {
                        cr.translate(w, 0.0);
                        cr.scale(-1.0, 1.0);
                    }
                    if fv {
                        cr.translate(0.0, h);
                        cr.scale(1.0, -1.0);
                    }
                    if self.shadow(ctx, dom, n, cr, &sh, w, h) {}
                    cr.new_path();
                    if sh.outline(cr, w, h) {
                        self.paint_fill(deck, cr, &fill, w, h, (0.0, 0.0, w, h));
                    }
                    cr.new_path();
                    cr.restore().ok();
                }
                cr.save().ok();
                if fh {
                    cr.translate(w, 0.0);
                    cr.scale(-1.0, 1.0);
                }
                if fv {
                    cr.translate(0.0, h);
                    cr.scale(1.0, -1.0);
                }
                self.outline(deck, ctx, cr, it, &mut sh, w, h);
                cr.restore().ok();
                // text
                if let Some(tb) = dom.child(n, "p:txBody") {
                    let lay = self.layout_text(deck, ctx, it.part, dom, n, tb, w, h, env);
                    let empty = lay.paras.iter().all(|p| p.is_empty());
                    if empty && ph.is_some() && opts.edit && it.part.contains("slides/") {
                        self.draw_prompt(deck, ctx, cr, it, w, h, env);
                    } else {
                        self.draw_text(cr, &lay, w, h, &scene::body_props(deck, ctx, it.part, n), fv);
                    }
                } else if ph.is_some() && opts.edit && it.part.contains("slides/") {
                    self.draw_prompt(deck, ctx, cr, it, w, h, env);
                }
            }
        }
        cr.restore().ok();
        if collect {
            let has_text = dom.child(n, "p:txBody").is_some();
            let empty = has_text && text::plain_text(dom, dom.child(n, "p:txBody").unwrap()).iter().all(|s| s.is_empty());
            out.push(ShapeInfo {
                id, name: sname, kind: name.trim_start_matches("p:").to_string(), x, y, w, h, rot, flip_h: fh, flip_v: fv,
                ph: ph.map(|p| p.kind), has_text, empty: empty || (!has_text && scene::ph_of(dom, n).is_some()), group, geom,
                descr: dom.elements(n).find(|&c| dom.name(c).starts_with("p:nv")).and_then(|nv| dom.child(nv, "p:cNvPr"))
                    .and_then(|c| dom.attr(c, "descr")).unwrap_or("").to_string(),
            });
        }
        out
    }

    #[allow(clippy::too_many_arguments)]
    fn shadow(&mut self, ctx: &Context, dom: &XmlDoc, n: NodeId, cr: &cairo::Context, sh: &Shape, w: f64, h: f64) -> bool {
        let Some(s) = path(dom, n, &["p:spPr", "a:effectLst", "a:outerShdw"]) else { return false };
        let dist = emu(dom, s, "dist").unwrap_or(0.0) / EMU_PT;
        let dir = emu(dom, s, "dir").unwrap_or(0.0) / 60000.0;
        let c = ctx.scheme.color_in(dom, s, None).unwrap_or(Rgba { rgb: 0, a: 0.4 });
        cr.save().ok();
        cr.translate(dist * dir.to_radians().cos(), dist * dir.to_radians().sin());
        cr.new_path();
        if sh.outline(cr, w, h) {
            c.set(cr);
            cr.fill().ok();
        }
        cr.restore().ok();
        true
    }

    fn shape_fill(&mut self, deck: &mut Deck, ctx: &Context, chain: &[(String, NodeId)], docs: &[(String, XmlDoc)]) -> Fill {
        for ((p, node), (_, d)) in chain.iter().zip(docs.iter()) {
            if let Some(sp) = d.child(*node, "p:spPr") {
                if let Some(f) = fill_of(deck, &ctx.scheme, p, d, sp, None) {
                    return f;
                }
            }
        }
        // the shape style's fill
        for ((_, node), (_, d)) in chain.iter().zip(docs.iter()) {
            if let Some(fr) = path(d, *node, &["p:style", "a:fillRef"]) {
                let ph = ctx.scheme.color_in(d, fr, None);
                let idx = emu(d, fr, "idx").unwrap_or(0.0) as usize;
                if idx == 0 {
                    return Fill::None;
                }
                return theme_style(deck, ctx, if idx >= 1001 { "a:bgFillStyleLst" } else { "a:fillStyleLst" },
                                   if idx >= 1001 { idx - 1000 } else { idx }, ph)
                    .unwrap_or(ph.map(Fill::Solid).unwrap_or(Fill::None));
            }
        }
        Fill::None
    }

    fn outline(&mut self, deck: &mut Deck, ctx: &Context, cr: &cairo::Context, it: &Item, sh: &mut Shape, w: f64, h: f64) {
        let chain = scene::sppr_chain(deck, ctx, it.part, it.node);
        let mut line: Option<Option<Line>> = None;
        let mut width: Option<f64> = None;
        let mut dash: Option<String> = None;
        for (p, node) in &chain {
            let d = if p == it.part { it.dom.clone() } else { match deck.pkg.xml(p) { Ok(d) => d.clone(), Err(_) => continue } };
            let sp = d.child(*node, "p:spPr").or_else(|| d.child(*node, "p:grpSpPr"));
            if let Some(ln) = sp.and_then(|s| d.child(s, "a:ln")) {
                if width.is_none() {
                    width = emu(&d, ln, "w").map(|v| v / EMU_PT);
                }
                if dash.is_none() {
                    dash = d.child(ln, "a:prstDash").and_then(|x| d.attr(x, "val")).map(|s| s.to_string());
                }
                if line.is_none() {
                    if d.child(ln, "a:noFill").is_some() {
                        line = Some(None);
                    } else if let Some(f) = fill_of(deck, &ctx.scheme, p, &d, ln, None) {
                        line = Some(Some(Line { w: 0.75, fill: f, dash: "solid".into() }));
                    }
                }
            }
            if line.is_none() {
                if let Some(lr) = path(&d, *node, &["p:style", "a:lnRef"]) {
                    let idx = emu(&d, lr, "idx").unwrap_or(0.0) as usize;
                    let ph = ctx.scheme.color_in(&d, lr, None);
                    if idx == 0 {
                        line = Some(None);
                    } else if let Some((tw, tf, td)) = theme_line(deck, ctx, idx, ph) {
                        if width.is_none() {
                            width = Some(tw);
                        }
                        if dash.is_none() {
                            dash = Some(td);
                        }
                        line = Some(Some(Line { w: tw, fill: tf, dash: "solid".into() }));
                    }
                }
            }
        }
        let Some(Some(l)) = line else { return };
        let color = match l.fill {
            Fill::Solid(c) => c,
            Fill::Grad(ref s, _, _) => s.first().map(|x| x.1).unwrap_or(Rgba::new(0)),
            _ => Rgba::new(0),
        };
        if color.a <= 0.0 {
            return;
        }
        sh.fill = None;
        sh.line = Some((width.unwrap_or(l.w).max(0.1), color.rgb, dash.unwrap_or(l.dash)));
        cr.save().ok();
        cr.push_group();
        sh.draw(cr, w, h);
        cr.pop_group_to_source().ok();
        cr.paint_with_alpha(color.a).ok();
        cr.restore().ok();
    }

    /// Lay out a shape's text box.
    #[allow(clippy::too_many_arguments)]
    pub fn layout_text(&mut self, deck: &mut Deck, ctx: &Context, part: &str, dom: &XmlDoc, sp: NodeId, tb: NodeId,
                       w: f64, h: f64, env: &Env) -> Layout {
        let levels = scene::text_levels(deck, ctx, part, sp);
        let body = scene::body_props(deck, ctx, part, sp);
        let mut env = env.clone();
        if let Some((fs, red)) = body.norm_autofit {
            env.font_scale = fs;
            env.spc_reduction = red;
        }
        let paras = text::read_paras(dom, tb, &levels, &ctx.scheme, &env);
        let c = ctx.clone();
        text::layout(paras, &body, w, h, &mut self.fonts, &move |f: &str| c.font(f), &env)
    }

    fn draw_prompt(&mut self, deck: &mut Deck, ctx: &Context, cr: &cairo::Context, it: &Item, w: f64, h: f64, env: &Env) {
        let Some(ph) = scene::ph_of(it.dom, it.node) else { return };
        // dashed edge
        cr.save().ok();
        cr.rectangle(0.0, 0.0, w, h);
        cr.set_source_rgb(0.6, 0.6, 0.6);
        cr.set_line_width(0.75);
        cr.set_dash(&[3.0, 2.0], 0.0);
        cr.stroke().ok();
        cr.restore().ok();
        // the layout's prompt text, else PowerPoint's
        let inh = scene::inherit(deck, ctx, it.part, &ph);
        let mut prompt = String::new();
        if let Some((l, ln)) = &inh.layout {
            if let Ok(d) = deck.pkg.xml(l) {
                if let Some(tb) = d.child(*ln, "p:txBody") {
                    prompt = text::plain_text(d, tb).join("\n");
                }
            }
        }
        if prompt.trim().is_empty() {
            prompt = prompt_for(&ph.kind).to_string();
        }
        if prompt.is_empty() {
            return;
        }
        let levels = scene::text_levels(deck, ctx, it.part, it.node);
        let body = scene::body_props(deck, ctx, it.part, it.node);
        let paras: Vec<Para> = prompt.split('\n').map(|t| {
            let mut props = levels[0].clone();
            if matches!(ph.kind.as_str(), "pic" | "tbl" | "chart" | "media") {
                props.bullet = Some(scene::Bullet::None);
            }
            Para { node: None, level: 0, props: props.clone(), end: props.def.clone(),
                   pieces: vec![text::Piece { text: t.to_string(), props: props.def.clone(), node: None, kind: text::PieceKind::Run }] }
        }).collect();
        let c = ctx.clone();
        let lay = text::layout(paras, &body, w, h, &mut self.fonts, &move |f: &str| c.font(f), env);
        self.draw_text(cr, &lay, w, h, &body, false);
    }

    /// Draw laid-out text in a w x h box (the context at the box's top-left).
    pub fn draw_text(&mut self, cr: &cairo::Context, lay: &Layout, w: f64, h: f64, body: &scene::BodyP, flip_v: bool) {
        cr.save().ok();
        if flip_v {
            cr.translate(w, h);
            cr.rotate(PI);
        }
        match body.vert.as_str() {
            "vert" | "eaVert" => {
                cr.translate(w, 0.0);
                cr.rotate(PI / 2.0);
            }
            "vert270" => {
                cr.translate(0.0, h);
                cr.rotate(-PI / 2.0);
            }
            _ => {}
        }
        if body.rot != 0.0 {
            cr.translate(w / 2.0, h / 2.0);
            cr.rotate(body.rot.to_radians());
            cr.translate(-w / 2.0, -h / 2.0);
        }
        for l in &lay.lines {
            if let Some(b) = &l.bullet {
                self.draw_seg(cr, b, lay.x, lay.y + l.baseline);
            }
            for s in &l.segs {
                if let Some(hc) = s.highlight {
                    hc.set(cr);
                    cr.rectangle(lay.x + s.x0, lay.y + l.top, s.x1 - s.x0, l.height);
                    cr.fill().ok();
                }
                self.draw_seg(cr, s, lay.x, lay.y + l.baseline);
            }
        }
        cr.restore().ok();
    }

    fn draw_seg(&mut self, cr: &cairo::Context, s: &Seg, x0: f64, base: f64) {
        if s.no_fill {
            return;
        }
        let y = base - s.rise;
        let glyphs: Vec<cairo::Glyph> = s.glyphs.iter().map(|g| cairo::Glyph::new(g.0 as _, x0 + g.1, y - g.2)).collect();
        let Some(face) = self.face(&s.font) else { return };
        cr.save().ok();
        cr.set_font_face(&face);
        let size = s.size;
        let m = if s.italic && s.font.synth_italic {
            cairo::Matrix::new(size, 0.0, -0.2 * size, size, 0.0, 0.0)
        } else {
            cairo::Matrix::new(size, 0.0, 0.0, size, 0.0, 0.0)
        };
        cr.set_font_matrix(m);
        let mut fo = cairo::FontOptions::new().unwrap();
        fo.set_hint_style(cairo::HintStyle::None);
        fo.set_hint_metrics(cairo::HintMetrics::Off);
        fo.set_antialias(cairo::Antialias::Gray);
        cr.set_font_options(&fo);
        s.color.set(cr);
        if s.bold && s.font.synth_bold {
            cr.glyph_path(&glyphs);
            cr.set_line_width(size / 28.0);
            cr.fill_preserve().ok();
            cr.stroke().ok();
        } else {
            cr.show_glyphs(&glyphs).ok();
        }
        let upem = s.font.upem.max(1.0);
        if s.underline {
            let pos = -s.font.underline_pos / upem * size;
            let th = (s.font.underline_thick / upem * size).max(size / 20.0);
            cr.rectangle(x0 + s.x0, y + pos.max(size * 0.08), s.x1 - s.x0, th);
            cr.fill().ok();
        }
        if s.strike {
            let pos = s.font.strike_pos / upem * size;
            let th = (s.font.strike_thick / upem * size).max(size / 20.0);
            let pos = if pos > 0.0 { pos } else { size * 0.3 };
            cr.rectangle(x0 + s.x0, y - pos, s.x1 - s.x0, th);
            cr.fill().ok();
        }
        cr.restore().ok();
    }

    fn draw_table(&mut self, deck: &mut Deck, ctx: &Context, cr: &cairo::Context, it: &Item, tbl: NodeId, env: &Env) {
        let dom = it.dom;
        let cols: Vec<f64> = dom.child(tbl, "a:tblGrid").map(|g| dom.children_named(g, "a:gridCol")
            .map(|c| emu(dom, c, "w").unwrap_or(0.0) / EMU_PT).collect()).unwrap_or_default();
        let tpr = dom.child(tbl, "a:tblPr");
        let flag = |k: &str| tpr.and_then(|t| dom.attr(t, k)).map(|v| v == "1" || v == "true").unwrap_or(false);
        let (first_row, band_row, first_col, last_row) = (flag("firstRow"), flag("bandRow"), flag("firstCol"), flag("lastRow"));
        let styled = tpr.and_then(|t| dom.child(t, "a:tableStyleId")).is_some() || tpr.is_some_and(|t| dom.elements(t).next().is_none());
        let accent = Rgba::new(ctx.scheme.named("accent1"));
        let tint = |c: Rgba, t: f64| {
            let f = |v: f64| v + (1.0 - v) * t;
            Rgba { rgb: (((f(c.r()) * 255.0).round() as u32) << 16) | (((f(c.g()) * 255.0).round() as u32) << 8) | ((f(c.b()) * 255.0).round() as u32), a: 1.0 }
        };
        let rows: Vec<NodeId> = dom.children_named(tbl, "a:tr").collect();
        // row heights grow to fit their text
        let mut heights: Vec<f64> = rows.iter().map(|r| emu(dom, *r, "h").unwrap_or(0.0) / EMU_PT).collect();
        let mut cells: Vec<(usize, usize, NodeId, f64, f64, Layout)> = Vec::new();
        let levels = {
            let mut lv: [crate::scene::ParaP; 9] = Default::default();
            let pres = deck.pres.clone();
            if let Ok(d) = deck.pkg.xml(&pres) {
                if let Some(n) = d.child(d.root, "p:defaultTextStyle") {
                    lv = crate::scene::read_levels(d, n, &ctx.scheme);
                }
            }
            lv
        };
        let nrows = rows.len();
        for (ri, r) in rows.iter().enumerate() {
            for (ci, c) in dom.children_named(*r, "a:tc").enumerate() {
                if dom.attr(c, "hMerge").is_some() || dom.attr(c, "vMerge").is_some() {
                    continue;
                }
                let span = emu(dom, c, "gridSpan").unwrap_or(1.0) as usize;
                let cw: f64 = cols.iter().skip(ci).take(span.max(1)).sum();
                let pr = dom.child(c, "a:tcPr");
                let m = |k: &str, d: f64| pr.and_then(|p| emu(dom, p, k)).map(|v| v / EMU_PT).unwrap_or(d);
                let mut body = crate::scene::default_body();
                body.l = m("marL", 7.2);
                body.r = m("marR", 7.2);
                body.t = m("marT", 3.6);
                body.b = m("marB", 3.6);
                if let Some(a) = pr.and_then(|p| dom.attr(p, "anchor")) {
                    body.anchor = a.to_string();
                }
                let mut lv = levels.clone();
                let header = styled && ((first_row && ri == 0) || (last_row && ri + 1 == nrows));
                for l in lv.iter_mut() {
                    l.bullet = Some(crate::scene::Bullet::None);
                    l.mar_l = Some(0.0);
                    l.indent = Some(0.0);
                    if header || (styled && first_col && ci == 0) {
                        l.def.b = Some(true);
                    }
                    if header {
                        l.def.color = Some(Rgba::new(ctx.scheme.named("lt1")));
                    } else if l.def.color.is_none() || styled {
                        l.def.color = Some(Rgba::new(ctx.scheme.named("dk1")));
                    }
                }
                let lay = match dom.child(c, "a:txBody") {
                    Some(tb) => {
                        let paras = text::read_paras(dom, tb, &lv, &ctx.scheme, env);
                        let cc = ctx.clone();
                        text::layout(paras, &body, cw, heights[ri], &mut self.fonts, &move |f: &str| cc.font(f), env)
                    }
                    None => Layout::default(),
                };
                let need = lay.height + body.t + body.b;
                let rspan = emu(dom, c, "rowSpan").unwrap_or(1.0) as usize;
                if rspan <= 1 && need > heights[ri] {
                    heights[ri] = need;
                }
                let x: f64 = cols.iter().take(ci).sum();
                cells.push((ri, ci, c, x, cw, lay));
            }
        }
        let tops: Vec<f64> = heights.iter().scan(0.0, |acc, h| { let t = *acc; *acc += h; Some(t) }).collect();
        for (ri, ci, c, x, cw, lay) in &cells {
            let rspan = emu(dom, *c, "rowSpan").unwrap_or(1.0) as usize;
            let ch: f64 = heights.iter().skip(*ri).take(rspan.max(1)).sum();
            let y = tops[*ri];
            let pr = dom.child(*c, "a:tcPr");
            // the cell's fill, else the table style's
            let own = pr.and_then(|p| fill_of(deck, &ctx.scheme, it.part, dom, p, None));
            let fill = own.unwrap_or_else(|| {
                if !styled {
                    Fill::None
                } else if (first_row && *ri == 0) || (last_row && *ri + 1 == nrows) {
                    Fill::Solid(accent)
                } else if band_row && (*ri - usize::from(first_row)) % 2 == 0 {
                    Fill::Solid(tint(accent, 0.6))
                } else {
                    Fill::Solid(tint(accent, 0.8))
                }
            });
            cr.rectangle(*x, y, *cw, ch);
            self.paint_fill(deck, cr, &fill, *cw, ch, (*x, y, *cw, ch));
            // borders
            let mut any = false;
            for (k, x0, y0, x1, y1) in [("a:lnL", *x, y, *x, y + ch), ("a:lnR", *x + cw, y, *x + cw, y + ch),
                                         ("a:lnT", *x, y, *x + cw, y), ("a:lnB", *x, y + ch, *x + cw, y + ch)] {
                if let Some(ln) = pr.and_then(|p| dom.child(p, k)) {
                    any = true;
                    if dom.child(ln, "a:noFill").is_some() {
                        continue;
                    }
                    if let Some(Fill::Solid(col)) = fill_of(deck, &ctx.scheme, it.part, dom, ln, None) {
                        col.set(cr);
                        cr.set_line_width(emu(dom, ln, "w").unwrap_or(12700.0) / EMU_PT);
                        cr.move_to(x0, y0);
                        cr.line_to(x1, y1);
                        cr.stroke().ok();
                    }
                }
            }
            if !any && styled {
                cr.set_source_rgb(1.0, 1.0, 1.0);
                cr.set_line_width(1.0);
                cr.rectangle(*x, y, *cw, ch);
                cr.stroke().ok();
            }
            cr.save().ok();
            cr.translate(*x, y);
            // anchor again now the row height is known
            let mut lay2 = lay.clone();
            let anchor = pr.and_then(|p| dom.attr(p, "anchor")).unwrap_or("t");
            let th = ch - (lay.y) - 3.6;
            lay2.y = match anchor {
                "ctr" => (ch - lay.height) / 2.0,
                "b" => th - lay.height + lay.y,
                _ => lay.y,
            };
            self.draw_text(cr, &lay2, *cw, ch, &crate::scene::default_body(), false);
            cr.restore().ok();
        }
    }

    /// SmartArt: the drawing PowerPoint saved with it.
    #[allow(clippy::too_many_arguments)]
    fn draw_diagram(&mut self, deck: &mut Deck, ctx: &Context, cr: &cairo::Context, it: &Item, w: f64, h: f64, env: &Env) {
        let rels = deck.pkg.rels(it.part);
        let Some(r) = rels.iter().find(|r| r.kind.ends_with("/diagramDrawing")) else {
            cr.rectangle(0.0, 0.0, w, h);
            cr.set_source_rgba(0.5, 0.5, 0.5, 0.15);
            cr.fill().ok();
            return;
        };
        let target = Package::resolve(it.part, &r.target);
        let Ok(d) = deck.pkg.xml(&target) else { return };
        let d = d.clone();
        let Some(tree) = path(&d, d.root, &["dsp:spTree"]) else { return };
        for sp in d.elements(tree).collect::<Vec<_>>() {
            if d.name(sp) != "dsp:sp" {
                continue;
            }
            let Some(sppr) = d.child(sp, "dsp:spPr") else { continue };
            let Some(xf) = d.child(sppr, "a:xfrm") else { continue };
            let off = d.child(xf, "a:off");
            let ext = d.child(xf, "a:ext");
            let (x, y) = (off.and_then(|o| emu(&d, o, "x")).unwrap_or(0.0) / EMU_PT, off.and_then(|o| emu(&d, o, "y")).unwrap_or(0.0) / EMU_PT);
            let (sw, shh) = (ext.and_then(|o| emu(&d, o, "cx")).unwrap_or(0.0) / EMU_PT, ext.and_then(|o| emu(&d, o, "cy")).unwrap_or(0.0) / EMU_PT);
            let rot = emu(&d, xf, "rot").unwrap_or(0.0) / 60000.0;
            cr.save().ok();
            cr.translate(x + sw / 2.0, y + shh / 2.0);
            cr.rotate(rot.to_radians());
            cr.translate(-sw / 2.0, -shh / 2.0);
            let mut sh = Shape::parse_sppr(&d, sppr, &HashMap::new());
            let fill = fill_of(deck, &ctx.scheme, &target, &d, sppr, None).or_else(|| {
                let fr = path(&d, sp, &["dsp:style", "a:fillRef"])?;
                let ph = ctx.scheme.color_in(&d, fr, None);
                let idx = emu(&d, fr, "idx").unwrap_or(0.0) as usize;
                if idx == 0 { Some(Fill::None) } else { theme_style(deck, ctx, "a:fillStyleLst", idx, ph).or(ph.map(Fill::Solid)) }
            }).unwrap_or(Fill::None);
            if sh.outline(cr, sw, shh) {
                self.paint_fill(deck, cr, &fill, sw, shh, (0.0, 0.0, sw, shh));
            }
            cr.new_path();
            let line = d.child(sppr, "a:ln").and_then(|ln| if d.child(ln, "a:noFill").is_some() { None } else {
                fill_of(deck, &ctx.scheme, &target, &d, ln, None).map(|f| (emu(&d, ln, "w").unwrap_or(12700.0) / EMU_PT, f))
            }).or_else(|| {
                let lr = path(&d, sp, &["dsp:style", "a:lnRef"])?;
                let idx = emu(&d, lr, "idx").unwrap_or(0.0) as usize;
                if idx == 0 { return None; }
                let ph = ctx.scheme.color_in(&d, lr, None);
                theme_line(deck, ctx, idx, ph).map(|(w, f, _)| (w, f))
            });
            if let Some((lw, Fill::Solid(c))) = line {
                sh.fill = None;
                sh.line = Some((lw, c.rgb, "solid".into()));
                sh.draw(cr, sw, shh);
            }
            if let Some(tb) = d.child(sp, "dsp:txBody") {
                let mut body = crate::scene::default_body();
                if let Some(bp) = d.child(tb, "a:bodyPr") {
                    crate::scene::apply_body(&mut body, &d, bp);
                }
                let mut lv: [crate::scene::ParaP; 9] = Default::default();
                if let Some(fr) = path(&d, sp, &["dsp:style", "a:fontRef"]) {
                    let c = ctx.scheme.color_in(&d, fr, None);
                    for l in lv.iter_mut() {
                        l.def.color = c;
                    }
                }
                if let Some(ls) = d.child(tb, "a:lstStyle") {
                    let more = crate::scene::read_levels(&d, ls, &ctx.scheme);
                    crate::scene::merge_levels(&mut lv, &more);
                }
                let (tx, ty, tw, th) = match d.child(sp, "dsp:txXfrm") {
                    Some(t) => {
                        let o = d.child(t, "a:off");
                        let e = d.child(t, "a:ext");
                        (o.and_then(|o| emu(&d, o, "x")).unwrap_or(0.0) / EMU_PT - x, o.and_then(|o| emu(&d, o, "y")).unwrap_or(0.0) / EMU_PT - y,
                         e.and_then(|o| emu(&d, o, "cx")).unwrap_or(0.0) / EMU_PT, e.and_then(|o| emu(&d, o, "cy")).unwrap_or(0.0) / EMU_PT)
                    }
                    None => (0.0, 0.0, sw, shh),
                };
                let paras = text::read_paras(&d, tb, &lv, &ctx.scheme, env);
                let cc = ctx.clone();
                let lay = text::layout(paras, &body, tw, th, &mut self.fonts, &move |f: &str| cc.font(f), env);
                cr.save().ok();
                cr.translate(tx, ty);
                self.draw_text(cr, &lay, tw, th, &body, false);
                cr.restore().ok();
            }
            cr.restore().ok();
        }
    }
}

fn rect_shape() -> Shape {
    Shape { geom: "rect".into(), fill: None, line: None, adj: Vec::new(), ends: (false, false), custom: Vec::new() }
}

/// The shapes of a tree in drawing order (alternate content: the fallback).
pub fn kids(dom: &XmlDoc, tree: NodeId) -> Vec<NodeId> {
    let mut out = Vec::new();
    for c in dom.elements(tree) {
        match dom.name(c) {
            "p:sp" | "p:pic" | "p:graphicFrame" | "p:cxnSp" | "p:grpSp" => out.push(c),
            "mc:AlternateContent" => {
                let pick = dom.child(c, "mc:Choice").filter(|ch| {
                    let req = dom.attr(*ch, "Requires").unwrap_or("");
                    req.split_whitespace().all(|r| matches!(r, "p14" | "p15" | "a14" | "v" | "p159"))
                        && !dom.elements(*ch).any(|e| dom.name(e) == "p:sp" && dom.child(e, "p:txBody")
                            .is_some_and(|tb| has_math(dom, tb)))
                }).or_else(|| dom.child(c, "mc:Fallback"));
                if let Some(p) = pick {
                    out.extend(kids(dom, p));
                }
            }
            _ => {}
        }
    }
    out
}

fn has_math(dom: &XmlDoc, n: NodeId) -> bool {
    dom.elements(n).any(|c| dom.name(c) == "a14:m" || has_math(dom, c))
}

/// A blipFill: the picture part, its crop and tiling.
pub fn blip_fill(deck: &mut Deck, part: &str, dom: &XmlDoc, bf: NodeId) -> Option<Fill> {
    let blip = dom.child(bf, "a:blip")?;
    let rid = dom.attr(blip, "r:embed").or_else(|| dom.attr(blip, "r:link"))?;
    let target = Package::resolve(part, &deck.pkg.rel_target(part, rid)?);
    let mut crop = [0.0; 4];
    if let Some(sr) = dom.child(bf, "a:srcRect") {
        for (i, k) in ["l", "t", "r", "b"].iter().enumerate() {
            crop[i] = emu(dom, sr, k).unwrap_or(0.0) / 100000.0;
        }
    }
    let alpha = dom.child(blip, "a:alphaModFix").and_then(|a| emu(dom, a, "amt")).map(|v| v / 100000.0).unwrap_or(1.0);
    Some(Fill::Pic(target, crop, dom.child(bf, "a:tile").is_some(), alpha))
}

/// The fill named in a spPr-like element (None: not named here, inherit).
pub fn fill_of(deck: &mut Deck, scheme: &Scheme, part: &str, dom: &XmlDoc, n: NodeId, ph: Option<Rgba>) -> Option<Fill> {
    for c in dom.elements(n) {
        match dom.name(c) {
            "a:noFill" => return Some(Fill::None),
            "a:solidFill" => return Some(scheme.color_in(dom, c, ph).map(Fill::Solid).unwrap_or(Fill::None)),
            "a:gradFill" => {
                let mut stops: Vec<(f64, Rgba)> = dom.child(c, "a:gsLst").map(|l| dom.children_named(l, "a:gs")
                    .filter_map(|g| Some((emu(dom, g, "pos").unwrap_or(0.0) / 100000.0, scheme.color_in(dom, g, ph)?)))
                    .collect()).unwrap_or_default();
                stops.sort_by(|a, b| a.0.partial_cmp(&b.0).unwrap_or(std::cmp::Ordering::Equal));
                let ang = dom.child(c, "a:lin").and_then(|l| emu(dom, l, "ang")).map(|v| v / 60000.0).unwrap_or(90.0);
                let kind = dom.child(c, "a:path").map(|p| dom.attr(p, "path").unwrap_or("circle").to_string());
                if stops.is_empty() {
                    return Some(Fill::None);
                }
                return Some(Fill::Grad(stops, ang, kind));
            }
            "a:blipFill" => return blip_fill(deck, part, dom, c).or(Some(Fill::None)),
            "a:pattFill" => {
                let fg = dom.child(c, "a:fgClr").and_then(|f| scheme.color_in(dom, f, ph)).unwrap_or(Rgba::new(0));
                let bg = dom.child(c, "a:bgClr").and_then(|f| scheme.color_in(dom, f, ph)).unwrap_or(Rgba::new(0xFFFFFF));
                return Some(Fill::Patt(fg, bg, dom.attr(c, "prst").unwrap_or("pct50").to_string()));
            }
            "a:grpFill" => return Some(Fill::None),
            _ => {}
        }
    }
    None
}

/// A theme style list entry (fillStyleLst / bgFillStyleLst, 1-based) with phClr.
fn theme_style(deck: &mut Deck, ctx: &Context, list: &str, idx: usize, ph: Option<Rgba>) -> Option<Fill> {
    let t = ctx.theme.clone()?;
    let dom = deck.pkg.xml(&t).ok()?.clone();
    let l = path(&dom, dom.root, &["a:themeElements", "a:fmtScheme", list])?;
    let entry = dom.elements(l).nth(idx.checked_sub(1)?)?;
    // wrap: fill_of looks at children
    let parent = dom.parent(entry)?;
    let _ = parent;
    let name = dom.name(entry).to_string();
    match name.as_str() {
        "a:noFill" => Some(Fill::None),
        "a:solidFill" => ctx.scheme.color_in(&dom, entry, ph).map(Fill::Solid),
        _ => {
            // fill_of needs a container: find this entry among the list's children
            let mut tmp = XmlDoc::with_root("x", &[]);
            let imported = tmp.import_node(&dom, entry);
            let root = tmp.root;
            tmp.append(root, imported);
            fill_of(deck, &ctx.scheme, &t, &tmp, root, ph)
        }
    }
}

fn theme_line(deck: &mut Deck, ctx: &Context, idx: usize, ph: Option<Rgba>) -> Option<(f64, Fill, String)> {
    let t = ctx.theme.clone()?;
    let dom = deck.pkg.xml(&t).ok()?.clone();
    let l = path(&dom, dom.root, &["a:themeElements", "a:fmtScheme", "a:lnStyleLst"])?;
    let ln = dom.elements(l).nth(idx.checked_sub(1)?)?;
    let w = emu(&dom, ln, "w").unwrap_or(9525.0) / EMU_PT;
    let f = fill_of(deck, &ctx.scheme, &t, &dom, ln, ph).unwrap_or(ph.map(Fill::Solid).unwrap_or(Fill::None));
    let dash = dom.child(ln, "a:prstDash").and_then(|d| dom.attr(d, "val")).unwrap_or("solid").to_string();
    Some((w, f, dash))
}

/// Unused helper kept for callers that only have a Ph.
pub fn is_title(ph: &Option<Ph>) -> bool {
    ph.as_ref().is_some_and(|p| p.kind == "title" || p.kind == "ctrTitle")
}

/// An 8x8 tile for a preset pattern (in points: one cell is one point).
fn pattern_tile(fg: &Rgba, bg: &Rgba, prst: &str) -> Option<cairo::ImageSurface> {
    // rows of 8 bits, MSB at the left
    let rows: [u8; 8] = match prst {
        "horz" => [0xFF, 0, 0, 0, 0xFF, 0, 0, 0],
        "ltHorz" => [0xFF, 0, 0, 0, 0, 0, 0, 0],
        "narHorz" => [0xFF, 0, 0xFF, 0, 0xFF, 0, 0xFF, 0],
        "dkHorz" => [0xFF, 0xFF, 0, 0, 0xFF, 0xFF, 0, 0],
        "wdHorz" => [0xFF, 0xFF, 0xFF, 0, 0, 0, 0, 0],
        "vert" => [0x88; 8],
        "ltVert" => [0x80; 8],
        "narVert" => [0xAA; 8],
        "dkVert" => [0xCC; 8],
        "wdVert" => [0xE0; 8],
        "cross" | "smGrid" => [0xFF, 0x88, 0x88, 0x88, 0xFF, 0x88, 0x88, 0x88],
        "lgGrid" => [0xFF, 0x80, 0x80, 0x80, 0x80, 0x80, 0x80, 0x80],
        "dotGrid" => [0xAA, 0, 0x80, 0, 0x80, 0, 0x80, 0],
        "dnDiag" | "ltDnDiag" => [0x80, 0x40, 0x20, 0x10, 0x08, 0x04, 0x02, 0x01],
        "upDiag" | "ltUpDiag" => [0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80],
        "dkDnDiag" | "wdDnDiag" => [0xC1, 0xE0, 0x70, 0x38, 0x1C, 0x0E, 0x07, 0x83],
        "dkUpDiag" | "wdUpDiag" => [0x83, 0x07, 0x0E, 0x1C, 0x38, 0x70, 0xE0, 0xC1],
        "diagCross" | "smCheck" => [0x81, 0x42, 0x24, 0x18, 0x18, 0x24, 0x42, 0x81],
        "pct5" => [0x80, 0, 0, 0, 0x08, 0, 0, 0],
        "pct10" => [0x80, 0, 0x08, 0, 0x80, 0, 0x08, 0],
        "pct20" => [0x88, 0, 0x22, 0, 0x88, 0, 0x22, 0],
        "pct25" => [0x88, 0x22, 0x88, 0x22, 0x88, 0x22, 0x88, 0x22],
        "pct30" => [0xAA, 0x44, 0xAA, 0x11, 0xAA, 0x44, 0xAA, 0x11],
        "pct40" => [0xAA, 0x55, 0xAA, 0x15, 0xAA, 0x55, 0xAA, 0x51],
        "pct50" => [0xAA, 0x55, 0xAA, 0x55, 0xAA, 0x55, 0xAA, 0x55],
        "pct60" => [0xEE, 0x55, 0xBB, 0x55, 0xEE, 0x55, 0xBB, 0x55],
        "pct70" => [0x77, 0xFF, 0xDD, 0xFF, 0x77, 0xFF, 0xDD, 0xFF],
        "pct75" => [0x77, 0xDD, 0x77, 0xDD, 0x77, 0xDD, 0x77, 0xDD],
        "pct80" => [0xF7, 0xFF, 0x7F, 0xFF, 0xF7, 0xFF, 0x7F, 0xFF],
        "pct90" => [0xFF, 0xF7, 0xFF, 0xFF, 0xFF, 0x7F, 0xFF, 0xFF],
        "lgCheck" => [0xF0, 0xF0, 0xF0, 0xF0, 0x0F, 0x0F, 0x0F, 0x0F],
        _ => return None,
    };
    let mut surf = cairo::ImageSurface::create(cairo::Format::ARgb32, 8, 8).ok()?;
    let stride = surf.stride() as usize;
    {
        let mut data = surf.data().ok()?;
        let px = |c: &Rgba| {
            let a = c.a.clamp(0.0, 1.0);
            let p = |v: f64| (v * a * 255.0).round() as u8;
            [p(c.b()), p(c.g()), p(c.r()), (a * 255.0).round() as u8]
        };
        let (f, b) = (px(fg), px(bg));
        for (y, row) in rows.iter().enumerate() {
            for x in 0..8 {
                let on = row & (0x80 >> x) != 0;
                let v = if on { f } else { b };
                data[y * stride + x * 4..y * stride + x * 4 + 4].copy_from_slice(&v);
            }
        }
    }
    Some(surf)
}

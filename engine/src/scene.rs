//! What a slide shows: its shapes and the layout's and master's, with placeholders
//! inheriting position, look and text styles from the layout and the master.

use crate::color::{Rgba, Scheme};
use crate::model::{emu, path, Deck, EMU_PT};
use folio_core::xml::{NodeId, XmlDoc};

#[derive(Clone, Debug, PartialEq)]
pub enum Spc {
    Pct(f64),
    Pts(f64),
}

#[derive(Clone, Debug, PartialEq)]
pub enum Bullet {
    None,
    Char(String),
    Auto(String, i32),
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct RunP {
    pub sz: Option<f64>,
    pub b: Option<bool>,
    pub i: Option<bool>,
    pub u: Option<String>,
    pub strike: Option<String>,
    pub latin: Option<String>,
    pub color: Option<Rgba>,
    pub baseline: Option<f64>,
    pub cap: Option<String>,
    pub spc: Option<f64>,
    pub highlight: Option<Rgba>,
    pub link: Option<String>,
    pub no_fill: bool,
}

impl RunP {
    pub fn merge(&mut self, o: &RunP) {
        macro_rules! m { ($($f:ident),*) => { $( if o.$f.is_some() { self.$f = o.$f.clone(); } )* } }
        m!(sz, b, i, u, strike, latin, color, baseline, cap, spc, highlight, link);
        if o.no_fill {
            self.no_fill = true;
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ParaP {
    pub algn: Option<String>,
    pub mar_l: Option<f64>,
    pub indent: Option<f64>,
    pub ln_spc: Option<Spc>,
    pub spc_bef: Option<Spc>,
    pub spc_aft: Option<Spc>,
    pub bullet: Option<Bullet>,
    /// None: follow the text colour
    pub bu_clr: Option<Option<Rgba>>,
    /// percent of the text size (Some(None): follow the text)
    pub bu_sz: Option<Option<f64>>,
    pub bu_font: Option<Option<String>>,
    pub def_tab: Option<f64>,
    pub tabs: Option<Vec<(f64, String)>>,
    pub def: RunP,
}

impl ParaP {
    pub fn merge(&mut self, o: &ParaP) {
        macro_rules! m { ($($f:ident),*) => { $( if o.$f.is_some() { self.$f = o.$f.clone(); } )* } }
        m!(algn, mar_l, indent, ln_spc, spc_bef, spc_aft, bullet, bu_clr, bu_sz, bu_font, def_tab, tabs);
        self.def.merge(&o.def);
    }
}

fn spc(dom: &XmlDoc, n: NodeId) -> Option<Spc> {
    if let Some(p) = dom.child(n, "a:spcPct") {
        return Some(Spc::Pct(emu(dom, p, "val").unwrap_or(100000.0) / 100000.0));
    }
    if let Some(p) = dom.child(n, "a:spcPts") {
        return Some(Spc::Pts(emu(dom, p, "val").unwrap_or(0.0) / 100.0));
    }
    None
}

fn on(v: &str) -> bool {
    matches!(v, "1" | "true" | "on")
}

pub fn read_rpr(dom: &XmlDoc, n: NodeId, scheme: &Scheme) -> RunP {
    let mut r = RunP::default();
    if let Some(v) = emu(dom, n, "sz") {
        r.sz = Some(v / 100.0);
    }
    if let Some(v) = dom.attr(n, "b") {
        r.b = Some(on(v));
    }
    if let Some(v) = dom.attr(n, "i") {
        r.i = Some(on(v));
    }
    if let Some(v) = dom.attr(n, "u") {
        r.u = Some(v.to_string());
    }
    if let Some(v) = dom.attr(n, "strike") {
        r.strike = Some(v.to_string());
    }
    if let Some(v) = emu(dom, n, "baseline") {
        r.baseline = Some(v / 1000.0);
    }
    if let Some(v) = dom.attr(n, "cap") {
        r.cap = Some(v.to_string());
    }
    if let Some(v) = emu(dom, n, "spc") {
        r.spc = Some(v / 100.0);
    }
    for c in dom.elements(n) {
        match dom.name(c) {
            "a:solidFill" => r.color = scheme.color_in(dom, c, None),
            "a:gradFill" => {
                // the first stop stands for the gradient
                if let Some(gs) = dom.child(c, "a:gsLst").and_then(|l| dom.elements(l).next()) {
                    r.color = scheme.color_in(dom, gs, None);
                }
            }
            "a:noFill" => r.no_fill = true,
            "a:latin" => r.latin = dom.attr(c, "typeface").map(|s| s.to_string()),
            "a:highlight" => r.highlight = scheme.color_in(dom, c, None),
            "a:hlinkClick" => {
                let rid = dom.attr(c, "r:id").unwrap_or("");
                let act = dom.attr(c, "action").unwrap_or("");
                if !rid.is_empty() || !act.is_empty() {
                    r.link = Some(format!("{rid}\t{act}"));
                }
            }
            _ => {}
        }
    }
    if r.link.is_some() {
        // links show in the theme's link colour, underlined
        r.color = Some(Rgba::new(scheme.named("hlink")));
        r.u = Some("sng".to_string());
    }
    r
}

pub fn read_ppr(dom: &XmlDoc, n: NodeId, scheme: &Scheme) -> ParaP {
    let mut p = ParaP::default();
    if let Some(v) = dom.attr(n, "algn") {
        p.algn = Some(v.to_string());
    }
    if let Some(v) = emu(dom, n, "marL") {
        p.mar_l = Some(v / EMU_PT);
    }
    if let Some(v) = emu(dom, n, "indent") {
        p.indent = Some(v / EMU_PT);
    }
    if let Some(v) = emu(dom, n, "defTabSz") {
        p.def_tab = Some(v / EMU_PT);
    }
    for c in dom.elements(n) {
        match dom.name(c) {
            "a:lnSpc" => p.ln_spc = spc(dom, c),
            "a:spcBef" => p.spc_bef = spc(dom, c),
            "a:spcAft" => p.spc_aft = spc(dom, c),
            "a:buClrTx" => p.bu_clr = Some(None),
            "a:buClr" => p.bu_clr = Some(scheme.color_in(dom, c, None)),
            "a:buSzTx" => p.bu_sz = Some(None),
            "a:buSzPct" => p.bu_sz = Some(Some(emu(dom, c, "val").unwrap_or(100000.0) / 100000.0)),
            "a:buSzPts" => p.bu_sz = Some(Some(-(emu(dom, c, "val").unwrap_or(1200.0) / 100.0))),
            "a:buFontTx" => p.bu_font = Some(None),
            "a:buFont" => p.bu_font = Some(dom.attr(c, "typeface").map(|s| s.to_string())),
            "a:buNone" => p.bullet = Some(Bullet::None),
            "a:buChar" => p.bullet = Some(Bullet::Char(dom.attr(c, "char").unwrap_or("\u{2022}").to_string())),
            "a:buAutoNum" => p.bullet = Some(Bullet::Auto(dom.attr(c, "type").unwrap_or("arabicPeriod").to_string(),
                                                          emu(dom, c, "startAt").unwrap_or(1.0) as i32)),
            "a:buBlip" => p.bullet = Some(Bullet::Char("\u{25A0}".into())),
            "a:tabLst" => {
                p.tabs = Some(dom.children_named(c, "a:tab")
                    .map(|t| (emu(dom, t, "pos").unwrap_or(0.0) / EMU_PT, dom.attr(t, "algn").unwrap_or("l").to_string()))
                    .collect());
            }
            "a:defRPr" => p.def = read_rpr(dom, c, scheme),
            _ => {}
        }
    }
    p
}

/// A list style (a:lstStyle, p:titleStyle, ...): its nine levels.
pub fn read_levels(dom: &XmlDoc, n: NodeId, scheme: &Scheme) -> [ParaP; 9] {
    let mut out: [ParaP; 9] = Default::default();
    if let Some(d) = dom.child(n, "a:defPPr") {
        let def = read_ppr(dom, d, scheme);
        for l in out.iter_mut() {
            l.merge(&def);
        }
    }
    for (i, l) in out.iter_mut().enumerate() {
        if let Some(c) = dom.child(n, &format!("a:lvl{}pPr", i + 1)) {
            l.merge(&read_ppr(dom, c, scheme));
        }
    }
    out
}

pub fn merge_levels(a: &mut [ParaP; 9], b: &[ParaP; 9]) {
    for (x, y) in a.iter_mut().zip(b.iter()) {
        x.merge(y);
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct BodyP {
    pub l: f64,
    pub t: f64,
    pub r: f64,
    pub b: f64,
    pub anchor: String,
    pub anchor_ctr: bool,
    pub wrap: bool,
    /// normAutofit: (font scale, line spacing reduction)
    pub norm_autofit: Option<(f64, f64)>,
    pub sp_autofit: bool,
    pub vert: String,
    pub num_col: u32,
    pub rot: f64,
}

pub fn default_body() -> BodyP {
    BodyP { l: 7.2, t: 3.6, r: 7.2, b: 3.6, anchor: "t".into(), anchor_ctr: false, wrap: true, norm_autofit: None,
            sp_autofit: false, vert: "horz".into(), num_col: 1, rot: 0.0 }
}

pub fn apply_body(b: &mut BodyP, dom: &XmlDoc, n: NodeId) {
    if let Some(v) = emu(dom, n, "lIns") {
        b.l = v / EMU_PT;
    }
    if let Some(v) = emu(dom, n, "tIns") {
        b.t = v / EMU_PT;
    }
    if let Some(v) = emu(dom, n, "rIns") {
        b.r = v / EMU_PT;
    }
    if let Some(v) = emu(dom, n, "bIns") {
        b.b = v / EMU_PT;
    }
    if let Some(v) = dom.attr(n, "anchor") {
        b.anchor = v.to_string();
    }
    if let Some(v) = dom.attr(n, "anchorCtr") {
        b.anchor_ctr = on(v);
    }
    if let Some(v) = dom.attr(n, "wrap") {
        b.wrap = v != "none";
    }
    if let Some(v) = dom.attr(n, "vert") {
        b.vert = v.to_string();
    }
    if let Some(v) = emu(dom, n, "numCol") {
        b.num_col = (v as u32).max(1);
    }
    if let Some(v) = emu(dom, n, "rot") {
        b.rot = v / 60000.0;
    }
    for c in dom.elements(n) {
        match dom.name(c) {
            "a:normAutofit" => {
                b.norm_autofit = Some((emu(dom, c, "fontScale").unwrap_or(100000.0) / 100000.0,
                                       emu(dom, c, "lnSpcReduction").unwrap_or(0.0) / 100000.0));
                b.sp_autofit = false;
            }
            "a:spAutoFit" => {
                b.sp_autofit = true;
                b.norm_autofit = None;
            }
            "a:noAutofit" => {
                b.sp_autofit = false;
                b.norm_autofit = None;
            }
            _ => {}
        }
    }
}

/// A placeholder: its type ("title", "body", "ctrTitle", "subTitle", "dt", "ftr",
/// "sldNum", "pic", "obj" ...) and index.
#[derive(Clone, Debug, PartialEq)]
pub struct Ph {
    pub kind: String,
    pub idx: Option<u32>,
}

pub fn ph_of(dom: &XmlDoc, sp: NodeId) -> Option<Ph> {
    let nv = dom.elements(sp).find(|&c| dom.name(c).starts_with("p:nv"))?;
    let nvpr = dom.child(nv, "p:nvPr")?;
    let ph = dom.child(nvpr, "p:ph")?;
    Some(Ph { kind: dom.attr(ph, "type").unwrap_or("body").to_string(), idx: emu(dom, ph, "idx").map(|v| v as u32) })
}

fn family(k: &str) -> &str {
    match k {
        "ctrTitle" | "title" => "title",
        "subTitle" | "body" | "obj" => "body",
        k => k,
    }
}

fn same_family(a: &str, b: &str) -> bool {
    family(a) == family(b)
}

/// The shape in `dom`'s tree that a placeholder `ph` inherits from.
pub fn find_ph(dom: &XmlDoc, ph: &Ph, by_type_only: bool) -> Option<NodeId> {
    let tree = path(dom, dom.root, &["p:cSld", "p:spTree"])?;
    let mut all = Vec::new();
    collect_shapes(dom, tree, &mut all);
    let cands: Vec<(NodeId, Ph)> = all.into_iter().filter_map(|n| ph_of(dom, n).map(|p| (n, p))).collect();
    if !by_type_only {
        if let Some(idx) = ph.idx {
            if let Some((n, _)) = cands.iter().find(|(_, p)| p.idx == Some(idx)) {
                return Some(*n);
            }
        }
        if let Some((n, _)) = cands.iter().find(|(_, p)| p.kind == ph.kind && (ph.idx.is_none() || p.idx.is_none())) {
            return Some(*n);
        }
        if let Some((n, _)) = cands.iter().find(|(_, p)| p.kind == ph.kind) {
            return Some(*n);
        }
    }
    let want = if by_type_only {
        match ph.kind.as_str() {
            "ctrTitle" => "title",
            "subTitle" | "obj" | "pic" | "tbl" | "chart" | "clipArt" | "dgm" | "media" => "body",
            k => k,
        }
    } else {
        ph.kind.as_str()
    };
    cands.iter().find(|(_, p)| p.kind == want).or_else(|| cands.iter().find(|(_, p)| same_family(&p.kind, want)))
        .map(|(n, _)| *n)
}

pub fn collect_shapes(dom: &XmlDoc, tree: NodeId, out: &mut Vec<NodeId>) {
    for c in dom.elements(tree) {
        match dom.name(c) {
            "p:sp" | "p:pic" | "p:graphicFrame" | "p:cxnSp" => out.push(c),
            "p:grpSp" => {
                out.push(c);
                collect_shapes(dom, c, out);
            }
            "mc:AlternateContent" => {
                if let Some(ch) = dom.child(c, "mc:Choice").or_else(|| dom.child(c, "mc:Fallback")) {
                    collect_shapes(dom, ch, out);
                }
            }
            _ => {}
        }
    }
}

/// The parts and nodes a slide shape inherits from: (layout, master).
#[derive(Clone, Debug, Default)]
pub struct Inherit {
    pub layout: Option<(String, NodeId)>,
    pub master: Option<(String, NodeId)>,
}

/// Everything about the theme and master a slide needs.
#[derive(Clone)]
pub struct Context {
    pub slide: String,
    pub layout: Option<String>,
    pub master: Option<String>,
    pub theme: Option<String>,
    pub scheme: Scheme,
    pub major: String,
    pub minor: String,
}

impl Context {
    pub fn font(&self, face: &str) -> String {
        match face {
            "+mj-lt" | "+mj-ea" | "+mj-cs" => self.major.clone(),
            "+mn-lt" | "+mn-ea" | "+mn-cs" | "" => self.minor.clone(),
            f => f.to_string(),
        }
    }
}

pub fn context(deck: &mut Deck, part: &str) -> Context {
    let (layout, master, theme) = deck.chain(part);
    let mut scheme = Scheme::office();
    let (mut major, mut minor) = ("Calibri Light".to_string(), "Calibri".to_string());
    if let Some(t) = &theme {
        if let Ok(dom) = deck.pkg.xml(t) {
            if let Some(te) = dom.child(dom.root, "a:themeElements") {
                if let Some(cs) = dom.child(te, "a:clrScheme") {
                    scheme.read_theme(dom, cs);
                }
                if let Some(fs) = dom.child(te, "a:fontScheme") {
                    if let Some(f) = path(dom, fs, &["a:majorFont", "a:latin"]).and_then(|l| dom.attr(l, "typeface")) {
                        major = f.to_string();
                    }
                    if let Some(f) = path(dom, fs, &["a:minorFont", "a:latin"]).and_then(|l| dom.attr(l, "typeface")) {
                        minor = f.to_string();
                    }
                }
            }
        }
    }
    if let Some(m) = &master {
        if let Ok(dom) = deck.pkg.xml(m) {
            if let Some(map) = dom.child(dom.root, "p:clrMap") {
                scheme.read_map(dom, map);
            }
        }
    }
    // a layout or slide can map colours its own way
    for p in [layout.clone(), Some(part.to_string())].into_iter().flatten() {
        if p.contains("slideMasters/") {
            continue;
        }
        if let Ok(dom) = deck.pkg.xml(&p) {
            if let Some(o) = path(dom, dom.root, &["p:clrMapOvr", "a:overrideClrMapping"]) {
                scheme.map.clear();
                scheme.read_map(dom, o);
            }
        }
    }
    Context { slide: part.to_string(), layout, master, theme, scheme, major, minor }
}

/// For a placeholder on `part`, the layout's and the master's placeholder it inherits from.
pub fn inherit(deck: &mut Deck, ctx: &Context, part: &str, ph: &Ph) -> Inherit {
    let mut out = Inherit::default();
    let is_master = part.contains("slideMasters/");
    let is_layout = part.contains("slideLayouts/");
    if !is_master && !is_layout {
        if let Some(l) = &ctx.layout {
            if let Ok(dom) = deck.pkg.xml(l) {
                if let Some(n) = find_ph(dom, ph, false) {
                    out.layout = Some((l.clone(), n));
                }
            }
        }
    }
    if !is_master {
        if let Some(m) = &ctx.master {
            // the master's placeholder of the layout placeholder's type
            let lph = out.layout.as_ref().and_then(|(l, n)| deck.pkg.xml(l).ok().and_then(|d| ph_of(d, *n)));
            let key = lph.unwrap_or_else(|| ph.clone());
            if let Ok(dom) = deck.pkg.xml(m) {
                if let Some(n) = find_ph(dom, &key, true) {
                    out.master = Some((m.clone(), n));
                }
            }
        }
    }
    out
}

/// The nine paragraph levels a shape's text starts from.
pub fn text_levels(deck: &mut Deck, ctx: &Context, part: &str, sp: NodeId) -> [ParaP; 9] {
    let ph = deck.pkg.xml(part).ok().and_then(|d| ph_of(d, sp));
    let mut lv: [ParaP; 9] = Default::default();
    // the master's style for this kind of text
    let style = match ph.as_ref().map(|p| p.kind.as_str()) {
        Some("title") | Some("ctrTitle") => Some("p:titleStyle"),
        Some("body") | Some("subTitle") | Some("obj") => Some("p:bodyStyle"),
        Some(_) => Some("p:otherStyle"),
        None => None,
    };
    if let Some(st) = style {
        if let Some(m) = &ctx.master {
            if let Ok(dom) = deck.pkg.xml(m) {
                if let Some(n) = path(dom, dom.root, &["p:txStyles", st]) {
                    lv = read_levels(dom, n, &ctx.scheme);
                }
            }
        }
    } else {
        let pres = deck.pres.clone();
        if let Ok(dom) = deck.pkg.xml(&pres) {
            if let Some(n) = dom.child(dom.root, "p:defaultTextStyle") {
                lv = read_levels(dom, n, &ctx.scheme);
            }
        }
        // the theme's text-box defaults
        if let Some(t) = &ctx.theme {
            if let Ok(dom) = deck.pkg.xml(t) {
                if let Some(n) = path(dom, dom.root, &["a:objectDefaults", "a:txDef", "a:lstStyle"]) {
                    let more = read_levels(dom, n, &ctx.scheme);
                    merge_levels(&mut lv, &more);
                }
            }
        }
    }
    if let Some(ph) = &ph {
        let inh = inherit(deck, ctx, part, ph);
        for (p, n) in [inh.master, inh.layout].into_iter().flatten() {
            if let Ok(dom) = deck.pkg.xml(&p) {
                if let Some(ls) = path(dom, n, &["p:txBody", "a:lstStyle"]) {
                    let more = read_levels(dom, ls, &ctx.scheme);
                    merge_levels(&mut lv, &more);
                }
            }
        }
    }
    if let Ok(dom) = deck.pkg.xml(part) {
        // the shape style's font: above the presentation's defaults, below the shape's own
        if let Some(fr) = path(dom, sp, &["p:style", "a:fontRef"]) {
            let c = ctx.scheme.color_in(dom, fr, None);
            let face = match dom.attr(fr, "idx") {
                Some("major") => Some("+mj-lt".to_string()),
                Some("minor") => Some("+mn-lt".to_string()),
                _ => None,
            };
            for l in lv.iter_mut() {
                if c.is_some() {
                    l.def.color = c;
                }
                if face.is_some() {
                    l.def.latin = face.clone();
                }
            }
        }
        if let Some(ls) = path(dom, sp, &["p:txBody", "a:lstStyle"]) {
            let more = read_levels(dom, ls, &ctx.scheme);
            merge_levels(&mut lv, &more);
        }
    }
    lv
}

/// The text box settings: master, layout, slide.
pub fn body_props(deck: &mut Deck, ctx: &Context, part: &str, sp: NodeId) -> BodyP {
    let mut b = default_body();
    let ph = deck.pkg.xml(part).ok().and_then(|d| ph_of(d, sp));
    if ph.is_none() {
        // text boxes and shapes: the theme's defaults
        if let Some(t) = &ctx.theme {
            if let Ok(dom) = deck.pkg.xml(t) {
                if let Some(n) = path(dom, dom.root, &["a:objectDefaults", "a:txDef", "a:bodyPr"]) {
                    apply_body(&mut b, dom, n);
                }
            }
        }
    }
    if let Some(ph) = &ph {
        let inh = inherit(deck, ctx, part, ph);
        for (p, n) in [inh.master, inh.layout].into_iter().flatten() {
            if let Ok(dom) = deck.pkg.xml(&p) {
                if let Some(bp) = path(dom, n, &["p:txBody", "a:bodyPr"]) {
                    apply_body(&mut b, dom, bp);
                }
            }
        }
    }
    if let Ok(dom) = deck.pkg.xml(part) {
        if let Some(bp) = path(dom, sp, &["p:txBody", "a:bodyPr"]) {
            apply_body(&mut b, dom, bp);
        }
    }
    b
}

/// A shape's box on the slide (points): its own, else its placeholder's.
pub fn xfrm(dom: &XmlDoc, sp: NodeId) -> Option<(f64, f64, f64, f64, f64, bool, bool)> {
    let x = match dom.name(sp) {
        "p:graphicFrame" => dom.child(sp, "p:xfrm"),
        "p:grpSp" => path(dom, sp, &["p:grpSpPr", "a:xfrm"]),
        _ => path(dom, sp, &["p:spPr", "a:xfrm"]),
    }?;
    let off = dom.child(x, "a:off")?;
    let ext = dom.child(x, "a:ext")?;
    Some((emu(dom, off, "x").unwrap_or(0.0) / EMU_PT, emu(dom, off, "y").unwrap_or(0.0) / EMU_PT,
          emu(dom, ext, "cx").unwrap_or(0.0) / EMU_PT, emu(dom, ext, "cy").unwrap_or(0.0) / EMU_PT,
          emu(dom, x, "rot").unwrap_or(0.0) / 60000.0,
          dom.attr(x, "flipH").map(on).unwrap_or(false), dom.attr(x, "flipV").map(on).unwrap_or(false)))
}

pub fn shape_id(dom: &XmlDoc, sp: NodeId) -> (u32, String) {
    let nv = dom.elements(sp).find(|&c| dom.name(c).starts_with("p:nv"));
    let c = nv.and_then(|n| dom.child(n, "p:cNvPr"));
    (c.and_then(|c| emu(dom, c, "id")).unwrap_or(0.0) as u32,
     c.and_then(|c| dom.attr(c, "name")).unwrap_or("").to_string())
}

pub fn hidden(dom: &XmlDoc, sp: NodeId) -> bool {
    let nv = dom.elements(sp).find(|&c| dom.name(c).starts_with("p:nv"));
    nv.and_then(|n| dom.child(n, "p:cNvPr")).and_then(|c| dom.attr(c, "hidden")).map(on).unwrap_or(false)
}

/// The box of a shape, following placeholders up to the layout and master.
pub fn shape_box(deck: &mut Deck, ctx: &Context, part: &str, sp: NodeId) -> (f64, f64, f64, f64, f64, bool, bool) {
    if let Some(b) = deck.pkg.xml(part).ok().and_then(|d| xfrm(d, sp)) {
        return b;
    }
    if let Some(ph) = deck.pkg.xml(part).ok().and_then(|d| ph_of(d, sp)) {
        let inh = inherit(deck, ctx, part, &ph);
        for (p, n) in [inh.layout, inh.master].into_iter().flatten() {
            if let Some(b) = deck.pkg.xml(&p).ok().and_then(|d| xfrm(d, n)) {
                return b;
            }
        }
    }
    (0.0, 0.0, 0.0, 0.0, 0.0, false, false)
}

/// The shape's spPr chain for fills and outlines: slide first, then layout, then master.
pub fn sppr_chain(deck: &mut Deck, ctx: &Context, part: &str, sp: NodeId) -> Vec<(String, NodeId)> {
    let mut out = Vec::new();
    let ph = deck.pkg.xml(part).ok().and_then(|d| ph_of(d, sp));
    out.push((part.to_string(), sp));
    if let Some(ph) = ph {
        let inh = inherit(deck, ctx, part, &ph);
        for x in [inh.layout, inh.master].into_iter().flatten() {
            out.push(x);
        }
    }
    out
}

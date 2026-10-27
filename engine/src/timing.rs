//! Animations: the slide's main sequence (p:timing) read as a list of effects and written back.
//! Effects Deliver doesn't change keep their XML as it was; new or changed ones are written in
//! PowerPoint's form for their preset.

use crate::edit::fragment;
use crate::model::{emu, path, Deck};
use folio_core::xml::{NodeId, XmlDoc};

#[derive(Clone, Debug)]
pub struct Effect {
    pub spid: u32,
    /// "entr", "exit", "emph", "path"
    pub class: String,
    pub preset: u32,
    pub subtype: u32,
    /// "click", "with", "after"
    pub trigger: String,
    /// seconds
    pub delay: f64,
    pub dur: f64,
    /// repeat count (1 = once)
    pub repeat: f64,
    /// the effect's own p:par, as saved (None: write it from the preset)
    pub xml: Option<String>,
}

/// (class, preset id, name, default subtype, default duration)
pub const PRESETS: &[(&str, u32, &str, u32, f64)] = &[
    ("entr", 1, "Appear", 0, 0.001),
    ("entr", 10, "Fade", 0, 0.5),
    ("entr", 2, "Fly In", 4, 0.5),
    ("entr", 42, "Float In", 0, 1.0),
    ("entr", 16, "Split", 21, 0.5),
    ("entr", 22, "Wipe", 4, 0.5),
    ("entr", 17, "Shape", 16, 2.0),
    ("entr", 21, "Wheel", 1, 2.0),
    ("entr", 14, "Random Bars", 10, 0.5),
    ("entr", 31, "Grow & Turn", 0, 0.5),
    ("entr", 53, "Zoom", 16, 0.5),
    ("entr", 26, "Bounce", 0, 2.0),
    ("emph", 26, "Pulse", 0, 0.5),
    ("emph", 8, "Spin", 0, 2.0),
    ("emph", 6, "Grow/Shrink", 0, 2.0),
    ("emph", 32, "Teeter", 0, 1.0),
    ("emph", 9, "Transparency", 0, 0.5),
    ("exit", 1, "Disappear", 0, 0.001),
    ("exit", 10, "Fade", 0, 0.5),
    ("exit", 2, "Fly Out", 4, 0.5),
    ("exit", 42, "Float Out", 0, 1.0),
    ("exit", 22, "Wipe", 4, 0.5),
    ("exit", 53, "Zoom", 16, 0.5),
    ("exit", 31, "Shrink & Turn", 0, 0.5),
];

pub fn preset_name(class: &str, id: u32) -> String {
    PRESETS.iter().find(|p| p.0 == class && p.1 == id).map(|p| p.2.to_string())
        .unwrap_or_else(|| format!("{} {}", match class { "entr" => "Entrance", "exit" => "Exit", "emph" => "Emphasis", _ => "Motion Path" }, id))
}

fn secs(v: Option<&str>) -> f64 {
    match v {
        Some("indefinite") | None => 0.0,
        Some(x) => x.parse::<f64>().map(|v| v / 1000.0).unwrap_or(0.0),
    }
}

fn main_seq(d: &XmlDoc) -> Option<NodeId> {
    let root_par = path(d, d.root, &["p:timing", "p:tnLst", "p:par"])?;
    let lst = path(d, root_par, &["p:cTn", "p:childTnLst"])?;
    d.children_named(lst, "p:seq").find(|&s| d.child(s, "p:cTn").and_then(|c| d.attr(c, "nodeType")) == Some("mainSeq"))
}

/// The effects of a slide's main sequence, in order.
pub fn read(d: &XmlDoc) -> Vec<Effect> {
    let mut out = Vec::new();
    let Some(seq) = main_seq(d) else { return out };
    let Some(groups) = path(d, seq, &["p:cTn", "p:childTnLst"]) else { return out };
    for g in d.children_named(groups, "p:par") {
        let Some(gl) = path(d, g, &["p:cTn", "p:childTnLst"]) else { continue };
        for sub in d.children_named(gl, "p:par") {
            let Some(sc) = d.child(sub, "p:cTn") else { continue };
            let Some(el) = d.child(sc, "p:childTnLst") else { continue };
            for e in d.children_named(el, "p:par") {
                let Some(ec) = d.child(e, "p:cTn") else { continue };
                let class = d.attr(ec, "presetClass").unwrap_or("entr").to_string();
                let trigger = match d.attr(ec, "nodeType") {
                    Some("withEffect") => "with",
                    Some("afterEffect") => "after",
                    _ => "click",
                }.to_string();
                let delay = path(d, ec, &["p:stCondLst", "p:cond"]).and_then(|c| d.attr(c, "delay")).map(|v| secs(Some(v))).unwrap_or(0.0);
                // the target and the duration: the first behaviour that names them
                let mut spid = 0u32;
                let mut dur = 0.0f64;
                fn walk(d: &XmlDoc, n: NodeId, spid: &mut u32, dur: &mut f64) {
                    for c in d.elements(n) {
                        if d.name(c) == "p:spTgt" && *spid == 0 {
                            *spid = emu(d, c, "spid").unwrap_or(0.0) as u32;
                        }
                        if d.name(c) == "p:cTn" {
                            if let Some(v) = d.attr(c, "dur") {
                                if v != "indefinite" {
                                    *dur = dur.max(secs(Some(v)));
                                }
                            }
                        }
                        walk(d, c, spid, dur);
                    }
                }
                walk(d, e, &mut spid, &mut dur);
                let repeat = d.attr(ec, "repeatCount").and_then(|v| v.parse::<f64>().ok()).map(|v| v / 1000.0).unwrap_or(1.0);
                out.push(Effect {
                    spid, class, preset: emu(d, ec, "presetID").unwrap_or(0.0) as u32,
                    subtype: emu(d, ec, "presetSubtype").unwrap_or(0.0) as u32, trigger,
                    delay, dur, repeat,
                    xml: Some(d.serialize_node(e)),
                });
            }
        }
    }
    out
}

fn dir_of(sub: u32) -> (&'static str, &'static str) {
    // Fly In / Wipe subtypes: 1 top, 2 right, 4 bottom, 8 left
    match sub {
        1 => ("#ppt_x", "0-#ppt_h/2"),
        2 => ("1+#ppt_w/2", "#ppt_y"),
        8 => ("0-#ppt_w/2", "#ppt_y"),
        _ => ("#ppt_x", "1+#ppt_h/2"),
    }
}

fn wipe_dir(sub: u32) -> &'static str {
    match sub {
        1 => "up",
        2 => "right",
        8 => "left",
        _ => "down",
    }
}

/// The p:par of one effect, written for its preset (ids from `next`).
fn effect_xml(e: &Effect, next: &mut u32, group: u32) -> String {
    let mut id = || {
        *next += 1;
        *next
    };
    let node = match e.trigger.as_str() { "with" => "withEffect", "after" => "afterEffect", _ => "clickEffect" };
    let ms = |s: f64| format!("{}", (s * 1000.0).round().max(1.0) as i64);
    let dur = ms(e.dur.max(0.001));
    let tgt = format!(r#"<p:tgtEl><p:spTgt spid="{}"/></p:tgtEl>"#, e.spid);
    let vis = |val: &str, id: u32| format!(
        r#"<p:set><p:cBhvr><p:cTn id="{id}" dur="1" fill="hold"><p:stCondLst><p:cond delay="{}"/></p:stCondLst></p:cTn>{tgt}<p:attrNameLst><p:attrName>style.visibility</p:attrName></p:attrNameLst></p:cBhvr><p:to><p:strVal val="{val}"/></p:to></p:set>"#,
        if val == "hidden" { dur.clone() } else { "0".into() });
    let anim = |attr: &str, from: &str, to: &str, id: u32| format!(
        r#"<p:anim calcmode="lin" valueType="num"><p:cBhvr additive="base"><p:cTn id="{id}" dur="{dur}" fill="hold"/>{tgt}<p:attrNameLst><p:attrName>{attr}</p:attrName></p:attrNameLst></p:cBhvr><p:tavLst><p:tav tm="0"><p:val><p:strVal val="{from}"/></p:val></p:tav><p:tav tm="100000"><p:val><p:strVal val="{to}"/></p:val></p:tav></p:tavLst></p:anim>"#);
    let effect = |dir: &str, filter: &str, id: u32| format!(
        r#"<p:animEffect transition="{dir}" filter="{filter}"><p:cBhvr><p:cTn id="{id}" dur="{dur}"/>{tgt}</p:cBhvr></p:animEffect>"#);
    let inner = match (e.class.as_str(), e.preset) {
        ("entr", 1) => vis("visible", id()),
        ("entr", 10) => format!("{}{}", vis("visible", id()), effect("in", "fade", id())),
        ("entr", 2) => {
            let (x, y) = dir_of(e.subtype);
            format!("{}{}{}", vis("visible", id()), anim("ppt_x", x, "#ppt_x", id()), anim("ppt_y", y, "#ppt_y", id()))
        }
        ("entr", 42) => format!("{}{}{}", vis("visible", id()), effect("in", "fade", id()), anim("ppt_y", "#ppt_y+0.1", "#ppt_y", id())),
        ("entr", 16) => format!("{}{}", vis("visible", id()), effect("in", if e.subtype == 26 { "barn(inVertical)" } else { "barn(inHorizontal)" }, id())),
        ("entr", 22) => format!("{}{}", vis("visible", id()), effect("in", &format!("wipe({})", wipe_dir(e.subtype)), id())),
        ("entr", 17) => format!("{}{}", vis("visible", id()), effect("in", "circle(in)", id())),
        ("entr", 21) => format!("{}{}", vis("visible", id()), effect("in", "wheel(1)", id())),
        ("entr", 14) => format!("{}{}", vis("visible", id()), effect("in", "randombar(horizontal)", id())),
        ("entr", 31) => format!("{}{}{}{}", vis("visible", id()), anim("ppt_w", "0", "#ppt_w", id()), anim("ppt_h", "0", "#ppt_h", id()),
                                anim("style.rotation", "90", "0", id())),
        ("entr", 53) => format!("{}{}{}", vis("visible", id()), anim("ppt_w", "0", "#ppt_w", id()), anim("ppt_h", "0", "#ppt_h", id())),
        ("entr", _) => format!("{}{}", vis("visible", id()), effect("in", "fade", id())),
        ("exit", 1) => vis("hidden", id()),
        ("exit", 10) => format!("{}{}", effect("out", "fade", id()), vis("hidden", id())),
        ("exit", 2) => {
            let (x, y) = dir_of(e.subtype);
            format!("{}{}{}", anim("ppt_x", "#ppt_x", x, id()), anim("ppt_y", "#ppt_y", y, id()), vis("hidden", id()))
        }
        ("exit", 42) => format!("{}{}{}", effect("out", "fade", id()), anim("ppt_y", "#ppt_y", "#ppt_y+0.1", id()), vis("hidden", id())),
        ("exit", 22) => format!("{}{}", effect("out", &format!("wipe({})", wipe_dir(e.subtype)), id()), vis("hidden", id())),
        ("exit", 53) | ("exit", 31) => format!("{}{}{}", anim("ppt_w", "#ppt_w", "0", id()), anim("ppt_h", "#ppt_h", "0", id()), vis("hidden", id())),
        ("exit", _) => format!("{}{}", effect("out", "fade", id()), vis("hidden", id())),
        ("emph", 8) => format!(r#"<p:animRot by="21600000"><p:cBhvr><p:cTn id="{}" dur="{dur}" fill="hold"/>{tgt}<p:attrNameLst><p:attrName>r</p:attrName></p:attrNameLst></p:cBhvr></p:animRot>"#, id()),
        ("emph", 6) => format!(r#"<p:animScale><p:cBhvr><p:cTn id="{}" dur="{dur}" fill="hold"/>{tgt}</p:cBhvr><p:by x="150000" y="150000"/></p:animScale>"#, id()),
        ("emph", 9) => format!(r#"<p:set><p:cBhvr><p:cTn id="{}" dur="{dur}" fill="hold"/>{tgt}<p:attrNameLst><p:attrName>style.opacity</p:attrName></p:attrNameLst></p:cBhvr><p:to><p:strVal val="0.5"/></p:to></p:set>"#, id()),
        ("emph", 32) => format!(r#"<p:animRot by="120000"><p:cBhvr><p:cTn id="{}" dur="100" autoRev="1" fill="hold"><p:stCondLst><p:cond delay="0"/></p:stCondLst></p:cTn>{tgt}<p:attrNameLst><p:attrName>r</p:attrName></p:attrNameLst></p:cBhvr></p:animRot>"#, id()),
        ("emph", _) => format!(r#"<p:animScale><p:cBhvr><p:cTn id="{}" dur="{}" autoRev="1" fill="hold"/>{tgt}</p:cBhvr><p:by x="105000" y="105000"/></p:animScale>"#, id(), ms(e.dur / 2.0)),
        _ => String::new(),
    };
    let rep = if (e.repeat - 1.0).abs() > 0.001 { format!(r#" repeatCount="{}""#, (e.repeat * 1000.0).round() as i64) } else { String::new() };
    let fill = "hold";
    format!(
        r#"<p:par><p:cTn id="{}" presetID="{}" presetClass="{}" presetSubtype="{}" fill="{fill}" grpId="{group}" nodeType="{node}"{rep}><p:stCondLst><p:cond delay="{}"/></p:stCondLst><p:childTnLst>{inner}</p:childTnLst></p:cTn></p:par>"#,
        id(), e.preset, e.class, e.subtype, (e.delay * 1000.0).round() as i64)
}

/// Replace the slide's main sequence with `effects` (and its build list).
pub fn write(d: &mut XmlDoc, effects: &[Effect]) {
    let root = d.root;
    if let Some(t) = d.child(root, "p:timing") {
        d.detach(t);
    }
    if effects.is_empty() {
        return;
    }
    let mut next = 2u32;
    // click groups: a "click" effect starts one; "after" starts a new part of the group;
    // "with" joins the current part
    let mut subs: Vec<Vec<Vec<String>>> = Vec::new();
    for e in effects {
        let x = match &e.xml {
            Some(x) => {
                let node = match e.trigger.as_str() { "with" => "withEffect", "after" => "afterEffect", _ => "clickEffect" };
                retrigger(x, node, e.delay, &mut next)
            }
            None => effect_xml(e, &mut next, 0),
        };
        if e.trigger == "click" || subs.is_empty() {
            subs.push(vec![Vec::new()]);
        } else if e.trigger == "after" {
            subs.last_mut().unwrap().push(Vec::new());
        }
        subs.last_mut().unwrap().last_mut().unwrap().push(x);
    }
    let mut body = String::new();
    for (gi, g) in subs.iter().enumerate() {
        next += 1;
        let gid = next;
        // the first group plays by itself when the slide's first effect isn't on a click
        let gdelay = if gi == 0 && effects[0].trigger != "click" { "0" } else { "indefinite" };
        body.push_str(&format!(r#"<p:par><p:cTn id="{gid}" fill="hold"><p:stCondLst><p:cond delay="{gdelay}"/></p:stCondLst><p:childTnLst>"#));
        // each "after" part starts when the parts before it have ended
        let mut start: f64 = 0.0;
        for (si, part) in g.iter().enumerate() {
            next += 1;
            body.push_str(&format!(r#"<p:par><p:cTn id="{}" fill="hold"><p:stCondLst><p:cond delay="{}"/></p:stCondLst><p:childTnLst>"#,
                                   next, (start * 1000.0).round() as i64));
            for x in part {
                body.push_str(x);
            }
            body.push_str("</p:childTnLst></p:cTn></p:par>");
            start += part_len(effects, gi, si);
        }
        body.push_str("</p:childTnLst></p:cTn></p:par>");
    }
    let xml = format!(
        r#"<p:timing><p:tnLst><p:par><p:cTn id="1" dur="indefinite" restart="never" nodeType="tmRoot"><p:childTnLst><p:seq concurrent="1" nextAc="seek"><p:cTn id="2" dur="indefinite" nodeType="mainSeq"><p:childTnLst>{body}</p:childTnLst></p:cTn><p:prevCondLst><p:cond evt="onPrev" delay="0"><p:tgtEl><p:sldTgt/></p:tgtEl></p:cond></p:prevCondLst><p:nextCondLst><p:cond evt="onNext" delay="0"><p:tgtEl><p:sldTgt/></p:tgtEl></p:cond></p:nextCondLst></p:seq></p:childTnLst></p:cTn></p:par></p:tnLst></p:timing>"#);
    let Some(el) = fragment(d, &xml) else { return };
    // after cSld, clrMapOvr and transition; before extLst
    let at = d.elements(root).position(|c| d.name(c) == "p:extLst")
        .map(|k| d.index_in_parent(d.elements(root).nth(k).unwrap()).unwrap())
        .unwrap_or(d.children(root).len());
    d.insert(root, at, el);
}

/// Seconds from the start of part `si` of click group `gi` to its end.
fn part_len(effects: &[Effect], gi: usize, si: usize) -> f64 {
    let mut g = 0usize;
    let mut s = 0usize;
    let mut started = false;
    let mut longest: f64 = 0.0;
    for e in effects {
        if e.trigger == "click" || !started {
            if started {
                g += 1;
            }
            started = true;
            s = 0;
        } else if e.trigger == "after" {
            s += 1;
        }
        if g == gi && s == si {
            longest = longest.max(e.delay + e.dur * e.repeat.max(1.0));
        }
    }
    longest
}

/// Kept effect XML with a new nodeType, delay and fresh ids.
fn retrigger(x: &str, node: &str, delay: f64, next: &mut u32) -> String {
    let Some(mut tmp) = parse_fragment(x) else { return x.to_string() };
    let r = tmp.elements(tmp.root).next();
    let Some(par) = r else { return x.to_string() };
    if let Some(c) = tmp.child(par, "p:cTn") {
        tmp.set_attr(c, "nodeType", node);
        if let Some(cond) = path(&tmp, c, &["p:stCondLst", "p:cond"]) {
            tmp.set_attr(cond, "delay", &format!("{}", (delay * 1000.0).round() as i64));
        }
    }
    // every cTn gets a new id
    let mut stack = vec![par];
    while let Some(n) = stack.pop() {
        if tmp.name(n) == "p:cTn" {
            *next += 1;
            tmp.set_attr(n, "id", &next.to_string());
        }
        stack.extend(tmp.elements(n).collect::<Vec<_>>().into_iter().rev());
    }
    tmp.serialize_node(par)
}

fn parse_fragment(x: &str) -> Option<XmlDoc> {
    let w = format!(r#"<w xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">{x}</w>"#);
    XmlDoc::parse(w.as_bytes()).ok()
}

impl Deck {
    pub fn animations(&mut self, i: usize) -> Vec<Effect> {
        let Ok(p) = self.slide_part(i) else { return Vec::new() };
        let Ok(d) = self.pkg.xml(&p) else { return Vec::new() };
        read(d)
    }

    pub fn set_animations(&mut self, i: usize, effects: &[Effect], label: &str) -> Result<(), String> {
        let p = self.slide_part(i)?;
        self.begin(label, &[p.clone()]);
        let d = self.pkg.xml_mut(&p).map_err(|e| e.to_string())?;
        write(d, effects);
        self.commit();
        Ok(())
    }
}

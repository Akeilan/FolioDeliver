//! Text in a shape: paragraphs of runs laid out into lines, with bullets and
//! numbering, line spacing, alignment, anchoring and autofit; caret and selection
//! geometry for editing. Positions are (paragraph, char offset).

use crate::color::Rgba;
use crate::model::path;
use crate::scene::{BodyP, Bullet, ParaP, RunP, Spc};
use folio_core::fonts::{Font, FontCache};
use folio_core::xml::{NodeId, XmlDoc};
use std::sync::Arc;

/// One run's text as laid out (a:r, a:fld, or a:br as "\n").
#[derive(Clone, Debug)]
pub struct Piece {
    pub text: String,
    pub props: RunP,
    /// the a:r / a:fld / a:br node
    pub node: Option<NodeId>,
    pub kind: PieceKind,
}

#[derive(Clone, Copy, Debug, PartialEq)]
pub enum PieceKind {
    Run,
    Field,
    Break,
}

#[derive(Clone, Debug)]
pub struct Para {
    pub node: Option<NodeId>,
    pub level: usize,
    pub props: ParaP,
    pub pieces: Vec<Piece>,
    /// the paragraph mark's run properties (a:endParaRPr)
    pub end: RunP,
}

impl Para {
    pub fn text(&self) -> String {
        self.pieces.iter().map(|p| p.text.as_str()).collect()
    }
    pub fn len(&self) -> usize {
        self.pieces.iter().map(|p| p.text.chars().count()).sum()
    }
    pub fn is_empty(&self) -> bool {
        self.len() == 0
    }
}

/// What fields show.
#[derive(Clone, Debug, Default)]
pub struct Env {
    pub slide_num: usize,
    pub date: String,
    /// scale every size by this (autofit)
    pub font_scale: f64,
    pub spc_reduction: f64,
}

/// Read a txBody's paragraphs with their inherited props.
pub fn read_paras(dom: &XmlDoc, body: NodeId, levels: &[ParaP; 9], scheme: &crate::color::Scheme, env: &Env) -> Vec<Para> {
    let mut out = Vec::new();
    for p in dom.children_named(body, "a:p") {
        let ppr = dom.child(p, "a:pPr");
        let level = ppr.and_then(|n| dom.attr(n, "lvl")).and_then(|v| v.parse::<usize>().ok()).unwrap_or(0).min(8);
        let mut props = levels[level].clone();
        if let Some(n) = ppr {
            props.merge(&crate::scene::read_ppr(dom, n, scheme));
        }
        let mut pieces = Vec::new();
        for c in dom.elements(p) {
            let kind = match dom.name(c) {
                "a:r" => PieceKind::Run,
                "a:fld" => PieceKind::Field,
                "a:br" => PieceKind::Break,
                _ => continue,
            };
            let mut rp = props.def.clone();
            if let Some(r) = dom.child(c, "a:rPr") {
                rp.merge(&crate::scene::read_rpr(dom, r, scheme));
            }
            let text = match kind {
                PieceKind::Break => "\n".to_string(),
                PieceKind::Run => dom.child(c, "a:t").map(|t| dom.text(t)).unwrap_or_default(),
                PieceKind::Field => {
                    let ty = dom.attr(c, "type").unwrap_or("");
                    if ty == "slidenum" && env.slide_num > 0 {
                        env.slide_num.to_string()
                    } else if ty.starts_with("datetime") && !env.date.is_empty() {
                        env.date.clone()
                    } else {
                        dom.child(c, "a:t").map(|t| dom.text(t)).unwrap_or_default()
                    }
                }
            };
            pieces.push(Piece { text, props: rp, node: Some(c), kind });
        }
        let mut end = props.def.clone();
        if let Some(e) = dom.child(p, "a:endParaRPr") {
            end.merge(&crate::scene::read_rpr(dom, e, scheme));
        }
        out.push(Para { node: Some(p), level, props, pieces, end });
    }
    if out.is_empty() {
        out.push(Para { node: None, level: 0, props: levels[0].clone(), pieces: Vec::new(), end: levels[0].def.clone() });
    }
    out
}

/// A run of glyphs in one font on a line.
#[derive(Clone, Debug)]
pub struct Seg {
    pub font: Arc<Font>,
    pub size: f64,
    pub color: Rgba,
    pub glyphs: Vec<(u16, f64, f64)>,
    pub bold: bool,
    pub italic: bool,
    pub underline: bool,
    pub strike: bool,
    pub highlight: Option<Rgba>,
    pub x0: f64,
    pub x1: f64,
    pub rise: f64,
    pub no_fill: bool,
}

#[derive(Clone, Debug)]
pub struct Line {
    pub para: usize,
    /// char range in the paragraph
    pub start: usize,
    pub end: usize,
    /// x of every char boundary start..=end (box coordinates)
    pub xs: Vec<f64>,
    pub top: f64,
    pub baseline: f64,
    pub height: f64,
    pub segs: Vec<Seg>,
    /// the bullet: text, font, size, colour, x
    pub bullet: Option<Seg>,
}

#[derive(Clone, Debug, Default)]
pub struct Layout {
    pub lines: Vec<Line>,
    /// text height (with insets not included)
    pub height: f64,
    /// widest line
    pub width: f64,
    /// where the text area sits in the shape box
    pub x: f64,
    pub y: f64,
    pub w: f64,
    pub h: f64,
    pub paras: Vec<Para>,
}

struct CharInfo {
    adv: f64,
    piece: usize,
}

fn font_for(fonts: &mut FontCache, face: &str, rp: &RunP) -> Arc<Font> {
    fonts.get(face, rp.b.unwrap_or(false), rp.i.unwrap_or(false))
}

pub fn run_size(rp: &RunP, env: &Env) -> f64 {
    rp.sz.unwrap_or(18.0) * if env.font_scale > 0.0 { env.font_scale } else { 1.0 }
}

fn numeral(kind: &str, n: i32) -> String {
    let roman = |mut n: i32| {
        let t = [(1000, "m"), (900, "cm"), (500, "d"), (400, "cd"), (100, "c"), (90, "xc"), (50, "l"), (40, "xl"),
                 (10, "x"), (9, "ix"), (5, "v"), (4, "iv"), (1, "i")];
        let mut s = String::new();
        for (v, r) in t {
            while n >= v {
                s.push_str(r);
                n -= v;
            }
        }
        s
    };
    let alpha = |n: i32| {
        let n = (n - 1).max(0);
        let c = (b'a' + (n % 26) as u8) as char;
        std::iter::repeat(c).take((n / 26 + 1) as usize).collect::<String>()
    };
    let body = if kind.starts_with("alphaLc") {
        alpha(n)
    } else if kind.starts_with("alphaUc") {
        alpha(n).to_uppercase()
    } else if kind.starts_with("romanLc") {
        roman(n)
    } else if kind.starts_with("romanUc") {
        roman(n).to_uppercase()
    } else if kind.starts_with("circleNumDbPlain") || kind.starts_with("circleNumWdBlackPlain") {
        char::from_u32(0x2460 + (n - 1).clamp(0, 19) as u32).map(|c| c.to_string()).unwrap_or_default()
    } else {
        n.to_string()
    };
    if kind.ends_with("ParenBoth") {
        format!("({body})")
    } else if kind.ends_with("ParenR") {
        format!("{body})")
    } else if kind.ends_with("Period") {
        format!("{body}.")
    } else if kind.ends_with("Minus") {
        format!("- {body} -")
    } else {
        body
    }
}

/// The numbers of auto-numbered paragraphs (as PowerPoint counts them).
fn auto_numbers(paras: &[Para]) -> Vec<Option<String>> {
    let mut out = vec![None; paras.len()];
    // per level: (kind, next)
    let mut counters: Vec<Option<(String, i32)>> = vec![None; 9];
    for (i, p) in paras.iter().enumerate() {
        match &p.props.bullet {
            Some(Bullet::Auto(kind, start)) if !p.is_empty() => {
                let lv = p.level;
                for c in counters.iter_mut().skip(lv + 1) {
                    *c = None;
                }
                let n = match &counters[lv] {
                    Some((k, n)) if k == kind => *n,
                    _ => *start,
                };
                out[i] = Some(numeral(kind, n));
                counters[lv] = Some((kind.clone(), n + 1));
            }
            _ => {
                if !p.is_empty() {
                    for c in counters.iter_mut().skip(p.level) {
                        *c = None;
                    }
                }
            }
        }
    }
    out
}

fn line_gap(sp: &Option<Spc>, size: f64, natural: f64, reduction: f64) -> f64 {
    match sp {
        Some(Spc::Pct(p)) => natural * (p - reduction).max(0.1),
        Some(Spc::Pts(p)) => *p,
        None => natural * (1.0 - reduction).max(0.1),
    }
    .max(size * 0.1)
}

fn para_space(sp: &Option<Spc>, size: f64) -> f64 {
    match sp {
        Some(Spc::Pct(p)) => p * size * 1.2,
        Some(Spc::Pts(p)) => *p,
        None => 0.0,
    }
}

/// Shape a paragraph's pieces into per-char advances and glyph runs.
struct Shaped {
    chars: Vec<char>,
    info: Vec<CharInfo>,
    /// per piece: (font, size, glyphs with their char index)
    runs: Vec<(usize, Arc<Font>, f64, Vec<(u16, usize, f64, f64, f64)>)>,
}

fn shape_para(p: &Para, fonts: &mut FontCache, font_name: &dyn Fn(&str) -> String, env: &Env) -> Shaped {
    let mut chars = Vec::new();
    let mut info = Vec::new();
    let mut runs = Vec::new();
    for (pi, piece) in p.pieces.iter().enumerate() {
        let rp = &piece.props;
        let mut size = run_size(rp, env);
        if rp.baseline.map(|b| b != 0.0).unwrap_or(false) {
            size *= 2.0 / 3.0;
        }
        let shown: String = match rp.cap.as_deref() {
            Some("all") | Some("small") => piece.text.to_uppercase(),
            _ => piece.text.clone(),
        };
        // keep char counts equal to the source text
        let shown: String = if shown.chars().count() == piece.text.chars().count() { shown } else { piece.text.clone() };
        let face = font_name(rp.latin.as_deref().unwrap_or("+mn-lt"));
        let base = font_for(fonts, &face, rp);
        let first = chars.len();
        let cs: Vec<char> = shown.chars().collect();
        // split into spans by the font that has the chars
        let mut k = 0;
        while k < cs.len() {
            let ch = cs[k];
            let f = if ch == '\n' || ch == '\t' || base.has_char(ch) {
                base.clone()
            } else {
                fonts.fallback(ch, rp.b.unwrap_or(false), rp.i.unwrap_or(false)).unwrap_or(base.clone())
            };
            let mut e = k + 1;
            while e < cs.len() {
                let c2 = cs[e];
                let ok = if Arc::ptr_eq(&f, &base) { c2 == '\n' || c2 == '\t' || base.has_char(c2) } else { f.has_char(c2) && !base.has_char(c2) };
                if !ok {
                    break;
                }
                e += 1;
            }
            let span: String = cs[k..e].iter().map(|c| if *c == '\n' || *c == '\t' { ' ' } else { *c }).collect();
            let glyphs = f.shape(&span, size, true, true);
            // byte offsets -> char index
            let mut byte_to_char = Vec::with_capacity(span.len() + 1);
            for (ci, c) in span.chars().enumerate() {
                for _ in 0..c.len_utf8() {
                    byte_to_char.push(ci);
                }
            }
            byte_to_char.push(span.chars().count());
            let mut advs = vec![0.0; e - k];
            let mut gl = Vec::new();
            let extra = rp.spc.unwrap_or(0.0);
            for g in &glyphs {
                let ci = byte_to_char.get(g.cluster as usize).copied().unwrap_or(0).min(e - k - 1);
                let within = advs[ci];
                advs[ci] += g.advance;
                gl.push((g.gid, first + (chars.len() - first) + ci, within, g.x_offset, g.y_offset));
            }
            for (ci, a) in advs.iter().enumerate() {
                let c = cs[k + ci];
                let a = if c == '\n' { 0.0 } else { *a + extra };
                chars.push(c);
                info.push(CharInfo { adv: a, piece: pi });
            }
            runs.push((pi, f, size, gl));
            k = e;
        }
    }
    Shaped { chars, info, runs }
}

/// Lay out paragraphs in a box of `w` x `h` points (the shape's), with `body` settings.
pub fn layout(paras: Vec<Para>, body: &BodyP, w: f64, h: f64, fonts: &mut FontCache,
              font_name: &dyn Fn(&str) -> String, env: &Env) -> Layout {
    let vertical = matches!(body.vert.as_str(), "vert" | "vert270" | "eaVert" | "wordArtVert" | "mongolianVert");
    let (bw, bh) = if vertical { (h, w) } else { (w, h) };
    let tx = body.l;
    let ty = body.t;
    let tw = (bw - body.l - body.r).max(1.0);
    let th = (bh - body.t - body.b).max(1.0);
    let width = if body.wrap { tw } else { f64::INFINITY };
    let nums = auto_numbers(&paras);
    let mut lines: Vec<Line> = Vec::new();
    let mut y = 0.0;
    let mut widest: f64 = 0.0;
    let reduction = env.spc_reduction;
    for (pi, p) in paras.iter().enumerate() {
        let sh = shape_para(p, fonts, font_name, env);
        let first_size = p.pieces.first().map(|x| run_size(&x.props, env)).unwrap_or_else(|| run_size(&p.end, env));
        let mar_l = p.props.mar_l.unwrap_or(0.0);
        let indent = p.props.indent.unwrap_or(0.0);
        if pi > 0 {
            y += para_space(&p.props.spc_bef, first_size);
        } else {
            // PowerPoint ignores space before the first paragraph... except it doesn't: keep it
            y += para_space(&p.props.spc_bef, first_size);
        }
        // the bullet
        let mut bullet: Option<Seg> = None;
        if !p.is_empty() {
            let btext = match &p.props.bullet {
                Some(Bullet::Char(c)) => Some(c.clone()),
                Some(Bullet::Auto(..)) => nums[pi].clone(),
                _ => None,
            };
            if let Some(bt) = btext.map(|b| symbol_bullet(&b, p.props.bu_font.clone().flatten().as_deref())) {
                let rp0 = p.pieces.first().map(|x| x.props.clone()).unwrap_or_default();
                let tsize = run_size(&rp0, env);
                let size = match p.props.bu_sz.clone().flatten() {
                    Some(v) if v < 0.0 => -v,
                    Some(v) => tsize * v,
                    None => tsize,
                };
                let face = match p.props.bu_font.clone().flatten().filter(|f| !is_symbol_font(f)) {
                    Some(f) => font_name(&f),
                    None => font_name(rp0.latin.as_deref().unwrap_or("+mn-lt")),
                };
                let mut brp = rp0.clone();
                if matches!(p.props.bullet, Some(Bullet::Char(_))) {
                    brp.b = None;
                    brp.i = None;
                }
                let mut f = font_for(fonts, &face, &brp);
                let ch = bt.chars().next().unwrap_or('•');
                if !f.has_char(ch) {
                    if let Some(fb) = fonts.fallback(ch, false, false) {
                        f = fb;
                    }
                }
                let gl = f.shape(&bt, size, true, true);
                let mut x = 0.0;
                let glyphs: Vec<(u16, f64, f64)> = gl.iter().map(|g| {
                    let r = (g.gid, x + g.x_offset, g.y_offset);
                    x += g.advance;
                    r
                }).collect();
                let color = match p.props.bu_clr.clone() {
                    Some(Some(c)) => c,
                    _ => rp0.color.unwrap_or(Rgba::new(0)),
                };
                bullet = Some(Seg { font: f, size, color, glyphs, bold: false, italic: false, underline: false, strike: false,
                                    highlight: None, x0: 0.0, x1: x, rise: 0.0, no_fill: false });
            }
        }
        // break opportunities
        let text: String = sh.chars.iter().collect();
        let mut can_break = vec![false; sh.chars.len() + 1];
        let mut must_break = vec![false; sh.chars.len() + 1];
        {
            let mut byte_to_char = vec![0usize; text.len() + 1];
            let mut ci = 0;
            for (bi, c) in text.char_indices() {
                for k in 0..c.len_utf8() {
                    byte_to_char[bi + k] = ci;
                }
                ci += 1;
            }
            byte_to_char[text.len()] = ci;
            for (b, op) in unicode_linebreak::linebreaks(&text) {
                let c = byte_to_char[b];
                can_break[c] = true;
                if op == unicode_linebreak::BreakOpportunity::Mandatory && c < sh.chars.len() {
                    must_break[c] = true;
                }
            }
            for (i, c) in sh.chars.iter().enumerate() {
                if *c == '\n' {
                    must_break[i + 1] = true;
                    can_break[i + 1] = true;
                }
            }
        }
        // lines
        let n = sh.chars.len();
        let mut start = 0;
        let mut first_line = true;
        loop {
            let left = if first_line { mar_l + indent } else { mar_l };
            let mut text_left = if first_line { mar_l } else { mar_l };
            if first_line {
                if let Some(b) = &bullet {
                    let bx = (mar_l + indent).max(0.0);
                    if bx + b.x1 > text_left - 0.01 {
                        // the bullet pushes the text on to the next tab stop
                        let tab = p.props.def_tab.unwrap_or(72.0).max(1.0);
                        text_left = ((bx + b.x1) / tab).ceil() * tab;
                        if bullet.is_some() && indent >= 0.0 && mar_l > bx + b.x1 {
                            text_left = mar_l;
                        }
                    }
                }
            }
            let _ = left;
            let first_x = if first_line && bullet.is_none() { (mar_l + indent).max(0.0) } else { text_left };
            let avail = width - first_x;
            // greedy fill
            let mut x = 0.0;
            let mut end = start;
            let mut last_ok: Option<usize> = None;
            while end < n {
                if must_break[end] && end > start {
                    break;
                }
                let c = sh.chars[end];
                let adv = if c == '\t' {
                    let tab = p.props.def_tab.unwrap_or(72.0).max(1.0);
                    let abs = first_x + x;
                    let stops: Vec<f64> = p.props.tabs.clone().unwrap_or_default().into_iter().map(|(p, _)| p).collect();
                    let next = stops.into_iter().find(|s| *s > abs + 0.01).unwrap_or(((abs / tab).floor() + 1.0) * tab);
                    next - abs
                } else {
                    sh.info[end].adv
                };
                let is_space = c == ' ' || c == '\u{3000}';
                if x + adv > avail && end > start && !is_space {
                    break;
                }
                x += adv;
                end += 1;
                if can_break[end] {
                    last_ok = Some(end);
                }
                if c == '\n' {
                    break;
                }
            }
            if end < n && !(end > 0 && must_break[end]) && !(end > 0 && sh.chars[end - 1] == '\n') {
                if let Some(b) = last_ok.filter(|b| *b > start) {
                    end = b;
                }
            }
            if end == start && start < n {
                end = start + 1;
            }
            // char positions
            let mut xs = Vec::with_capacity(end - start + 1);
            let mut cx = first_x;
            xs.push(cx);
            let mut tab_adv = Vec::with_capacity(end - start);
            for i in start..end {
                let c = sh.chars[i];
                let adv = if c == '\t' {
                    let tab = p.props.def_tab.unwrap_or(72.0).max(1.0);
                    let stops: Vec<f64> = p.props.tabs.clone().unwrap_or_default().into_iter().map(|(p, _)| p).collect();
                    let next = stops.into_iter().find(|s| *s > cx + 0.01).unwrap_or(((cx / tab).floor() + 1.0) * tab);
                    next - cx
                } else {
                    sh.info[i].adv
                };
                tab_adv.push(adv);
                cx += adv;
                xs.push(cx);
            }
            // trailing spaces don't count for alignment
            let mut vis_end = end;
            while vis_end > start && matches!(sh.chars[vis_end - 1], ' ' | '\n' | '\u{3000}') {
                vis_end -= 1;
            }
            let line_w = xs[vis_end - start] - first_x;
            widest = widest.max(xs[vis_end - start]);
            // metrics
            let mut asc: f64 = 0.0;
            let mut desc: f64 = 0.0;
            let mut nat: f64 = 0.0;
            let mut max_size: f64 = 0.0;
            let mut seen = false;
            for (pi2, f, size, gl) in &sh.runs {
                let _ = pi2;
                if gl.iter().any(|g| g.1 >= start && g.1 < end) {
                    seen = true;
                    asc = asc.max(f.ascent_pt(*size));
                    desc = desc.max(f.descent_pt(*size));
                    nat = nat.max(f.line_height(*size));
                    max_size = max_size.max(*size);
                }
            }
            if !seen {
                let rp = if n == 0 { p.end.clone() } else { p.pieces.last().map(|x| x.props.clone()).unwrap_or_default() };
                let size = run_size(&rp, env);
                let face = font_name(rp.latin.as_deref().unwrap_or("+mn-lt"));
                let f = font_for(fonts, &face, &rp);
                asc = f.ascent_pt(size);
                desc = f.descent_pt(size);
                nat = f.line_height(size);
                max_size = size;
            }
            if first_line {
                if let Some(b) = &bullet {
                    asc = asc.max(b.font.ascent_pt(b.size));
                }
            }
            // PowerPoint's single spacing is 1.2 x the size
            let natural = (max_size * 1.2).max(nat * 0.95);
            let lh = line_gap(&p.props.ln_spc, max_size, natural, reduction);
            let (top, baseline, height) = match &p.props.ln_spc {
                Some(Spc::Pts(_)) => (y, y + lh * 0.8, lh),
                _ => {
                    // the extra (or missing) space goes above the text
                    let base = y + asc * (lh / natural.max(0.01)).min(1.0).max(0.5) + (lh - natural).max(0.0) * 0.0;
                    let base = base.max(y + lh - desc.min(lh));
                    (y, base.min(y + lh), lh)
                }
            };
            // alignment shift
            let algn = p.props.algn.as_deref().unwrap_or("l");
            let slack = if width.is_finite() { (width - first_x - line_w).max(0.0) } else { 0.0 };
            let last_of_para = end >= n || (end > 0 && sh.chars[end - 1] == '\n');
            let (shift, gap) = match algn {
                "ctr" => (slack / 2.0, 0.0),
                "r" => (slack, 0.0),
                "just" | "dist" if !last_of_para || algn == "dist" => {
                    let spaces = (start..vis_end).filter(|&i| sh.chars[i] == ' ').count();
                    if spaces > 0 { (0.0, slack / spaces as f64) } else { (0.0, 0.0) }
                }
                _ => (0.0, 0.0),
            };
            if gap > 0.0 {
                let mut add = 0.0;
                for (k, i) in (start..end).enumerate() {
                    xs[k] += add;
                    if sh.chars[i] == ' ' && i < vis_end {
                        add += gap;
                    }
                }
                let k = end - start;
                xs[k] += add;
            }
            for v in xs.iter_mut() {
                *v += shift;
            }
            // segments
            let mut segs = Vec::new();
            for (piece_i, f, size, gl) in &sh.runs {
                let mine: Vec<&(u16, usize, f64, f64, f64)> = gl.iter().filter(|g| g.1 >= start && g.1 < vis_end.max(start)).collect();
                if mine.is_empty() {
                    continue;
                }
                let piece = &p.pieces[*piece_i];
                let rp = &piece.props;
                let glyphs: Vec<(u16, f64, f64)> = mine.iter()
                    .filter(|g| !matches!(sh.chars[g.1], '\n' | '\t'))
                    .map(|g| (g.0, xs[g.1 - start] + g.2 + g.3, g.4)).collect();
                let c0 = mine.iter().map(|g| g.1).min().unwrap();
                let c1 = mine.iter().map(|g| g.1).max().unwrap() + 1;
                let rise = rp.baseline.map(|b| b * run_size(rp, env)).unwrap_or(0.0);
                segs.push(Seg {
                    font: f.clone(), size: *size, color: rp.color.unwrap_or(Rgba::new(0)), glyphs,
                    bold: rp.b.unwrap_or(false), italic: rp.i.unwrap_or(false),
                    underline: rp.u.as_deref().map(|u| u != "none").unwrap_or(false),
                    strike: rp.strike.as_deref().map(|s| s != "noStrike").unwrap_or(false),
                    highlight: rp.highlight, x0: xs[c0 - start], x1: xs[c1 - start], rise, no_fill: rp.no_fill,
                });
            }
            let mut b = if first_line { bullet.clone() } else { None };
            if let Some(bs) = b.as_mut() {
                let bx = (mar_l + indent).max(0.0) + if bullet.is_some() { shift } else { 0.0 };
                let shift_b = if algn == "l" || algn == "just" { 0.0 } else { 0.0 };
                for g in bs.glyphs.iter_mut() {
                    g.1 += bx + shift_b;
                }
                bs.x0 += bx;
                bs.x1 += bx;
            }
            lines.push(Line { para: pi, start, end, xs, top, baseline, height, segs, bullet: b });
            y += height;
            first_line = false;
            start = end;
            if start >= n {
                // a paragraph ending in a line break gets an empty last line
                if n > 0 && sh.chars[n - 1] == '\n' {
                    let size = run_size(&p.end, env);
                    let lh = line_gap(&p.props.ln_spc, size, size * 1.2, reduction);
                    let f = font_for(fonts, &font_name(p.end.latin.as_deref().unwrap_or("+mn-lt")), &p.end);
                    let fx = mar_l + shift;
                    lines.push(Line { para: pi, start: n, end: n, xs: vec![fx], top: y, baseline: y + f.ascent_pt(size),
                                      height: lh, segs: Vec::new(), bullet: None });
                    y += lh;
                }
                break;
            }
        }
        let last_size = p.pieces.last().map(|x| run_size(&x.props, env)).unwrap_or_else(|| run_size(&p.end, env));
        y += para_space(&p.props.spc_aft, last_size);
    }
    // anchoring
    let total = y;
    let dy = match body.anchor.as_str() {
        "ctr" => (th - total) / 2.0,
        "b" => th - total,
        _ => 0.0,
    };
    let dy = if body.anchor != "t" { dy } else { 0.0 };
    let dx = if body.anchor_ctr && width.is_finite() { ((tw - widest) / 2.0).max(0.0) } else { 0.0 };
    let mut lay = Layout { lines, height: total, width: widest, x: tx + dx, y: ty + dy, w: tw, h: th, paras };
    if !body.wrap {
        // unwrapped text centres on the box as PowerPoint does
        let algn = lay.paras.first().and_then(|p| p.props.algn.clone()).unwrap_or_else(|| "l".into());
        if algn == "ctr" {
            lay.x = tx + (tw - widest) / 2.0;
        } else if algn == "r" {
            lay.x = tx + tw - widest;
        }
    }
    lay
}

impl Layout {
    /// Caret geometry for (para, offset): (x, top, height) in shape coordinates.
    pub fn caret(&self, para: usize, off: usize) -> Option<(f64, f64, f64)> {
        let mut best: Option<&Line> = None;
        for l in &self.lines {
            if l.para == para && off >= l.start && off <= l.end {
                // at a line end prefer the next line's start (except the paragraph's last)
                if off == l.end && l.end > l.start && self.lines.iter().any(|m| m.para == para && m.start == off && m.start > l.start) {
                    continue;
                }
                best = Some(l);
                break;
            }
        }
        let l = best.or_else(|| self.lines.iter().filter(|l| l.para == para).last())?;
        let k = off.clamp(l.start, l.end) - l.start;
        let x = l.xs.get(k).copied().unwrap_or(*l.xs.last().unwrap_or(&0.0));
        Some((self.x + x, self.y + l.top, l.height))
    }

    /// The text position nearest a point (shape coordinates).
    pub fn hit(&self, x: f64, y: f64) -> (usize, usize) {
        if self.lines.is_empty() {
            return (0, 0);
        }
        let ly = y - self.y;
        let lx = x - self.x;
        let line = self.lines.iter().find(|l| ly < l.top + l.height).unwrap_or(self.lines.last().unwrap());
        let mut best = line.start;
        let mut bd = f64::INFINITY;
        // don't land after a line's trailing break / soft-wrap boundary except at the paragraph's end
        let last = if line.end > line.start && self.lines.iter().any(|m| m.para == line.para && m.start == line.end) {
            line.end - 1
        } else {
            line.end
        };
        let para_text: Vec<char> = self.paras.get(line.para).map(|p| p.text().chars().collect()).unwrap_or_default();
        let last = if last > line.start && para_text.get(last - 1) == Some(&'\n') { last - 1 } else { last };
        for k in line.start..=last.max(line.start) {
            let d = (line.xs[k - line.start] - lx).abs();
            if d < bd {
                bd = d;
                best = k;
            }
        }
        (line.para, best)
    }

    /// Selection rectangles between two positions (shape coordinates).
    pub fn selection(&self, a: (usize, usize), b: (usize, usize)) -> Vec<(f64, f64, f64, f64)> {
        let (a, b) = if a <= b { (a, b) } else { (b, a) };
        let mut out = Vec::new();
        for l in &self.lines {
            let ls = (l.para, l.start);
            let le = (l.para, l.end);
            if le < a || ls > b {
                continue;
            }
            let s = if a > ls { a.1 } else { l.start };
            let e = if b < le { b.1 } else { l.end };
            let x0 = l.xs[s.clamp(l.start, l.end) - l.start];
            let mut x1 = l.xs[e.clamp(l.start, l.end) - l.start];
            if b > le && x1 - x0 < 4.0 {
                x1 = x0 + 4.0;
            }
            if x1 > x0 {
                out.push((self.x + x0, self.y + l.top, x1 - x0, l.height));
            }
        }
        out
    }

    /// The line a position is on and the one above/below it, for Up/Down.
    pub fn vertical(&self, para: usize, off: usize, down: bool, want_x: f64) -> Option<(usize, usize)> {
        let idx = self.lines.iter().position(|l| l.para == para && off >= l.start && off <= l.end
            && !(off == l.end && l.end > l.start && self.lines.iter().any(|m| m.para == para && m.start == off && m.start > l.start)))?;
        let j = if down { idx + 1 } else { idx.checked_sub(1)? };
        let l = self.lines.get(j)?;
        Some(self.hit(want_x, self.y + l.top + l.height / 2.0))
    }

    pub fn line_bounds(&self, para: usize, off: usize) -> Option<((usize, usize), (usize, usize))> {
        let l = self.lines.iter().find(|l| l.para == para && off >= l.start && off <= l.end
            && !(off == l.end && l.end > l.start && self.lines.iter().any(|m| m.para == para && m.start == off && m.start > l.start)))?;
        let para_text: Vec<char> = self.paras.get(para).map(|p| p.text().chars().collect()).unwrap_or_default();
        let mut e = l.end;
        if self.lines.iter().any(|m| m.para == para && m.start == l.end && m.start > l.start) {
            // soft wrap: the end is before the next line
        } else if e > l.start && para_text.get(e - 1) == Some(&'\n') {
            e -= 1;
        }
        Some(((para, l.start), (para, e)))
    }
}

/// The paragraphs of a txBody node with nothing inherited: just their text.
pub fn plain_text(dom: &XmlDoc, body: NodeId) -> Vec<String> {
    dom.children_named(body, "a:p").map(|p| {
        let mut s = String::new();
        for c in dom.elements(p) {
            match dom.name(c) {
                "a:r" | "a:fld" => s.push_str(&dom.child(c, "a:t").map(|t| dom.text(t)).unwrap_or_default()),
                "a:br" => s.push('\n'),
                _ => {}
            }
        }
        s
    }).collect()
}

pub fn tx_body(dom: &XmlDoc, sp: NodeId) -> Option<NodeId> {
    dom.child(sp, "p:txBody").or_else(|| path(dom, sp, &["a:txBody"]))
}

fn is_symbol_font(f: &str) -> bool {
    let f = f.to_lowercase();
    f.starts_with("wingdings") || f == "symbol" || f == "opensymbol" || f == "starsymbol" || f.starts_with("webdings") || f == "monotype sorts"
}

/// Bullets written in symbol fonts (Wingdings, Symbol, OpenSymbol's private area) as real characters.
pub fn symbol_bullet(b: &str, font: Option<&str>) -> String {
    let mut c = match b.chars().next() { Some(c) => c, None => return b.to_string() };
    let code = c as u32;
    if (0xF000..=0xF0FF).contains(&code) {
        c = char::from_u32(code - 0xF000).unwrap_or(c);
    }
    let f = font.map(|f| f.to_lowercase()).unwrap_or_default();
    let mapped = if f.starts_with("wingdings") {
        match c {
            'l' => '\u{25CF}', 'n' => '\u{25A0}', 'q' => '\u{274F}', 'v' => '\u{2756}', 'u' => '\u{25C6}',
            '\u{A7}' => '\u{25AA}', '\u{D8}' => '\u{27A2}', '\u{FC}' => '\u{2714}', '\u{FB}' => '\u{2718}',
            '\u{E0}' | '\u{E8}' => '\u{2794}', 'o' => '\u{25A1}', 'p' => '\u{25A2}', 'ò' => '\u{25C7}',
            _ => '\u{2022}',
        }
    } else if f == "symbol" {
        match c { '\u{B7}' => '\u{2022}', '-' => '\u{2013}', 'o' => 'o', _ => c }
    } else if (0xE000..=0xF8FF).contains(&(c as u32)) {
        match c as u32 {
            0xE00A | 0xE00C => '\u{25A0}', 0xE011 => '\u{2794}', 0xE012 | 0xE013 => '\u{27A2}', 0xE016 => '\u{2713}',
            0xE00B => '\u{25C6}', _ => '\u{2022}',
        }
    } else {
        c
    };
    let mut out = String::new();
    out.push(mapped);
    out.extend(b.chars().skip(1));
    out
}

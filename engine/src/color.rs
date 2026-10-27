//! DrawingML colours: scheme colours through the slide's colour map and the
//! theme, preset and system colours, and the colour transforms.

use folio_core::xml::{NodeId, XmlDoc};
use std::collections::HashMap;

/// A colour as drawn: 0xRRGGBB and opacity 0..1.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Rgba {
    pub rgb: u32,
    pub a: f64,
}

impl Rgba {
    pub fn new(rgb: u32) -> Rgba {
        Rgba { rgb: rgb & 0xFFFFFF, a: 1.0 }
    }
    pub fn r(&self) -> f64 {
        ((self.rgb >> 16) & 255) as f64 / 255.0
    }
    pub fn g(&self) -> f64 {
        ((self.rgb >> 8) & 255) as f64 / 255.0
    }
    pub fn b(&self) -> f64 {
        (self.rgb & 255) as f64 / 255.0
    }
    pub fn set(&self, cr: &cairo::Context) {
        cr.set_source_rgba(self.r(), self.g(), self.b(), self.a);
    }
}

/// The theme's colours by name (dk1, lt1, dk2, lt2, accent1..6, hlink, folHlink) and the
/// colour map (bg1 -> lt1, tx1 -> dk1 ...).
#[derive(Clone, Debug, Default)]
pub struct Scheme {
    pub colors: HashMap<String, u32>,
    pub map: HashMap<String, String>,
}

impl Scheme {
    pub fn office() -> Scheme {
        let mut colors = HashMap::new();
        for (k, v) in [("dk1", 0x000000), ("lt1", 0xFFFFFF), ("dk2", 0x44546A), ("lt2", 0xE7E6E6),
                       ("accent1", 0x4472C4), ("accent2", 0xED7D31), ("accent3", 0xA5A5A5),
                       ("accent4", 0xFFC000), ("accent5", 0x5B9BD5), ("accent6", 0x70AD47),
                       ("hlink", 0x0563C1), ("folHlink", 0x954F72)] {
            colors.insert(k.to_string(), v);
        }
        let mut s = Scheme { colors, map: HashMap::new() };
        s.default_map();
        s
    }

    pub fn default_map(&mut self) {
        for (k, v) in [("bg1", "lt1"), ("tx1", "dk1"), ("bg2", "lt2"), ("tx2", "dk2")] {
            self.map.insert(k.into(), v.into());
        }
    }

    /// Read a:clrScheme.
    pub fn read_theme(&mut self, dom: &XmlDoc, scheme: NodeId) {
        for c in dom.elements(scheme) {
            let name = dom.name(c).trim_start_matches("a:").to_string();
            if let Some(v) = dom.elements(c).find_map(|e| base(dom, e)) {
                self.colors.insert(name, v);
            }
        }
    }

    /// Read a p:clrMap (attributes bg1="lt1" ...).
    pub fn read_map(&mut self, dom: &XmlDoc, map: NodeId) {
        if let folio_core::xml::Kind::Element { attrs, .. } = &dom.node(map).kind {
            for (k, v) in attrs {
                if !k.contains(':') {
                    self.map.insert(k.clone(), v.clone());
                }
            }
        }
    }

    pub fn named(&self, name: &str) -> u32 {
        let key = self.map.get(name).map(|s| s.as_str()).unwrap_or(name);
        if let Some(v) = self.colors.get(key) {
            return *v;
        }
        match key {
            "dk1" | "tx1" => 0,
            "lt1" | "bg1" => 0xFFFFFF,
            _ => 0x808080,
        }
    }

    /// The colour of an element such as a:srgbClr or a:schemeClr (with its transforms);
    /// `ph` is what a:schemeClr val="phClr" stands for.
    pub fn resolve(&self, dom: &XmlDoc, c: NodeId, ph: Option<Rgba>) -> Option<Rgba> {
        let val = dom.attr(c, "val").unwrap_or("");
        let mut out = match dom.name(c) {
            "a:schemeClr" => {
                if val == "phClr" {
                    ph.unwrap_or(Rgba::new(0))
                } else {
                    Rgba::new(self.named(val))
                }
            }
            _ => Rgba::new(base(dom, c)?),
        };
        apply_mods(dom, c, &mut out);
        Some(out)
    }

    /// The colour inside a container (a:solidFill, a:fontRef, a:buClr ...).
    pub fn color_in(&self, dom: &XmlDoc, n: NodeId, ph: Option<Rgba>) -> Option<Rgba> {
        dom.elements(n).find_map(|c| self.resolve(dom, c, ph))
    }
}

/// The colour before transforms (not scheme colours).
fn base(dom: &XmlDoc, c: NodeId) -> Option<u32> {
    let val = dom.attr(c, "val").unwrap_or("");
    Some(match dom.name(c) {
        "a:srgbClr" => u32::from_str_radix(val, 16).ok()?,
        "a:sysClr" => dom.attr(c, "lastClr").and_then(|v| u32::from_str_radix(v, 16).ok())
            .unwrap_or(if val == "window" { 0xFFFFFF } else { 0 }),
        "a:prstClr" => preset(val)?,
        "a:scrgbClr" => {
            let g = |k: &str| (dom.attr(c, k).and_then(|v| v.parse::<f64>().ok()).unwrap_or(0.0) / 100000.0).clamp(0.0, 1.0);
            let to = |v: f64| (lin_to_srgb(v) * 255.0).round() as u32;
            (to(g("r")) << 16) | (to(g("g")) << 8) | to(g("b"))
        }
        "a:hslClr" => {
            let h = dom.attr(c, "hue").and_then(|v| v.parse::<f64>().ok()).unwrap_or(0.0) / 60000.0 / 360.0;
            let s = dom.attr(c, "sat").and_then(|v| v.parse::<f64>().ok()).unwrap_or(0.0) / 100000.0;
            let l = dom.attr(c, "lum").and_then(|v| v.parse::<f64>().ok()).unwrap_or(0.0) / 100000.0;
            from_hsl(h, s, l)
        }
        _ => return None,
    })
}

fn lin_to_srgb(v: f64) -> f64 {
    if v <= 0.0031308 { v * 12.92 } else { 1.055 * v.powf(1.0 / 2.4) - 0.055 }
}

fn srgb_to_lin(v: f64) -> f64 {
    if v <= 0.04045 { v / 12.92 } else { ((v + 0.055) / 1.055).powf(2.4) }
}

pub fn hsl(rgb: u32) -> (f64, f64, f64) {
    let r = ((rgb >> 16) & 255) as f64 / 255.0;
    let g = ((rgb >> 8) & 255) as f64 / 255.0;
    let b = (rgb & 255) as f64 / 255.0;
    let max = r.max(g).max(b);
    let min = r.min(g).min(b);
    let l = (max + min) / 2.0;
    if (max - min).abs() < 1e-9 {
        return (0.0, 0.0, l);
    }
    let d = max - min;
    let s = if l > 0.5 { d / (2.0 - max - min) } else { d / (max + min) };
    let h = if max == r {
        ((g - b) / d + if g < b { 6.0 } else { 0.0 }) / 6.0
    } else if max == g {
        ((b - r) / d + 2.0) / 6.0
    } else {
        ((r - g) / d + 4.0) / 6.0
    };
    (h, s, l)
}

pub fn from_hsl(h: f64, s: f64, l: f64) -> u32 {
    let l = l.clamp(0.0, 1.0);
    let s = s.clamp(0.0, 1.0);
    let h = h.rem_euclid(1.0);
    let to = |v: f64| (v.clamp(0.0, 1.0) * 255.0).round() as u32;
    if s == 0.0 {
        let v = to(l);
        return (v << 16) | (v << 8) | v;
    }
    let q = if l < 0.5 { l * (1.0 + s) } else { l + s - l * s };
    let p = 2.0 * l - q;
    let hue = |mut t: f64| {
        if t < 0.0 {
            t += 1.0;
        }
        if t > 1.0 {
            t -= 1.0;
        }
        if t < 1.0 / 6.0 {
            p + (q - p) * 6.0 * t
        } else if t < 0.5 {
            q
        } else if t < 2.0 / 3.0 {
            p + (q - p) * (2.0 / 3.0 - t) * 6.0
        } else {
            p
        }
    };
    (to(hue(h + 1.0 / 3.0)) << 16) | (to(hue(h)) << 8) | to(hue(h - 1.0 / 3.0))
}

/// The colour transforms, in document order.
pub fn apply_mods(dom: &XmlDoc, c: NodeId, out: &mut Rgba) {
    for m in dom.elements(c) {
        let v = dom.attr(m, "val").and_then(|v| v.parse::<f64>().ok()).unwrap_or(0.0) / 100000.0;
        let rgb = out.rgb;
        match dom.name(m) {
            "a:lumMod" => {
                let (h, s, l) = hsl(rgb);
                out.rgb = from_hsl(h, s, l * v);
            }
            "a:lumOff" => {
                let (h, s, l) = hsl(rgb);
                out.rgb = from_hsl(h, s, l + v);
            }
            "a:satMod" => {
                let (h, s, l) = hsl(rgb);
                out.rgb = from_hsl(h, s * v, l);
            }
            "a:satOff" => {
                let (h, s, l) = hsl(rgb);
                out.rgb = from_hsl(h, s + v, l);
            }
            "a:hueOff" => {
                let (h, s, l) = hsl(rgb);
                out.rgb = from_hsl(h + v * 100000.0 / 60000.0 / 360.0, s, l);
            }
            "a:hueMod" => {
                let (h, s, l) = hsl(rgb);
                out.rgb = from_hsl(h * v, s, l);
            }
            "a:tint" => {
                // towards white, in linear light (as the original)
                let f = |x: u32| {
                    let lin = srgb_to_lin(x as f64 / 255.0);
                    (lin_to_srgb(lin * v + (1.0 - v)) * 255.0).round() as u32
                };
                out.rgb = (f((rgb >> 16) & 255) << 16) | (f((rgb >> 8) & 255) << 8) | f(rgb & 255);
            }
            "a:shade" => {
                let f = |x: u32| {
                    let lin = srgb_to_lin(x as f64 / 255.0);
                    (lin_to_srgb(lin * v) * 255.0).round() as u32
                };
                out.rgb = (f((rgb >> 16) & 255) << 16) | (f((rgb >> 8) & 255) << 8) | f(rgb & 255);
            }
            "a:alpha" => out.a = v,
            "a:alphaMod" => out.a *= v,
            "a:alphaOff" => out.a = (out.a + v).clamp(0.0, 1.0),
            "a:gray" => {
                let y = (0.3 * out.r() + 0.59 * out.g() + 0.11 * out.b()) * 255.0;
                let y = y.round() as u32;
                out.rgb = (y << 16) | (y << 8) | y;
            }
            "a:inv" => out.rgb = !rgb & 0xFFFFFF,
            "a:comp" => {
                let (h, s, l) = hsl(rgb);
                out.rgb = from_hsl(h + 0.5, s, l);
            }
            _ => {}
        }
    }
}

fn preset(name: &str) -> Option<u32> {
    Some(match name {
        "black" => 0x000000,
        "white" => 0xFFFFFF,
        "red" => 0xFF0000,
        "green" => 0x008000,
        "blue" => 0x0000FF,
        "yellow" => 0xFFFF00,
        "cyan" | "aqua" => 0x00FFFF,
        "magenta" | "fuchsia" => 0xFF00FF,
        "gray" | "grey" => 0x808080,
        "dkGray" | "dkGrey" => 0xA9A9A9,
        "ltGray" | "ltGrey" => 0xD3D3D3,
        "silver" => 0xC0C0C0,
        "orange" => 0xFFA500,
        "purple" => 0x800080,
        "navy" => 0x000080,
        "maroon" => 0x800000,
        "olive" => 0x808000,
        "teal" => 0x008080,
        "lime" => 0x00FF00,
        "brown" => 0xA52A2A,
        "pink" => 0xFFC0CB,
        "gold" => 0xFFD700,
        "dkBlue" => 0x00008B,
        "dkRed" => 0x8B0000,
        "dkGreen" => 0x006400,
        "ltBlue" => 0xADD8E6,
        "ltGreen" => 0x90EE90,
        "ltYellow" => 0xFFFFE0,
        "indigo" => 0x4B0082,
        "violet" => 0xEE82EE,
        _ => return None,
    })
}

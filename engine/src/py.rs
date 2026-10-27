//! The Python face of the engine: `deliver_core.Presentation`.

use crate::model::{Deck, EMU_PT};
use crate::render::{Opts, Painter, ShapeInfo};
use crate::scene;
use crate::text::{Env, Layout};
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use pyo3::types::{PyBytes, PyDict};

fn err<E: ToString>(e: E) -> PyErr {
    PyValueError::new_err(e.to_string())
}

#[pyclass(unsendable, name = "Presentation")]
pub struct PyPresentation {
    deck: Deck,
    painter: Painter,
    /// text layout cache: (slide part, shape id, deck version) -> layout and box
    cache: Option<(String, u32, u64, Layout, (f64, f64, f64, f64, f64))>,
}

fn info_dict<'py>(py: Python<'py>, s: &ShapeInfo) -> PyResult<Bound<'py, PyDict>> {
    let d = PyDict::new_bound(py);
    d.set_item("id", s.id)?;
    d.set_item("name", &s.name)?;
    d.set_item("kind", &s.kind)?;
    d.set_item("x", s.x)?;
    d.set_item("y", s.y)?;
    d.set_item("w", s.w)?;
    d.set_item("h", s.h)?;
    d.set_item("rot", s.rot)?;
    d.set_item("flip_h", s.flip_h)?;
    d.set_item("flip_v", s.flip_v)?;
    d.set_item("ph", s.ph.clone())?;
    d.set_item("has_text", s.has_text)?;
    d.set_item("empty", s.empty)?;
    d.set_item("group", s.group)?;
    d.set_item("geom", &s.geom)?;
    d.set_item("descr", &s.descr)?;
    Ok(d)
}

impl PyPresentation {
    fn layout_of(&mut self, i: usize, id: u32) -> PyResult<(Layout, (f64, f64, f64, f64, f64))> {
        let part = self.deck.slide_part(i).map_err(err)?;
        if let Some((p, sid, v, lay, bx)) = &self.cache {
            if *p == part && *sid == id && *v == self.deck.version {
                return Ok((lay.clone(), *bx));
            }
        }
        let ctx = scene::context(&mut self.deck, &part);
        let n = self.deck.find_shape(&part, id).ok_or_else(|| err("no such shape"))?;
        let (x, y, w, h, rot, _, _) = scene::shape_box(&mut self.deck, &ctx, &part, n);
        let dom = self.deck.pkg.xml(&part).map_err(err)?.clone();
        let lay = match dom.child(n, "p:txBody") {
            Some(tb) => {
                let num = i + 1;
                let env = Env { slide_num: num, date: chrono::Local::now().format("%-m/%-d/%Y").to_string(), font_scale: 1.0, spc_reduction: 0.0 };
                self.painter.layout_text(&mut self.deck, &ctx, &part, &dom, n, tb, w, h, &env)
            }
            None => Layout::default(),
        };
        let bx = (x, y, w, h, rot);
        self.cache = Some((part, id, self.deck.version, lay.clone(), bx));
        Ok((lay, bx))
    }
}

#[pymethods]
impl PyPresentation {
    #[new]
    fn new(data: &[u8]) -> PyResult<Self> {
        Ok(PyPresentation { deck: Deck::open(data).map_err(err)?, painter: Painter::new(), cache: None })
    }

    #[staticmethod]
    fn open(path: &str) -> PyResult<Self> {
        let data = std::fs::read(path).map_err(err)?;
        let mut p = PyPresentation { deck: Deck::open(&data).map_err(err)?, painter: Painter::new(), cache: None };
        p.deck.path = path.to_string();
        Ok(p)
    }

    fn save(&mut self, path: &str) -> PyResult<()> {
        self.deck.save(path).map_err(err)
    }

    fn to_bytes<'py>(&mut self, py: Python<'py>) -> PyResult<Bound<'py, PyBytes>> {
        let b = self.deck.bytes().map_err(err)?;
        Ok(PyBytes::new_bound(py, &b))
    }

    #[getter]
    fn path(&self) -> String {
        self.deck.path.clone()
    }

    #[getter]
    fn modified(&self) -> bool {
        self.deck.modified
    }

    #[setter]
    fn set_modified(&mut self, v: bool) {
        self.deck.modified = v;
    }

    #[getter]
    fn version(&self) -> u64 {
        self.deck.version
    }

    fn slide_count(&self) -> usize {
        self.deck.slides.len()
    }

    /// Slide size in points.
    fn size(&self) -> (f64, f64) {
        (self.deck.cx / EMU_PT, self.deck.cy / EMU_PT)
    }

    fn slide_parts(&self) -> Vec<String> {
        self.deck.slides.clone()
    }

    /// Render slide i at `scale` px per point: (w, h, stride, ARGB32 bytes, shapes).
    #[pyo3(signature = (i, scale, edit=true))]
    fn render<'py>(&mut self, py: Python<'py>, i: usize, scale: f64, edit: bool)
                   -> PyResult<(i32, i32, i32, Bound<'py, PyBytes>, Vec<Bound<'py, PyDict>>)> {
        let part = self.deck.slide_part(i).map_err(err)?;
        let (w, h) = self.size();
        let pw = ((w * scale).round() as i32).max(1);
        let ph = ((h * scale).round() as i32).max(1);
        let mut surf = cairo::ImageSurface::create(cairo::Format::ARgb32, pw, ph).map_err(err)?;
        let infos = {
            let cr = cairo::Context::new(&surf).map_err(err)?;
            cr.scale(scale, scale);
            self.painter.draw(&mut self.deck, &part, &cr, &Opts { edit, hide: None })
        };
        surf.flush();
        let stride = surf.stride();
        let data = surf.data().map_err(err)?;
        let bytes = PyBytes::new_bound(py, &data);
        let list = infos.iter().map(|s| info_dict(py, s)).collect::<PyResult<Vec<_>>>()?;
        Ok((pw, ph, stride, bytes, list))
    }

    /// The shapes of slide i (without drawing at a useful size).
    fn shapes<'py>(&mut self, py: Python<'py>, i: usize) -> PyResult<Vec<Bound<'py, PyDict>>> {
        let part = self.deck.slide_part(i).map_err(err)?;
        let surf = cairo::ImageSurface::create(cairo::Format::A8, 1, 1).map_err(err)?;
        let cr = cairo::Context::new(&surf).map_err(err)?;
        cr.scale(0.001, 0.001);
        let infos = self.painter.draw(&mut self.deck, &part, &cr, &Opts { edit: true, hide: None });
        infos.iter().map(|s| info_dict(py, s)).collect()
    }

    /// Write every slide (not the hidden ones unless asked) to a PDF.
    #[pyo3(signature = (path, hidden=false))]
    fn export_pdf(&mut self, path: &str, hidden: bool) -> PyResult<()> {
        let (w, h) = self.size();
        let surf = cairo::PdfSurface::new(w, h, path).map_err(err)?;
        {
            let cr = cairo::Context::new(&surf).map_err(err)?;
            for i in 0..self.deck.slides.len() {
                if !hidden && self.deck.is_hidden(i) {
                    continue;
                }
                let part = self.deck.slides[i].clone();
                self.painter.draw(&mut self.deck, &part, &cr, &Opts { edit: false, hide: None });
                cr.show_page().map_err(err)?;
            }
        }
        surf.finish();
        Ok(())
    }

    /// Slide i as a PNG file at `width` pixels.
    fn export_png(&mut self, i: usize, path: &str, width: i32) -> PyResult<()> {
        let part = self.deck.slide_part(i).map_err(err)?;
        let (w, h) = self.size();
        let scale = width as f64 / w;
        let surf = cairo::ImageSurface::create(cairo::Format::ARgb32, width, (h * scale).round() as i32).map_err(err)?;
        {
            let cr = cairo::Context::new(&surf).map_err(err)?;
            cr.scale(scale, scale);
            self.painter.draw(&mut self.deck, &part, &cr, &Opts { edit: false, hide: None });
        }
        let mut f = std::fs::File::create(path).map_err(err)?;
        surf.write_to_png(&mut f).map_err(err)?;
        Ok(())
    }

    // --------------------------------------------------------- masters and layouts
    /// (master part, [(layout part, name)]) for every master.
    fn layouts(&mut self) -> Vec<(String, Vec<(String, String)>)> {
        let mut out = Vec::new();
        for m in self.deck.masters() {
            let ls = self.deck.layouts_of(&m);
            let named = ls.into_iter().map(|l| { let n = self.deck.layout_name(&l); (l, n) }).collect();
            out.push((m, named));
        }
        out
    }

    fn slide_layout(&mut self, i: usize) -> Option<String> {
        let p = self.deck.slides.get(i)?.clone();
        self.deck.layout_of(&p)
    }

    /// A layout's picture (for the New Slide gallery): (w, h, stride, bytes).
    fn render_part<'py>(&mut self, py: Python<'py>, part: &str, scale: f64) -> PyResult<(i32, i32, i32, Bound<'py, PyBytes>)> {
        let (w, h) = self.size();
        let pw = ((w * scale).round() as i32).max(1);
        let ph = ((h * scale).round() as i32).max(1);
        let mut surf = cairo::ImageSurface::create(cairo::Format::ARgb32, pw, ph).map_err(err)?;
        {
            let cr = cairo::Context::new(&surf).map_err(err)?;
            cr.scale(scale, scale);
            self.painter.draw(&mut self.deck, part, &cr, &Opts { edit: false, hide: None });
        }
        surf.flush();
        let stride = surf.stride();
        let data = surf.data().map_err(err)?;
        Ok((pw, ph, stride, PyBytes::new_bound(py, &data)))
    }

    // --------------------------------------------------------- slides
    #[pyo3(signature = (after, layout))]
    fn new_slide(&mut self, after: Option<usize>, layout: &str) -> PyResult<usize> {
        self.deck.new_slide(after, layout).map_err(err)
    }

    fn duplicate_slides(&mut self, idx: Vec<usize>) -> PyResult<usize> {
        self.deck.duplicate_slides(&idx).map_err(err)
    }

    fn delete_slides(&mut self, idx: Vec<usize>) -> PyResult<()> {
        self.deck.delete_slides(&idx).map_err(err)
    }

    fn move_slides(&mut self, idx: Vec<usize>, to: usize) -> PyResult<usize> {
        self.deck.move_slides(&idx, to).map_err(err)
    }

    fn is_hidden(&mut self, i: usize) -> bool {
        self.deck.is_hidden(i)
    }

    fn set_hidden(&mut self, idx: Vec<usize>, hidden: bool) -> PyResult<()> {
        self.deck.set_hidden(&idx, hidden).map_err(err)
    }

    fn set_layout(&mut self, idx: Vec<usize>, layout: &str) -> PyResult<()> {
        self.deck.set_layout(&idx, layout).map_err(err)
    }

    // --------------------------------------------------------- shapes
    #[pyo3(signature = (i, x, y, w, h, text=""))]
    fn add_textbox(&mut self, i: usize, x: f64, y: f64, w: f64, h: f64, text: &str) -> PyResult<u32> {
        self.deck.add_textbox(i, x, y, w, h, text).map_err(err)
    }

    fn add_shape(&mut self, i: usize, prst: &str, x: f64, y: f64, w: f64, h: f64) -> PyResult<u32> {
        self.deck.add_shape(i, prst, x, y, w, h).map_err(err)
    }

    #[allow(clippy::too_many_arguments)]
    fn add_picture(&mut self, i: usize, data: Vec<u8>, ext: &str, name: &str, x: f64, y: f64, w: f64, h: f64) -> PyResult<u32> {
        let r = self.deck.add_picture(i, data, ext, name, x, y, w, h).map_err(err);
        self.painter.forget_pictures();
        r
    }

    /// Picture size in pixels from file bytes.
    #[staticmethod]
    fn picture_size(data: &[u8]) -> Option<(i32, i32)> {
        folio_core::pictures::decode(data, 100000).map(|s| (s.width(), s.height()))
    }

    #[pyo3(signature = (i, boxes, label="Move"))]
    fn set_boxes(&mut self, i: usize, boxes: Vec<(u32, f64, f64, f64, f64, Option<f64>)>, label: &str) -> PyResult<()> {
        self.deck.set_boxes(i, &boxes, label).map_err(err)
    }

    fn flip(&mut self, i: usize, ids: Vec<u32>, horizontal: bool) -> PyResult<()> {
        self.deck.flip(i, &ids, horizontal).map_err(err)
    }

    fn delete_shapes(&mut self, i: usize, ids: Vec<u32>) -> PyResult<()> {
        self.deck.delete_shapes(i, &ids).map_err(err)
    }

    fn reorder(&mut self, i: usize, ids: Vec<u32>, how: &str) -> PyResult<()> {
        self.deck.reorder(i, &ids, how).map_err(err)
    }

    fn duplicate_shapes(&mut self, i: usize, ids: Vec<u32>, dx: f64, dy: f64) -> PyResult<Vec<u32>> {
        self.deck.duplicate_shapes(i, &ids, dx, dy).map_err(err)
    }

    fn shapes_xml(&mut self, i: usize, ids: Vec<u32>) -> PyResult<String> {
        self.deck.shapes_xml(i, &ids).map_err(err)
    }

    fn paste_shapes(&mut self, i: usize, xml: &str, dx: f64, dy: f64) -> PyResult<Vec<u32>> {
        self.deck.paste_shapes(i, xml, dx, dy).map_err(err)
    }

    fn group(&mut self, i: usize, ids: Vec<u32>) -> PyResult<u32> {
        self.deck.group(i, &ids).map_err(err)
    }

    fn ungroup(&mut self, i: usize, id: u32) -> PyResult<Vec<u32>> {
        self.deck.ungroup(i, id).map_err(err)
    }

    // --------------------------------------------------------- text
    fn paragraphs(&mut self, i: usize, id: u32) -> Vec<String> {
        self.deck.paragraphs(i, id)
    }

    #[pyo3(signature = (i, id, para, off, text, label="Typing"))]
    fn insert_text(&mut self, i: usize, id: u32, para: usize, off: usize, text: &str, label: &str) -> PyResult<(usize, usize)> {
        self.deck.insert_text(i, id, para, off, text, label).map_err(err)
    }

    #[pyo3(signature = (i, id, a, b, label="Delete"))]
    fn delete_text(&mut self, i: usize, id: u32, a: (usize, usize), b: (usize, usize), label: &str) -> PyResult<(usize, usize)> {
        self.deck.delete_text(i, id, a, b, label).map_err(err)
    }

    fn set_text(&mut self, i: usize, id: u32, text: &str) -> PyResult<()> {
        self.deck.set_text(i, id, text).map_err(err)
    }

    fn format_runs(&mut self, i: usize, id: u32, a: (usize, usize), b: (usize, usize), key: &str, value: &str) -> PyResult<()> {
        self.deck.format_runs(i, id, a, b, key, value).map_err(err)
    }

    fn format_paras(&mut self, i: usize, id: u32, p0: usize, p1: usize, key: &str, value: &str) -> PyResult<()> {
        self.deck.format_paras(i, id, p0, p1, key, value).map_err(err)
    }

    /// Run properties at a position: dict of b, i, u, strike, sz, font, color.
    fn run_props<'py>(&mut self, py: Python<'py>, i: usize, id: u32, para: usize, off: usize) -> PyResult<Bound<'py, PyDict>> {
        let d = PyDict::new_bound(py);
        if let Some(r) = self.deck.run_props_at(i, id, para, off) {
            d.set_item("b", r.b.unwrap_or(false))?;
            d.set_item("i", r.i.unwrap_or(false))?;
            d.set_item("u", r.u.map(|u| u != "none").unwrap_or(false))?;
            d.set_item("strike", r.strike.map(|s| s != "noStrike").unwrap_or(false))?;
            d.set_item("sz", r.sz.unwrap_or(18.0))?;
            d.set_item("font", r.latin.unwrap_or_default())?;
            d.set_item("color", r.color.map(|c| format!("{:06X}", c.rgb)))?;
            d.set_item("baseline", r.baseline.unwrap_or(0.0))?;
        }
        Ok(d)
    }

    /// Paragraph properties of paragraph `para`: algn, lvl, bullet kind.
    fn para_props<'py>(&mut self, py: Python<'py>, i: usize, id: u32, para: usize) -> PyResult<Bound<'py, PyDict>> {
        let d = PyDict::new_bound(py);
        let part = self.deck.slide_part(i).map_err(err)?;
        let ctx = scene::context(&mut self.deck, &part);
        let n = self.deck.find_shape(&part, id).ok_or_else(|| err("no such shape"))?;
        let levels = scene::text_levels(&mut self.deck, &ctx, &part, n);
        let dom = self.deck.pkg.xml(&part).map_err(err)?.clone();
        if let Some(tb) = dom.child(n, "p:txBody") {
            let paras = crate::text::read_paras(&dom, tb, &levels, &ctx.scheme, &Env::default());
            if let Some(p) = paras.get(para) {
                d.set_item("algn", p.props.algn.clone().unwrap_or_else(|| "l".into()))?;
                d.set_item("lvl", p.level)?;
                let b = match &p.props.bullet {
                    Some(scene::Bullet::Char(c)) => format!("char:{c}"),
                    Some(scene::Bullet::Auto(k, _)) => format!("auto:{k}"),
                    _ => "none".into(),
                };
                d.set_item("bullet", b)?;
                let ls = match &p.props.ln_spc {
                    Some(scene::Spc::Pct(v)) => *v,
                    _ => 1.0,
                };
                d.set_item("lnSpc", ls)?;
            }
        }
        Ok(d)
    }

    /// Caret (x, y, h) on the slide in points, and the shape's rotation.
    fn caret(&mut self, i: usize, id: u32, para: usize, off: usize) -> PyResult<Option<(f64, f64, f64, f64)>> {
        let (lay, (x, y, _w, _h, rot)) = self.layout_of(i, id)?;
        Ok(lay.caret(para, off).map(|(cx, cy, ch)| (x + cx, y + cy, ch, rot)))
    }

    /// The text position at a point inside the shape (slide points, unrotated).
    fn hit(&mut self, i: usize, id: u32, px: f64, py_: f64) -> PyResult<(usize, usize)> {
        let (lay, (x, y, w, h, rot)) = self.layout_of(i, id)?;
        // undo the shape's rotation about its centre
        let (cx, cy) = (x + w / 2.0, y + h / 2.0);
        let a = -rot.to_radians();
        let (dx, dy) = (px - cx, py_ - cy);
        let (rx, ry) = (dx * a.cos() - dy * a.sin(), dx * a.sin() + dy * a.cos());
        Ok(lay.hit(rx + w / 2.0, ry + h / 2.0))
    }

    fn selection_rects(&mut self, i: usize, id: u32, a: (usize, usize), b: (usize, usize)) -> PyResult<Vec<(f64, f64, f64, f64)>> {
        let (lay, (x, y, _, _, _)) = self.layout_of(i, id)?;
        Ok(lay.selection(a, b).into_iter().map(|(sx, sy, sw, sh)| (x + sx, y + sy, sw, sh)).collect())
    }

    fn vertical(&mut self, i: usize, id: u32, para: usize, off: usize, down: bool, want_x: f64) -> PyResult<Option<(usize, usize)>> {
        let (lay, (x, _, _, _, _)) = self.layout_of(i, id)?;
        Ok(lay.vertical(para, off, down, want_x - x))
    }

    fn line_bounds(&mut self, i: usize, id: u32, para: usize, off: usize) -> PyResult<Option<((usize, usize), (usize, usize))>> {
        let (lay, _) = self.layout_of(i, id)?;
        Ok(lay.line_bounds(para, off))
    }

    /// Text height of a shape (for autofit text boxes).
    fn text_height(&mut self, i: usize, id: u32) -> PyResult<f64> {
        let (lay, _) = self.layout_of(i, id)?;
        Ok(lay.height)
    }

    // --------------------------------------------------------- undo
    fn undo(&mut self) -> Option<String> {
        let r = self.deck.undo();
        self.painter.forget_pictures();
        r
    }

    fn redo(&mut self) -> Option<String> {
        let r = self.deck.redo();
        self.painter.forget_pictures();
        r
    }

    fn undo_label(&self) -> Option<String> {
        self.deck.undo_label()
    }

    fn redo_label(&self) -> Option<String> {
        self.deck.redo_label()
    }

    fn undo_labels(&self) -> Vec<String> {
        self.deck.undo_labels()
    }

    /// After a text change: a resize-to-fit box takes its text's height; a shrink-on-overflow box
    /// takes the font scale that fits (as PowerPoint does). True when something changed.
    #[pyo3(signature = (i, id, label="Typing"))]
    fn fit_text(&mut self, i: usize, id: u32, label: &str) -> PyResult<bool> {
        let part = self.deck.slide_part(i).map_err(err)?;
        let ctx = scene::context(&mut self.deck, &part);
        let Some(n) = self.deck.find_shape(&part, id) else { return Ok(false) };
        let body = scene::body_props(&mut self.deck, &ctx, &part, n);
        let (x, y, w, h, _, _, _) = scene::shape_box(&mut self.deck, &ctx, &part, n);
        let dom = self.deck.pkg.xml(&part).map_err(err)?.clone();
        let Some(tb) = dom.child(n, "p:txBody") else { return Ok(false) };
        let levels = scene::text_levels(&mut self.deck, &ctx, &part, n);
        let date = chrono::Local::now().format("%-m/%-d/%Y").to_string();
        let lay_at = |painter: &mut Painter, scale: f64, red: f64| {
            let env = Env { slide_num: i + 1, date: date.clone(), font_scale: scale, spc_reduction: red };
            let paras = crate::text::read_paras(&dom, tb, &levels, &ctx.scheme, &env);
            let mut b = body.clone();
            b.norm_autofit = None;
            let c = ctx.clone();
            crate::text::layout(paras, &b, w, h, &mut painter.fonts, &move |f: &str| c.font(f), &env)
        };
        if body.sp_autofit {
            let lay = lay_at(&mut self.painter, 1.0, 0.0);
            let need = (lay.height + body.t + body.b).max(1.0);
            let vertical = body.vert != "horz";
            if !vertical && (need - h).abs() > 0.5 {
                // grows down from the top (up from the bottom when anchored at the bottom)
                let ny = if body.anchor == "b" { y + h - need } else if body.anchor == "ctr" { y + (h - need) / 2.0 } else { y };
                self.deck.set_boxes(i, &[(id, x, ny, w, need, None)], label).map_err(err)?;
                return Ok(true);
            }
            return Ok(false);
        }
        if let Some((cur, cur_red)) = body.norm_autofit {
            let inner = h - body.t - body.b;
            let mut best = (1.0, 0.0);
            for k in 0..16 {
                let s = 1.0 - k as f64 * 0.05;
                let red = if k == 0 { 0.0 } else { (k as f64 * 0.05).min(0.2) };
                best = (s, red);
                if lay_at(&mut self.painter, s, red).height <= inner + 0.5 {
                    break;
                }
            }
            if (best.0 - cur).abs() > 0.001 || (best.1 - cur_red).abs() > 0.001 {
                self.deck.set_font_scale(i, id, best.0, best.1, label).map_err(err)?;
                return Ok(true);
            }
        }
        Ok(false)
    }

    /// Slide backgrounds: "RRGGBB", "scheme:bg2", or "" to follow the layout.
    fn set_background(&mut self, idx: Vec<usize>, spec: &str) -> PyResult<()> {
        self.deck.set_background(&idx, spec).map_err(err)
    }

    fn set_shape_fill(&mut self, i: usize, ids: Vec<u32>, spec: &str) -> PyResult<()> {
        self.deck.set_shape_fill(i, &ids, spec).map_err(err)
    }

    #[pyo3(signature = (i, ids, spec, width=None, dash=None))]
    fn set_shape_line(&mut self, i: usize, ids: Vec<u32>, spec: Option<&str>, width: Option<f64>, dash: Option<&str>) -> PyResult<()> {
        self.deck.set_shape_line(i, &ids, spec, width, dash).map_err(err)
    }

    fn set_shape_shadow(&mut self, i: usize, ids: Vec<u32>, on: bool) -> PyResult<()> {
        self.deck.set_shape_shadow(i, &ids, on).map_err(err)
    }

    fn set_alt_text(&mut self, i: usize, id: u32, text: &str) -> PyResult<()> {
        self.deck.set_alt_text(i, id, text).map_err(err)
    }

    fn rename_shape(&mut self, i: usize, id: u32, name: &str) -> PyResult<()> {
        self.deck.rename_shape(i, id, name).map_err(err)
    }

    fn set_notes(&mut self, i: usize, text: &str) -> PyResult<()> {
        self.deck.set_notes(i, text).map_err(err)
    }

    fn break_typing(&mut self) {
        self.deck.break_typing();
    }

    /// Notes text of slide i.
    fn notes(&mut self, i: usize) -> String {
        let Some(p) = self.deck.slides.get(i).cloned() else { return String::new() };
        let Some(n) = self.deck.notes_of(&p) else { return String::new() };
        let Ok(d) = self.deck.pkg.xml(&n) else { return String::new() };
        let Some(tree) = crate::model::path(d, d.root, &["p:cSld", "p:spTree"]) else { return String::new() };
        for c in d.elements(tree) {
            if scene::ph_of(d, c).is_some_and(|p| p.kind == "body") {
                if let Some(tb) = d.child(c, "p:txBody") {
                    return crate::text::plain_text(d, tb).join("\n");
                }
            }
        }
        String::new()
    }

    /// All text on a slide, in drawing order (for the outline and search).
    fn slide_text(&mut self, i: usize) -> Vec<(u32, Option<String>, Vec<String>)> {
        let Some(p) = self.deck.slides.get(i).cloned() else { return Vec::new() };
        let Ok(d) = self.deck.pkg.xml(&p) else { return Vec::new() };
        let Some(tree) = crate::model::path(d, d.root, &["p:cSld", "p:spTree"]) else { return Vec::new() };
        let mut all = Vec::new();
        scene::collect_shapes(d, tree, &mut all);
        all.into_iter().filter_map(|n| {
            let tb = d.child(n, "p:txBody")?;
            Some((scene::shape_id(d, n).0, scene::ph_of(d, n).map(|p| p.kind), crate::text::plain_text(d, tb)))
        }).collect()
    }
}

#[pymodule]
fn deliver_core(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<PyPresentation>()?;
    Ok(())
}

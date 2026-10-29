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
        let (sid, cell) = crate::edit::split_tid(id);
        let n = self.deck.find_shape(&part, sid).ok_or_else(|| err("no such shape"))?;
        let (x, y, w, h, rot, _, _) = scene::shape_box(&mut self.deck, &ctx, &part, n);
        let dom = self.deck.pkg.xml(&part).map_err(err)?.clone();
        let env = Env { slide_num: i + 1, date: chrono::Local::now().format("%-m/%-d/%Y").to_string(), font_scale: 1.0, spc_reduction: 0.0 };
        if let Some(k) = cell {
            let tbl = crate::model::path(&dom, n, &["a:graphic", "a:graphicData", "a:tbl"]).ok_or_else(|| err("not a table"))?;
            let cells = self.painter.table_cells(&mut self.deck, &ctx, &dom, tbl, &env);
            let cb = cells.into_iter().find(|c| c.index == k).ok_or_else(|| err("no such cell"))?;
            let bx = (x + cb.x, y + cb.y, cb.w, cb.h, rot);
            self.cache = Some((part, id, self.deck.version, cb.lay.clone(), bx));
            return Ok((cb.lay, bx));
        }
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
    /// `anim`: shape id -> (alpha, dx, dy, sx, sy, rot, hidden, clip direction, clip amount),
    /// how the show's animations have each shape at this moment.
    #[pyo3(signature = (i, scale, edit=true, anim=None, layers=0))]
    fn render<'py>(&mut self, py: Python<'py>, i: usize, scale: f64, edit: bool,
                   anim: Option<std::collections::HashMap<u32, (f64, f64, f64, f64, f64, f64, bool, String, f64)>>, layers: u8)
                   -> PyResult<(i32, i32, i32, Bound<'py, PyBytes>, Vec<Bound<'py, PyDict>>)> {
        let mut opts = Opts { edit, hide: None, layers, ..Default::default() };
        if let Some(a) = anim {
            for (id, (alpha, dx, dy, sx, sy, rot, hidden, cd, cf)) in a {
                opts.anim.insert(id, crate::render::Anim { alpha, dx, dy, sx, sy, rot, hidden,
                                                         clip: if cd.is_empty() { None } else { Some((cd, cf)) } });
            }
        }
        let part = self.deck.slide_part(i).map_err(err)?;
        let (w, h) = self.deck.page_size(&part);
        let pw = ((w * scale).round() as i32).max(1);
        let ph = ((h * scale).round() as i32).max(1);
        let mut surf = cairo::ImageSurface::create(cairo::Format::ARgb32, pw, ph).map_err(err)?;
        let infos = {
            let cr = cairo::Context::new(&surf).map_err(err)?;
            cr.scale(scale, scale);
            self.painter.draw(&mut self.deck, &part, &cr, &opts)
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
        let infos = self.painter.draw(&mut self.deck, &part, &cr, &Opts { edit: true, hide: None, ..Default::default() });
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
                self.painter.draw(&mut self.deck, &part, &cr, &Opts { edit: false, hide: None, ..Default::default() });
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
            self.painter.draw(&mut self.deck, &part, &cr, &Opts { edit: false, hide: None, ..Default::default() });
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
        let (w, h) = self.deck.page_size(part);
        let pw = ((w * scale).round() as i32).max(1);
        let ph = ((h * scale).round() as i32).max(1);
        let mut surf = cairo::ImageSurface::create(cairo::Format::ARgb32, pw, ph).map_err(err)?;
        {
            let cr = cairo::Context::new(&surf).map_err(err)?;
            cr.scale(scale, scale);
            self.painter.draw(&mut self.deck, part, &cr, &Opts { edit: false, hide: None, ..Default::default() });
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
            if let Some(l) = r.link {
                let (rid, act) = l.split_once('\t').unwrap_or((l.as_str(), ""));
                let part = self.deck.slide_part(i).map_err(err)?;
                d.set_item("link", self.deck.link_target(&part, rid, act))?;
            }
        }
        Ok(d)
    }

    /// Paragraph properties of paragraph `para`: algn, lvl, bullet kind.
    fn para_props<'py>(&mut self, py: Python<'py>, i: usize, id: u32, para: usize) -> PyResult<Bound<'py, PyDict>> {
        let d = PyDict::new_bound(py);
        let part = self.deck.slide_part(i).map_err(err)?;
        let ctx = scene::context(&mut self.deck, &part);
        let (sid, cell) = crate::edit::split_tid(id);
        let n = self.deck.find_shape(&part, sid).ok_or_else(|| err("no such shape"))?;
        let levels = if cell.is_some() {
            let pres = self.deck.pres.clone();
            let lv = self.deck.pkg.xml(&pres).ok().and_then(|d| d.child(d.root, "p:defaultTextStyle").map(|t| scene::read_levels(d, t, &ctx.scheme)));
            crate::render::cell_levels(&lv.unwrap_or_default(), &ctx, false, false, true)
        } else {
            scene::text_levels(&mut self.deck, &ctx, &part, n)
        };
        let dom = self.deck.pkg.xml(&part).map_err(err)?.clone();
        let tb = match cell {
            Some(k) => crate::edit::cell_node(&dom, n, k).and_then(|tc| dom.child(tc, "a:txBody")),
            None => dom.child(n, "p:txBody"),
        };
        if let Some(tb) = tb {
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

    // --------------------------------------------------------- charts
    #[allow(clippy::too_many_arguments)]
    #[pyo3(signature = (i, xml, xlsx, x, y, w, h, ex=false))]
    fn insert_chart(&mut self, i: usize, xml: &str, xlsx: Vec<u8>, x: f64, y: f64, w: f64, h: f64, ex: bool) -> PyResult<u32> {
        self.deck.insert_chart(i, xml, &xlsx, x, y, w, h, ex).map_err(err)
    }

    fn chart_part(&mut self, i: usize, id: u32) -> Option<String> {
        self.deck.chart_part(i, id)
    }

    fn chart_xml(&mut self, part: &str) -> Option<String> {
        self.deck.chart_xml(part)
    }

    fn set_chart_xml(&mut self, part: &str, xml: &str) -> PyResult<()> {
        self.deck.set_chart_xml(part, xml).map_err(err)
    }

    fn chart_workbook<'py>(&mut self, py: Python<'py>, part: &str) -> Option<Bound<'py, PyBytes>> {
        self.deck.chart_workbook(part).map(|b| PyBytes::new_bound(py, &b))
    }

    fn set_chart_workbook(&mut self, part: &str, data: Vec<u8>) -> PyResult<()> {
        self.deck.set_chart_workbook(part, &data).map_err(err)
    }

    #[allow(clippy::too_many_arguments)]
    fn add_svg_picture(&mut self, i: usize, svg: Vec<u8>, png: Vec<u8>, name: &str, x: f64, y: f64, w: f64, h: f64) -> PyResult<u32> {
        self.deck.add_svg_picture(i, &svg, &png, name, x, y, w, h).map_err(err)
    }

    // --------------------------------------------------------- ink, media, objects
    #[pyo3(signature = (i, pts, color, width, alpha=100.0, name="Ink"))]
    fn add_ink(&mut self, i: usize, pts: Vec<(f64, f64)>, color: u32, width: f64, alpha: f64, name: &str) -> PyResult<u32> {
        self.deck.add_ink(i, &pts, color, width, alpha, name).map_err(err)
    }

    #[allow(clippy::too_many_arguments)]
    fn add_media(&mut self, i: usize, kind: &str, data: Vec<u8>, ext: &str, poster: Vec<u8>, name: &str,
                 x: f64, y: f64, w: f64, h: f64) -> PyResult<u32> {
        self.deck.add_media(i, kind, data, ext, poster, name, x, y, w, h).map_err(err)
    }

    fn media_info(&mut self, i: usize, id: u32) -> Option<(String, String, String)> {
        self.deck.media_info(i, id)
    }

    #[allow(clippy::too_many_arguments)]
    fn add_embedded(&mut self, i: usize, data: Vec<u8>, ext: &str, prog_id: &str, icon: Vec<u8>, name: &str,
                    x: f64, y: f64, w: f64, h: f64) -> PyResult<u32> {
        self.deck.add_embedded(i, data, ext, prog_id, icon, name, x, y, w, h).map_err(err)
    }

    fn embedded_info(&mut self, i: usize, id: u32) -> Option<(String, String)> {
        self.deck.embedded_info(i, id)
    }

    fn part_bytes<'py>(&mut self, py: Python<'py>, part: &str) -> Option<Bound<'py, PyBytes>> {
        self.deck.part_bytes(part).map(|b| PyBytes::new_bound(py, &b))
    }

    #[allow(clippy::too_many_arguments)]
    fn insert_equation(&mut self, i: usize, omml: &str, png: Vec<u8>, x: f64, y: f64, w: f64, h: f64) -> PyResult<u32> {
        self.deck.insert_equation(i, omml, png, x, y, w, h).map_err(err)
    }

    fn equation(&mut self, i: usize, id: u32) -> Option<String> {
        self.deck.equation(i, id)
    }

    fn set_equation(&mut self, i: usize, id: u32, omml: &str, png: Vec<u8>, w: f64, h: f64) -> PyResult<()> {
        self.deck.set_equation(i, id, omml, png, w, h).map_err(err)
    }

    // --------------------------------------------------------- SmartArt
    #[allow(clippy::too_many_arguments)]
    fn insert_diagram(&mut self, i: usize, data: String, layout: String, style: String, colors: String, drawing: String,
                      x: f64, y: f64, w: f64, h: f64) -> PyResult<u32> {
        self.deck.insert_diagram(i, &[data, layout, style, colors, drawing], x, y, w, h).map_err(err)
    }

    fn diagram_parts(&mut self, i: usize, id: u32) -> Option<Vec<String>> {
        self.deck.diagram_parts(i, id)
    }

    fn part_xml(&mut self, part: &str) -> Option<String> {
        self.deck.pkg.bytes(part).map(|b| String::from_utf8_lossy(&b).into_owned())
    }

    #[allow(clippy::too_many_arguments)]
    fn set_diagram(&mut self, i: usize, id: u32, data: String, layout: String, style: String, colors: String, drawing: String) -> PyResult<()> {
        self.deck.set_diagram(i, id, &[data, layout, style, colors, drawing]).map_err(err)
    }

    // --------------------------------------------------------- Slide Master view
    /// Index base for design parts: slide index DESIGN + k is design part k.
    #[staticmethod]
    fn design_base() -> usize {
        crate::model::DESIGN
    }

    /// [(k, part, kind, name, slides using it)]; kind master | layout | notesMaster | handoutMaster.
    fn design_parts(&mut self) -> Vec<(usize, String, String, String, usize)> {
        self.deck.design_parts()
    }

    #[pyo3(signature = (master, after=None, name="Custom Layout"))]
    fn add_layout(&mut self, master: &str, after: Option<&str>, name: &str) -> PyResult<String> {
        self.deck.add_layout(master, after, name).map_err(err)
    }

    fn duplicate_design(&mut self, part: &str) -> PyResult<String> {
        self.deck.duplicate_design(part).map_err(err)
    }

    fn delete_design(&mut self, part: &str) -> PyResult<()> {
        self.deck.delete_design(part).map_err(err)
    }

    fn rename_design(&mut self, part: &str, name: &str) -> PyResult<()> {
        self.deck.rename_design(part, name).map_err(err)
    }

    fn preserved(&mut self, part: &str) -> bool {
        self.deck.preserved(part)
    }

    fn set_preserved(&mut self, part: &str, on: bool) -> PyResult<()> {
        self.deck.set_preserved(part, on).map_err(err)
    }

    fn design_placeholders(&mut self, part: &str) -> Vec<String> {
        self.deck.design_placeholders(part)
    }

    fn design_toggle(&mut self, part: &str, which: &str, on: bool) -> PyResult<()> {
        self.deck.design_toggle(part, which, on).map_err(err)
    }

    #[allow(clippy::too_many_arguments)]
    fn add_layout_placeholder(&mut self, part: &str, kind: &str, x: f64, y: f64, w: f64, h: f64) -> PyResult<u32> {
        self.deck.add_layout_placeholder(part, kind, x, y, w, h).map_err(err)
    }

    fn ensure_handout_master(&mut self) -> PyResult<String> {
        self.deck.ensure_handout_master().map_err(err)
    }

    fn notes_master_part(&mut self) -> PyResult<String> {
        self.deck.notes_master_part().map_err(err)
    }

    fn shows_master_shapes(&mut self, part: &str) -> bool {
        self.deck.shows_master_shapes(part)
    }

    fn set_show_master_shapes(&mut self, part: &str, on: bool) -> PyResult<()> {
        self.deck.set_show_master_shapes(part, on).map_err(err)
    }

    fn layouts_of(&mut self, master: &str) -> Vec<String> {
        self.deck.layouts_of(master)
    }

    fn page_size(&mut self, part: &str) -> (f64, f64) {
        self.deck.page_size(part)
    }

    // --------------------------------------------------------- reuse, change picture, show settings
    /// The slides of a presentation file: [(index, layout name)].
    #[staticmethod]
    fn file_slides(path: &str) -> PyResult<Vec<(usize, String)>> {
        let b = std::fs::read(path).map_err(err)?;
        Deck::file_slides(&b).map_err(err)
    }

    #[pyo3(signature = (path, which, after, fallback))]
    fn reuse_slides(&mut self, path: &str, which: Vec<usize>, after: Option<usize>, fallback: &str) -> PyResult<usize> {
        let b = std::fs::read(path).map_err(err)?;
        self.deck.reuse_slides(&b, &which, after, fallback).map_err(err)
    }

    fn replace_picture(&mut self, i: usize, id: u32, data: Vec<u8>, ext: &str) -> PyResult<()> {
        self.deck.replace_picture(i, id, data, ext).map_err(err)
    }

    /// What copied shapes refer to (pictures, media, links), to paste them in any presentation.
    fn shape_media<'py>(&mut self, py: Python<'py>, i: usize, xml: &str) -> Vec<(String, String, String, Bound<'py, PyBytes>, String, bool)> {
        self.deck.shape_media(i, xml).into_iter().map(|(a, b, c, d, e, f)| (a, b, c, PyBytes::new_bound(py, &d), e, f)).collect()
    }

    #[pyo3(signature = (i, xml, media, dx=0.0, dy=0.0))]
    fn paste_shapes_media(&mut self, i: usize, xml: &str, media: Vec<(String, String, String, Vec<u8>, String, bool)>, dx: f64, dy: f64) -> PyResult<Vec<u32>> {
        self.deck.paste_shapes_media(i, xml, &media, dx, dy).map_err(err)
    }

    fn custom_shows(&mut self) -> Vec<(String, Vec<usize>)> {
        self.deck.custom_shows()
    }

    fn set_custom_shows(&mut self, shows: Vec<(String, Vec<usize>)>) -> PyResult<()> {
        self.deck.set_custom_shows(&shows).map_err(err)
    }

    /// (kind, loop, no animation, from, to, use timings, pen colour)
    fn show_settings(&mut self) -> (String, bool, bool, i64, i64, bool, String) {
        self.deck.show_settings()
    }

    #[allow(clippy::too_many_arguments)]
    fn set_show_settings(&mut self, kind: &str, looped: bool, no_anim: bool, from: i64, to: i64, timings: bool, pen: &str) -> PyResult<()> {
        self.deck.set_show_settings(kind, looped, no_anim, from, to, timings, pen).map_err(err)
    }

    // --------------------------------------------------------- links, crop, comments
    /// Link text a..b ((para, char)) to an address, "slide:N", "next", "prev", "first", "last",
    /// "end"; "" removes it.
    fn set_link(&mut self, i: usize, id: u32, a: (usize, usize), b: (usize, usize), target: &str) -> PyResult<()> {
        self.deck.set_link(i, id, a, b, target).map_err(err)
    }

    fn link_at(&mut self, i: usize, id: u32, para: usize, off: usize) -> Option<String> {
        self.deck.link_at_pos(i, id, para, off)
    }

    fn set_shape_link(&mut self, i: usize, id: u32, target: &str) -> PyResult<()> {
        self.deck.set_shape_link(i, id, target).map_err(err)
    }

    // --------------------------------------------------------- Backlog 3
    /// A shape's outline polygons in slide points (Merge Shapes).
    fn shape_outline(&mut self, i: usize, id: u32) -> PyResult<Vec<Vec<(f64, f64)>>> {
        self.deck.shape_outline(i, id).map_err(err)
    }

    /// Add an object written as XML; parts: (key, rel, stem, ext, content type, bytes, target).
    #[pyo3(signature = (i, label, xml, parts=Vec::new()))]
    fn insert_object_xml(&mut self, i: usize, label: &str, xml: &str,
                         parts: Vec<(String, String, String, String, String, Vec<u8>, String)>) -> PyResult<u32> {
        let ps = parts.into_iter().map(|(key, rel, stem, ext, ctype, data, target)|
            crate::edit8::NewPart { key, rel, stem, ext, ctype, data, target }).collect();
        self.deck.insert_object_xml(i, label, xml, ps).map_err(err)
    }

    #[pyo3(signature = (i, id, label, xml, parts=Vec::new()))]
    fn replace_object_xml(&mut self, i: usize, id: u32, label: &str, xml: &str,
                          parts: Vec<(String, String, String, String, String, Vec<u8>, String)>) -> PyResult<()> {
        let ps = parts.into_iter().map(|(key, rel, stem, ext, ctype, data, target)|
            crate::edit8::NewPart { key, rel, stem, ext, ctype, data, target }).collect();
        self.deck.replace_object_xml(i, id, label, xml, ps).map_err(err)
    }

    fn object_xml(&mut self, i: usize, id: u32) -> Option<String> {
        self.deck.object_xml(i, id)
    }

    fn slide_rel_part(&mut self, i: usize, rid: &str) -> Option<String> {
        self.deck.slide_rel_part(i, rid)
    }

    fn set_part(&mut self, name: &str, data: Vec<u8>, label: &str) -> PyResult<()> {
        let r = self.deck.set_part(name, data, label).map_err(err);
        self.painter.forget_pictures();
        r
    }

    /// Join the last `n` undo steps into one labelled step (a command made of several changes).
    fn merge_undo(&mut self, n: usize, label: &str) {
        for _ in 1..n {
            self.deck.merge_last_two(label);
        }
    }

    fn pres_attr(&mut self, name: &str) -> Option<String> {
        self.deck.pres_attr(name)
    }

    #[pyo3(signature = (name, value=None))]
    fn set_pres_attr(&mut self, name: &str, value: Option<&str>) -> PyResult<()> {
        self.deck.set_pres_attr(name, value).map_err(err)
    }

    fn media_parts(&self) -> Vec<(String, usize)> {
        self.deck.media_parts()
    }

    fn custom_props(&mut self) -> Vec<(String, String)> {
        self.deck.custom_props()
    }

    fn set_custom_prop(&mut self, name: &str, kind: &str, value: &str) -> PyResult<()> {
        self.deck.set_custom_prop(name, kind, value).map_err(err)
    }

    fn embedded_fonts(&mut self) -> Vec<(String, String, String)> {
        self.deck.embedded_fonts()
    }

    fn set_embedded_fonts(&mut self, fonts: Vec<(String, Vec<(String, Vec<u8>)>)>) -> PyResult<()> {
        self.deck.set_embedded_fonts(fonts).map_err(err)
    }

    #[pyo3(signature = (i, id, which, target, sound=None, stop_sound=false, highlight=false))]
    #[allow(clippy::too_many_arguments)]
    fn set_shape_action(&mut self, i: usize, id: u32, which: &str, target: &str, sound: Option<(Vec<u8>, String)>,
                        stop_sound: bool, highlight: bool) -> PyResult<()> {
        self.deck.set_shape_action(i, id, which, target, sound, stop_sound, highlight).map_err(err)
    }

    fn shape_action(&mut self, i: usize, id: u32, which: &str) -> Option<(String, String, bool, bool)> {
        self.deck.shape_action(i, id, which)
    }

    /// Look for fonts again (after the app put a presentation's embedded fonts where the
    /// font search finds them).
    fn reload_fonts(&mut self) {
        self.painter = crate::render::Painter::new();
        self.cache = None;
    }

    fn shape_link(&mut self, i: usize, id: u32) -> Option<String> {
        self.deck.shape_link(i, id)
    }

    fn picture_data<'py>(&mut self, py: Python<'py>, i: usize, id: u32) -> Option<Bound<'py, pyo3::types::PyBytes>> {
        self.deck.picture_data(i, id).map(|b| pyo3::types::PyBytes::new_bound(py, &b))
    }

    /// A picture's crop: fractions cut from (left, top, right, bottom).
    fn crop(&mut self, i: usize, id: u32) -> Option<(f64, f64, f64, f64)> {
        self.deck.crop(i, id)
    }

    #[allow(clippy::too_many_arguments)]
    fn set_crop(&mut self, i: usize, id: u32, l: f64, t: f64, r: f64, b: f64, x: f64, y: f64, w: f64, h: f64) -> PyResult<()> {
        self.deck.set_crop(i, id, l, t, r, b, x, y, w, h).map_err(err)
    }

    /// [(idx, author, initials, date, text, x, y)]
    fn comments(&mut self, i: usize) -> Vec<(u32, String, String, String, String, f64, f64)> {
        self.deck.comments(i)
    }

    #[pyo3(signature = (i, text, author, initials, x=10.0, y=10.0))]
    fn add_comment(&mut self, i: usize, text: &str, author: &str, initials: &str, x: f64, y: f64) -> PyResult<u32> {
        self.deck.add_comment(i, text, author, initials, x, y).map_err(err)
    }

    fn edit_comment(&mut self, i: usize, idx: u32, text: &str) -> PyResult<()> {
        self.deck.edit_comment(i, idx, text).map_err(err)
    }

    #[pyo3(signature = (i, idx=None))]
    fn delete_comment(&mut self, i: usize, idx: Option<u32>) -> PyResult<()> {
        self.deck.delete_comment(i, idx).map_err(err)
    }

    fn rename_shape(&mut self, i: usize, id: u32, name: &str) -> PyResult<()> {
        self.deck.rename_shape(i, id, name).map_err(err)
    }

    // --------------------------------------------------------- tables
    #[staticmethod]
    fn cell_id(id: u32, cell: usize) -> u32 {
        crate::edit::cell_tid(id, cell)
    }

    #[staticmethod]
    fn split_id(tid: u32) -> (u32, Option<usize>) {
        crate::edit::split_tid(tid)
    }

    fn add_table(&mut self, i: usize, rows: usize, cols: usize, x: f64, y: f64, w: f64) -> PyResult<u32> {
        self.deck.add_table(i, rows, cols, x, y, w).map_err(err)
    }

    /// Cells of a table on slide i: [(cell index, row, col, x, y, w, h)] in slide points.
    fn table_cells(&mut self, i: usize, id: u32) -> PyResult<Vec<(usize, usize, usize, f64, f64, f64, f64)>> {
        let part = self.deck.slide_part(i).map_err(err)?;
        let ctx = scene::context(&mut self.deck, &part);
        let n = self.deck.find_shape(&part, id).ok_or_else(|| err("no such shape"))?;
        let (x, y, ..) = scene::shape_box(&mut self.deck, &ctx, &part, n);
        let dom = self.deck.pkg.xml(&part).map_err(err)?.clone();
        let Some(tbl) = crate::model::path(&dom, n, &["a:graphic", "a:graphicData", "a:tbl"]) else { return Ok(Vec::new()) };
        let env = Env { slide_num: i + 1, date: String::new(), font_scale: 1.0, spc_reduction: 0.0 };
        let cells = self.painter.table_cells(&mut self.deck, &ctx, &dom, tbl, &env);
        Ok(cells.into_iter().map(|c| (c.index, c.row, c.col, x + c.x, y + c.y, c.w, c.h)).collect())
    }

    fn table_size(&mut self, i: usize, id: u32) -> Option<(usize, usize)> {
        self.deck.table_size(i, id)
    }

    fn table_insert_row(&mut self, i: usize, id: u32, at: usize) -> PyResult<()> {
        self.deck.table_insert_row(i, id, at).map_err(err)
    }

    fn table_insert_col(&mut self, i: usize, id: u32, at: usize) -> PyResult<()> {
        self.deck.table_insert_col(i, id, at).map_err(err)
    }

    fn table_delete_row(&mut self, i: usize, id: u32, row: usize) -> PyResult<bool> {
        self.deck.table_delete_row(i, id, row).map_err(err)
    }

    fn table_delete_col(&mut self, i: usize, id: u32, col: usize) -> PyResult<bool> {
        self.deck.table_delete_col(i, id, col).map_err(err)
    }

    fn table_option(&mut self, i: usize, id: u32, key: &str, on: bool) -> PyResult<()> {
        self.deck.table_option(i, id, key, on).map_err(err)
    }

    fn table_option_value(&mut self, i: usize, id: u32, key: &str) -> bool {
        self.deck.table_option_value(i, id, key)
    }

    fn table_shade(&mut self, i: usize, id: u32, cells: Vec<usize>, spec: &str) -> PyResult<()> {
        self.deck.table_shade(i, id, &cells, spec).map_err(err)
    }

    // --------------------------------------------------------- slides: footer, size, sections, transitions, theme
    #[pyo3(signature = (idx, date, number, footer, skip_title))]
    fn set_header_footer(&mut self, idx: Vec<usize>, date: Option<&str>, number: bool, footer: Option<&str>, skip_title: bool) -> PyResult<()> {
        self.deck.set_header_footer(&idx, date, number, footer, skip_title).map_err(err)
    }

    fn header_footer(&mut self, i: usize) -> (bool, String, bool, bool, String) {
        self.deck.header_footer(i)
    }

    fn set_slide_size(&mut self, w: f64, h: f64, mode: &str) -> PyResult<()> {
        self.deck.set_slide_size(w, h, mode).map_err(err)
    }

    fn sections(&mut self) -> Vec<(String, usize, usize)> {
        self.deck.sections()
    }

    #[pyo3(signature = (secs, label="Section"))]
    fn write_sections(&mut self, secs: Vec<(String, usize)>, label: &str) -> PyResult<()> {
        self.deck.write_sections(&secs, label).map_err(err)
    }

    fn transition(&mut self, i: usize) -> (String, String, f64, bool, f64) {
        self.deck.transition(i)
    }

    fn set_transition(&mut self, idx: Vec<usize>, kind: &str, opt: &str, dur: f64, click: bool, after: f64) -> PyResult<()> {
        self.deck.set_transition(&idx, kind, opt, dur, click, after).map_err(err)
    }

    fn theme_info(&mut self) -> (Vec<(String, u32)>, String, String) {
        self.deck.theme_info()
    }

    #[pyo3(signature = (name=None, colors=None, major=None, minor=None))]
    fn set_theme(&mut self, name: Option<&str>, colors: Option<Vec<u32>>, major: Option<&str>, minor: Option<&str>) -> PyResult<()> {
        let r = self.deck.set_theme(name, colors.as_deref(), major, minor).map_err(err);
        self.painter.forget_pictures();
        r
    }

    // --------------------------------------------------------- animations
    /// Slide i's effects: dicts of spid, class, preset, subtype, name, trigger, delay, dur, repeat, index.
    fn animations<'py>(&mut self, py: Python<'py>, i: usize) -> PyResult<Vec<Bound<'py, PyDict>>> {
        let fx = self.deck.animations(i);
        fx.iter().enumerate().map(|(k, e)| {
            let d = PyDict::new_bound(py);
            d.set_item("index", k)?;
            d.set_item("spid", e.spid)?;
            d.set_item("class", &e.class)?;
            d.set_item("preset", e.preset)?;
            d.set_item("subtype", e.subtype)?;
            d.set_item("name", crate::timing::preset_name(&e.class, e.preset))?;
            d.set_item("trigger", &e.trigger)?;
            d.set_item("delay", e.delay)?;
            d.set_item("dur", e.dur)?;
            d.set_item("repeat", e.repeat)?;
            d.set_item("on", e.on)?;
            d.set_item("motion", &e.motion)?;
            Ok(d)
        }).collect()
    }

    /// Write slide i's effects: each a dict as `animations` gives (an "index" keeps that effect's
    /// saved form when its kind is unchanged; without one the effect is written from its preset).
    #[pyo3(signature = (i, effects, label="Animation"))]
    fn set_animations(&mut self, i: usize, effects: Vec<Bound<'_, PyDict>>, label: &str) -> PyResult<()> {
        let old = self.deck.animations(i);
        let mut out = Vec::new();
        for d in effects {
            let get_f = |k: &str, dflt: f64| -> f64 { d.get_item(k).ok().flatten().and_then(|v| v.extract::<f64>().ok()).unwrap_or(dflt) };
            let get_s = |k: &str, dflt: &str| -> String { d.get_item(k).ok().flatten().and_then(|v| v.extract::<String>().ok()).unwrap_or_else(|| dflt.to_string()) };
            let class = get_s("class", "entr");
            let preset = get_f("preset", 10.0) as u32;
            let subtype = get_f("subtype", 0.0) as u32;
            let keep = d.get_item("index").ok().flatten().and_then(|v| v.extract::<usize>().ok())
                .and_then(|k| old.get(k)).filter(|o| o.class == class && o.preset == preset && o.subtype == subtype
                    && (o.dur - get_f("dur", o.dur)).abs() < 1e-6 && (o.repeat - get_f("repeat", o.repeat)).abs() < 1e-6
                    && o.motion == get_s("motion", &o.motion))
                .and_then(|o| o.xml.clone());
            out.push(crate::timing::Effect {
                spid: get_f("spid", 0.0) as u32, class, preset, subtype, trigger: get_s("trigger", "click"),
                delay: get_f("delay", 0.0), dur: get_f("dur", 0.5), repeat: get_f("repeat", 1.0), xml: keep,
                on: get_f("on", 0.0) as u32, motion: get_s("motion", ""),
            });
        }
        self.deck.set_animations(i, &out, label).map_err(err)
    }

    #[staticmethod]
    fn animation_presets() -> Vec<(String, u32, String, u32, f64)> {
        crate::timing::PRESETS.iter().map(|p| (p.0.to_string(), p.1, p.2.to_string(), p.3, p.4)).collect()
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

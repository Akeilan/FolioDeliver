//! The presentation package: slides in order, their layouts, masters and themes,
//! and undo by part snapshots.

use folio_core::package::Package;
use folio_core::xml::{NodeId, XmlDoc};

pub const EMU_PT: f64 = 12700.0;
pub const NS_A: &str = "http://schemas.openxmlformats.org/drawingml/2006/main";
pub const NS_R: &str = "http://schemas.openxmlformats.org/officeDocument/2006/relationships";
pub const NS_P: &str = "http://schemas.openxmlformats.org/presentationml/2006/main";
pub const RT: &str = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/";
pub const CT_SLIDE: &str = "application/vnd.openxmlformats-officedocument.presentationml.slide+xml";
pub const CT_NOTES: &str = "application/vnd.openxmlformats-officedocument.presentationml.notesSlide+xml";

#[derive(Clone)]
struct Step {
    label: String,
    parts: Vec<(String, Option<Vec<u8>>)>,
    slides: Vec<String>,
}

/// Slide indexes from here on stand for the design parts (masters, layouts, notes and handout masters).
pub const DESIGN: usize = 1 << 24;

pub struct Deck {
    /// masters and their layouts in order, then the notes and handout masters
    pub design: Vec<String>,
    pub pkg: Package,
    pub pres: String,
    pub slides: Vec<String>,
    /// slide size in EMU
    pub cx: f64,
    pub cy: f64,
    undo: Vec<Step>,
    redo: Vec<Step>,
    open_step: Option<Step>,
    pub version: u64,
    pub modified: bool,
    pub path: String,
    /// consecutive typing merges into one undo step until the caret moves
    pub typing_chain: bool,
}

pub fn emu(dom: &XmlDoc, n: NodeId, key: &str) -> Option<f64> {
    dom.attr(n, key).and_then(|v| v.parse::<f64>().ok())
}

/// Follow a path of child names.
pub fn path(dom: &XmlDoc, n: NodeId, names: &[&str]) -> Option<NodeId> {
    let mut cur = n;
    for nm in names {
        cur = dom.child(cur, nm)?;
    }
    Some(cur)
}

impl Deck {
    pub fn open(bytes: &[u8]) -> Result<Deck, String> {
        let mut pkg = Package::open(bytes).map_err(|e| e.to_string())?;
        let pres = pkg.main_part().ok()
            .filter(|p| p.ends_with(".xml"))
            .unwrap_or_else(|| "ppt/presentation.xml".to_string());
        if !pkg.has(&pres) {
            return Err("this file has no presentation in it".into());
        }
        let mut d = Deck { design: Vec::new(), pkg, pres, slides: Vec::new(), cx: 12192000.0, cy: 6858000.0, undo: Vec::new(),
                           redo: Vec::new(), open_step: None, version: 1, modified: false, path: String::new(), typing_chain: false };
        d.read_slides();
        Ok(d)
    }

    /// The slide list and size from presentation.xml.
    pub fn read_slides(&mut self) {
        let pres = self.pres.clone();
        let rels = self.pkg.rels(&pres);
        let Ok(dom) = self.pkg.xml(&pres) else { return };
        let root = dom.root;
        if let Some(sz) = dom.child(root, "p:sldSz") {
            self.cx = emu(dom, sz, "cx").unwrap_or(12192000.0);
            self.cy = emu(dom, sz, "cy").unwrap_or(6858000.0);
        }
        let mut out = Vec::new();
        if let Some(lst) = dom.child(root, "p:sldIdLst") {
            for s in dom.children_named(lst, "p:sldId") {
                let rid = dom.attr(s, "r:id").unwrap_or("");
                if let Some(r) = rels.iter().find(|r| r.id == rid) {
                    out.push(Package::resolve(&pres, &r.target));
                }
            }
        }
        self.slides = out.into_iter().filter(|p| self.pkg.has(p)).collect();
        self.refresh_design();
    }

    /// The design parts list (masters, each followed by its layouts; then notes and handout masters).
    pub fn refresh_design(&mut self) {
        let mut v = Vec::new();
        for m in self.masters() {
            v.push(m.clone());
            v.extend(self.layouts_of(&m));
        }
        let pres = self.pres.clone();
        for k in ["/notesMaster", "/handoutMaster"] {
            if let Some(p) = self.pkg.related(&pres, k) {
                v.push(p);
            }
        }
        self.design = v.into_iter().filter(|p| self.pkg.has(p)).collect();
    }

    /// The page size (points) a part is drawn on: notes and handout pages have their own.
    pub fn page_size(&mut self, part: &str) -> (f64, f64) {
        if part.contains("notesMaster") || part.contains("handoutMaster") || part.contains("notesSlide") {
            let pres = self.pres.clone();
            if let Ok(d) = self.pkg.xml(&pres) {
                if let Some(n) = d.child(d.root, "p:notesSz") {
                    return (emu(d, n, "cx").unwrap_or(6858000.0) / EMU_PT, emu(d, n, "cy").unwrap_or(9144000.0) / EMU_PT);
                }
            }
            return (540.0, 720.0);
        }
        (self.cx / EMU_PT, self.cy / EMU_PT)
    }

    pub fn layout_of(&mut self, slide: &str) -> Option<String> {
        self.pkg.related(slide, "/slideLayout")
    }

    pub fn master_of(&mut self, layout: &str) -> Option<String> {
        self.pkg.related(layout, "/slideMaster")
    }

    pub fn theme_of(&mut self, master: &str) -> Option<String> {
        self.pkg.related(master, "/theme")
    }

    pub fn notes_of(&mut self, slide: &str) -> Option<String> {
        self.pkg.related(slide, "/notesSlide")
    }

    /// (layout, master, theme) behind a slide (or a layout, or a master).
    pub fn chain(&mut self, part: &str) -> (Option<String>, Option<String>, Option<String>) {
        if part.contains("slideMasters/") {
            let t = self.theme_of(part);
            return (None, Some(part.to_string()), t);
        }
        let layout = if part.contains("slideLayouts/") { Some(part.to_string()) } else { self.layout_of(part) };
        let master = layout.as_ref().and_then(|l| self.master_of(l));
        let theme = master.as_ref().and_then(|m| self.theme_of(m));
        (layout, master, theme)
    }

    pub fn masters(&mut self) -> Vec<String> {
        let pres = self.pres.clone();
        let rels = self.pkg.rels(&pres);
        let Ok(dom) = self.pkg.xml(&pres) else { return Vec::new() };
        let mut out = Vec::new();
        if let Some(lst) = dom.child(dom.root, "p:sldMasterIdLst") {
            for m in dom.children_named(lst, "p:sldMasterId") {
                let rid = dom.attr(m, "r:id").unwrap_or("");
                if let Some(r) = rels.iter().find(|r| r.id == rid) {
                    out.push(Package::resolve(&pres, &r.target));
                }
            }
        }
        out
    }

    /// The layouts of a master, in its order.
    pub fn layouts_of(&mut self, master: &str) -> Vec<String> {
        let rels = self.pkg.rels(master);
        let Ok(dom) = self.pkg.xml(master) else { return Vec::new() };
        let mut out = Vec::new();
        if let Some(lst) = dom.child(dom.root, "p:sldLayoutIdLst") {
            for l in dom.children_named(lst, "p:sldLayoutId") {
                let rid = dom.attr(l, "r:id").unwrap_or("");
                if let Some(r) = rels.iter().find(|r| r.id == rid) {
                    out.push(Package::resolve(master, &r.target));
                }
            }
        }
        out
    }

    pub fn layout_name(&mut self, layout: &str) -> String {
        let Ok(dom) = self.pkg.xml(layout) else { return String::new() };
        dom.child(dom.root, "p:cSld").and_then(|c| dom.attr(c, "name")).unwrap_or("").to_string()
    }

    // ------------------------------------------------------------ undo
    /// Start an undoable change touching `parts` (their state now is kept).
    pub fn begin(&mut self, label: &str, parts: &[String]) {
        let mut step = self.open_step.take().unwrap_or(Step { label: label.to_string(), parts: Vec::new(), slides: self.slides.clone() });
        for p in parts {
            if step.parts.iter().any(|(n, _)| n == p) {
                continue;
            }
            step.parts.push((p.clone(), self.pkg.bytes(p)));
        }
        self.open_step = Some(step);
    }

    /// Add parts to the change in progress (before touching them).
    pub fn touch(&mut self, parts: &[String]) {
        if self.open_step.is_none() {
            self.begin("Edit", parts);
            return;
        }
        let label = self.open_step.as_ref().unwrap().label.clone();
        self.begin(&label, parts);
    }

    pub fn commit(&mut self) {
        if let Some(s) = self.open_step.take() {
            let typing = s.label == "Typing";
            let merge = typing && self.typing_chain && self.undo.last().is_some_and(|u| {
                u.label == "Typing" && s.parts.iter().all(|(n, _)| u.parts.iter().any(|(m, _)| m == n))
            });
            if !merge {
                self.undo.push(s);
            }
            if self.undo.len() > 200 {
                self.undo.remove(0);
            }
            self.typing_chain = typing;
            self.redo.clear();
            self.version += 1;
            self.modified = true;
        }
    }

    /// Join the last two undo steps into one (a change made of two operations).
    pub fn merge_last_two(&mut self, label: &str) {
        if self.undo.len() < 2 {
            return;
        }
        let last = self.undo.pop().unwrap();
        let prev = self.undo.last_mut().unwrap();
        for (n, b) in last.parts {
            if !prev.parts.iter().any(|(m, _)| *m == n) {
                prev.parts.push((n, b));
            }
        }
        prev.label = label.to_string();
    }

    /// The caret moved: the next typing starts a new undo step.
    pub fn break_typing(&mut self) {
        self.typing_chain = false;
    }

    /// Drop the change in progress, putting the parts back.
    pub fn cancel(&mut self) {
        if let Some(s) = self.open_step.take() {
            self.restore(&s);
        }
    }

    fn snapshot_of(&self, step: &Step) -> Step {
        Step {
            label: step.label.clone(),
            parts: step.parts.iter().map(|(n, _)| (n.clone(), self.pkg.bytes(n))).collect(),
            slides: self.slides.clone(),
        }
    }

    fn restore(&mut self, s: &Step) {
        for (name, data) in &s.parts {
            match data {
                Some(d) => self.pkg.put_raw(name, d.clone()),
                None => self.pkg.remove(name),
            }
        }
        // the slide size may have changed with the presentation part
        self.read_slides();
        self.slides = s.slides.clone();
        self.version += 1;
    }

    pub fn undo(&mut self) -> Option<String> {
        self.commit();
        self.typing_chain = false;
        let s = self.undo.pop()?;
        let now = self.snapshot_of(&s);
        self.restore(&s);
        self.redo.push(now);
        self.modified = true;
        Some(s.label)
    }

    pub fn redo(&mut self) -> Option<String> {
        let s = self.redo.pop()?;
        let now = self.snapshot_of(&s);
        self.restore(&s);
        self.undo.push(now);
        self.modified = true;
        Some(s.label)
    }

    pub fn undo_label(&self) -> Option<String> {
        self.undo.last().map(|s| s.label.clone())
    }

    pub fn redo_label(&self) -> Option<String> {
        self.redo.last().map(|s| s.label.clone())
    }

    /// The labels of the undo list, newest first.
    pub fn undo_labels(&self) -> Vec<String> {
        self.undo.iter().rev().map(|s| s.label.clone()).collect()
    }

    pub fn save(&mut self, path: &str) -> Result<(), String> {
        self.commit();
        self.pkg.save(path).map_err(|e| e.to_string())?;
        self.modified = false;
        self.path = path.to_string();
        Ok(())
    }

    pub fn bytes(&mut self) -> Result<Vec<u8>, String> {
        self.commit();
        self.pkg.write().map_err(|e| e.to_string())
    }

    /// A part name not yet in the package: "ppt/slides/slide7.xml".
    pub fn free_name(&self, dir: &str, stem: &str, ext: &str) -> String {
        let mut n = 1;
        loop {
            let name = format!("{dir}/{stem}{n}.{ext}");
            if !self.pkg.has(&name) {
                return name;
            }
            n += 1;
        }
    }
}

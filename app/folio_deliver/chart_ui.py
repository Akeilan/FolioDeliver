"""Charts on slides: Insert Chart, the Chart Design tab and its commands (the chart code is
shared with Folio Writer: charts_classic and charts_model)."""
from . import charts_classic as classic
from . import charts_model as CM


def _arg(v):
    if v in ("True", "False", "None"):
        return {"True": True, "False": False, "None": None}[v]
    try:
        return int(v)
    except ValueError:
        return v


class ChartCommands:
    def act_insert_chart(self, kind=None):
        """Insert > Chart: pick a type, then edit its numbers (into an empty content or chart
        placeholder when the slide has one)."""
        if self.current is None:
            return None
        box = None
        for s in self.canvas.shapes:
            if s["empty"] and s["ph"] in ("chart", "obj"):
                box = (s["x"], s["y"], s["w"], s["h"])
                self.deck.delete_shapes(self.current, [s["id"]])
                break
        if kind not in (None, ""):
            ref = CM.insert(self, int(kind), box=box)
            CM.edit_chart(self, ref)
            return ref
        return CM.insert_chart_dialog(self, box)

    def selected_chart(self):
        return CM.selected(self)

    def act_chart(self, spec):
        """chart:<function>[:<arg>[:<arg>]] on the selected chart."""
        ref = CM.selected(self)
        if ref is None:
            self.dialogs.info("Select a chart first.")
            return None
        fn, *args = spec.split(":")
        args = [_arg(a) for a in args]
        if fn == "edit":
            return CM.edit_chart(self, ref)
        if fn == "type":
            idx = classic.type_dialog(self, CM.type_index(ref), "Change Chart Type")
            if idx is not None:
                CM.set_type(ref, idx)
        elif fn == "title":
            t = self.dialogs.ask_text("Chart Title", "Title:", CM.title_of(ref))
            if t is not None:
                CM.set_title(ref, t)
        elif fn == "axis-title":
            x, y = CM.axis_titles(ref)
            which = args[0]
            t = self.dialogs.ask_text("Axis Title", "Title:", x if which == "x" else y)
            if t is not None:
                CM.set_axis_titles(ref, **{which: t or False})
        elif fn == "switch":
            d = CM.get_data(ref)
            CM.set_data(ref, {"rows": list(d["cols"]), "cols": list(d["rows"]),
                              "values": [[d["values"][r][c] for r in range(len(d["rows"]))] for c in range(len(d["cols"]))]})
        elif fn == "grid":
            cur = CM.gridlines(ref)
            cur[args[0]] = not cur[args[0]]
            CM.set_gridlines(ref, *cur)
        elif fn == "colors":
            sets = classic.COLORFUL + classic.MONOCHROMATIC
            CM.set_colors(ref, sets[args[0]][1])
        elif fn in ("set_axes", "set_axis_titles", "set_title", "set_legend", "set_data_labels", "set_data_table",
                    "quick_layout", "set_chart_style", "set_type"):
            getattr(CM, fn)(ref, *args)
        else:
            return None
        self.changed(slide=True)
        self.canvas.select([ref.sid])
        return ref


def chart_tab(win, r, B, Tab):
    """Chart Design (shown while a chart is selected)."""
    t = r.building(Tab("Chart Design", "JC", contextual=True))
    add = [("#", "Axes"), ("Primary Horizontal", "chart:set_axes:True:None"), ("Primary Vertical", "chart:set_axes:None:True"),
           ("No Axes", "chart:set_axes:False:False"),
           ("#", "Axis Titles"), ("Primary Horizontal Title...", "chart:axis-title:x"),
           ("Primary Vertical Title...", "chart:axis-title:y"), ("No Axis Titles", "chart:set_axis_titles:False:False"),
           ("#", "Chart Title"), ("Above Chart...", "chart:title"), ("None", "chart:set_title:"),
           ("#", "Data Labels"), ("None", "chart:set_data_labels:None"), ("Center", "chart:set_data_labels:center"),
           ("Inside End", "chart:set_data_labels:inside-end"), ("Inside Base", "chart:set_data_labels:inside-base"),
           ("Outside End", "chart:set_data_labels:outside-end"),
           ("#", "Data Table"), ("None", "chart:set_data_table:False"), ("With Legend Keys", "chart:set_data_table:True"),
           ("#", "Gridlines"), ("Primary Major Horizontal", "chart:grid:0"), ("Primary Major Vertical", "chart:grid:1"),
           ("Primary Minor Horizontal", "chart:grid:2"), ("Primary Minor Vertical", "chart:grid:3"),
           ("#", "Legend"), ("None", "chart:set_legend:none"), ("Right", "chart:set_legend:right"),
           ("Top", "chart:set_legend:top"), ("Left", "chart:set_legend:left"), ("Bottom", "chart:set_legend:bottom")]
    B.group(t, "Chart Layouts", [B.big("Add Chart Element", "insertgraphic", None, "A", menu=add),
                                 B.big("Quick Layout", "diagramtype", None, "L",
                                       menu=[(name, "chart:quick_layout:%d" % i) for i, (name, *_r) in enumerate(classic.QUICK_LAYOUTS)])])
    colors = [("#", "Colorful")] + [(n, "chart:colors:%d" % i) for i, (n, _c) in enumerate(classic.COLORFUL)] + \
             [("#", "Monochromatic")] + [(n, "chart:colors:%d" % (len(classic.COLORFUL) + i)) for i, (n, _c) in enumerate(classic.MONOCHROMATIC)]
    B.group(t, "Chart Styles", [B.big("Change Colors", "diagramarea", None, "H", menu=colors),
                                B.big("Chart Styles", "autoformat", None, "S",
                                      menu=[(n, "chart:set_chart_style:%d" % i) for i, n in enumerate(classic.CHART_STYLES)])])
    B.group(t, "Data", [B.big("Switch Row/Column", "datainrows", "chart:switch", "W"),
                        B.big("Edit Data", "diagramdata", "chart:edit", "D")])
    B.group(t, "Type", [B.big("Change Chart Type", "diagramtype", "chart:type", "C")])
    r.add_tab(t)

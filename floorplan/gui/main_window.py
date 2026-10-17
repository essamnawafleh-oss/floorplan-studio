"""Main window."""

from __future__ import annotations

import json
import os
import sys
import traceback

from PySide6.QtCore import QObject, QRectF, QRunnable, QSettings, QSize, Qt, QThreadPool, QTimer, Signal
from PySide6.QtGui import QAction, QActionGroup, QColor, QIcon, QPageLayout, QPageSize, QPainter, QPdfWriter
from PySide6.QtWidgets import (QApplication, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout,
                               QGridLayout, QHBoxLayout, QHeaderView, QLabel, QListWidget, QListWidgetItem,
                               QMainWindow, QMenu, QMessageBox, QPushButton, QScrollArea, QSizePolicy, QSplitter,
                               QTableWidget, QTableWidgetItem, QTabWidget, QToolButton, QVBoxLayout, QWidget)

from .. import design, editing
from ..blocks import BlockLibrary
from ..export import to_dxf, to_glb, to_obj, to_svg
from ..models import Plan
from ..paths import user_dir
from . import theme
from .addons import AddonManager, AddonsDialog
from .command_line import CommandLine
from .editor import UNITS, Editor
from .library_panel import LibraryPanel
from .panels import InputPanel
from .plan_view import S, PlanScene, PlanView, render_pixmap
from .properties import PropertiesPanel
from .settings_dialog import SettingsDialog, load_prefs, save_prefs
from .strings import tr

N_VARIANTS = 6
CAD_DRAW = [("Line", "L"), ("Pline", "PL"), ("Rect", "REC"), ("Circle", "C"), ("Arc", "A"), ("Text", "T"), ("Dim", "DIM")]
CAD_MODIFY = [("Offset", "O"), ("Trim", "TR"), ("Extend", "EX"), ("Explode", "X"), ("Move", "M"), ("Copy", "CO"),
              ("Rotate", "RO"), ("Scale", "SC"), ("Mirror", "MI"), ("Erase", "E")]
PAPERS = {"A4": QPageSize.A4, "A3": QPageSize.A3, "A2": QPageSize.A2, "A1": QPageSize.A1}
SCALES = [0, 20, 50, 75, 100, 200, 500]          # 0 = fit


class _Signals(QObject):
    plan = Signal(int, object, str)            # request id, plan, error
    variant = Signal(int, int, object)         # request id, seed, plan
    cancelled = False


class _PlanTask(QRunnable):
    def __init__(self, req, cfg, seed, cand, sig):
        super().__init__()
        self.req, self.cfg, self.seed, self.cand, self.sig = req, cfg, seed, cand, sig

    def run(self):
        try:
            plan, err = design(self.cfg, seed=self.seed, candidates=self.cand), ""
        except Exception as e:  # shown to the user
            if sys.stderr:       # None in the windowed .exe
                traceback.print_exc()
            plan, err = None, str(e)
        try:
            self.sig.plan.emit(self.req, plan, err)
        except RuntimeError:     # window already closed
            pass


class _VariantTask(QRunnable):
    def __init__(self, req, cfg, seeds, cand, sig):
        super().__init__()
        self.req, self.cfg, self.seeds, self.cand, self.sig = req, cfg, seeds, cand, sig

    def run(self):
        for s in self.seeds:
            if self.sig.cancelled:
                return
            try:
                plan = design(self.cfg, seed=s, candidates=self.cand)
            except Exception:
                plan = None
            try:
                self.sig.variant.emit(self.req, s, plan)
            except RuntimeError:     # window already closed
                return


class MainWindow(QMainWindow):
    def __init__(self, examples_dir: str | None = None):
        super().__init__()
        self.settings = QSettings("FloorPlanStudio", "FloorPlanStudio")
        self.lang = self.settings.value("lang", "ar")
        self.label_lang = self.settings.value("label_lang", "both")
        self.examples_dir = examples_dir
        self.req = 0
        self.var_req = 0
        self.project_path = None
        self.pool = QThreadPool.globalInstance()
        self.sig = _Signals()
        self.sig.plan.connect(self._on_plan)
        self.sig.variant.connect(self._on_variant)
        self.timer = QTimer(self, singleShot=True, interval=450)
        self.timer.timeout.connect(self.regenerate)
        self.resize(1560, 940)
        self.prefs = load_prefs(self.settings)
        self.tokens = theme.apply(QApplication.instance(), self.prefs)
        self.plan_colors = theme.plan_colors(self.tokens, self.prefs["plan_theme"])

        self.library = BlockLibrary(user_dir("blocks"))
        self.editor = Editor(self.library, self)
        self.editor.unit = self.settings.value("unit", "m")
        self.editor.changed.connect(self.redraw)
        self.editor.overlayChanged.connect(self._overlay)
        self.editor.selectionChanged.connect(self._sync_table_selection)
        self.editor.message.connect(lambda m: self.status.setText(m))
        self.editor.togglesChanged.connect(lambda: self.cmdline.sync_toggles())
        self.addons = AddonManager(self, self.settings,
                                   os.path.join(examples_dir, "addons") if examples_dir else None)

        self._build(initial=self._initial_config())
        self.addons.load_all()
        self.regenerate()

    @property
    def plan(self) -> Plan | None:
        return self.editor.plan

    def t(self, key):
        return tr(key, self.lang)

    def _initial_config(self) -> dict:
        if self.examples_dir:
            path = os.path.join(self.examples_dir, "family.json")
            if os.path.exists(path):
                with open(path, encoding="utf-8") as f:
                    return json.load(f)
        return {"footprint": {"width": 18, "depth": 13},
                "household": {"parents": True, "sons": 2, "daughters": 1, "guests": 10}}

    # ------------------------------------------------------------------ UI
    def _build(self, initial: dict, seed: int | None = None):
        QApplication.instance().setLayoutDirection(Qt.RightToLeft if self.lang == "ar" else Qt.LeftToRight)
        self.setWindowTitle(self.t("app"))
        self.editor.lang = self.lang
        self._build_toolbars()

        self.panel = InputPanel(self.lang)
        self.panel.set_config(initial)
        if seed is not None:
            self.panel.seed.setValue(seed)
        self.panel.changed.connect(self.timer.start)
        self.panel.generateRequested.connect(self.regenerate)
        left = QScrollArea()
        left.setWidget(self.panel)
        left.setWidgetResizable(True)
        left.setMinimumWidth(360)

        self.scene = PlanScene()
        self.view = PlanView(self.scene)
        self.view.handler = self.editor
        self.view.set_canvas(self.tokens["canvas"])
        self.view.zoomChanged.connect(self._update_scale_label)

        center = QWidget()
        cv = QVBoxLayout(center)
        cv.setContentsMargins(0, 0, 0, 0)
        bar = QHBoxLayout()
        bar.setContentsMargins(8, 6, 8, 0)
        self.summary = QLabel()
        bar.addWidget(self.summary, 1)
        self.scale_label = QLabel()
        bar.addWidget(self.scale_label)
        self.scale_combo = QComboBox()
        for n in SCALES:
            self.scale_combo.addItem(self.t("fit") if n == 0 else f"1:{n}", n)
        self.scale_combo.activated.connect(self._scale_chosen)
        bar.addWidget(self.scale_combo)
        bar.addWidget(QLabel(self.t("labels")))
        self.label_combo = QComboBox()
        for k, code in (("lang_both", "both"), ("lang_ar", "ar"), ("lang_en", "en")):
            self.label_combo.addItem(self.t(k), code)
        self.label_combo.setCurrentIndex(max(0, self.label_combo.findData(self.label_lang)))
        self.label_combo.currentIndexChanged.connect(self._label_lang_changed)
        bar.addWidget(self.label_combo)
        cv.addLayout(bar)
        cv.addWidget(self.view, 1)
        self.cmdline = CommandLine(self.editor.cad)
        self.view.command_line = self.cmdline
        cv.addWidget(self.cmdline)
        self.status = QLabel()
        self.status.setObjectName("status")
        cv.addWidget(self.status)

        self.tabs = QTabWidget()
        self.tabs.setMinimumWidth(390)
        self.rooms_table = QTableWidget(0, 4)
        self.rooms_table.setHorizontalHeaderLabels([self.t("col_name"), self.t("col_target"),
                                                    self.t("col_actual"), self.t("col_dims")])
        self.rooms_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        for c in (1, 2, 3):
            self.rooms_table.horizontalHeader().setSectionResizeMode(c, QHeaderView.ResizeToContents)
        self.rooms_table.verticalHeader().setVisible(False)
        self.rooms_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.rooms_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.rooms_table.itemSelectionChanged.connect(self._table_selected)
        self.tabs.addTab(self.rooms_table, self.t("tab_rooms"))
        self.warn_list = QListWidget()
        self.warn_list.setWordWrap(True)
        self.tabs.addTab(self.warn_list, self.t("tab_warnings"))
        self.tabs.addTab(self._build_variants(), self.t("tab_variants"))
        self.props = PropertiesPanel(self.editor, self.lang)
        props_scroll = QScrollArea()
        props_scroll.setWidget(self.props)
        props_scroll.setWidgetResizable(True)
        self.props_tab = props_scroll
        self.tabs.addTab(props_scroll, self.t("tab_props"))
        self.libpanel = LibraryPanel(self.library, self.lang, self.plan_colors["ink"])
        self.libpanel.placeRequested.connect(self.place_block)
        self.tabs.addTab(self.libpanel, self.t("tab_library"))

        split = QSplitter()
        split.addWidget(left)
        split.addWidget(center)
        split.addWidget(self.tabs)
        split.setStretchFactor(1, 1)
        split.setSizes([380, 780, 400])
        self.setCentralWidget(split)
        self.addons.attach_menu(self.tools_menu)
        self.set_edit_mode(self.editor.enabled)
        if self.plan is not None:
            self.redraw(fit=True)

    def _action(self, tb, label, slot, checkable=False, tip=""):
        a = QAction(label, self)
        a.setCheckable(checkable)
        if tip:
            a.setToolTip(tip)
        a.triggered.connect(slot)
        tb.addAction(a)
        return a

    def _build_toolbars(self):
        for name in ("toolbar", "edit_toolbar", "cad_toolbar"):
            if hasattr(self, name):
                self.removeToolBar(getattr(self, name))
        tb = self.addToolBar("main")
        tb.setMovable(False)
        self.toolbar = tb
        for key, slot in (("new", self.new_project), ("open", self.open_project), ("save", self.save_project)):
            self._action(tb, self.t(key), slot)
        menu = QMenu(self)
        for label, ext in (("SVG (2D)", "svg"), ("PNG", "png"), ("PDF…", "pdf"), ("DXF (CAD)", "dxf"),
                           ("GLB (3D)", "glb"), ("OBJ (3D)", "obj"), ("JSON", "json")):
            a = menu.addAction(label)
            a.triggered.connect(lambda _=False, e=ext: self.export_one(e))
        menu.addSeparator()
        menu.addAction(self.t("export_all")).triggered.connect(self.export_all)
        btn = QToolButton()
        btn.setText(self.t("export") + " ▾")
        btn.setMenu(menu)
        btn.setPopupMode(QToolButton.InstantPopup)
        tb.addWidget(btn)
        tb.addSeparator()
        self.edit_action = self._action(tb, self.t("edit_mode"), self.set_edit_mode, checkable=True)
        tb.addSeparator()

        self.tool_group = QActionGroup(self)
        self.tool_actions = {}
        for tool, key in (("measure_len", "measure_len"), ("measure_area", "measure_area")):
            a = self._action(tb, self.t(key), lambda _=False, tl=tool: self.set_tool(tl), checkable=True)
            self.tool_group.addAction(a)
            self.tool_actions[tool] = a
        self.unit_combo = QComboBox()
        for u in UNITS:
            self.unit_combo.addItem(u, u)
        self.unit_combo.setCurrentIndex(max(0, self.unit_combo.findData(self.editor.unit)))
        self.unit_combo.currentIndexChanged.connect(self._unit_changed)
        tb.addWidget(self.unit_combo)
        self._action(tb, self.t("clear_measures"), self.editor.clear_measures)
        tb.addSeparator()
        self._action(tb, self.t("view3d"), self.open_3d)
        self._action(tb, self.t("quantities"), self.open_quantities)
        self.tools_menu = QMenu(self)
        self.tools_menu.addAction(self.t("addons_manage")).triggered.connect(self.open_addons)
        self.tools_menu.addSeparator()
        tbtn = QToolButton()
        tbtn.setText(self.t("addons") + " ▾")
        tbtn.setMenu(self.tools_menu)
        tbtn.setPopupMode(QToolButton.InstantPopup)
        tb.addWidget(tbtn)
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        tb.addWidget(spacer)
        self._action(tb, self.t("settings_btn"), self.open_settings)
        self._action(tb, self.t("about"), lambda: QMessageBox.information(self, self.t("about"), self.t("about_text")))
        self._action(tb, "🌐 " + self.t("language"), self.toggle_language)

        self.addToolBarBreak()
        et = self.addToolBar("edit")
        et.setMovable(False)
        self.edit_toolbar = et
        for tool, key in (("select", "tool_select"), ("door", "tool_door"), ("window", "tool_window"),
                          ("main_door", "tool_main_door")):
            a = self._action(et, self.t(key), lambda _=False, tl=tool: self.set_tool(tl), checkable=True)
            self.tool_group.addAction(a)
            self.tool_actions[tool] = a
        a = self._action(et, self.t("tool_furniture"), lambda: self.tabs.setCurrentWidget(self.libpanel))
        et.addSeparator()
        self._action(et, "↶ " + self.t("undo"), self.editor.undo)
        self._action(et, "↷ " + self.t("redo"), self.editor.redo)
        self._action(et, "⟲ 90°", lambda: self.editor.rotate_furniture(90))
        self._action(et, "🗑 " + self.t("delete"), self.editor.delete_selection)
        hint = QLabel("   " + self.t("edit_hint"))
        hint.setObjectName("muted")
        et.addWidget(hint)

        self.addToolBarBreak()
        ct = self.addToolBar("cad")
        ct.setMovable(False)
        self.cad_toolbar = ct
        ct.addWidget(QLabel(" " + self.t("cad_draw") + ": "))
        for name, alias in CAD_DRAW:
            self._action(ct, self.t("cad_" + name.lower()), lambda _=False, n=name: self.cad_command(n),
                         tip=f"{alias}  ·  {name.upper()}")
        ct.addSeparator()
        ct.addWidget(QLabel(" " + self.t("cad_modify") + ": "))
        for name, alias in CAD_MODIFY:
            self._action(ct, self.t("cad_" + name.lower()), lambda _=False, n=name: self.cad_command(n),
                         tip=f"{alias}  ·  {name.upper()}")
        ct.addSeparator()
        ct.addWidget(QLabel(" " + self.t("layer") + " "))
        self.layer_combo = QComboBox()
        from ..cad import LAYERS
        for name in LAYERS:
            self.layer_combo.addItem(name, name)
        self.layer_combo.setCurrentIndex(max(0, self.layer_combo.findData(self.editor.cad.layer)))
        self.layer_combo.currentIndexChanged.connect(lambda: setattr(self.editor.cad, "layer", self.layer_combo.currentData()))
        ct.addWidget(self.layer_combo)
        self.tool_actions.get(self.editor.tool, self.tool_actions["select"]).setChecked(True)

    def _build_variants(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        hint = QLabel(self.t("variants_hint"))
        hint.setObjectName("muted")
        v.addWidget(hint)
        grid = QGridLayout()
        self.var_buttons = []
        for i in range(N_VARIANTS):
            b = QToolButton()
            b.setObjectName("variant")
            b.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
            b.setIconSize(QSize(160, 117))
            b.setMinimumSize(170, 160)
            b.clicked.connect(lambda _=False, i=i: self._pick_variant(i))
            grid.addWidget(b, i // 2, i % 2)
            self.var_buttons.append(b)
        v.addLayout(grid)
        more = QPushButton(self.t("more_variants"))
        more.clicked.connect(lambda: self.run_variants(self.var_seeds[-1] + 1 if getattr(self, "var_seeds", None) else None))
        v.addWidget(more)
        v.addStretch(1)
        self.var_seeds = getattr(self, "var_seeds", [])
        self._variant_plans = getattr(self, "_variant_plans", {})
        return w

    # ------------------------------------------------------------- modes / tools
    def set_edit_mode(self, on: bool):
        on = bool(on) and self.plan is not None
        self.editor.enabled = on
        self.edit_action.setChecked(on)
        self.edit_toolbar.setVisible(on)
        self.cad_toolbar.setVisible(on)
        self.cmdline.setVisible(on)
        if not on:
            self.editor.cad.cancel()
        self.panel.setEnabled(not on)
        if not on and self.editor.tool not in ("measure_len", "measure_area"):
            self.set_tool("select")
        if on:
            self.tabs.setCurrentWidget(self.props_tab)
            self.status.setText(self.t("edit_on"))
        self.props.rebuild()
        self.redraw()

    def set_tool(self, tool: str):
        if self.editor.tool == tool and tool in ("measure_len", "measure_area"):
            tool = "select"                    # clicking an active measure tool turns it off
        self.editor.set_tool(tool)
        if tool in self.tool_actions:
            self.tool_actions[tool].setChecked(True)
        else:
            for a in self.tool_actions.values():
                a.setChecked(False)
        hints = {"measure_len": "hint_measure_len", "measure_area": "hint_measure_area", "door": "hint_door",
                 "window": "hint_window", "main_door": "hint_window", "block": "hint_block"}
        if tool in hints:
            self.status.setText(self.t(hints[tool]))

    def cad_command(self, name: str):
        if self.plan is None:
            return
        if not self.editor.enabled:
            self.set_edit_mode(True)
        for a in self.tool_actions.values():
            a.setChecked(False)
        self.editor.cad.start(name)
        self.view.setFocus()

    def place_block(self, block_id: str):
        if self.plan is None:
            return
        if not self.editor.enabled:
            self.set_edit_mode(True)
        self.editor.pending_block = block_id
        self.set_tool("block")

    def _unit_changed(self):
        self.editor.unit = self.unit_combo.currentData()
        self.settings.setValue("unit", self.editor.unit)
        self._overlay()

    # ----------------------------------------------------------- generation
    def _confirm_discard(self) -> bool:
        if self.plan is not None and self.plan.edited:
            ans = QMessageBox.question(self, self.t("app"), self.t("discard_edits"))
            return ans == QMessageBox.Yes
        return True

    def regenerate(self):
        self.timer.stop()
        if self.editor.enabled or not self._confirm_discard():
            return
        self.req += 1
        cfg = self.panel.get_config()
        self.status.setText(self.t("working"))
        self.panel.btn_generate.setEnabled(False)
        self.pool.start(_PlanTask(self.req, cfg, self.panel.seed.value(), self.panel.candidates(), self.sig))
        self.run_variants()

    def run_variants(self, start: int | None = None):
        self.var_req += 1
        start = self.panel.seed.value() + 1 if start is None else start
        self.var_seeds = list(range(start, start + N_VARIANTS))
        self._variant_plans = {}
        for b, s in zip(self.var_buttons, self.var_seeds):
            b.setIcon(QIcon())
            b.setText(f"Seed {s}  …")
        cand = min(self.panel.candidates(), 250)
        self.pool.start(_VariantTask(self.var_req, self.panel.get_config(), self.var_seeds, cand, self.sig))

    def _on_plan(self, req, plan, err):
        if req != self.req:
            return
        self.panel.btn_generate.setEnabled(True)
        if plan is None:
            self.status.setText(f"⚠ {self.t('error')}: {err}")
            return
        first = self.plan is None or (self.plan.width, self.plan.depth) != (plan.width, plan.depth)
        self.editor.set_plan(plan)
        self.redraw(fit=first)
        self.status.setText(self.t("ready"))

    def _on_variant(self, req, seed, plan):
        if req != self.var_req or seed not in self.var_seeds:
            return
        b = self.var_buttons[self.var_seeds.index(seed)]
        if plan is None:
            b.setText(f"Seed {seed}  ✕")
            return
        self._variant_plans[seed] = plan
        self._variant_icon(self.var_seeds.index(seed), plan)
        b.setText(f"Seed {seed}  ·  {plan.score:.0f}")

    def _variant_icon(self, i, plan):
        self.var_buttons[i].setIcon(QIcon(render_pixmap(plan, 300, 220, "en", self.plan_colors, self.library)))

    def _pick_variant(self, i):
        if i < len(self.var_seeds) and not self.editor.enabled:
            self.panel.seed.setValue(self.var_seeds[i])
            self.regenerate()

    def load_edited_plan(self, plan: Plan):
        self.editor.set_plan(plan)
        editing.refresh(plan)
        self.redraw(fit=True)

    # ----------------------------------------------------------- drawing
    def redraw(self, fit: bool = False):
        plan = self.plan
        self.scene.set_plan(plan, self.label_lang, self.plan_colors, self.library, self.editor.selection,
                            cad_sel=self.editor.cad.sel)
        self._overlay()
        if fit:
            self.view.fit()
        if plan is None:
            return
        edited = f" &nbsp;·&nbsp; ✏ {self.t('edited')}" if plan.edited else ""
        self.summary.setText(
            f"<b>{plan.width:.2f} × {plan.depth:.2f} m</b> &nbsp;·&nbsp; {self.t('gross')}: {plan.gross_area:.1f} m²"
            f" &nbsp;·&nbsp; {self.t('net')}: {plan.net_area:.1f} m² &nbsp;·&nbsp; {self.t('score')}: {plan.score:.1f}{edited}")
        self.rooms_table.blockSignals(True)
        self.rooms_table.setRowCount(0)
        for r in plan.rooms:
            row = self.rooms_table.rowCount()
            self.rooms_table.insertRow(row)
            name = r.spec.name_ar if self.lang == "ar" else r.spec.name_en
            target = "" if r.spec.type == "corridor" else f"{r.spec.area:.1f}"
            vals = [name, target, f"{r.net.area:.1f}", f"{r.net.w:.2f}×{r.net.h:.2f}"]
            for c, val in enumerate(vals):
                it = QTableWidgetItem(val)
                it.setData(Qt.UserRole, r.id)
                if c > 0:
                    it.setTextAlignment(Qt.AlignCenter)
                self.rooms_table.setItem(row, c, it)
        self.rooms_table.blockSignals(False)
        self._sync_table_selection()
        self.warn_list.clear()
        if not plan.warnings:
            self.warn_list.addItem(self.t("no_warnings"))
        for w in plan.warnings:
            it = QListWidgetItem("⚠  " + (w["ar"] if self.lang == "ar" else w["en"]))
            it.setForeground(QColor(self.tokens["warn"]))
            self.warn_list.addItem(it)
        self.tabs.setTabText(1, f"{self.t('tab_warnings')} ({len(plan.warnings)})")
        self._update_scale_label()

    def _overlay(self):
        self.scene.draw_overlay(self.editor.overlay())

    def _update_scale_label(self):
        self.scale_label.setText(f"{self.t('scale')} 1:{self.view.screen_scale():.0f}")

    def _scale_chosen(self):
        n = self.scale_combo.currentData()
        if n:
            self.view.set_screen_scale(n)
        else:
            self.view.fit()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if hasattr(self, "scale_label"):
            self._update_scale_label()

    def _sync_table_selection(self):
        sel = self.editor.selection
        rid = sel[1] if sel and sel[0] == "room" else None
        self.rooms_table.blockSignals(True)
        self.rooms_table.clearSelection()
        for row in range(self.rooms_table.rowCount()):
            if rid and self.rooms_table.item(row, 0).data(Qt.UserRole) == rid:
                self.rooms_table.selectRow(row)
        self.rooms_table.blockSignals(False)

    def _table_selected(self):
        items = self.rooms_table.selectedItems()
        if items:
            self.editor.selection = ("room", items[0].data(Qt.UserRole))
            self.editor.selectionChanged.emit()
            self.redraw()

    def _label_lang_changed(self):
        self.label_lang = self.label_combo.currentData()
        self.settings.setValue("label_lang", self.label_lang)
        self.redraw()

    # ------------------------------------------------------------ dialogs
    def open_settings(self):
        dlg = SettingsDialog(self.prefs, self.lang, self.apply_prefs, self)
        if dlg.exec():
            self.apply_prefs(dlg.prefs)
            save_prefs(self.settings, self.prefs)

    def apply_prefs(self, prefs: dict):
        """Apply look & feel to every widget, the plan and the thumbnails."""
        self.prefs = prefs
        self.tokens = theme.apply(QApplication.instance(), prefs)
        self.plan_colors = theme.plan_colors(self.tokens, prefs.get("plan_theme", "match"))
        self.view.set_canvas(self.tokens["canvas"])
        for i, s in enumerate(self.var_seeds):
            if i < len(self.var_buttons) and self._variant_plans.get(s):
                self._variant_icon(i, self._variant_plans[s])
        self.libpanel.ink = self.plan_colors["ink"]
        self.libpanel.refresh()
        self.redraw()

    def open_3d(self):
        if self.plan is None:
            return
        from .viewer3d import Viewer3DDialog
        dark = QColor(self.tokens["window"]).lightness() < 128
        Viewer3DDialog(self.plan.copy(), self.library, self.lang, dark, self).exec()

    def open_quantities(self):
        if self.plan is None:
            return
        from .quantities_dialog import QuantitiesDialog
        QuantitiesDialog(self.plan, self.lang, self.settings, self).exec()

    def open_addons(self):
        dark = QColor(self.tokens["window"]).lightness() < 128
        AddonsDialog(self.addons, self.lang, dark, self).exec()

    def toggle_language(self):
        cfg, seed = self.panel.get_config(), self.panel.seed.value()
        self.lang = "en" if self.lang == "ar" else "ar"
        self.settings.setValue("lang", self.lang)
        self._build(cfg, seed)
        self.run_variants()

    def closeEvent(self, e):
        self.sig.cancelled = True
        self.pool.clear()
        self.pool.waitForDone(5000)
        super().closeEvent(e)

    # ------------------------------------------------------------ files
    def _dir(self):
        return self.settings.value("last_dir", os.path.expanduser("~"))

    def _remember(self, path):
        self.settings.setValue("last_dir", os.path.dirname(path))

    def new_project(self):
        if not self._confirm_discard():
            return
        self.set_edit_mode(False)
        if self.plan:
            self.plan.edited = False
        self.project_path = None
        self.panel.set_config({"footprint": {"width": 15, "depth": 12},
                               "household": {"parents": True, "sons": 1, "daughters": 1, "guests": 8}})
        self.regenerate()

    def open_project(self):
        start = self.examples_dir if self.examples_dir and not self.settings.value("last_dir") else self._dir()
        path, _ = QFileDialog.getOpenFileName(self, self.t("open"), start, "Project (*.json)")
        if not path:
            return
        try:
            with open(path, encoding="utf-8") as f:
                cfg = json.load(f)
        except Exception as e:
            QMessageBox.warning(self, self.t("error"), str(e))
            return
        self._remember(path)
        self.open_config(cfg)
        self.project_path = path

    def open_config(self, cfg: dict):
        self.set_edit_mode(False)
        if self.plan:
            self.plan.edited = False          # opening a project replaces the current one
        self.panel.set_config(cfg)
        if "seed" in cfg:
            self.panel.seed.setValue(int(cfg["seed"]))
        if cfg.get("plan"):
            self.timer.stop()
            self.load_edited_plan(Plan.from_dict(cfg["plan"]))
        else:
            self.regenerate()

    def project_dict(self) -> dict:
        cfg = self.panel.get_config()
        cfg["seed"] = self.panel.seed.value()
        if self.plan is not None and self.plan.edited:
            cfg["plan"] = self.plan.to_dict()        # manual edits are saved with the project
        return cfg

    def save_project(self):
        path, _ = QFileDialog.getSaveFileName(self, self.t("save"), self.project_path or
                                              os.path.join(self._dir(), "project.json"), "Project (*.json)")
        if not path:
            return
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.project_dict(), f, ensure_ascii=False, indent=2)
        self._remember(path)
        self.project_path = path
        self.status.setText(f"{self.t('saved')}: {path}")

    def _stem(self):
        name = (self.plan.project or "plan").strip() or "plan"
        safe = "".join(ch if ch.isalnum() or ch in "-_ " else "_" for ch in name).strip()
        return f"{safe or 'plan'}_seed{self.plan.seed}" + ("_edited" if self.plan.edited else "")

    def export_one(self, ext):
        if not self.plan:
            return
        pdf_opts = None
        if ext == "pdf":
            pdf_opts = self._ask_pdf()
            if pdf_opts is None:
                return
        path, _ = QFileDialog.getSaveFileName(self, self.t("export"), os.path.join(self._dir(), f"{self._stem()}.{ext}"),
                                              f"{ext.upper()} (*.{ext})")
        if path:
            self.write_file(ext, path, pdf_opts)
            self._remember(path)
            self.status.setText(f"{self.t('exported')}: {path}")

    def export_all(self):
        if not self.plan:
            return
        folder = QFileDialog.getExistingDirectory(self, self.t("export_all"), self._dir())
        if not folder:
            return
        for ext in ("svg", "png", "pdf", "dxf", "glb", "obj", "json"):
            self.write_file(ext, os.path.join(folder, f"{self._stem()}.{ext}"))
        self.settings.setValue("last_dir", folder)
        self.status.setText(f"{self.t('exported')}: {folder}")

    def write_file(self, ext, path, pdf_opts=None):
        p, lib = self.plan, self.library
        try:
            if ext == "svg":
                with open(path, "w", encoding="utf-8") as f:
                    f.write(to_svg(p, lang=self.label_lang, library=lib))
            elif ext == "png":
                render_pixmap(p, 3000, int(3000 * (p.depth + 3) / (p.width + 3)), self.label_lang, library=lib).save(path)
            elif ext == "pdf":
                self.write_pdf(path, **(pdf_opts or {}))
            elif ext == "dxf":
                to_dxf(p, path, lang="en", library=lib)
            elif ext == "glb":
                to_glb(p, path, lib)
            elif ext == "obj":
                to_obj(p, path, lib)
            elif ext == "json":
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(p.to_dict(), f, ensure_ascii=False, indent=2)
        except Exception as e:
            QMessageBox.warning(self, self.t("error"), f"{ext}: {e}")

    def _ask_pdf(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("PDF")
        f = QFormLayout(dlg)
        paper, scale = QComboBox(), QComboBox()
        for k in PAPERS:
            paper.addItem(k, k)
        paper.setCurrentIndex(1)
        for n in SCALES:
            scale.addItem(self.t("fit") if n == 0 else f"1:{n}", n)
        scale.setCurrentIndex(SCALES.index(100))
        f.addRow(self.t("paper"), paper)
        f.addRow(self.t("scale"), scale)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        f.addRow(bb)
        if not dlg.exec():
            return None
        return dict(paper=paper.currentData(), scale=scale.currentData())

    def write_pdf(self, path, paper: str = "A3", scale: int = 0):
        """PDF with a title line; scale=N draws at true 1:N (0 = fit the page)."""
        pdf = QPdfWriter(path)
        pdf.setPageSize(QPageSize(PAPERS.get(paper, QPageSize.A3)))
        pdf.setPageOrientation(QPageLayout.Landscape)
        pdf.setResolution(300)
        scene = PlanScene()
        scene.set_plan(self.plan, self.label_lang, None, self.library)
        src = scene.sceneRect()
        painter = QPainter(pdf)
        page = painter.viewport()
        title_h = page.height() * 0.05
        area = QRectF(0, title_h, page.width(), page.height() - title_h)
        if scale:
            k = (1000.0 / scale / 25.4 * 300) / S          # device px per scene unit
            w, h = src.width() * k, src.height() * k
            if w > area.width() or h > area.height():
                painter.end()
                QMessageBox.warning(self, "PDF", self.t("pdf_too_big"))
                os.remove(path) if os.path.exists(path) else None
                return
            target = QRectF(area.center().x() - w / 2, area.center().y() - h / 2, w, h)
        else:
            target = area
        f = painter.font()
        f.setPixelSize(int(title_h * 0.42))
        painter.setFont(f)
        p = self.plan
        painter.drawText(QRectF(0, 0, page.width(), title_h), Qt.AlignLeft | Qt.AlignVCenter,
                         f"{p.project or 'Floor plan'}   |   {p.width:.2f} x {p.depth:.2f} m   |   "
                         f"{p.gross_area:.1f} m²   |   {self.t('scale')} {'1:' + str(scale) if scale else self.t('fit')}"
                         f"   |   {paper}")
        scene.render(painter, target, src, Qt.KeepAspectRatio)
        painter.end()

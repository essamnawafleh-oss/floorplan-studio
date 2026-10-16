"""Main window."""

from __future__ import annotations

import json
import os
import sys
import traceback

from PySide6.QtCore import QObject, QRectF, QRunnable, QSettings, QSize, Qt, QThreadPool, QTimer, Signal
from PySide6.QtGui import QAction, QColor, QIcon, QPageLayout, QPageSize, QPainter, QPdfWriter
from PySide6.QtWidgets import (QApplication, QButtonGroup, QComboBox, QFileDialog, QGridLayout, QHBoxLayout,
                               QHeaderView, QLabel, QListWidget, QListWidgetItem, QMainWindow, QMenu,
                               QMessageBox, QPushButton, QScrollArea, QSizePolicy, QSplitter, QTableWidget,
                               QTableWidgetItem, QTabWidget, QToolButton, QVBoxLayout, QWidget)

from .. import design
from ..export import to_dxf, to_glb, to_obj, to_svg
from . import theme
from .panels import InputPanel
from .settings_dialog import SettingsDialog, load_prefs, save_prefs
from .plan_view import PlanScene, PlanView, render_pixmap
from .strings import tr

N_VARIANTS = 6


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
        self.plan = None
        self.req = 0
        self.var_req = 0
        self.project_path = None
        self.pool = QThreadPool.globalInstance()
        self.sig = _Signals()
        self.sig.plan.connect(self._on_plan)
        self.sig.variant.connect(self._on_variant)
        self.timer = QTimer(self, singleShot=True, interval=450)
        self.timer.timeout.connect(self.regenerate)
        self.resize(1500, 900)
        self.prefs = load_prefs(self.settings)
        self.tokens = theme.apply(QApplication.instance(), self.prefs)
        self.plan_colors = theme.plan_colors(self.tokens, self.prefs["plan_theme"])
        self._build(initial=self._initial_config())
        self.regenerate()

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
        self._build_toolbar()

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
        self.scene.roomClicked.connect(self._select_room)
        self.view = PlanView(self.scene)
        self.view.set_canvas(self.tokens["canvas"])

        center = QWidget()
        cv = QVBoxLayout(center)
        cv.setContentsMargins(0, 0, 0, 0)
        bar = QHBoxLayout()
        bar.setContentsMargins(8, 6, 8, 0)
        self.summary = QLabel()
        self.summary.setObjectName("summary")
        bar.addWidget(self.summary, 1)
        bar.addWidget(QLabel(self.t("labels")))
        self.label_combo = QComboBox()
        for k, code in (("lang_both", "both"), ("lang_ar", "ar"), ("lang_en", "en")):
            self.label_combo.addItem(self.t(k), code)
        self.label_combo.setCurrentIndex(max(0, self.label_combo.findData(self.label_lang)))
        self.label_combo.currentIndexChanged.connect(self._label_lang_changed)
        bar.addWidget(self.label_combo)
        fit = QPushButton(self.t("fit"))
        fit.clicked.connect(self.view.fit)
        bar.addWidget(fit)
        cv.addLayout(bar)
        cv.addWidget(self.view, 1)
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

        split = QSplitter()
        split.addWidget(left)
        split.addWidget(center)
        split.addWidget(self.tabs)
        split.setStretchFactor(1, 1)
        split.setSizes([380, 760, 400])
        self.setCentralWidget(split)
        if self.plan is not None:
            self._show_plan(self.plan)

    def _build_toolbar(self):
        if hasattr(self, "toolbar"):
            self.removeToolBar(self.toolbar)
        tb = self.addToolBar("main")
        tb.setMovable(False)
        tb.setIconSize(QSize(18, 18))
        self.toolbar = tb
        for key, slot in (("new", self.new_project), ("open", self.open_project), ("save", self.save_project)):
            a = QAction(self.t(key), self)
            a.triggered.connect(slot)
            tb.addAction(a)
        tb.addSeparator()
        menu = QMenu(self)
        for label, ext in (("SVG (2D)", "svg"), ("PNG", "png"), ("PDF", "pdf"), ("DXF (CAD)", "dxf"),
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
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        tb.addWidget(spacer)
        a = QAction(self.t("settings_btn"), self)
        a.triggered.connect(self.open_settings)
        tb.addAction(a)
        a = QAction(self.t("about"), self)
        a.triggered.connect(lambda: QMessageBox.information(self, self.t("about"), self.t("about_text")))
        tb.addAction(a)
        a = QAction("🌐 " + self.t("language"), self)
        a.triggered.connect(self.toggle_language)
        tb.addAction(a)

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
        self.var_seeds = []
        self._variant_plans = {}
        return w

    # ----------------------------------------------------------- generation
    def regenerate(self):
        self.timer.stop()
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
        self.plan = plan
        self._show_plan(plan)
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
        self.var_buttons[i].setIcon(QIcon(render_pixmap(plan, 300, 220, "en", self.plan_colors)))

    def _pick_variant(self, i):
        if i < len(self.var_seeds):
            self.panel.seed.setValue(self.var_seeds[i])
            self.regenerate()

    def _show_plan(self, plan):
        first = not self.scene.items()
        self.scene.set_plan(plan, self.label_lang, self.plan_colors)
        if first or getattr(self, "_last_size", None) != (plan.width, plan.depth):
            self.view.fit()
        self._last_size = (plan.width, plan.depth)
        self.summary.setText(
            f"<b>{plan.width:.2f} × {plan.depth:.2f} m</b> &nbsp;·&nbsp; {self.t('gross')}: {plan.gross_area:.1f} m²"
            f" &nbsp;·&nbsp; {self.t('net')}: {plan.net_area:.1f} m² &nbsp;·&nbsp; {self.t('score')}: {plan.score:.1f}")
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
        self.warn_list.clear()
        if not plan.warnings:
            self.warn_list.addItem(self.t("no_warnings"))
        for w in plan.warnings:
            it = QListWidgetItem("⚠  " + (w["ar"] if self.lang == "ar" else w["en"]))
            it.setForeground(QColor(self.tokens["warn"]))
            self.warn_list.addItem(it)
        self.tabs.setTabText(1, f"{self.t('tab_warnings')} ({len(plan.warnings)})")

    def _select_room(self, rid):
        self.scene.select_room(rid)
        for row in range(self.rooms_table.rowCount()):
            if self.rooms_table.item(row, 0).data(Qt.UserRole) == rid:
                self.rooms_table.blockSignals(True)
                self.rooms_table.selectRow(row)
                self.rooms_table.blockSignals(False)

    def _table_selected(self):
        items = self.rooms_table.selectedItems()
        if items:
            self.scene.select_room(items[0].data(Qt.UserRole))

    def _label_lang_changed(self):
        self.label_lang = self.label_combo.currentData()
        self.settings.setValue("label_lang", self.label_lang)
        if self.plan:
            self.scene.set_plan(self.plan, self.label_lang, self.plan_colors)

    def open_settings(self):
        dlg = SettingsDialog(self.prefs, self.lang, self.apply_prefs, self)
        if dlg.exec():
            self.apply_prefs(dlg.prefs)
            save_prefs(self.settings, self.prefs)

    def apply_prefs(self, prefs: dict):
        """Apply look & feel and rebuild the window so every widget picks it up."""
        self.prefs = prefs
        self.tokens = theme.apply(QApplication.instance(), prefs)
        self.plan_colors = theme.plan_colors(self.tokens, prefs.get("plan_theme", "match"))
        self.view.set_canvas(self.tokens["canvas"])
        if self.plan:
            self.scene.set_plan(self.plan, self.label_lang, self.plan_colors)
            for i, s in enumerate(self.var_seeds):
                if i < len(self.var_buttons) and self._variant_plans.get(s):
                    self._variant_icon(i, self._variant_plans[s])
        if self.plan is not None:
            self._show_plan(self.plan)

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
        self.project_path = path
        self.panel.set_config(cfg)
        self.regenerate()

    def save_project(self):
        path, _ = QFileDialog.getSaveFileName(self, self.t("save"), self.project_path or
                                              os.path.join(self._dir(), "project.json"), "Project (*.json)")
        if not path:
            return
        cfg = self.panel.get_config()
        cfg["seed"] = self.panel.seed.value()
        with open(path, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
        self._remember(path)
        self.project_path = path
        self.status.setText(f"{self.t('saved')}: {path}")

    def _stem(self):
        name = (self.plan.project or "plan").strip() or "plan"
        safe = "".join(ch if ch.isalnum() or ch in "-_ " else "_" for ch in name).strip()
        return f"{safe or 'plan'}_seed{self.plan.seed}"

    def export_one(self, ext):
        if not self.plan:
            return
        path, _ = QFileDialog.getSaveFileName(self, self.t("export"), os.path.join(self._dir(), f"{self._stem()}.{ext}"),
                                              f"{ext.upper()} (*.{ext})")
        if path:
            self._write(ext, path)
            self._remember(path)
            self.status.setText(f"{self.t('exported')}: {path}")

    def export_all(self):
        if not self.plan:
            return
        folder = QFileDialog.getExistingDirectory(self, self.t("export_all"), self._dir())
        if not folder:
            return
        for ext in ("svg", "png", "pdf", "dxf", "glb", "obj", "json"):
            self._write(ext, os.path.join(folder, f"{self._stem()}.{ext}"))
        self.settings.setValue("last_dir", folder)
        self.status.setText(f"{self.t('exported')}: {folder}")

    def _write(self, ext, path):
        p = self.plan
        try:
            if ext == "svg":
                with open(path, "w", encoding="utf-8") as f:
                    f.write(to_svg(p, lang=self.label_lang))
            elif ext == "png":
                render_pixmap(p, 3000, int(3000 * (p.depth + 3) / (p.width + 3)), self.label_lang).save(path)
            elif ext == "pdf":
                self._write_pdf(path)
            elif ext == "dxf":
                to_dxf(p, path, lang="en")
            elif ext == "glb":
                to_glb(p, path)
            elif ext == "obj":
                to_obj(p, path)
            elif ext == "json":
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(p.to_dict(), f, ensure_ascii=False, indent=2)
        except Exception as e:
            QMessageBox.warning(self, self.t("error"), f"{ext}: {e}")

    def _write_pdf(self, path):
        pdf = QPdfWriter(path)
        pdf.setPageSize(QPageSize(QPageSize.A3))
        pdf.setPageOrientation(QPageLayout.Landscape)
        pdf.setResolution(300)
        painter = QPainter(pdf)
        scene = PlanScene()
        scene.set_plan(self.plan, self.label_lang)
        page = painter.viewport()
        title_h = page.height() * 0.06
        f = painter.font()
        f.setPixelSize(int(title_h * 0.45))
        painter.setFont(f)
        p = self.plan
        painter.drawText(QRectF(0, 0, page.width(), title_h), Qt.AlignLeft | Qt.AlignVCenter,
                         f"{p.project or 'Floor plan'}   |   {p.width:.2f} x {p.depth:.2f} m   |   "
                         f"{p.gross_area:.1f} m²   |   seed {p.seed}")
        scene.render(painter, QRectF(0, title_h, page.width(), page.height() - title_h),
                     scene.sceneRect(), Qt.KeepAspectRatio)
        painter.end()

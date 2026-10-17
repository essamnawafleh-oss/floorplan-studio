"""Parametric workspace: parameters -> constraints -> alternatives -> compare -> apply.

Works on a ParametricStudy and in-memory candidates only. Nothing here touches
the project plan; the window applies a candidate when the user asks for it.
"""

from __future__ import annotations

import copy

from PySide6.QtCore import QObject, QRunnable, QSize, Qt, QThreadPool, Signal
from PySide6.QtGui import QColor, QIcon
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDoubleSpinBox, QFormLayout, QGroupBox,
                               QHBoxLayout, QHeaderView, QLabel, QListWidget, QListWidgetItem, QListView,
                               QMessageBox, QProgressBar, QPushButton, QScrollArea, QSpinBox, QSplitter,
                               QTableWidget, QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget)

from ..i18n import room_name
from ..parametric import ParametricStudy, programme, run_study
from ..rules import get_rules
from .plan_view import PlanScene, PlanView, render_pixmap
from .strings import tr

TERM_KEYS = ["area", "proportion", "width", "min_area", "window", "ventilation", "access", "circulation",
             "adjacency", "entrance"]


class _Sig(QObject):
    progress = Signal(int, int, int)       # request, done, total
    done = Signal(int, object, str)        # request, candidates, error


class _StudyTask(QRunnable):
    def __init__(self, req, study, sig, flag):
        super().__init__()
        self.req, self.study, self.sig, self.flag = req, study, sig, flag

    def run(self):
        try:
            res, err = run_study(self.study, progress=lambda d, t: self._emit_progress(d, t),
                                 cancelled=lambda: self.flag["cancel"]), ""
        except Exception as e:      # shown in the panel
            res, err = None, str(e)
        try:
            self.sig.done.emit(self.req, res, err)
        except RuntimeError:
            pass

    def _emit_progress(self, d, t):
        try:
            self.sig.progress.emit(self.req, d, t)
        except RuntimeError:
            pass


def _dspin(lo, hi, val, step=0.5, dec=2):
    s = QDoubleSpinBox()
    s.setRange(lo, hi)
    s.setDecimals(dec)
    s.setSingleStep(step)
    s.setValue(val)
    return s


def _ispin(lo, hi, val):
    s = QSpinBox()
    s.setRange(lo, hi)
    s.setValue(val)
    return s


class ParametricPanel(QWidget):
    applyRequested = Signal(object)        # Candidate
    backRequested = Signal()

    def __init__(self, window, study: ParametricStudy, candidates: list, parent=None):
        super().__init__(parent)
        self.w, self.lang = window, window.lang
        self.study = study
        self.candidates = candidates          # owned by the window, survives rebuilds
        self.selected = None
        self.req = 0
        self.flag = {"cancel": False}
        self.sig = _Sig()
        self.sig.progress.connect(self._on_progress)
        self.sig.done.connect(self._on_done)
        self.rules = get_rules(study.base_config.get("rules", "jordan"))
        t = self.t

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        split = QSplitter()
        root.addWidget(split)

        # ---- left: parameters + constraints + search
        left = QWidget()
        lv = QVBoxLayout(left)
        head = QLabel(t("pm_title"))
        head.setStyleSheet("font-weight:700;font-size:15px")
        lv.addWidget(head)
        steps = QLabel(t("pm_steps"))
        steps.setObjectName("muted")
        steps.setWordWrap(True)
        lv.addWidget(steps)

        g = QGroupBox("1 · " + t("pm_params"))
        gv = QVBoxLayout(g)
        self.rooms_table = QTableWidget(0, 4)
        self.rooms_table.setHorizontalHeaderLabels([t("col_name"), t("pm_base"), t("pm_new"), t("fixed")])
        self.rooms_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.rooms_table.verticalHeader().setVisible(False)
        self.rooms_table.setMinimumHeight(260)
        gv.addWidget(self.rooms_table)
        reset = QPushButton(t("pm_reset"))
        reset.clicked.connect(self.reset_parameters)
        gv.addWidget(reset)
        lv.addWidget(g)

        g = QGroupBox("2 · " + t("pm_constraints"))
        gv = QVBoxLayout(g)
        self.strict = QCheckBox(t("strict"))
        self.strict.setChecked(bool(study.strict if study.strict is not None else study.base_config.get("strict")))
        gv.addWidget(self.strict)
        gv.addWidget(QLabel(t("pm_room_rules")))
        self.types_table = QTableWidget(0, 4)
        self.types_table.setHorizontalHeaderLabels([t("type"), t("pm_min_w"), t("pm_min_a"), t("pm_max_aspect")])
        self.types_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.types_table.verticalHeader().setVisible(False)
        self.types_table.setMinimumHeight(220)
        gv.addWidget(self.types_table)
        gv.addWidget(QLabel(t("pm_adjacency")))
        self.adj_table = QTableWidget(0, 3)
        self.adj_table.setHorizontalHeaderLabels([t("pm_room_a"), t("pm_room_b"), t("pm_weight")])
        self.adj_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.adj_table.verticalHeader().setVisible(False)
        self.adj_table.setMinimumHeight(170)
        gv.addWidget(self.adj_table)
        add_adj = QPushButton(t("pm_add_adj"))
        add_adj.clicked.connect(lambda: self._add_adj_row("kitchen", "living", 3.0))
        gv.addWidget(add_adj)
        lv.addWidget(g)

        g = QGroupBox("3 · " + t("pm_search"))
        f = QFormLayout(g)
        seeds = list(study.seeds) or [1]
        self.first_seed, self.n_seeds = _ispin(0, 999999, seeds[0]), _ispin(1, 40, len(seeds))
        self.cands, self.keep = _ispin(20, 3000, study.candidates), _ispin(1, 10, study.keep)
        self.passes, self.max_res = _ispin(0, 6, study.refine_passes), _ispin(1, 24, study.max_results)
        for k, wdg in (("pm_first_seed", self.first_seed), ("pm_n_seeds", self.n_seeds),
                       ("pm_candidates", self.cands), ("pm_keep", self.keep),
                       ("pm_refine", self.passes), ("pm_max", self.max_res)):
            f.addRow(t(k), wdg)
        self.run_btn = QPushButton(t("pm_run"))
        self.run_btn.setObjectName("primary")
        self.run_btn.clicked.connect(self.run)
        self.cancel_btn = QPushButton(t("cancel"))
        self.cancel_btn.clicked.connect(self.cancel)
        self.cancel_btn.setEnabled(False)
        row = QHBoxLayout()
        row.addWidget(self.run_btn, 1)
        row.addWidget(self.cancel_btn)
        f.addRow(row)
        self.progress = QProgressBar()
        self.progress.setVisible(False)
        f.addRow(self.progress)
        lv.addWidget(g)
        lv.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidget(left)
        scroll.setWidgetResizable(True)
        scroll.setMinimumWidth(400)
        split.addWidget(scroll)

        # ---- centre: alternatives + preview
        center = QWidget()
        cv = QVBoxLayout(center)
        cv.addWidget(QLabel("4 · " + t("pm_alternatives")))
        self.grid = QListWidget()
        self.grid.setViewMode(QListView.IconMode)
        self.grid.setIconSize(QSize(200, 146))
        self.grid.setGridSize(QSize(224, 186))
        self.grid.setResizeMode(QListView.Adjust)
        self.grid.setMovement(QListView.Static)
        self.grid.setMaximumHeight(410)
        self.grid.currentRowChanged.connect(self.select)
        cv.addWidget(self.grid)
        self.scene = PlanScene()
        self.view = PlanView(self.scene)
        self.view.setDragMode(PlanView.ScrollHandDrag)
        self.view.set_canvas(window.tokens["canvas"])
        cv.addWidget(self.view, 1)
        self.status = QLabel()
        self.status.setObjectName("status")
        cv.addWidget(self.status)
        split.addWidget(center)

        # ---- right: comparison + details + apply
        right = QWidget()
        rv = QVBoxLayout(right)
        rv.addWidget(QLabel("5 · " + t("pm_compare")))
        self.compare = QTableWidget(0, 7)
        self.compare.setHorizontalHeaderLabels(["#", "Seed", t("pm_score"), t("pm_hard"), t("pm_mean_dev"),
                                                t("pm_max_dev"), t("pm_corridor")])
        self.compare.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.compare.verticalHeader().setVisible(False)
        self.compare.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.compare.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.compare.itemSelectionChanged.connect(
            lambda: self.select(self.compare.currentRow()) if self.compare.currentRow() >= 0 else None)
        rv.addWidget(self.compare, 2)
        self.details = QTabWidget()
        self.room_detail = QTableWidget(0, 5)
        self.room_detail.setHorizontalHeaderLabels([t("col_name"), t("pm_target"), t("col_actual"), "Δ %", t("col_dims")])
        self.room_detail.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.room_detail.verticalHeader().setVisible(False)
        self.room_detail.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.terms = QTableWidget(0, 2)
        self.terms.setHorizontalHeaderLabels([t("pm_term"), t("pm_points")])
        self.terms.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.terms.verticalHeader().setVisible(False)
        self.terms.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.warn = QListWidget()
        self.warn.setWordWrap(True)
        self.details.addTab(self.room_detail, t("tab_rooms"))
        self.details.addTab(self.terms, t("pm_why"))
        self.details.addTab(self.warn, t("tab_warnings"))
        rv.addWidget(self.details, 3)
        self.apply_btn = QPushButton("6 · " + t("pm_apply"))
        self.apply_btn.setObjectName("primary")
        self.apply_btn.setEnabled(False)
        self.apply_btn.clicked.connect(self._apply)
        rv.addWidget(self.apply_btn)
        back = QPushButton(t("pm_back"))
        back.clicked.connect(self.backRequested.emit)
        rv.addWidget(back)
        note = QLabel(t("pm_safe_note"))
        note.setObjectName("muted")
        note.setWordWrap(True)
        rv.addWidget(note)
        right.setMinimumWidth(460)
        split.addWidget(right)
        split.setStretchFactor(1, 1)
        split.setSizes([440, 640, 480])

        self._fill_parameters()
        self._show_candidates()

    def t(self, k):
        return tr(k, self.lang)

    def _name(self, d):
        return d.get("name_ar") if self.lang == "ar" else d.get("name_en")

    # ------------------------------------------------------------ parameters
    def _fill_parameters(self):
        base_study = ParametricStudy(base_config=self.study.base_config)
        base = {r["id"]: r for r in programme(base_study)}
        cur = {r["id"]: r for r in programme(self.study)}
        self.rooms_table.setRowCount(0)
        for rid, b in base.items():
            row = self.rooms_table.rowCount()
            self.rooms_table.insertRow(row)
            it = QTableWidgetItem(self._name(b))
            it.setData(Qt.UserRole, rid)
            it.setFlags(it.flags() & ~Qt.ItemIsEditable)
            self.rooms_table.setItem(row, 0, it)
            bi = QTableWidgetItem(f"{b['area']:.1f}")
            bi.setFlags(bi.flags() & ~Qt.ItemIsEditable)
            self.rooms_table.setItem(row, 1, bi)
            spin = _dspin(1.0, 500.0, cur[rid]["area"], 0.5, 1)
            self.rooms_table.setCellWidget(row, 2, spin)
            fx = QCheckBox()
            fx.setChecked(cur[rid]["fixed"])
            cell = QWidget()
            cl = QHBoxLayout(cell)
            cl.setContentsMargins(0, 0, 0, 0)
            cl.setAlignment(Qt.AlignCenter)
            cl.addWidget(fx)
            self.rooms_table.setCellWidget(row, 3, cell)
        # room-type rules present in this programme
        types = []
        for r in base.values():
            if r["type"] not in types:
                types.append(r["type"])
        ov = (self.study.rule_overrides or {}).get("room_types", {})
        self.types_table.setRowCount(0)
        for rtype in types:
            info = {**self.rules.ROOM_TYPES[rtype], **ov.get(rtype, {})}
            row = self.types_table.rowCount()
            self.types_table.insertRow(row)
            it = QTableWidgetItem(room_name(rtype, self.lang))
            it.setData(Qt.UserRole, rtype)
            it.setFlags(it.flags() & ~Qt.ItemIsEditable)
            self.types_table.setItem(row, 0, it)
            self.types_table.setCellWidget(row, 1, _dspin(0.5, 10, info["min_width"], 0.05))
            self.types_table.setCellWidget(row, 2, _dspin(0, 200, info["min_area"], 0.5, 1))
            self.types_table.setCellWidget(row, 3, _dspin(1.0, 99, info["max_aspect"], 0.1))
        # adjacency: built-in wishes with study weights applied
        adj = {(a, b): w for a, b, w in self.rules.ADJACENCY_WISHES}
        for a, b, w in (self.study.rule_overrides or {}).get("adjacency", []):
            adj[(a, b)] = w
        self.adj_table.setRowCount(0)
        for (a, b), w in adj.items():
            self._add_adj_row(a, b, w)

    def _type_combo(self, value):
        c = QComboBox()
        for k in self.rules.ROOM_TYPES:
            c.addItem(room_name(k, self.lang), k)
        c.setCurrentIndex(max(0, c.findData(value)))
        return c

    def _add_adj_row(self, a, b, w):
        row = self.adj_table.rowCount()
        self.adj_table.insertRow(row)
        self.adj_table.setCellWidget(row, 0, self._type_combo(a))
        self.adj_table.setCellWidget(row, 1, self._type_combo(b))
        self.adj_table.setCellWidget(row, 2, _dspin(0, 50, w, 0.5, 1))

    def reset_parameters(self):
        self.study = ParametricStudy(base_config=self.study.base_config, seeds=self.study.seeds,
                                     candidates=self.study.candidates, keep=self.study.keep,
                                     refine_passes=self.study.refine_passes, max_results=self.study.max_results)
        self.w.study = self.study
        self.strict.setChecked(bool(self.study.base_config.get("strict")))
        self._fill_parameters()

    def read_study(self) -> ParametricStudy:
        """Study from the widgets. Only values that differ from the base are stored."""
        base_study = ParametricStudy(base_config=self.study.base_config)
        base = {r["id"]: r for r in programme(base_study)}
        room_ov = {}
        for row in range(self.rooms_table.rowCount()):
            rid = self.rooms_table.item(row, 0).data(Qt.UserRole)
            area = self.rooms_table.cellWidget(row, 2).value()
            fixed = self.rooms_table.cellWidget(row, 3).findChild(QCheckBox).isChecked()
            ov = {}
            if abs(area - base[rid]["area"]) > 0.049:
                ov["area"] = round(area, 2)
            if fixed != base[rid]["fixed"]:
                ov["fixed"] = fixed
            if ov:
                room_ov[rid] = ov
        rt = {}
        for row in range(self.types_table.rowCount()):
            rtype = self.types_table.item(row, 0).data(Qt.UserRole)
            info = self.rules.ROOM_TYPES[rtype]
            vals = {}
            for col, key in ((1, "min_width"), (2, "min_area"), (3, "max_aspect")):
                v = round(self.types_table.cellWidget(row, col).value(), 3)
                if abs(v - info[key]) > 1e-6:
                    vals[key] = v
            if vals:
                rt[rtype] = vals
        builtin = {(a, b): w for a, b, w in self.rules.ADJACENCY_WISHES}
        adj, seen = [], set()
        for row in range(self.adj_table.rowCount()):
            a = self.adj_table.cellWidget(row, 0).currentData()
            b = self.adj_table.cellWidget(row, 1).currentData()
            w = round(self.adj_table.cellWidget(row, 2).value(), 2)
            seen.add((a, b))
            if a != b and builtin.get((a, b)) != w:
                adj.append([a, b, w])
        adj += [[a, b, 0] for (a, b) in builtin if (a, b) not in seen]       # removed rows = switched off
        rule_ov = {}
        if rt:
            rule_ov["room_types"] = rt
        if adj:
            rule_ov["adjacency"] = adj
        base_strict = bool(self.study.base_config.get("strict"))
        strict = self.strict.isChecked()
        first = self.first_seed.value()
        return ParametricStudy(base_config=self.study.base_config, room_overrides=room_ov, rule_overrides=rule_ov,
                               strict=None if strict == base_strict else strict,
                               seeds=list(range(first, first + self.n_seeds.value())),
                               candidates=self.cands.value(), keep=self.keep.value(),
                               refine_passes=self.passes.value(), max_results=self.max_res.value())

    # ------------------------------------------------------------ run
    def run(self):
        try:
            study = self.read_study()
            programme(study)                     # validates the overrides
        except Exception as e:
            QMessageBox.warning(self, self.t("error"), str(e))
            return
        self.study = study
        self.w.study = study
        self.req += 1
        self.flag = {"cancel": False}
        self.run_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)
        self.progress.setVisible(True)
        self.progress.setValue(0)
        self.status.setText(self.t("working"))
        QThreadPool.globalInstance().start(_StudyTask(self.req, copy.deepcopy(study), self.sig, self.flag))

    def cancel(self):
        self.flag["cancel"] = True
        self.cancel_btn.setEnabled(False)

    def shutdown(self):
        self.flag["cancel"] = True

    def _on_progress(self, req, done, total):
        if req == self.req:
            self.progress.setMaximum(max(total, 1))
            self.progress.setValue(done)

    def _on_done(self, req, cands, err):
        if req != self.req:
            return
        self.run_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        self.progress.setVisible(False)
        if cands is None:
            self.status.setText(f"⚠ {self.t('error')}: {err}")
            return
        self.candidates[:] = cands
        self.status.setText(f"{len(cands)} {self.t('pm_found')}")
        self._show_candidates()

    # ------------------------------------------------------------ compare
    def _show_candidates(self):
        self.grid.blockSignals(True)
        self.grid.clear()
        colors = self.w.plan_colors
        for c in self.candidates:
            pm = render_pixmap(c.plan, 400, 292, "en", colors, self.w.library)
            label = f"#{c.rank}  ·  {c.score:.1f}" + ("  ✓" if c.hard == 0 else f"  ⚠{c.hard}")
            it = QListWidgetItem(QIcon(pm), label)
            self.grid.addItem(it)
        self.grid.blockSignals(False)
        self.compare.blockSignals(True)
        self.compare.setRowCount(0)
        for c in self.candidates:
            m = c.metrics
            row = self.compare.rowCount()
            self.compare.insertRow(row)
            vals = [c.rank, c.seed, f"{c.score:.1f}", c.hard, f"{m['mean_dev_pct']:.1f}", f"{m['max_dev_pct']:.1f}",
                    f"{m['corridor_pct']:.1f}"]
            for col, v in enumerate(vals):
                it = QTableWidgetItem(str(v))
                it.setTextAlignment(Qt.AlignCenter)
                if col == 3 and c.hard:
                    it.setForeground(QColor(self.w.tokens["warn"]))
                self.compare.setItem(row, col, it)
        self.compare.blockSignals(False)
        if self.candidates:
            self.select(0)
        else:
            self.selected = None
            self.scene.set_plan(None)
            self.apply_btn.setEnabled(False)

    def select(self, i):
        if i is None or not (0 <= i < len(self.candidates)):
            return
        c = self.candidates[i]
        self.selected = c
        for wdg, setter in ((self.grid, lambda: self.grid.setCurrentRow(i)),
                            (self.compare, lambda: self.compare.selectRow(i))):
            wdg.blockSignals(True)
            setter()
            wdg.blockSignals(False)
        self.scene.set_plan(c.plan, self.w.label_lang, self.w.plan_colors, self.w.library)
        self.view.fit()
        rows = c.metrics["rooms"]
        self.room_detail.setRowCount(len(rows))
        for r, d in enumerate(rows):
            vals = [self._name(d) + (" 🔒" if d["fixed"] else ""), f"{d['expected']:.1f}", f"{d['actual']:.1f}",
                    f"{d['dev_pct']:+.1f}", f"{d['width']:.2f}×{d['length']:.2f}"]
            for col, v in enumerate(vals):
                it = QTableWidgetItem(v)
                if col == 3 and abs(d["dev_pct"]) > 10:
                    it.setForeground(QColor(self.w.tokens["warn"]))
                self.room_detail.setItem(r, col, it)
        terms = [(k, c.terms.get(k, 0.0)) for k in TERM_KEYS if c.terms.get(k, 0.0) > 1e-9]
        self.terms.setRowCount(len(terms))
        for r, (k, v) in enumerate(terms):
            self.terms.setItem(r, 0, QTableWidgetItem(self.t("pmt_" + k)))
            self.terms.setItem(r, 1, QTableWidgetItem(f"{v:.2f}"))
        self.warn.clear()
        for wd in c.plan.warnings:
            self.warn.addItem("⚠  " + (wd["ar"] if self.lang == "ar" else wd["en"]))
        if not c.plan.warnings:
            self.warn.addItem(self.t("no_warnings"))
        self.apply_btn.setEnabled(True)

    def _apply(self):
        if self.selected is not None:
            self.applyRequested.emit(self.selected)

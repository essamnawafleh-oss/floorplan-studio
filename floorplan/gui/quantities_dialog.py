"""Quantities calculator window (blocks, tiles, paint)."""

from __future__ import annotations

import json

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDoubleSpinBox, QFileDialog, QFormLayout,
                               QGroupBox, QHBoxLayout, QHeaderView, QLabel, QPushButton, QSpinBox, QTableWidget,
                               QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget)

from ..quantities import DEFAULTS, TILE_PRESETS, compute, to_csv
from .strings import tr


def _d(lo, hi, val, step, dec=2):
    s = QDoubleSpinBox()
    s.setRange(lo, hi)
    s.setSingleStep(step)
    s.setDecimals(dec)
    s.setValue(val)
    return s


class QuantitiesDialog(QDialog):
    def __init__(self, plan, lang: str, settings, parent=None):
        super().__init__(parent)
        self.plan, self.lang, self.settings = plan, lang, settings
        t = self.t
        self.setWindowTitle(t("qty_title"))
        self.resize(980, 640)
        root = QHBoxLayout(self)

        # options
        opts = QWidget()
        ov = QVBoxLayout(opts)
        try:
            saved = json.loads(settings.value("qty_opts") or "{}")
        except (TypeError, ValueError):
            saved = {}
        o = {**DEFAULTS, **saved}
        g = QGroupBox(t("qty_blocks"))
        f = QFormLayout(g)
        self.height = _d(2.0, 8.0, o["wall_height"] or plan.settings["wall_height"], 0.05)
        self.block_l, self.block_h = _d(5, 100, o["block_l"] * 100, 1, 1), _d(5, 100, o["block_h"] * 100, 1, 1)
        self.joint = _d(0, 5, o["joint"] * 100, 0.5, 1)
        self.block_waste = _d(0, 50, o["block_waste"] * 100, 1, 0)
        for k, w in (("wall_height", self.height), ("block_l", self.block_l), ("block_h", self.block_h),
                     ("joint_cm", self.joint), ("waste_pct", self.block_waste)):
            f.addRow(t(k), w)
        ov.addWidget(g)

        g = QGroupBox(t("qty_tiles"))
        f = QFormLayout(g)
        self.tile = QComboBox()
        for a, b in TILE_PRESETS:
            self.tile.addItem(f"{a * 100:.0f} × {b * 100:.0f} cm", (a, b))
        self.tile.addItem(t("custom"), None)
        idx = next((i for i, v in enumerate(TILE_PRESETS) if abs(v[0] - o["tile_l"]) < 1e-6 and abs(v[1] - o["tile_w"]) < 1e-6), len(TILE_PRESETS))
        self.tile.setCurrentIndex(idx)
        self.tile_l, self.tile_w = _d(1, 300, o["tile_l"] * 100, 1, 1), _d(1, 300, o["tile_w"] * 100, 1, 1)
        self.tile_joint = _d(0, 20, o["tile_joint"] * 1000, 0.5, 1)
        self.tile_waste = _d(0, 50, o["tile_waste"] * 100, 1, 0)
        self.box = _d(0, 10, o["box_m2"], 0.01)
        self.skip_wet = QCheckBox()
        self.skip_wet.setChecked(bool(o["skip_wet_tiles"]))
        for k, w in (("tile_size", self.tile), ("tile_l", self.tile_l), ("tile_w", self.tile_w),
                     ("tile_joint", self.tile_joint), ("waste_pct", self.tile_waste), ("box_m2", self.box),
                     ("skip_wet", self.skip_wet)):
            f.addRow(t(k), w)
        ov.addWidget(g)

        g = QGroupBox(t("qty_paint"))
        f = QFormLayout(g)
        self.coverage = _d(1, 30, o["paint_coverage"], 0.5, 1)
        self.coats = QSpinBox()
        self.coats.setRange(1, 5)
        self.coats.setValue(int(o["coats"]))
        self.paint_waste = _d(0, 50, o["paint_waste"] * 100, 1, 0)
        self.gallon = _d(1, 20, o["gallon_l"], 0.1, 3)
        self.ceilings = QCheckBox()
        self.ceilings.setChecked(bool(o["ceilings"]))
        for k, w in (("coverage", self.coverage), ("coats", self.coats), ("waste_pct", self.paint_waste),
                     ("gallon", self.gallon), ("ceilings", self.ceilings)):
            f.addRow(t(k), w)
        ov.addWidget(g)
        ov.addStretch(1)
        root.addWidget(opts)

        # results
        right = QVBoxLayout()
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        self.summary.setTextFormat(Qt.RichText)
        right.addWidget(self.summary)
        self.tabs = QTabWidget()
        self.tile_table, self.paint_table = self._table(4), self._table(4)
        self.tabs.addTab(self.tile_table, t("qty_tiles"))
        self.tabs.addTab(self.paint_table, t("qty_paint"))
        right.addWidget(self.tabs, 1)
        row = QHBoxLayout()
        csv = QPushButton(t("export_csv"))
        csv.clicked.connect(self.export_csv)
        close = QPushButton(t("close"))
        close.clicked.connect(self.accept)
        row.addStretch(1)
        row.addWidget(csv)
        row.addWidget(close)
        right.addLayout(row)
        root.addLayout(right, 1)

        for w in (self.height, self.block_l, self.block_h, self.joint, self.block_waste, self.tile_l, self.tile_w,
                  self.tile_joint, self.tile_waste, self.box, self.coverage, self.paint_waste, self.gallon):
            w.valueChanged.connect(self.recalc)
        self.coats.valueChanged.connect(self.recalc)
        for w in (self.skip_wet, self.ceilings):
            w.toggled.connect(self.recalc)
        self.tile.currentIndexChanged.connect(self._preset)
        self._preset()

    def t(self, k):
        return tr(k, self.lang)

    def _table(self, cols):
        tb = QTableWidget(0, cols)
        tb.verticalHeader().setVisible(False)
        tb.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        tb.setEditTriggers(QTableWidget.NoEditTriggers)
        return tb

    def _preset(self, *_):
        v = self.tile.currentData()
        custom = v is None
        self.tile_l.setEnabled(custom)
        self.tile_w.setEnabled(custom)
        if v:
            self.tile_l.blockSignals(True)
            self.tile_w.blockSignals(True)
            self.tile_l.setValue(v[0] * 100)
            self.tile_w.setValue(v[1] * 100)
            self.tile_l.blockSignals(False)
            self.tile_w.blockSignals(False)
        self.recalc()

    def options(self) -> dict:
        return dict(wall_height=self.height.value(), block_l=self.block_l.value() / 100, block_h=self.block_h.value() / 100,
                    joint=self.joint.value() / 100, block_waste=self.block_waste.value() / 100,
                    tile_l=self.tile_l.value() / 100, tile_w=self.tile_w.value() / 100,
                    tile_joint=self.tile_joint.value() / 1000, tile_waste=self.tile_waste.value() / 100,
                    box_m2=self.box.value(), skip_wet_tiles=self.skip_wet.isChecked(),
                    paint_coverage=self.coverage.value(), coats=self.coats.value(),
                    paint_waste=self.paint_waste.value() / 100, gallon_l=self.gallon.value(),
                    ceilings=self.ceilings.isChecked())

    def recalc(self, *_):
        self.result = q = compute(self.plan, self.options())
        self.settings.setValue("qty_opts", json.dumps(self.options()))
        b, ti, p = q["blocks"], q["tiles"], q["paint"]
        t = self.t
        self.summary.setText(
            f"<h3>{t('qty_blocks')}</h3>"
            f"{t('ext_walls')}: <b>{b['ext_count']:,}</b> {t('pcs')} &nbsp;({b['ext_length']:.2f} m · {b['ext_area']:.1f} m²)<br>"
            f"{t('int_walls')}: <b>{b['int_count']:,}</b> {t('pcs')} &nbsp;({b['int_length']:.2f} m · {b['int_area']:.1f} m²)<br>"
            f"{t('total')}: <b>{b['total']:,}</b> {t('pcs')} &nbsp;·&nbsp; {b['per_m2']:.1f} {t('per_m2')}"
            f"<h3>{t('qty_tiles')} {ti['tile'][0] * 100:.0f}×{ti['tile'][1] * 100:.0f} cm</h3>"
            f"{t('total')}: <b>{ti['count']:,}</b> {t('pcs')} &nbsp;·&nbsp; {ti['m2_with_waste']:.1f} m² "
            f"&nbsp;·&nbsp; <b>{ti['boxes']}</b> {t('boxes')}"
            f"<h3>{t('qty_paint')}</h3>"
            f"{t('facade')}: <b>{p['facade_litres']:.1f} L</b> ({p['facade_gallons']:.1f} {t('gallons')}) · {p['facade_area']:.1f} m²<br>"
            f"{t('interior')}: <b>{p['interior_litres']:.1f} L</b> ({p['interior_gallons']:.1f} {t('gallons')}) · {p['interior_area']:.1f} m²")
        name = (lambda r: r["name_ar"]) if self.lang == "ar" else (lambda r: r["name_en"])
        self._fill(self.tile_table, [t("col_name"), "m²", t("pcs"), t("boxes")],
                   [[name(r), f"{r['area']:.2f}", f"{r['tiles']:,}",
                     f"{(r['area'] * (1 + self.options()['tile_waste']) / self.box.value()):.1f}" if self.box.value() else ""]
                    for r in ti["rooms"]])
        self._fill(self.paint_table, [t("col_name"), t("walls_m2"), t("ceiling_m2"), "L"],
                   [[name(r), f"{r['walls']:.2f}", f"{r['ceiling']:.2f}", f"{r['litres']:.1f}"] for r in p["rooms"]])

    @staticmethod
    def _fill(table, headers, rows):
        table.setColumnCount(len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.setRowCount(len(rows))
        for i, row in enumerate(rows):
            for j, v in enumerate(row):
                table.setItem(i, j, QTableWidgetItem(str(v)))

    def export_csv(self):
        path, _ = QFileDialog.getSaveFileName(self, self.t("export_csv"), "quantities.csv", "CSV (*.csv)")
        if path:
            with open(path, "w", encoding="utf-8") as f:
                f.write(to_csv(self.result, self.lang))

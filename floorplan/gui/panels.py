"""Left-hand input form. Produces/consumes the same project dict as the JSON files."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QAbstractItemView, QButtonGroup, QCheckBox, QComboBox, QDoubleSpinBox,
                               QFormLayout, QGroupBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
                               QPushButton, QRadioButton, QSpinBox, QStackedWidget, QTableWidget,
                               QVBoxLayout, QWidget)

from ..i18n import room_name
from ..program import build_program
from ..rules import get_rules
from .strings import tr

FP_MODES = ["fp_fixed", "fp_width", "fp_depth", "fp_plot", "fp_auto"]
QUALITY = [("q_fast", 150), ("q_normal", 400), ("q_high", 1200)]
ROOM_ORDER = ["entrance", "salon", "living", "dining", "kitchen", "guest_wc", "laundry", "storage",
              "maid", "master", "ensuite", "bedroom", "bathroom", "office"]


def dspin(lo, hi, step, val, dec=2):
    s = QDoubleSpinBox()
    s.setRange(lo, hi)
    s.setSingleStep(step)
    s.setDecimals(dec)
    s.setValue(val)
    return s


def ispin(lo, hi, val):
    s = QSpinBox()
    s.setRange(lo, hi)
    s.setValue(val)
    return s


class InputPanel(QWidget):
    changed = Signal()
    generateRequested = Signal()

    def __init__(self, lang: str, parent=None):
        super().__init__(parent)
        self.lang = lang
        self._loading = False
        t = lambda k: tr(k, lang)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(10)

        # project
        g = QGroupBox(t("project"))
        f = QFormLayout(g)
        self.name = QLineEdit()
        f.addRow(t("project_name"), self.name)
        lay.addWidget(g)

        # footprint
        g = QGroupBox(t("footprint"))
        f = QFormLayout(g)
        self.fp_mode = QComboBox()
        for k in FP_MODES:
            self.fp_mode.addItem(t(k), k)
        f.addRow(t("fp_mode"), self.fp_mode)
        self.width = dspin(4, 200, 0.05, 18.0)
        self.depth = dspin(4, 200, 0.05, 13.0)
        self.aspect = dspin(0.4, 3.0, 0.05, 1.35)
        self.plot_w = dspin(5, 500, 0.5, 25.0, 1)
        self.plot_d = dspin(5, 500, 0.5, 32.0, 1)
        self.zoning = QComboBox()
        for key, z in get_rules("jordan").ZONING_PRESETS.items():
            self.zoning.addItem(z["label_ar"] if lang == "ar" else z["label_en"], key)
        self.fp_rows = {}
        for key, label, w in [("width", "width", self.width), ("depth", "depth", self.depth),
                              ("aspect", "aspect", self.aspect), ("plot_w", "plot_w", self.plot_w),
                              ("plot_d", "plot_d", self.plot_d), ("zoning", "zoning", self.zoning)]:
            lbl = QLabel(t(label))
            f.addRow(lbl, w)
            self.fp_rows[key] = (lbl, w)
        lay.addWidget(g)

        # rooms
        g = QGroupBox(t("rooms"))
        v = QVBoxLayout(g)
        hl = QHBoxLayout()
        self.r_house, self.r_custom = QRadioButton(t("rooms_household")), QRadioButton(t("rooms_custom"))
        self.r_house.setChecked(True)
        grp = QButtonGroup(self)
        grp.addButton(self.r_house)
        grp.addButton(self.r_custom)
        hl.addWidget(self.r_house)
        hl.addWidget(self.r_custom)
        v.addLayout(hl)
        self.rooms_stack = QStackedWidget()
        # household page
        hp = QWidget()
        hf = QFormLayout(hp)
        hf.setContentsMargins(0, 0, 0, 0)
        self.parents = QCheckBox()
        self.parents.setChecked(True)
        self.sons, self.daughters = ispin(0, 12, 2), ispin(0, 12, 1)
        self.others, self.guests = ispin(0, 8, 0), ispin(0, 60, 10)
        self.office, self.maid = QCheckBox(), QCheckBox()
        for k, w in [("parents", self.parents), ("sons", self.sons), ("daughters", self.daughters),
                     ("others", self.others), ("guests", self.guests), ("office", self.office), ("maid", self.maid)]:
            hf.addRow(t(k), w)
        self.rooms_stack.addWidget(hp)
        # custom page
        cp = QWidget()
        cv = QVBoxLayout(cp)
        cv.setContentsMargins(0, 0, 0, 0)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels([t("type"), t("area"), t("occupants"), t("fixed")])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setMinimumHeight(220)
        cv.addWidget(self.table)
        bl = QHBoxLayout()
        b_add, b_del, b_fill = QPushButton(t("add_room")), QPushButton(t("remove_room")), QPushButton(t("from_household"))
        b_add.clicked.connect(lambda: (self.add_room_row("bedroom", 0, 1, False), self._emit()))
        b_del.clicked.connect(self._remove_rows)
        b_fill.clicked.connect(self.fill_from_household)
        for b in (b_add, b_del, b_fill):
            bl.addWidget(b)
        cv.addLayout(bl)
        hint = QLabel(t("area_auto_hint"))
        hint.setObjectName("muted")
        cv.addWidget(hint)
        self.rooms_stack.addWidget(cp)
        v.addWidget(self.rooms_stack)
        lay.addWidget(g)

        # construction
        g = QGroupBox(t("settings"))
        g.setCheckable(True)
        g.setChecked(False)
        f = QFormLayout(g)
        self.ext_wall, self.int_wall = dspin(0.1, 0.8, 0.01, 0.30), dspin(0.05, 0.4, 0.01, 0.15)
        self.corridor, self.wall_h = dspin(0.9, 3.0, 0.05, 1.20), dspin(2.4, 6.0, 0.05, 3.00)
        self.door_h = dspin(1.9, 3.0, 0.05, 2.10)
        self.settings_rows = [(t("ext_wall"), self.ext_wall), (t("int_wall"), self.int_wall),
                              (t("corridor"), self.corridor), (t("wall_height"), self.wall_h),
                              (t("door_height"), self.door_h)]
        self.settings_box = g
        holder = QWidget()
        hf2 = QFormLayout(holder)
        hf2.setContentsMargins(0, 0, 0, 0)
        for label, w in self.settings_rows:
            hf2.addRow(label, w)
        f.addRow(holder)
        g.toggled.connect(holder.setVisible)
        holder.setVisible(False)
        lay.addWidget(g)

        # generation
        g = QGroupBox(t("generation"))
        f = QFormLayout(g)
        sl = QHBoxLayout()
        self.seed = ispin(0, 999999, 1)
        b_prev, b_next, b_rand = QPushButton("◀"), QPushButton("▶"), QPushButton("🎲 " + t("random"))
        for b in (b_prev, b_next):
            b.setFixedWidth(34)
        b_prev.clicked.connect(lambda: self.seed.setValue(self.seed.value() - 1))
        b_next.clicked.connect(lambda: self.seed.setValue(self.seed.value() + 1))
        b_rand.clicked.connect(self._random_seed)
        sl.addWidget(self.seed, 1)
        sl.addWidget(b_prev)
        sl.addWidget(b_next)
        sl.addWidget(b_rand)
        f.addRow(t("seed"), sl)
        self.quality = QComboBox()
        for k, n in QUALITY:
            self.quality.addItem(t(k), n)
        self.quality.setCurrentIndex(1)
        f.addRow(t("quality"), self.quality)
        self.btn_generate = QPushButton(t("generate"))
        self.btn_generate.setObjectName("primary")
        self.btn_generate.clicked.connect(self.generateRequested.emit)
        f.addRow(self.btn_generate)
        lay.addWidget(g)
        lay.addStretch(1)

        # wiring
        self.fp_mode.currentIndexChanged.connect(self._update_fp_rows)
        self.r_house.toggled.connect(lambda on: self.rooms_stack.setCurrentIndex(0 if on else 1))
        for w in [self.width, self.depth, self.aspect, self.plot_w, self.plot_d, self.ext_wall, self.int_wall,
                  self.corridor, self.wall_h, self.door_h]:
            w.valueChanged.connect(self._emit)
        for w in [self.sons, self.daughters, self.others, self.guests, self.seed]:
            w.valueChanged.connect(self._emit)
        for w in [self.parents, self.office, self.maid]:
            w.toggled.connect(self._emit)
        self.fp_mode.currentIndexChanged.connect(self._emit)
        self.zoning.currentIndexChanged.connect(self._emit)
        self.quality.currentIndexChanged.connect(self._emit)
        self.r_house.toggled.connect(self._emit)
        self.name.editingFinished.connect(self._emit)
        self._update_fp_rows()

    # -- helpers --
    def _emit(self, *_):
        if not self._loading:
            self.changed.emit()

    def _random_seed(self):
        import random
        self.seed.setValue(random.randint(0, 99999))

    def _update_fp_rows(self, *_):
        mode = self.fp_mode.currentData()
        show = {"fp_fixed": {"width", "depth"}, "fp_width": {"width"}, "fp_depth": {"depth"},
                "fp_plot": {"plot_w", "plot_d", "zoning"}, "fp_auto": {"aspect"}}[mode]
        for key, (lbl, w) in self.fp_rows.items():
            lbl.setVisible(key in show)
            w.setVisible(key in show)

    def add_room_row(self, rtype="bedroom", area=0.0, occ=0, fixed=False):
        r = self.table.rowCount()
        self.table.insertRow(r)
        combo = QComboBox()
        for k in ROOM_ORDER:
            combo.addItem(room_name(k, self.lang), k)
        combo.setCurrentIndex(max(0, combo.findData(rtype)))
        a, o, fx = dspin(0, 500, 0.5, area, 1), ispin(0, 60, occ), QCheckBox()
        fx.setChecked(fixed)
        cell = QWidget()
        cl = QHBoxLayout(cell)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setAlignment(Qt.AlignCenter)
        cl.addWidget(fx)
        self.table.setCellWidget(r, 0, combo)
        self.table.setCellWidget(r, 1, a)
        self.table.setCellWidget(r, 2, o)
        self.table.setCellWidget(r, 3, cell)
        combo.currentIndexChanged.connect(self._emit)
        a.valueChanged.connect(self._emit)
        o.valueChanged.connect(self._emit)
        fx.toggled.connect(self._emit)

    def _remove_rows(self):
        rows = sorted({i.row() for i in self.table.selectedIndexes()} or {self.table.rowCount() - 1}, reverse=True)
        for r in rows:
            if r >= 0:
                self.table.removeRow(r)
        self._emit()

    def _rows(self):
        for r in range(self.table.rowCount()):
            combo = self.table.cellWidget(r, 0)
            area = self.table.cellWidget(r, 1).value()
            occ = self.table.cellWidget(r, 2).value()
            fixed = self.table.cellWidget(r, 3).findChild(QCheckBox).isChecked()
            yield combo.currentData(), area, occ, fixed

    def fill_from_household(self):
        cfg = self.get_config()
        cfg.pop("rooms", None)
        self._loading = True
        self.table.setRowCount(0)
        for s in build_program(cfg):
            self.add_room_row(s.type, round(s.area, 1), s.occupants, False)
        self._loading = False
        self.r_custom.setChecked(True)
        self._emit()

    # -- config in/out --
    def household(self) -> dict:
        return dict(parents=self.parents.isChecked(), sons=self.sons.value(), daughters=self.daughters.value(),
                    others=self.others.value(), guests=self.guests.value(),
                    office=self.office.isChecked(), maid=self.maid.isChecked())

    def get_config(self) -> dict:
        cfg = {"project": self.name.text().strip(), "rules": "jordan", "household": self.household()}
        mode = self.fp_mode.currentData()
        if mode == "fp_fixed":
            cfg["footprint"] = {"width": self.width.value(), "depth": self.depth.value()}
        elif mode == "fp_width":
            cfg["footprint"] = {"width": self.width.value()}
        elif mode == "fp_depth":
            cfg["footprint"] = {"depth": self.depth.value()}
        elif mode == "fp_plot":
            cfg["plot"] = {"width": self.plot_w.value(), "depth": self.plot_d.value(),
                           "zoning": self.zoning.currentData()}
        else:
            cfg["footprint"] = {"aspect": self.aspect.value()}
        if self.r_custom.isChecked():
            rooms = []
            for rtype, area, occ, fixed in self._rows():
                r = {"type": rtype}
                if occ:
                    r["occupants"] = occ
                if area > 0:
                    r["area"], r["fixed"] = area, fixed
                rooms.append(r)
            if rooms:
                cfg["rooms"] = rooms
        cfg["settings"] = {"exterior_wall": self.ext_wall.value(), "interior_wall": self.int_wall.value(),
                           "corridor": self.corridor.value(), "wall_height": self.wall_h.value(),
                           "door_height": self.door_h.value()}
        return cfg

    def set_config(self, cfg: dict):
        self._loading = True
        try:
            self.name.setText(cfg.get("project", ""))
            fp, plot = cfg.get("footprint", {}), cfg.get("plot")
            if plot:
                mode = "fp_plot"
                self.plot_w.setValue(plot.get("width", 25))
                self.plot_d.setValue(plot.get("depth", 32))
                i = self.zoning.findData(plot.get("zoning"))
                if i >= 0:
                    self.zoning.setCurrentIndex(i)
            elif "width" in fp and "depth" in fp:
                mode = "fp_fixed"
            elif "width" in fp:
                mode = "fp_width"
            elif "depth" in fp:
                mode = "fp_depth"
            else:
                mode = "fp_auto"
            self.width.setValue(fp.get("width", self.width.value()))
            self.depth.setValue(fp.get("depth", self.depth.value()))
            self.aspect.setValue(fp.get("aspect", self.aspect.value()))
            self.fp_mode.setCurrentIndex(FP_MODES.index(mode))
            hh = cfg.get("household", {})
            self.parents.setChecked(hh.get("parents", True))
            self.sons.setValue(hh.get("sons", 0))
            self.daughters.setValue(hh.get("daughters", 0))
            self.others.setValue(hh.get("others", 0))
            self.guests.setValue(hh.get("guests", 0))
            self.office.setChecked(hh.get("office", False))
            self.maid.setChecked(hh.get("maid", False))
            self.table.setRowCount(0)
            for r in cfg.get("rooms", []):
                self.add_room_row(r["type"], r.get("area", 0.0), r.get("occupants", 0),
                                  bool(r.get("fixed", True)) if "area" in r else False)
            (self.r_custom if cfg.get("rooms") else self.r_house).setChecked(True)
            st = cfg.get("settings", {})
            self.ext_wall.setValue(st.get("exterior_wall", 0.30))
            self.int_wall.setValue(st.get("interior_wall", 0.15))
            self.corridor.setValue(st.get("corridor", 1.20))
            self.wall_h.setValue(st.get("wall_height", 3.0))
            self.door_h.setValue(st.get("door_height", 2.1))
        finally:
            self._loading = False
        self._update_fp_rows()

    def candidates(self) -> int:
        return self.quality.currentData()

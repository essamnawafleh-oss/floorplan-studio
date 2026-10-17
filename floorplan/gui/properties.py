"""Properties of the selected element (edit mode)."""

from __future__ import annotations

from PySide6.QtWidgets import (QComboBox, QDoubleSpinBox, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
                               QPushButton, QVBoxLayout, QWidget)

from .. import editing
from ..i18n import room_name
from .panels import ROOM_ORDER
from .strings import tr


def _spin(lo, hi, val, step=0.05, dec=2):
    s = QDoubleSpinBox()
    s.setRange(lo, hi)
    s.setDecimals(dec)
    s.setSingleStep(step)
    s.setValue(val)
    s.setKeyboardTracking(False)
    return s


class PropertiesPanel(QWidget):
    def __init__(self, editor, lang: str, parent=None):
        super().__init__(parent)
        self.editor, self.lang = editor, lang
        self.lay = QVBoxLayout(self)
        self.body = None
        editor.selectionChanged.connect(self.rebuild)
        self.rebuild()

    def t(self, k):
        return tr(k, self.lang)

    def rebuild(self):
        if self.body is not None:
            self.body.setParent(None)
            self.body.deleteLater()
        self.body = QWidget()
        form = QFormLayout(self.body)
        self.lay.addWidget(self.body)
        ed, plan, sel = self.editor, self.editor.plan, self.editor.selection
        if not ed.enabled:
            form.addRow(self._muted(self.t("props_need_edit")))
            return
        if plan is not None and sel is None and ed.cad.sel:
            self._cad_props(form, plan, sorted(i for i in ed.cad.sel if 0 <= i < len(plan.drawing)))
            return
        if plan is None or sel is None:
            form.addRow(self._muted(self.t("props_hint")))
            return
        kind, ref = sel
        title = QLabel()
        title.setStyleSheet("font-weight:600;font-size:14px")
        form.addRow(title)

        if kind == "room":
            room = next((r for r in plan.rooms if r.id == ref), None)
            if not room:
                return
            title.setText(room.spec.name_ar if self.lang == "ar" else room.spec.name_en)
            name_ar, name_en = QLineEdit(room.spec.name_ar), QLineEdit(room.spec.name_en)
            typ = QComboBox()
            for k in ROOM_ORDER + ["corridor"]:
                typ.addItem(room_name(k, self.lang), k)
            typ.setCurrentIndex(max(0, typ.findData(room.spec.type)))
            w, h = _spin(0.6, 100, room.net.w), _spin(0.6, 100, room.net.h)
            form.addRow(self.t("name_ar"), name_ar)
            form.addRow(self.t("name_en"), name_en)
            form.addRow(self.t("type"), typ)
            form.addRow(self.t("room_w"), w)
            form.addRow(self.t("room_h"), h)
            form.addRow(self._muted(f"{room.net.area:.2f} m²"))

            def rename(*_):
                def fn(p):
                    r = next(r for r in p.rooms if r.id == ref)
                    r.spec.name_ar, r.spec.name_en = name_ar.text(), name_en.text()
                ed.apply(fn, select=sel)
            name_ar.editingFinished.connect(rename)
            name_en.editingFinished.connect(rename)
            typ.currentIndexChanged.connect(lambda *_: ed.apply(
                lambda p: editing.set_room_type(p, next(r for r in p.rooms if r.id == ref), typ.currentData()),
                select=sel))
            w.valueChanged.connect(lambda v: ed.apply(
                lambda p: editing.set_room_size(p, next(r for r in p.rooms if r.id == ref), width=v), select=sel))
            h.valueChanged.connect(lambda v: ed.apply(
                lambda p: editing.set_room_size(p, next(r for r in p.rooms if r.id == ref), length=v), select=sel))

        elif kind == "wall":
            ln = ref
            title.setText(self.t("wall_ext") + f" ({self.t('side_' + ln.side)})" if ln.side else self.t("wall_int"))
            pos = _spin(-100, 300, ln.coord)
            form.addRow(self.t("wall_pos"), pos)
            form.addRow(self._muted(f"{self.t('length')}: {ln.length:.2f} m"))
            if ln.side:
                form.addRow(self._muted(f"{plan.width:.2f} × {plan.depth:.2f} m"))

            def moved(v):
                new_line = editing.WallLine(ln.orient, v, ln.s0, ln.s1, ln.side)
                ed.apply(lambda p: editing.move_wall(p, ln, v), select=("wall", new_line))
            pos.valueChanged.connect(moved)

        elif kind == "opening":
            if ref >= len(plan.openings):
                return
            o = plan.openings[ref]
            title.setText(self.t("op_" + o.kind))
            width = _spin(0.4, 6, o.width)
            form.addRow(self.t("op_width"), width)
            width.valueChanged.connect(lambda v: ed.apply(
                lambda p: editing.set_opening_width(p, p.openings[ref], v), select=sel))
            if o.kind == "window":
                sill, head = _spin(0, 3, o.sill), _spin(0.5, 4, o.head)
                form.addRow(self.t("sill"), sill)
                form.addRow(self.t("head"), head)
                sill.valueChanged.connect(lambda v: ed.apply(lambda p: setattr(p.openings[ref], "sill", v), select=sel))
                head.valueChanged.connect(lambda v: ed.apply(lambda p: setattr(p.openings[ref], "head", v), select=sel))
            symbol = QComboBox()
            symbol.addItem(self.t("symbol_default"), "")
            cat = "window" if o.kind == "window" else "door"
            for b in ed.library.by_category(cat):
                symbol.addItem(b.name_ar if self.lang == "ar" else b.name_en, b.id)
            symbol.setCurrentIndex(max(0, symbol.findData(o.block)))
            form.addRow(self.t("symbol"), symbol)
            symbol.currentIndexChanged.connect(lambda *_: ed.apply(
                lambda p: setattr(p.openings[ref], "block", symbol.currentData()), select=sel))
            row = QHBoxLayout()
            if o.kind != "window":
                flip = QPushButton(self.t("flip_swing"))
                flip.clicked.connect(lambda: ed.apply(lambda p: setattr(p.openings[ref], "into", -p.openings[ref].into), select=sel))
                hinge = QPushButton(self.t("flip_hinge"))
                hinge.clicked.connect(lambda: ed.apply(lambda p: setattr(p.openings[ref], "hinge", 1 - p.openings[ref].hinge), select=sel))
                row.addWidget(flip)
                row.addWidget(hinge)
            delete = QPushButton("🗑 " + self.t("delete"))
            delete.clicked.connect(ed.delete_selection)
            row.addWidget(delete)
            form.addRow(self._wrap(row))

        elif kind == "furniture":
            if ref >= len(plan.furniture):
                return
            f = plan.furniture[ref]
            b = ed.library.get(f.block)
            title.setText((b.name_ar if self.lang == "ar" else b.name_en) if b else f.block)
            x, y = _spin(-50, 300, f.x), _spin(-50, 300, f.y)
            rot, sc = _spin(-360, 360, f.rotation, 15, 0), _spin(0.1, 10, f.scale, 0.05)
            for label, w, attr in ((self.t("x"), x, "x"), (self.t("y"), y, "y"),
                                   (self.t("rotation"), rot, "rotation"), (self.t("scale_f"), sc, "scale")):
                form.addRow(label, w)
                w.valueChanged.connect(lambda v, a=attr: ed.apply(lambda p: setattr(p.furniture[ref], a, v), select=sel))
            row = QHBoxLayout()
            r90 = QPushButton("⟲ 90°")
            r90.clicked.connect(lambda: ed.rotate_furniture(90))
            delete = QPushButton("🗑 " + self.t("delete"))
            delete.clicked.connect(ed.delete_selection)
            row.addWidget(r90)
            row.addWidget(delete)
            form.addRow(self._wrap(row))

    def _cad_props(self, form, plan, idx):
        from PySide6.QtGui import QColor
        from PySide6.QtWidgets import QColorDialog
        from ..cad import LAYERS
        ed = self.editor
        title = QLabel(f"{len(idx)} {self.t('cad_selected')}")
        title.setStyleSheet("font-weight:600;font-size:14px")
        form.addRow(title)
        if not idx:
            return
        first = plan.drawing[idx[0]]
        layer = QComboBox()
        for name in LAYERS:
            layer.addItem(name, name)
        layer.setCurrentIndex(max(0, layer.findData(first.get("layer", "A-DRAW"))))
        form.addRow(self.t("layer"), layer)

        def set_all(key, value):
            def fn(p):
                for i in idx:
                    p.drawing[i] = {**p.drawing[i], key: value}
            ed.apply(fn)
        layer.currentIndexChanged.connect(lambda *_: set_all("layer", layer.currentData()))
        color = QPushButton(first.get("color") or "ByLayer")
        def pick():
            c = QColorDialog.getColor(QColor(first.get("color") or LAYERS.get(first.get("layer", ""), "#3a3d42")), self)
            if c.isValid():
                set_all("color", c.name())
        color.clicked.connect(pick)
        reset = QPushButton("ByLayer")
        reset.clicked.connect(lambda: set_all("color", ""))
        row = QHBoxLayout()
        row.addWidget(color, 1)
        row.addWidget(reset)
        form.addRow(self.t("color"), self._wrap(row))
        if len(idx) == 1:
            i, e = idx[0], first
            if e["t"] == "text":
                txt, h = QLineEdit(e["s"]), _spin(0.02, 10, e["h"], 0.05, 3)
                form.addRow(self.t("text"), txt)
                form.addRow(self.t("height"), h)
                txt.editingFinished.connect(lambda: ed.apply(lambda p: p.drawing.__setitem__(i, {**p.drawing[i], "s": txt.text()})))
                h.valueChanged.connect(lambda v: ed.apply(lambda p: p.drawing.__setitem__(i, {**p.drawing[i], "h": v})))
            elif e["t"] in ("circle", "arc"):
                r = _spin(0.001, 500, e["r"], 0.05, 3)
                form.addRow(self.t("radius"), r)
                r.valueChanged.connect(lambda v: ed.apply(lambda p: p.drawing.__setitem__(i, {**p.drawing[i], "r": v})))
            elif e["t"] == "line":
                from ..cad import dist
                x1, y1, x2, y2 = e["p"]
                import math
                form.addRow(self._muted(f"{self.t('length')}: {dist((x1, y1), (x2, y2)):.3f} m · "
                                        f"{math.degrees(math.atan2(y2 - y1, x2 - x1)) % 360:.1f}°"))
        delete = QPushButton("🗑 " + self.t("delete"))
        delete.clicked.connect(lambda: ed.cad.start("Erase"))
        form.addRow(delete)

    @staticmethod
    def _wrap(layout):
        w = QWidget()
        layout.setContentsMargins(0, 0, 0, 0)
        w.setLayout(layout)
        return w

    @staticmethod
    def _muted(text):
        lbl = QLabel(text)
        lbl.setObjectName("muted")
        lbl.setWordWrap(True)
        return lbl

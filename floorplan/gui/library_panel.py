"""Block library browser: pick a block to place, import blocks from DXF."""

from __future__ import annotations

from PySide6.QtCore import QPointF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (QComboBox, QFileDialog, QHBoxLayout, QInputDialog, QLabel, QListView, QListWidget,
                               QListWidgetItem, QMessageBox, QPushButton, QVBoxLayout, QWidget)

from ..blocks import CATEGORIES, blocks_from_dxf, transform_prims
from .strings import tr


def block_icon(block, size: int = 72, color: str = "#3a3d42") -> QIcon:
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    lines = transform_prims(block.prims, lambda x, y: (x, y))
    pts = [p for pl in lines for p in pl] or [(0, 0), (1, 1)]
    x0, y0 = min(p[0] for p in pts), min(p[1] for p in pts)
    x1, y1 = max(p[0] for p in pts), max(p[1] for p in pts)
    k = (size - 10) / max(x1 - x0, y1 - y0, 1e-6)
    ox, oy = (size - (x1 - x0) * k) / 2, (size - (y1 - y0) * k) / 2
    path = QPainterPath()
    for pl in lines:
        if len(pl) < 2:
            continue
        path.moveTo(QPointF(ox + (pl[0][0] - x0) * k, size - oy - (pl[0][1] - y0) * k))
        for x, y in pl[1:]:
            path.lineTo(QPointF(ox + (x - x0) * k, size - oy - (y - y0) * k))
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(QPen(QColor(color), 1.4))
    p.drawPath(path)
    p.end()
    return QIcon(pm)


class LibraryPanel(QWidget):
    placeRequested = Signal(str)      # block id

    def __init__(self, library, lang: str, ink: str, parent=None):
        super().__init__(parent)
        self.library, self.lang, self.ink = library, lang, ink
        t = lambda k: tr(k, lang)
        lay = QVBoxLayout(self)
        self.cat = QComboBox()
        for key, (ar, en) in CATEGORIES.items():
            self.cat.addItem(ar if lang == "ar" else en, key)
        self.cat.currentIndexChanged.connect(self.refresh)
        lay.addWidget(self.cat)
        self.list = QListWidget()
        self.list.setViewMode(QListView.IconMode)
        self.list.setIconSize(QSize(72, 72))
        self.list.setGridSize(QSize(104, 112))
        self.list.setResizeMode(QListView.Adjust)
        self.list.setMovement(QListView.Static)
        self.list.setWordWrap(True)
        self.list.itemDoubleClicked.connect(lambda it: self.placeRequested.emit(it.data(Qt.UserRole)))
        lay.addWidget(self.list, 1)
        hint = QLabel(t("lib_hint"))
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        lay.addWidget(hint)
        row = QHBoxLayout()
        place, imp, rem = QPushButton(t("lib_place")), QPushButton(t("lib_import")), QPushButton(t("delete"))
        place.clicked.connect(self._place)
        imp.clicked.connect(self._import)
        rem.clicked.connect(self._remove)
        for b in (place, imp, rem):
            row.addWidget(b)
        lay.addLayout(row)
        self.refresh()

    def refresh(self, *_):
        self.list.clear()
        for b in self.library.by_category(self.cat.currentData()):
            name = b.name_ar if self.lang == "ar" else b.name_en
            it = QListWidgetItem(block_icon(b, color=self.ink), name)
            it.setData(Qt.UserRole, b.id)
            it.setToolTip(f"{name}\n{b.width:.2f} × {b.depth:.2f} m" if b.category not in ("door", "window") else name)
            self.list.addItem(it)

    def _place(self):
        it = self.list.currentItem()
        if it:
            self.placeRequested.emit(it.data(Qt.UserRole))

    def _import(self):
        t = lambda k: tr(k, self.lang)
        path, _ = QFileDialog.getOpenFileName(self, t("lib_import"), "", "DXF (*.dxf)")
        if not path:
            return
        units = [t("unit_auto"), "mm", "cm", "m"]
        unit, ok = QInputDialog.getItem(self, t("lib_import"), t("lib_unit"), units, 0, False)
        if not ok:
            return
        k = {"mm": 0.001, "cm": 0.01, "m": 1.0}.get(unit)
        try:
            blocks = blocks_from_dxf(path, self.cat.currentData(), k)
        except Exception as e:
            QMessageBox.warning(self, t("error"), str(e))
            return
        for b in blocks:
            self.library.add(b)
        self.refresh()
        QMessageBox.information(self, t("lib_import"), f"{t('lib_imported')}: {len(blocks)}")

    def _remove(self):
        it = self.list.currentItem()
        if not it:
            return
        bid = it.data(Qt.UserRole)
        if not bid.startswith("user/"):
            QMessageBox.information(self, tr("lib_import", self.lang), tr("lib_builtin", self.lang))
            return
        self.library.remove(bid)
        self.refresh()

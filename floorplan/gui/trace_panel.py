"""Image -> plan workspace: open a screenshot / photo / PDF, read it, set the
scale, name the rooms, preview, then create an editable plan.

Nothing here touches the project plan; the window applies the result when
the user asks for it (one undoable step), exactly like the parametric mode."""

from __future__ import annotations

import math
import os

import numpy as np
from PySide6.QtCore import QObject, QPointF, QRectF, QRunnable, Qt, QThreadPool, Signal
from PySide6.QtGui import QBrush, QColor, QGuiApplication, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog, QFormLayout,
                               QGraphicsPixmapItem, QGraphicsScene, QGraphicsView, QGroupBox, QHBoxLayout,
                               QHeaderView, QLabel, QMessageBox, QProgressBar, QPushButton, QRadioButton,
                               QScrollArea, QSpinBox, QSplitter, QTableWidget, QTableWidgetItem, QTabWidget,
                               QVBoxLayout, QWidget)

from .. import trace
from ..i18n import room_name
from ..rules.jordan import ROOM_TYPES
from ..trace import ocr as ocr_mod
from .plan_view import PlanScene, PlanView
from .strings import tr

PALETTE = ["#4dabf7", "#69db7c", "#ffa94d", "#da77f2", "#ffd43b", "#38d9a9", "#ff8787", "#748ffc",
           "#a9e34b", "#f783ac", "#3bc9db", "#e599f7", "#ffc078", "#8ce99a"]


def to_qimage(gray: np.ndarray) -> QImage:
    g = np.ascontiguousarray(gray)
    h, w = g.shape
    return QImage(g.data, w, h, w, QImage.Format_Grayscale8).copy()


def qimage_to_array(img: QImage) -> np.ndarray:
    img = img.convertToFormat(QImage.Format_RGBA8888)
    w, h = img.width(), img.height()
    arr = np.frombuffer(img.constBits(), np.uint8, img.bytesPerLine() * h).reshape(h, img.bytesPerLine() // 4, 4)
    return arr[:, :w, [2, 1, 0, 3]].copy()        # BGRA, like OpenCV


# --- background work ---------------------------------------------------------------------
class _Sig(QObject):
    progress = Signal(int, int)            # request, percent
    done = Signal(int, object, str)        # request, Analysis, error


class _ReadTask(QRunnable):
    def __init__(self, req, src, opts, sig, flag):
        super().__init__()
        self.req, self.src, self.opts, self.sig, self.flag = req, src, opts, sig, flag

    def run(self):
        try:
            a = trace.read(self.src, progress=self._p, cancelled=lambda: self.flag["cancel"], **self.opts)
            err = ""
        except Exception as e:             # shown in the panel
            a, err = None, f"{type(e).__name__}: {e}"
        try:
            self.sig.done.emit(self.req, a, err)
        except RuntimeError:
            pass

    def _p(self, f):
        try:
            self.sig.progress.emit(self.req, int(f * 100))
        except RuntimeError:
            pass


# --- the drawing view ---------------------------------------------------------------------
class ImageView(QGraphicsView):
    """Pan/zoom an image; 'crop' drags a rectangle, 'line' takes two clicks,
    'pick' reports a click. Coordinates are image pixels."""
    cropped = Signal(QRectF)
    lineDrawn = Signal(QPointF, QPointF)
    picked = Signal(QPointF)

    def __init__(self, scene):
        super().__init__(scene)
        self.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setLayoutDirection(Qt.LeftToRight)
        self.mode = "pick"
        self._start = None
        self._temp = None
        self._pan = None
        self.setMouseTracking(True)

    def set_mode(self, mode):
        self.mode = mode
        self._clear_temp()
        self._start = None
        self.setCursor(Qt.CrossCursor if mode in ("crop", "line") else Qt.ArrowCursor)

    def _clear_temp(self):
        if self._temp is not None:
            self.scene().removeItem(self._temp)
            self._temp = None

    def mousePressEvent(self, e):
        p = self.mapToScene(e.position().toPoint())
        if e.button() != Qt.LeftButton or self.mode == "pan":
            self._pan = e.position()
            self.setCursor(Qt.ClosedHandCursor)
            return
        if self.mode == "crop":
            self._start = p
        elif self.mode == "line":
            if self._start is None:
                self._start = p
            else:
                a, self._start = self._start, None
                self._clear_temp()
                self.lineDrawn.emit(a, p)
        elif self.mode == "pick":
            self._pan = e.position()               # a click picks, a drag pans
            self._press = e.position()

    def mouseMoveEvent(self, e):
        if self._pan is not None:
            d = e.position() - self._pan
            self._pan = e.position()
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - int(d.x()))
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - int(d.y()))
            return
        if self._start is None:
            return
        p = self.mapToScene(e.position().toPoint())
        self._clear_temp()
        pen = QPen(QColor("#e8590c"), 0)
        pen.setCosmetic(True)
        pen.setWidth(2)
        if self.mode == "crop":
            self._temp = self.scene().addRect(QRectF(self._start, p).normalized(), pen)
        else:
            if e.modifiers() & Qt.ShiftModifier:   # Shift keeps the line straight
                if abs(p.x() - self._start.x()) > abs(p.y() - self._start.y()):
                    p.setY(self._start.y())
                else:
                    p.setX(self._start.x())
            self._temp = self.scene().addLine(self._start.x(), self._start.y(), p.x(), p.y(), pen)
        self._temp.setZValue(50)

    def mouseReleaseEvent(self, e):
        if self._pan is not None:
            moved = getattr(self, "_press", None) is not None and \
                (e.position() - self._press).manhattanLength() > 4
            self._pan = None
            self.setCursor(Qt.CrossCursor if self.mode in ("crop", "line") else Qt.ArrowCursor)
            if self.mode == "pick" and not moved and e.button() == Qt.LeftButton:
                self.picked.emit(self.mapToScene(e.position().toPoint()))
            self._press = None
            return
        if self.mode == "crop" and self._start is not None:
            r = QRectF(self._start, self.mapToScene(e.position().toPoint())).normalized()
            self._start = None
            self._clear_temp()
            if r.width() > 20 and r.height() > 20:
                self.cropped.emit(r)

    def wheelEvent(self, e):
        f = 1.15 if e.angleDelta().y() > 0 else 1 / 1.15
        self.scale(f, f)

    def fit(self):
        if self.scene().items():
            self.fitInView(self.scene().itemsBoundingRect(), Qt.KeepAspectRatio)


def _dspin(lo, hi, val, step=0.05, dec=2, suffix=""):
    s = QDoubleSpinBox()
    s.setRange(lo, hi)
    s.setDecimals(dec)
    s.setSingleStep(step)
    s.setValue(val)
    if suffix:
        s.setSuffix(suffix)
    return s


# --- the panel ----------------------------------------------------------------------------
class TracePanel(QWidget):
    applyRequested = Signal(object)        # Plan
    backRequested = Signal()

    def __init__(self, window, state: dict, parent=None):
        super().__init__(parent)
        self.w, self.lang = window, window.lang
        self.state = state                 # owned by the window: survives language rebuilds
        self.req = 0
        self.flag = {"cancel": False}
        self.sig = _Sig()
        self.sig.progress.connect(self._on_progress)
        self.sig.done.connect(self._on_done)
        self.preview_plan = None
        t = self.t

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        split = QSplitter()
        root.addWidget(split)

        left = QWidget()
        lv = QVBoxLayout(left)
        head = QLabel(t("tr_title"))
        head.setStyleSheet("font-weight:700;font-size:15px")
        lv.addWidget(head)
        steps = QLabel(t("tr_steps"))
        steps.setObjectName("muted")
        steps.setWordWrap(True)
        lv.addWidget(steps)

        # 1 source
        g = QGroupBox("1 · " + t("tr_source"))
        gv = QVBoxLayout(g)
        row = QHBoxLayout()
        b = QPushButton(t("tr_open"))
        b.setObjectName("primary")
        b.clicked.connect(self.open_file)
        row.addWidget(b, 1)
        b = QPushButton(t("tr_paste"))
        b.clicked.connect(self.paste)
        row.addWidget(b)
        gv.addLayout(row)
        self.file_label = QLabel(t("tr_no_file"))
        self.file_label.setObjectName("muted")
        self.file_label.setWordWrap(True)
        gv.addWidget(self.file_label)
        f = QFormLayout()
        self.page = QSpinBox()
        self.page.setRange(1, 1)
        self.page.valueChanged.connect(self._page_changed)
        f.addRow(t("tr_page"), self.page)
        gv.addLayout(f)
        row = QHBoxLayout()
        self.crop_btn = QPushButton(t("tr_crop"))
        self.crop_btn.setCheckable(True)
        self.crop_btn.toggled.connect(lambda on: self.view.set_mode("crop" if on else "pick"))
        row.addWidget(self.crop_btn, 1)
        b = QPushButton(t("tr_uncrop"))
        b.clicked.connect(self.reset_crop)
        row.addWidget(b)
        gv.addLayout(row)
        lv.addWidget(g)

        # 2 read
        g = QGroupBox("2 · " + t("tr_read"))
        f = QFormLayout(g)
        self.ocr = QComboBox()
        avail = ocr_mod.engines()
        for key, label in (("auto", t("tr_ocr_auto")), ("rapidocr", "RapidOCR (PaddleOCR)"),
                           ("tesseract", "Tesseract"), ("always", t("tr_ocr_always")), ("off", t("tr_ocr_off"))):
            if key in ("rapidocr", "tesseract") and key not in avail:
                label += " — " + t("tr_not_installed")
            self.ocr.addItem(label, key)
        f.addRow(t("tr_ocr"), self.ocr)
        self.style = QComboBox()
        for key in ("auto", "filled", "outline"):
            self.style.addItem(t("tr_style_" + key), key)
        f.addRow(t("tr_wall_style"), self.style)
        self.wall_px = QSpinBox()
        self.wall_px.setRange(0, 200)
        self.wall_px.setSpecialValueText(t("tr_auto"))
        self.wall_px.setSuffix(" px")
        f.addRow(t("tr_wall_px"), self.wall_px)
        self.door_gap = _dspin(3, 15, 7, 0.5, 1)
        self.door_gap.setToolTip(t("tr_door_gap_tip"))
        f.addRow(t("tr_door_gap"), self.door_gap)
        row = QHBoxLayout()
        self.read_btn = QPushButton(t("tr_analyse"))
        self.read_btn.setObjectName("primary")
        self.read_btn.clicked.connect(self.analyse)
        row.addWidget(self.read_btn, 1)
        self.cancel_btn = QPushButton(t("cancel"))
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(lambda: self.flag.update(cancel=True))
        row.addWidget(self.cancel_btn)
        f.addRow(row)
        self.progress = QProgressBar()
        self.progress.setVisible(False)
        f.addRow(self.progress)
        self.read_info = QLabel("")
        self.read_info.setObjectName("muted")
        self.read_info.setWordWrap(True)
        f.addRow(self.read_info)
        lv.addWidget(g)

        # 3 scale
        g = QGroupBox("3 · " + t("tr_scale"))
        gv = QVBoxLayout(g)
        self.mode_group = QButtonGroup(self)
        self.r_dims = QRadioButton(t("tr_from_dims"))
        self.r_door = QRadioButton(t("tr_from_door"))
        self.r_line = QRadioButton(t("tr_from_line"))
        self.r_manual = QRadioButton(t("tr_manual"))
        for i, r in enumerate((self.r_dims, self.r_door, self.r_line, self.r_manual)):
            self.mode_group.addButton(r, i)
        gv.addWidget(self.r_dims)
        gv.addWidget(self.r_door)
        row = QHBoxLayout()
        row.addSpacing(22)
        row.addWidget(QLabel(t("tr_door_w")))
        self.door_m = _dspin(0.5, 2.5, 1.0, 0.05, 2, " m")
        self.door_m.valueChanged.connect(self._scale_inputs_changed)
        row.addWidget(self.door_m)
        row.addStretch(1)
        gv.addLayout(row)
        gv.addWidget(self.r_line)
        row = QHBoxLayout()
        row.addSpacing(22)
        self.line_btn = QPushButton(t("tr_draw_line"))
        self.line_btn.setCheckable(True)
        self.line_btn.toggled.connect(self._line_tool)
        row.addWidget(self.line_btn)
        row.addWidget(QLabel(t("tr_line_len")))
        self.line_m = _dspin(0.1, 500, 1.0, 0.1, 3, " m")
        self.line_m.valueChanged.connect(self._scale_inputs_changed)
        row.addWidget(self.line_m)
        gv.addLayout(row)
        gv.addWidget(self.r_manual)
        row = QHBoxLayout()
        row.addSpacing(22)
        row.addWidget(QLabel(t("tr_px_per_m")))
        self.ppm = _dspin(1, 5000, 50, 1, 2)
        self.ppm.valueChanged.connect(self._scale_inputs_changed)
        row.addWidget(self.ppm)
        row.addStretch(1)
        gv.addLayout(row)
        self.mode_group.idToggled.connect(lambda _i, on: on and self._scale_inputs_changed())
        self.scale_info = QLabel("")
        self.scale_info.setWordWrap(True)
        gv.addWidget(self.scale_info)
        lv.addWidget(g)

        # 4 rooms
        g = QGroupBox("4 · " + t("tr_rooms"))
        gv = QVBoxLayout(g)
        hint = QLabel(t("tr_rooms_hint"))
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        gv.addWidget(hint)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["#", t("type"), t("tr_area"), t("tr_text")])
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.Stretch)
        hh.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.verticalHeader().setVisible(False)
        self.table.setMinimumHeight(240)
        self.table.itemSelectionChanged.connect(self._row_selected)
        gv.addWidget(self.table)
        lv.addWidget(g)

        # 5 options
        g = QGroupBox("5 · " + t("tr_options"))
        f = QFormLayout(g)
        self.openings = QComboBox()
        self.openings.addItem(t("tr_open_detected"), "detected")
        self.openings.addItem(t("tr_open_auto"), "auto")
        self.openings.currentIndexChanged.connect(self.update_preview)
        f.addRow(t("tr_openings"), self.openings)
        self.walls_drawn = QCheckBox(t("tr_walls_drawn"))
        self.walls_drawn.setChecked(True)
        self.walls_drawn.toggled.connect(self.update_preview)
        f.addRow(self.walls_drawn)
        self.furn = QCheckBox(t("tr_furniture"))
        self.furn.setChecked(True)
        self.furn.toggled.connect(self.update_preview)
        f.addRow(self.furn)
        self.snap = _dspin(0, 0.5, 0.05, 0.01, 2, " m")
        self.snap.setSpecialValueText(t("tr_off"))
        self.snap.valueChanged.connect(self.update_preview)
        f.addRow(t("tr_snap"), self.snap)
        lv.addWidget(g)
        lv.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidget(left)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setMinimumWidth(500)
        split.addWidget(scroll)

        # centre: drawing + preview
        center = QWidget()
        cv = QVBoxLayout(center)
        bar = QHBoxLayout()
        self.show_rooms = QCheckBox(t("tr_show_rooms"))
        self.show_rooms.setChecked(True)
        self.show_walls = QCheckBox(t("tr_show_walls"))
        self.show_walls.setChecked(True)
        self.show_text = QCheckBox(t("tr_show_text"))
        self.show_text.setChecked(True)
        for c in (self.show_rooms, self.show_walls, self.show_text):
            c.toggled.connect(self._draw_overlay)
            bar.addWidget(c)
        bar.addStretch(1)
        b = QPushButton(t("tr_fit"))
        b.clicked.connect(lambda: (self.view.fit(), self.pview.fit()))
        bar.addWidget(b)
        cv.addLayout(bar)
        self.tabs = QTabWidget()
        self.iscene = QGraphicsScene()
        self.iscene.setBackgroundBrush(QColor("#ffffff"))
        self.view = ImageView(self.iscene)
        self.view.cropped.connect(self._cropped)
        self.view.lineDrawn.connect(self._line_drawn)
        self.view.picked.connect(self._picked)
        self.tabs.addTab(self.view, t("tr_tab_drawing"))
        self.pscene = PlanScene()
        self.pview = PlanView(self.pscene)
        self.pview.set_canvas(window.tokens["canvas"])
        self.tabs.addTab(self.pview, t("tr_tab_preview"))
        self.tabs.currentChanged.connect(lambda i: i == 1 and self.pview.fit())
        cv.addWidget(self.tabs, 1)
        self.status = QLabel(t("tr_hint"))
        self.status.setObjectName("status")
        self.status.setWordWrap(True)
        cv.addWidget(self.status)
        row = QHBoxLayout()
        self.apply_btn = QPushButton("6 · " + t("tr_apply"))
        self.apply_btn.setObjectName("primary")
        self.apply_btn.setEnabled(False)
        self.apply_btn.clicked.connect(self._apply)
        row.addWidget(self.apply_btn, 1)
        back = QPushButton(t("pm_back"))
        back.clicked.connect(self.backRequested.emit)
        row.addWidget(back)
        cv.addLayout(row)
        note = QLabel(t("tr_note"))
        note.setObjectName("muted")
        note.setWordWrap(True)
        cv.addWidget(note)
        split.addWidget(center)
        split.setStretchFactor(1, 1)
        split.setSizes([520, 1000])

        self._restore()

    def t(self, k):
        return tr(k, self.lang)

    # ------------------------------------------------------------ state
    def _restore(self):
        st = self.state
        for key, combo in (("ocr", self.ocr), ("style", self.style), ("openings", self.openings)):
            if key in st:
                combo.setCurrentIndex(max(0, combo.findData(st[key])))
        self.door_m.setValue(st.get("door_m", 1.0))
        self.wall_px.setValue(st.get("wall_px", 0))
        self.door_gap.setValue(st.get("door_gap", 7.0))
        self.furn.setChecked(st.get("furniture", True))
        self.walls_drawn.setChecked(st.get("walls_drawn", True))
        self.snap.setValue(st.get("snap", 0.05))
        self.line_m.setValue(st.get("line_m", 1.0))
        self.ppm.setValue(st.get("ppm", 50.0))
        if st.get("src") is not None:
            self._show_source()
        if st.get("analysis") is not None:
            self._after_analysis(restore=True)
        else:
            self.r_dims.setChecked(True)

    def _save(self):
        st = self.state
        st.update(ocr=self.ocr.currentData(), style=self.style.currentData(), openings=self.openings.currentData(),
                  door_m=self.door_m.value(), wall_px=self.wall_px.value(), door_gap=self.door_gap.value(),
                  furniture=self.furn.isChecked(), walls_drawn=self.walls_drawn.isChecked(),
                  snap=self.snap.value(), line_m=self.line_m.value(), ppm=self.ppm.value(),
                  mode=self.mode_group.checkedId())
        st["types"] = self._types()

    def shutdown(self):
        self.flag["cancel"] = True
        self._save()

    # ------------------------------------------------------------ source
    def open_file(self):
        exts = " ".join("*" + e for e in trace.IMAGE_EXT)
        path, _ = QFileDialog.getOpenFileName(self, self.t("tr_open"), self.w._dir(),
                                              f"{self.t('tr_files')} (*.pdf {exts});;PDF (*.pdf);;"
                                              f"{self.t('tr_images')} ({exts})")
        if path:
            self.load_path(path)

    def load_path(self, path: str, page: int = 0):
        try:
            n = trace.page_count(path)
            src = trace.load(path, page)
        except Exception as e:
            QMessageBox.warning(self, self.t("error"), f"{self.t('tr_cant_open')}\n{e}")
            return
        self.page.blockSignals(True)
        self.page.setRange(1, max(1, n))
        self.page.setValue(page + 1)
        self.page.setEnabled(n > 1)
        self.page.blockSignals(False)
        self._set_source(src)
        self.state["path"] = path
        self.analyse()

    def _page_changed(self, v):
        path = self.state.get("path")
        if path and path.lower().endswith(".pdf"):
            self.load_path(path, v - 1)

    def paste(self):
        img = QGuiApplication.clipboard().image()
        if img.isNull():
            QMessageBox.information(self, self.t("app"), self.t("tr_no_clip"))
            return
        self.state["path"] = ""
        self._set_source(trace.from_array(qimage_to_array(img)))
        self.page.setEnabled(False)
        self.analyse()

    def _set_source(self, src):
        self.state.update(full=src, src=src, analysis=None, line=None, types={})
        self.preview_plan = None
        self.apply_btn.setEnabled(False)
        self.table.setRowCount(0)
        self._show_source()

    def _show_source(self):
        src = self.state["src"]
        path = self.state.get("path") or self.t("tr_clipboard")
        w, h = src.size
        info = f"{os.path.basename(path)} · {w}×{h} px"
        if src.pages > 1:
            info += f" · {self.t('tr_page')} {src.page + 1}/{src.pages}"
        if src.texts and src.texts[0].source == "pdf":
            info += f" · {len(src.texts)} {self.t('tr_pdf_words')}"
        self.file_label.setText(info)
        self._draw_overlay(fit=True)

    def _cropped(self, r: QRectF):
        self.crop_btn.setChecked(False)
        full = self.state["full"]
        ox, oy = self.state.get("crop_origin", (0, 0))
        x0, y0 = ox + r.left(), oy + r.top()
        self.state["crop_origin"] = (int(max(0, x0)), int(max(0, y0)))
        self.state["src"] = full.crop(x0, y0, ox + r.right(), oy + r.bottom())
        self.state["analysis"] = None
        self._show_source()
        self.analyse()

    def reset_crop(self):
        if self.state.get("full") is not None:
            self.state["src"] = self.state["full"]
            self.state["crop_origin"] = (0, 0)
            self.state["analysis"] = None
            self._show_source()
            self.analyse()

    # ------------------------------------------------------------ analysis
    def analyse(self):
        src = self.state.get("src")
        if src is None:
            return
        self._save()
        import copy
        work = copy.copy(src)
        work.texts = [tk for tk in src.texts if tk.source == "pdf"]    # OCR is redone on the current crop
        opts = dict(ocr_engine=self.ocr.currentData(), wall_style=self.style.currentData(),
                    wall_px=float(self.wall_px.value()), door_gap=self.door_gap.value())
        self.req += 1
        self.flag = {"cancel": False}
        self.read_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)
        self.progress.setVisible(True)
        self.progress.setValue(0)
        self.status.setText(self.t("tr_working"))
        QThreadPool.globalInstance().start(_ReadTask(self.req, work, opts, self.sig, self.flag))

    def _on_progress(self, req, pct):
        if req == self.req:
            self.progress.setValue(pct)

    def _on_done(self, req, a, err):
        if req != self.req:
            return
        self.read_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        self.progress.setVisible(False)
        if a is None:
            self.status.setText(f"⚠ {self.t('error')}: {err}")
            return
        self.state["analysis"] = a
        self.state["types"] = {}
        self._after_analysis()

    def _after_analysis(self, restore=False):
        a = self.state["analysis"]
        dpx = a.t_int
        self.read_info.setText(self.t("tr_read_info").format(
            rooms=len(a.regions), words=len(a.texts), wall=f"{dpx:.0f}", ext=f"{a.t_ext:.0f}",
            style=self.t("tr_style_" + a.style), angle=f"{a.angle:.1f}"))
        mode, res = trace.auto_scale(a, self.door_m.value())
        self.state["auto"] = res
        self.mode_group.blockSignals(True)
        if restore and self.state.get("mode", -1) >= 0:
            self.mode_group.button(self.state["mode"]).setChecked(True)
        else:
            {"dims": self.r_dims, "door": self.r_door}.get(mode, self.r_line).setChecked(True)
        self.mode_group.blockSignals(False)
        if not a.regions:
            self.status.setText(self.t("tr_no_rooms"))
        elif mode == "none" and not restore:
            self.status.setText(self.t("tr_need_scale"))
        else:
            self.status.setText(self.t("tr_ready"))
        self._fill_table()
        self._scale_inputs_changed()
        self._draw_overlay(fit=not restore)

    # ------------------------------------------------------------ scale
    def _line_tool(self, on):
        self.view.set_mode("line" if on else "pick")
        if on:
            self.r_line.setChecked(True)
            self.status.setText(self.t("tr_line_hint"))

    def _line_drawn(self, a: QPointF, b: QPointF):
        self.line_btn.setChecked(False)
        self.state["line"] = (a.x(), a.y(), b.x(), b.y())
        self.r_line.setChecked(True)
        self._scale_inputs_changed()
        self._draw_overlay()
        self.line_m.setFocus()
        self.line_m.selectAll()

    def scale(self) -> tuple[float | None, str]:
        """(metres per pixel, explanation)."""
        a = self.state.get("analysis")
        mode = self.mode_group.checkedId()
        if mode == 0 and a is not None:
            r = trace.from_dimensions(a)
            if r.scale:
                used = ", ".join(sorted({v.text for v in r.agreeing}))[:80]
                return r.scale, self.t("tr_dims_info").format(n=r.support, used=used)
            return None, self.t("tr_no_dims")
        if mode == 1 and a is not None:
            r = trace.from_door(a, self.door_m.value())
            if r.scale:
                return r.scale, self.t("tr_door_info").format(n=r.support)
            return None, self.t("tr_no_doors")
        if mode == 2:
            ln = self.state.get("line")
            if not ln:
                return None, self.t("tr_line_hint")
            px = math.hypot(ln[2] - ln[0], ln[3] - ln[1])
            return trace.from_line(px, self.line_m.value()), self.t("tr_line_info").format(px=f"{px:.0f}")
        if mode == 3:
            return 1.0 / self.ppm.value(), ""
        return None, ""

    def _scale_inputs_changed(self, *_):
        if self.state.get("analysis") is not None and self.table.rowCount():
            self._save()                           # the page can be rebuilt any time (language switch)
        s, why = self.scale()
        a = self.state.get("analysis")
        if s and a is not None:
            x0, y0, x1, y1 = a.bbox
            self.scale_info.setText(f"<b>1 m = {1 / s:.1f} px</b> · {self.t('tr_building')} "
                                    f"{(x1 - x0) * s:.2f} × {(y1 - y0) * s:.2f} m<br>{why}")
        else:
            self.scale_info.setText(f"<span style='color:{self.w.tokens['warn']}'>⚠ {why}</span>" if why else "")
        self._fill_areas()
        self.update_preview()

    # ------------------------------------------------------------ rooms
    def _types(self) -> dict[int, str]:
        out = {}
        for r in range(self.table.rowCount()):
            combo = self.table.cellWidget(r, 1)
            if combo is not None:
                out[int(self.table.item(r, 0).text())] = combo.currentData()
        return out

    def _fill_table(self):
        a = self.state["analysis"]
        s, _ = self.scale()
        rows = trace.room_rows(a, s)
        saved = self.state.get("types") or {}
        self.table.blockSignals(True)
        self.table.setRowCount(len(rows))
        for i, d in enumerate(rows):
            it = QTableWidgetItem(str(d["label"]))
            it.setFlags(it.flags() & ~Qt.ItemIsEditable)
            it.setBackground(QColor(PALETTE[(d["label"] - 1) % len(PALETTE)]))
            self.table.setItem(i, 0, it)
            combo = QComboBox()
            for k in ROOM_TYPES:
                combo.addItem(room_name(k, self.lang), k)
            combo.setCurrentIndex(max(0, combo.findData(saved.get(d["label"], d["type"]))))
            combo.currentIndexChanged.connect(self._types_changed)
            self.table.setCellWidget(i, 1, combo)
            for col in (2, 3):
                it = QTableWidgetItem("")
                it.setFlags(it.flags() & ~Qt.ItemIsEditable)
                self.table.setItem(i, col, it)
            self.table.item(i, 3).setText(d["text"])
        self.table.blockSignals(False)
        self._fill_areas()

    def _fill_areas(self):
        a = self.state.get("analysis")
        if a is None:
            return
        s, _ = self.scale()
        for i, r in enumerate(a.regions[:self.table.rowCount()]):
            self.table.item(i, 2).setText(f"{r.area * s * s:.1f} m²" if s else "—")

    def _types_changed(self, *_):
        self.state["types"] = self._types()
        self._draw_overlay()
        self.update_preview()

    def _row_selected(self):
        r = self.table.currentRow()
        a = self.state.get("analysis")
        if a is None or r < 0 or r >= len(a.regions):
            return
        self.state["selected"] = a.regions[r].label
        self._draw_overlay()

    def _picked(self, p: QPointF):
        a = self.state.get("analysis")
        if a is None:
            return
        x, y = int(p.x()), int(p.y())
        h, w = a.labels.shape
        if 0 <= x < w and 0 <= y < h and a.labels[y, x] > 0:
            row = int(a.labels[y, x]) - 1
            self.table.selectRow(row)
            combo = self.table.cellWidget(row, 1)
            if combo is not None:
                combo.setFocus()
                combo.showPopup()

    # ------------------------------------------------------------ drawing
    def _draw_overlay(self, *_, fit=False):
        sc = self.iscene
        sc.clear()
        src = self.state.get("src")
        if src is None:
            return
        a = self.state.get("analysis")
        base = to_qimage(a.gray if a is not None else src.gray)
        sc.addItem(QGraphicsPixmapItem(QPixmap.fromImage(base)))
        if a is not None:
            h, w = a.labels.shape
            rgba = np.zeros((h, w, 4), np.uint8)
            if self.show_rooms.isChecked() and a.regions:
                cols = np.zeros((len(a.regions) + 1, 4), np.uint8)
                for r in a.regions:
                    c = QColor(PALETTE[(r.label - 1) % len(PALETTE)])
                    alpha = 150 if self.state.get("selected") == r.label else 85
                    cols[r.label] = (c.red(), c.green(), c.blue(), alpha)
                rgba[:] = cols[a.labels]
            if self.show_walls.isChecked():
                rgba[a.walls] = (224, 49, 49, 150)
            img = QImage(rgba.data, w, h, 4 * w, QImage.Format_RGBA8888).copy()
            item = QGraphicsPixmapItem(QPixmap.fromImage(img))
            item.setZValue(2)
            sc.addItem(item)
            pen = QPen(QColor("#1c7ed6"))
            pen.setCosmetic(True)
            pen.setWidth(2)
            x0, y0, x1, y1 = a.bbox
            sc.addRect(QRectF(x0, y0, x1 - x0, y1 - y0), pen).setZValue(3)
            types = self._types()
            for r in a.regions:
                rt = types.get(r.label)
                txt = f"{r.label}" + (f" · {room_name(rt, self.lang)}" if rt else "")
                it = sc.addSimpleText(txt)
                f = it.font()
                f.setPointSizeF(max(8.0, min(40.0, math.sqrt(r.area) / 9)))
                f.setBold(True)
                it.setFont(f)
                br = it.boundingRect()
                it.setPos(r.centroid[0] - br.width() / 2, r.centroid[1] - br.height() / 2)
                it.setBrush(QBrush(QColor("#212529")))
                it.setZValue(5)
            if self.show_text.isChecked():
                tpen = QPen(QColor("#f08c00"))
                tpen.setCosmetic(True)
                for tk in a.texts:
                    x0, y0, x1, y1 = tk.box
                    sc.addRect(QRectF(x0, y0, x1 - x0, y1 - y0), tpen).setZValue(4)
        ln = self.state.get("line")
        if ln:
            pen = QPen(QColor("#e8590c"))
            pen.setCosmetic(True)
            pen.setWidth(3)
            sc.addLine(*ln, pen).setZValue(6)
        sc.setSceneRect(sc.itemsBoundingRect())
        if fit:
            self.view.fit()

    # ------------------------------------------------------------ result
    def options(self) -> trace.Options:
        return trace.Options(openings=self.openings.currentData(), snap=self.snap.value(),
                             walls_from_drawing=self.walls_drawn.isChecked(), furniture=self.furn.isChecked())

    def build(self):
        a = self.state.get("analysis")
        s, _ = self.scale()
        if a is None or not s or not a.regions:
            return None
        settings = dict(self.w.plan.settings) if self.w.plan is not None else None
        rules = self.w.panel.get_config().get("rules", "jordan") if hasattr(self.w, "panel") else "jordan"
        return trace.to_plan(a, s, self._types(), settings, rules, self.options())

    def update_preview(self, *_):
        if not hasattr(self, "pscene"):
            return
        try:
            plan = self.build()
        except Exception as e:
            plan = None
            self.status.setText(f"⚠ {self.t('error')}: {e}")
        self.preview_plan = plan
        self.apply_btn.setEnabled(plan is not None)
        self.pscene.set_plan(plan, self.w.label_lang, self.w.plan_colors, self.w.library)
        if plan is not None:
            self.pview.fit()
            n = len(plan.warnings)
            self.status.setText(self.t("tr_result").format(w=f"{plan.width:.2f}", d=f"{plan.depth:.2f}",
                                                           rooms=len(plan.rooms), net=f"{plan.net_area:.1f}",
                                                           warn=n))

    def _apply(self):
        if self.preview_plan is None:
            self.update_preview()
        if self.preview_plan is not None:
            self._save()
            self.applyRequested.emit(self.preview_plan)

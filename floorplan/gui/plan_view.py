"""Native Qt drawing of a Plan + the interactive view.

The scene is rebuilt from the Plan after every change (plans are small, so
this is fast and keeps drawing code in one place). Interaction (selecting,
dragging walls, measuring...) lives in gui/editor.py; the view only turns
mouse events into metre coordinates and forwards them.
"""

from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPainterPath, QPen, QPixmap, QPolygonF
from PySide6.QtWidgets import QGraphicsScene, QGraphicsSimpleTextItem, QGraphicsView

from ..blocks import BUILTIN, furniture_polylines, opening_polylines
from ..export.svg import _chain
from ..geometry import door_geometry, walls
from ..models import Plan
from .theme import PLAN

S = 100.0                      # scene px per metre
FONT_FAMILY = "Segoe UI"       # has Arabic on Windows; Qt falls back elsewhere


def P(x: float, y: float) -> QPointF:
    return QPointF(x * S, -y * S)


def to_m(p: QPointF) -> tuple[float, float]:
    return p.x() / S, -p.y() / S


class PlanScene(QGraphicsScene):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.colors = PLAN["light"]
        self.overlay_items = []
        self.setBackgroundBrush(QColor(self.colors["paper"]))

    # -- helpers --
    def _text(self, txt, px, bold=False, color=None, z=0):
        item = QGraphicsSimpleTextItem(txt)
        f = QFont(FONT_FAMILY)
        f.setPixelSize(max(6, int(px)))
        f.setBold(bold)
        item.setFont(f)
        item.setBrush(QColor(color or self.colors["text"]))
        item.setZValue(z)
        self.addItem(item)
        return item

    def _center_text(self, item, x, y):
        b = item.boundingRect()
        item.setPos(x - b.width() / 2, y - b.height() / 2)

    def _polylines(self, lines, pen, z=3):
        path = QPainterPath()
        for pl in lines:
            if len(pl) < 2:
                continue
            path.moveTo(P(*pl[0]))
            for pt in pl[1:]:
                path.lineTo(P(*pt))
        item = self.addPath(path, pen)
        item.setZValue(z)
        return item

    def _dim(self, a, b, off, orient):
        dim = QColor(self.colors["dim"])
        pen = QPen(dim, 1.6)
        if orient == "h":
            p0, p1 = P(a, off), P(b, off)
        else:
            p0, p1 = P(off, a), P(off, b)
        self.addLine(p0.x(), p0.y(), p1.x(), p1.y(), pen)
        for p in (p0, p1):
            self.addLine(p.x() - 7, p.y() + 7, p.x() + 7, p.y() - 7, QPen(dim, 2.4))
        t = self._text(f"{b - a:.2f}", 22, color=self.colors["text2"])
        mid = QPointF((p0.x() + p1.x()) / 2, (p0.y() + p1.y()) / 2)
        br = t.boundingRect()
        if orient == "h":
            t.setPos(mid.x() - br.width() / 2, mid.y() - br.height() - 2)
        else:
            t.setRotation(-90)
            t.setPos(mid.x() - br.height() - 2, mid.y() + br.width() / 2)

    def _scale_bar(self, x0, y0):
        """0-1-2-3-4-5 m bar with alternating fills."""
        c = self.colors
        ink = QColor(c["ink"])
        for i in range(5):
            r = QRectF(P(x0 + i, y0 + 0.12), P(x0 + i + 1, y0))
            self.addRect(r, QPen(ink, 1.2), QBrush(ink if i % 2 == 0 else QColor(c["paper"])))
        for v in (0, 1, 2, 5):
            t = self._text(str(v), 20, color=c["text2"])
            self._center_text(t, P(x0 + v, 0).x(), P(0, y0 - 0.2).y())
        t = self._text("m", 20, color=c["text2"])
        t.setPos(P(x0 + 5.15, 0).x(), P(0, y0 + 0.16).y())

    # -- main --
    def set_plan(self, plan: Plan | None, lang: str = "both", colors: dict | None = None,
                 library=None, selection=None, scale_bar: bool = True):
        self.clear()
        self.overlay_items = []
        if colors:
            self.colors = colors
        c = self.colors
        self.setBackgroundBrush(QColor(c["paper"]))
        if plan is None:
            return
        blocks = library.blocks if library else BUILTIN

        for r in plan.rooms:
            n = r.net
            self.addRect(QRectF(P(n.x0, n.y1), P(n.x1, n.y0)), Qt.NoPen,
                         QBrush(QColor(c["zones"].get(r.spec.zone, c["paper"]))))

        wall_path = QPainterPath()
        wall_path.setFillRule(Qt.OddEvenFill)
        for poly in walls(plan):
            for ring in [poly.exterior, *poly.interiors]:
                pts = [P(x, y) for x, y in ring.coords]
                wall_path.moveTo(pts[0])
                for p in pts[1:]:
                    wall_path.lineTo(p)
                wall_path.closeSubpath()
        self.addPath(wall_path, Qt.NoPen, QBrush(QColor(c["wall"]))).setZValue(1)

        ink = QColor(c["ink"])
        door_pen, swing_pen = QPen(ink, 3), QPen(ink, 1.6, Qt.DashLine)
        for o in plan.openings:
            g = o.gap_rect()
            block = blocks.get(o.block) if o.block else None
            if o.kind == "window":
                rect = QRectF(P(g.x0, g.y1), P(g.x1, g.y0))
                self.addRect(rect, QPen(ink, 1.5), QBrush(QColor(c["window"]))).setZValue(2)
                if block:
                    self._polylines(opening_polylines(block, o), QPen(QColor(c["glass"]), 2.2))
                    continue
                glass = QPen(QColor(c["glass"]), 2.5)
                mid = rect.center()
                if o.seg.orient == "h":
                    self.addLine(rect.left(), mid.y(), rect.right(), mid.y(), glass).setZValue(3)
                else:
                    self.addLine(mid.x(), rect.top(), mid.x(), rect.bottom(), glass).setZValue(3)
                continue
            if block:
                self._polylines(opening_polylines(block, o), door_pen)
                continue
            hinge, leaf, closed, w = door_geometry(o)
            ph, pl = P(*hinge), P(*leaf)
            self.addLine(ph.x(), ph.y(), pl.x(), pl.y(), door_pen).setZValue(3)
            a0 = math.atan2(leaf[1] - hinge[1], leaf[0] - hinge[0])
            a1 = math.atan2(closed[1] - hinge[1], closed[0] - hinge[0])
            da = (a1 - a0 + math.pi) % (2 * math.pi) - math.pi
            arc = QPainterPath(pl)
            for i in range(1, 17):
                a = a0 + da * i / 16
                arc.lineTo(P(hinge[0] + w * math.cos(a), hinge[1] + w * math.sin(a)))
            self.addPath(arc, swing_pen).setZValue(3)

        fpen = QPen(QColor(c["ink"]), 1.6)
        for f in plan.furniture:
            b = blocks.get(f.block)
            if b:
                self._polylines(furniture_polylines(b, f.x, f.y, f.rotation, f.scale), fpen, z=2)

        for r in plan.rooms:
            n = r.net
            names = {"ar": [r.spec.name_ar], "en": [r.spec.name_en]}.get(lang, [r.spec.name_ar, r.spec.name_en])
            if r.spec.type == "corridor":
                names = names[:1]
            longest = max(len(t) for t in names)
            px = max(11.0, min(30.0, n.w * S / (longest * 0.56)))
            lines = [(t, px, True, c["text"]) for t in names]
            if r.spec.type != "corridor":
                lines += [(f"{n.area:.1f} m²", px * 0.8, False, c["text2"]),
                          (f"{n.w:.2f} × {n.h:.2f}", px * 0.72, False, c["text2"])]
            total = sum(p * 1.3 for _, p, _, _ in lines)
            cx, cy = P(*n.center).x(), P(*n.center).y()
            y = cy - total / 2
            for t, p, bold, col in lines:
                item = self._text(t, p, bold, col, z=4)
                self._center_text(item, cx, y + p * 0.65)
                y += p * 1.3

        xs = _chain(plan, "front")
        for a, b in zip(xs, xs[1:]):
            self._dim(a, b, -0.55, "h")
        self._dim(0, plan.width, -1.15, "h")
        ys = _chain(plan, "left")
        for a, b in zip(ys, ys[1:]):
            self._dim(a, b, -0.55, "v")
        self._dim(0, plan.depth, -1.15, "v")
        front = self._text("▲  FRONT / الواجهة", 22, color=c["dim"])
        self._center_text(front, P(plan.width / 2, 0).x(), P(0, -1.75).y())
        if scale_bar:
            self._scale_bar(0.0, -2.35)
        if selection:
            self._draw_selection(plan, selection, blocks)
        self.setSceneRect(self.itemsBoundingRect().adjusted(-60, -60, 60, 60))

    def _draw_selection(self, plan, sel, blocks):
        from ..blocks import furniture_footprint
        col = QColor(self.colors["select"])
        pen = QPen(col, 5)
        fill = QColor(col)
        fill.setAlpha(45)
        kind, ref = sel
        if kind == "room":
            r = next((r for r in plan.rooms if r.id == ref), None)
            if r:
                self.addRect(QRectF(P(r.net.x0, r.net.y1), P(r.net.x1, r.net.y0)), pen, QBrush(fill)).setZValue(5)
        elif kind == "wall":
            te, ti = plan.settings["exterior_wall"], plan.settings["interior_wall"]
            t = te if ref.side else ti
            c = ref.coord + {"left": -te / 2, "bottom": -te / 2, "right": te / 2, "top": te / 2}.get(ref.side, 0)
            if ref.orient == "v":
                rect = QRectF(P(c - t / 2, ref.s1), P(c + t / 2, ref.s0))
            else:
                rect = QRectF(P(ref.s0, c + t / 2), P(ref.s1, c - t / 2))
            self.addRect(rect, pen, QBrush(fill)).setZValue(5)
        elif kind == "opening" and ref < len(plan.openings):
            g = plan.openings[ref].gap_rect()
            self.addRect(QRectF(P(g.x0 - 0.05, g.y1 + 0.05), P(g.x1 + 0.05, g.y0 - 0.05)), pen, QBrush(fill)).setZValue(5)
        elif kind == "furniture" and ref < len(plan.furniture):
            f = plan.furniture[ref]
            b = blocks.get(f.block)
            if b:
                poly = QPolygonF([P(x, y) for x, y in furniture_footprint(b, f)])
                self.addPolygon(poly, pen, QBrush(fill)).setZValue(5)

    # -- overlay (measurements, rubber bands) --
    def clear_overlay(self):
        for it in self.overlay_items:
            if it.scene() is self:
                self.removeItem(it)
        self.overlay_items = []

    def draw_overlay(self, shapes: list):
        """shapes: dicts {"pts": [(x, y), ...], "closed": bool, "labels": [(x, y, text)], "snap": (x, y)}"""
        self.clear_overlay()
        col = QColor("#e8590c")
        for sh in shapes:
            pts = sh.get("pts", [])
            if len(pts) >= 2:
                path = QPainterPath(P(*pts[0]))
                for pt in pts[1:]:
                    path.lineTo(P(*pt))
                if sh.get("closed"):
                    path.closeSubpath()
                    fill = QColor(col)
                    fill.setAlpha(40)
                    it = self.addPath(path, QPen(col, 3, Qt.DashLine), QBrush(fill))
                else:
                    it = self.addPath(path, QPen(col, 3, Qt.DashLine))
                it.setZValue(10)
                self.overlay_items.append(it)
            for x, y in pts:
                it = self.addEllipse(x * S - 5, -y * S - 5, 10, 10, QPen(col, 2), QBrush(QColor("#ffffff")))
                it.setZValue(11)
                self.overlay_items.append(it)
            if sh.get("snap"):
                x, y = sh["snap"]
                it = self.addRect(x * S - 9, -y * S - 9, 18, 18, QPen(QColor("#2b8a3e"), 2.5))
                it.setZValue(12)
                self.overlay_items.append(it)
            for x, y, txt in sh.get("labels", []):
                t = self._text(txt, 24, True, "#ffffff", z=13)
                b = t.boundingRect()
                bg = self.addRect(QRectF(0, 0, b.width() + 12, b.height() + 4), Qt.NoPen, QBrush(col))
                bg.setZValue(12.5)
                bg.setPos(x * S - b.width() / 2 - 6, -y * S - b.height() / 2 - 2)
                t.setPos(x * S - b.width() / 2, -y * S - b.height() / 2)
                self.overlay_items += [t, bg]


class PlanView(QGraphicsView):
    """Forwards mouse/keyboard to `handler` (the Editor) in metres. Left drag
    pans when the handler does not want the event; middle/right drag always pans."""
    zoomChanged = Signal()

    def __init__(self, scene: PlanScene, parent=None):
        super().__init__(scene, parent)
        self.handler = None
        self.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing | QPainter.SmoothPixmapTransform)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setBackgroundBrush(QColor("#eceef1"))
        self.setLayoutDirection(Qt.LeftToRight)     # drawings never mirror
        self.setMouseTracking(True)
        self._pan = None

    def set_canvas(self, color: str):
        self.setBackgroundBrush(QColor(color))

    def tolerance(self, px: float = 10) -> float:
        """Screen pixels -> metres at the current zoom."""
        return px / (S * max(self.transform().m11(), 1e-6))

    def _m(self, e):
        return to_m(self.mapToScene(e.position().toPoint()))

    def mousePressEvent(self, e):
        if e.button() in (Qt.MiddleButton, Qt.RightButton) or (
                e.button() == Qt.LeftButton and not (self.handler and self.handler.press(*self._m(e), e.modifiers(), self.tolerance()))):
            if e.button() == Qt.RightButton and self.handler and self.handler.cancel_point():
                return
            self._pan = e.position()
            self.setCursor(Qt.ClosedHandCursor)
            return
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if self._pan is not None:
            d = e.position() - self._pan
            self._pan = e.position()
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - int(d.x()))
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - int(d.y()))
            return
        if self.handler:
            cursor = self.handler.move(*self._m(e), e.modifiers(), self.tolerance(), e.buttons() & Qt.LeftButton)
            self.setCursor(cursor if cursor is not None else Qt.ArrowCursor)

    def mouseReleaseEvent(self, e):
        if self._pan is not None:
            self._pan = None
            self.setCursor(Qt.ArrowCursor)
            return
        if self.handler and e.button() == Qt.LeftButton:
            self.handler.release(*self._m(e))

    def mouseDoubleClickEvent(self, e):
        if self.handler and e.button() == Qt.LeftButton:
            self.handler.double(*self._m(e))

    def keyPressEvent(self, e):
        if not (self.handler and self.handler.key(e.key(), e.modifiers())):
            super().keyPressEvent(e)

    def wheelEvent(self, e):
        f = 1.15 if e.angleDelta().y() > 0 else 1 / 1.15
        self.scale(f, f)
        self.zoomChanged.emit()

    def fit(self):
        if self.scene().items():
            self.fitInView(self.scene().sceneRect(), Qt.KeepAspectRatio)
            self.zoomChanged.emit()

    # -- drawing scale on screen --
    def screen_scale(self) -> float:
        """N of 1:N for what is on screen right now."""
        px_per_m = S * self.transform().m11()
        dpi = self.logicalDpiX() or 96
        return dpi / 0.0254 / max(px_per_m, 1e-9)

    def set_screen_scale(self, n: float):
        cur = self.screen_scale()
        f = cur / n
        self.scale(f, f)
        self.zoomChanged.emit()


def render_pixmap(plan: Plan, w: int, h: int, lang: str = "both", colors: dict | None = None,
                  library=None) -> QPixmap:
    """Exports use the light (printable) colours unless told otherwise."""
    colors = colors or PLAN["light"]
    scene = PlanScene()
    scene.set_plan(plan, lang, colors, library)
    pm = QPixmap(w, h)
    pm.fill(QColor(colors["paper"]))
    painter = QPainter(pm)
    painter.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing)
    scene.render(painter, QRectF(0, 0, w, h), scene.sceneRect(), Qt.KeepAspectRatio)
    painter.end()
    return pm

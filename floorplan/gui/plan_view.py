"""Native Qt drawing of a Plan (zoomable, rooms are hoverable/selectable)."""

from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (QGraphicsItem, QGraphicsRectItem, QGraphicsScene,
                               QGraphicsSimpleTextItem, QGraphicsView)

from ..export.svg import ZONE_FILL, _chain
from ..geometry import door_geometry, walls
from ..models import Plan

S = 100.0                      # scene px per metre
WALL = QColor("#26282c")
INK = QColor("#3a3d42")
DIM = QColor("#7a7f87")
SELECT = QColor("#2f6fd6")
FONT_FAMILY = "Segoe UI"       # has Arabic on Windows; Qt falls back elsewhere


def P(x: float, y: float) -> QPointF:
    return QPointF(x * S, -y * S)


class RoomItem(QGraphicsRectItem):
    def __init__(self, room, on_click):
        n = room.net
        super().__init__(QRectF(P(n.x0, n.y1), P(n.x1, n.y0)))
        self.room, self.on_click = room, on_click
        self.base = QColor(ZONE_FILL.get(room.spec.zone, "#eeeeee"))
        self.setBrush(self.base)
        self.setPen(Qt.NoPen)
        self.setAcceptHoverEvents(True)
        self.setCursor(Qt.PointingHandCursor)
        self.selected = False

    def set_selected(self, on: bool):
        self.selected = on
        self.setPen(QPen(SELECT, 6) if on else Qt.NoPen)

    def hoverEnterEvent(self, e):
        self.setBrush(self.base.darker(108))

    def hoverLeaveEvent(self, e):
        self.setBrush(self.base)

    def mousePressEvent(self, e):
        self.on_click(self.room.id)
        super().mousePressEvent(e)


class PlanScene(QGraphicsScene):
    roomClicked = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.room_items: dict[str, RoomItem] = {}
        self.setBackgroundBrush(QColor("#ffffff"))

    # -- helpers --
    def _text(self, txt, px, bold=False, color="#22252a"):
        item = QGraphicsSimpleTextItem(txt)
        f = QFont(FONT_FAMILY)
        f.setPixelSize(max(6, int(px)))
        f.setBold(bold)
        item.setFont(f)
        item.setBrush(QColor(color))
        self.addItem(item)
        return item

    def _center_text(self, item, x, y):
        b = item.boundingRect()
        item.setPos(x - b.width() / 2, y - b.height() / 2)

    def _dim(self, a, b, off, orient):
        pen = QPen(DIM, 1.6)
        if orient == "h":
            p0, p1 = P(a, off), P(b, off)
        else:
            p0, p1 = P(off, a), P(off, b)
        self.addLine(p0.x(), p0.y(), p1.x(), p1.y(), pen)
        for p in (p0, p1):
            self.addLine(p.x() - 7, p.y() + 7, p.x() + 7, p.y() - 7, QPen(DIM, 2.4))
        t = self._text(f"{b - a:.2f}", 22, color="#4a4f57")
        mid = QPointF((p0.x() + p1.x()) / 2, (p0.y() + p1.y()) / 2)
        br = t.boundingRect()
        if orient == "h":
            t.setPos(mid.x() - br.width() / 2, mid.y() - br.height() - 2)
        else:
            t.setRotation(-90)
            t.setPos(mid.x() - br.height() - 2, mid.y() + br.width() / 2)

    # -- main --
    def set_plan(self, plan: Plan | None, lang: str = "both"):
        self.clear()
        self.room_items = {}
        if plan is None:
            return
        for r in plan.rooms:
            item = RoomItem(r, self.roomClicked.emit)
            self.addItem(item)
            self.room_items[r.id] = item

        wall_path = QPainterPath()
        wall_path.setFillRule(Qt.OddEvenFill)
        for poly in walls(plan):
            for ring in [poly.exterior, *poly.interiors]:
                pts = [P(x, y) for x, y in ring.coords]
                wall_path.moveTo(pts[0])
                for p in pts[1:]:
                    wall_path.lineTo(p)
                wall_path.closeSubpath()
        self.addPath(wall_path, Qt.NoPen, QBrush(WALL))

        door_pen, swing_pen = QPen(INK, 3), QPen(INK, 1.6, Qt.DashLine)
        for o in plan.openings:
            g = o.gap_rect()
            if o.kind == "window":
                rect = QRectF(P(g.x0, g.y1), P(g.x1, g.y0))
                self.addRect(rect, QPen(INK, 1.5), QBrush(QColor("#ffffff")))
                glass = QPen(QColor("#4a7fb5"), 2.5)
                c = rect.center()
                if o.seg.orient == "h":
                    self.addLine(rect.left(), c.y(), rect.right(), c.y(), glass)
                else:
                    self.addLine(c.x(), rect.top(), c.x(), rect.bottom(), glass)
                continue
            hinge, leaf, closed, w = door_geometry(o)
            ph, pl = P(*hinge), P(*leaf)
            self.addLine(ph.x(), ph.y(), pl.x(), pl.y(), door_pen)
            a0 = math.atan2(leaf[1] - hinge[1], leaf[0] - hinge[0])
            a1 = math.atan2(closed[1] - hinge[1], closed[0] - hinge[0])
            da = (a1 - a0 + math.pi) % (2 * math.pi) - math.pi
            arc = QPainterPath(pl)
            for i in range(1, 17):
                a = a0 + da * i / 16
                arc.lineTo(P(hinge[0] + w * math.cos(a), hinge[1] + w * math.sin(a)))
            self.addPath(arc, swing_pen)

        for r in plan.rooms:
            n = r.net
            names = {"ar": [r.spec.name_ar], "en": [r.spec.name_en]}.get(lang, [r.spec.name_ar, r.spec.name_en])
            if r.spec.type == "corridor":
                names = names[:1]
            longest = max(len(t) for t in names)
            px = max(11.0, min(30.0, n.w * S / (longest * 0.56)))
            lines = [(t, px, True, "#22252a") for t in names]
            if r.spec.type != "corridor":
                lines += [(f"{n.area:.1f} m²", px * 0.8, False, "#555a62"),
                          (f"{n.w:.2f} × {n.h:.2f}", px * 0.72, False, "#6a6f77")]
            total = sum(p * 1.3 for _, p, _, _ in lines)
            cx, cy = P(*n.center).x(), P(*n.center).y()
            y = cy - total / 2
            for t, p, bold, col in lines:
                item = self._text(t, p, bold, col)
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
        front = self._text("▲  FRONT / الواجهة", 22, color="#666b73")
        self._center_text(front, P(plan.width / 2, 0).x(), P(0, -1.75).y())
        self.setSceneRect(self.itemsBoundingRect().adjusted(-60, -60, 60, 60))

    def select_room(self, room_id: str | None):
        for rid, item in self.room_items.items():
            item.set_selected(rid == room_id)


class PlanView(QGraphicsView):
    def __init__(self, scene: PlanScene, parent=None):
        super().__init__(scene, parent)
        self.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing | QPainter.SmoothPixmapTransform)
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setBackgroundBrush(QColor("#eceef1"))
        self.setLayoutDirection(Qt.LeftToRight)     # drawings never mirror

    def wheelEvent(self, e):
        f = 1.15 if e.angleDelta().y() > 0 else 1 / 1.15
        self.scale(f, f)

    def fit(self):
        if self.scene().items():
            self.fitInView(self.scene().sceneRect(), Qt.KeepAspectRatio)


def render_pixmap(plan: Plan, w: int, h: int, lang: str = "both") -> QPixmap:
    scene = PlanScene()
    scene.set_plan(plan, lang)
    pm = QPixmap(w, h)
    pm.fill(QColor("#ffffff"))
    painter = QPainter(pm)
    painter.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing)
    scene.render(painter, QRectF(0, 0, w, h), scene.sceneRect(), Qt.KeepAspectRatio)
    painter.end()
    return pm

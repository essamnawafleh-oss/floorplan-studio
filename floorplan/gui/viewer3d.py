"""In-app 3D viewer.

A small software renderer (painter's algorithm with QPainter) so it works on
every PC without OpenGL drivers. Walls are cut into narrow strips and floors
are drawn first, which keeps the depth ordering right for building models.
Left drag: orbit · right/middle drag: pan · wheel: zoom.
"""

from __future__ import annotations

import math
import os
import tempfile

import numpy as np
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QBrush, QColor, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import (QCheckBox, QDialog, QHBoxLayout, QLabel, QPushButton, QSlider, QVBoxLayout,
                               QWidget)

from ..blocks import furniture_footprint
from ..geometry import rect_poly, walls
from ..models import Plan, Rect
from .strings import tr

WALL = (236, 233, 227)
GLASS = (140, 190, 230)
FURN = (186, 160, 128)
ZONES = {"public": (225, 200, 160), "service": (196, 214, 196), "private": (196, 206, 226), "circulation": (220, 220, 214)}


class Mesh:
    def __init__(self):
        self.polys: list[np.ndarray] = []   # each (k, 3)
        self.colors: list[tuple] = []
        self.alpha: list[int] = []
        self.layer: list[int] = []          # 0 = floor (drawn first), 1 = everything else

    def add(self, pts, color, alpha=255, layer=1):
        self.polys.append(np.asarray(pts, dtype=float))
        self.colors.append(color)
        self.alpha.append(alpha)
        self.layer.append(layer)

    def box(self, r: Rect, z0, z1, color, alpha=255):
        x0, y0, x1, y1 = r.x0, r.y0, r.x1, r.y1
        self.add([(x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)], color, alpha)
        self.add([(x0, y0, z0), (x0, y1, z0), (x1, y1, z0), (x1, y0, z0)], color, alpha)
        for a, b in (((x0, y0), (x1, y0)), ((x1, y0), (x1, y1)), ((x1, y1), (x0, y1)), ((x0, y1), (x0, y0))):
            self.add([(a[0], a[1], z0), (b[0], b[1], z0), (b[0], b[1], z1), (a[0], a[1], z1)], color, alpha)

    def prism(self, pts2d, z0, z1, color, strip=0.6, alpha=255, cap=True):
        """Vertical faces of a closed 2D ring (split into strips) + optional top."""
        n = len(pts2d)
        for i in range(n):
            (ax, ay), (bx, by) = pts2d[i], pts2d[(i + 1) % n]
            length = math.hypot(bx - ax, by - ay)
            k = max(1, int(math.ceil(length / strip)))
            for j in range(k):
                t0, t1 = j / k, (j + 1) / k
                p0 = (ax + (bx - ax) * t0, ay + (by - ay) * t0)
                p1 = (ax + (bx - ax) * t1, ay + (by - ay) * t1)
                self.add([(p0[0], p0[1], z0), (p1[0], p1[1], z0), (p1[0], p1[1], z1), (p0[0], p0[1], z1)], color, alpha)
        if cap:
            self.add([(x, y, z1) for x, y in pts2d], color, alpha)


def build_mesh(plan: Plan, library=None, furniture: bool = True) -> Mesh:
    import trimesh
    m = Mesh()
    H = plan.settings["wall_height"]
    for r in plan.rooms:            # floors, split into 1 m tiles for better ordering
        n = r.net
        col = ZONES.get(r.spec.zone, (210, 210, 210))
        xs = np.linspace(n.x0, n.x1, max(2, int(math.ceil(n.w)) + 1))
        ys = np.linspace(n.y0, n.y1, max(2, int(math.ceil(n.h)) + 1))
        for i in range(len(xs) - 1):
            for j in range(len(ys) - 1):
                m.add([(xs[i], ys[j], 0), (xs[i + 1], ys[j], 0), (xs[i + 1], ys[j + 1], 0), (xs[i], ys[j + 1], 0)],
                      col, layer=0)
    for poly in walls(plan):
        for ring in [poly.exterior, *poly.interiors]:
            m.prism(list(ring.coords)[:-1], 0, H, WALL, cap=False)
        verts, faces = trimesh.creation.triangulate_polygon(poly)
        for f in faces:
            m.add([(verts[i][0], verts[i][1], H) for i in f], WALL)
    for o in plan.openings:
        g = o.gap_rect()
        if o.head < H:
            m.box(g, o.head, H, WALL)
        if o.kind == "window":
            if o.sill > 0:
                m.box(g, 0, o.sill, WALL)
            th = 0.02
            pane = (Rect(g.x0, o.seg.coord - th, g.x1, o.seg.coord + th) if o.seg.orient == "h"
                    else Rect(o.seg.coord - th, g.y0, o.seg.coord + th, g.y1))
            m.box(pane, o.sill, o.head, GLASS, alpha=120)
    if furniture and library:
        for f in plan.furniture:
            b = library.get(f.block)
            if b:
                m.prism(furniture_footprint(b, f), 0, b.height * f.scale if f.scale != 1 else b.height, FURN, strip=0.5)
    return m


class Viewer3D(QWidget):
    def __init__(self, plan: Plan, library=None, dark=False, parent=None):
        super().__init__(parent)
        self.plan, self.library, self.dark = plan, library, dark
        self.setMinimumSize(640, 420)
        self.show_furniture = True
        self.wall_scale = 1.0
        self.rebuild()
        self.reset()

    def rebuild(self):
        self.mesh = build_mesh(self.plan, self.library, self.show_furniture)
        H = self.plan.settings["wall_height"]
        if self.wall_scale != 1.0:      # cut-away: lower the walls to look inside
            for p in self.mesh.polys:
                p[:, 2] = np.minimum(p[:, 2], H * self.wall_scale)
        self.update()

    def reset(self):
        self.yaw, self.pitch = math.radians(-35), math.radians(42)
        self.dist = max(self.plan.width, self.plan.depth) * 1.6
        self.target = np.array([self.plan.width / 2, self.plan.depth / 2, 0.8])
        self.update()

    def top(self):
        self.yaw, self.pitch = 0.0, math.radians(89)
        self.update()

    # -- camera --
    def _basis(self):
        cp, sp, cy, sy = math.cos(self.pitch), math.sin(self.pitch), math.cos(self.yaw), math.sin(self.yaw)
        eye = self.target + self.dist * np.array([cp * sy, -cp * cy, sp])
        fwd = self.target - eye
        fwd /= np.linalg.norm(fwd)
        right = np.cross(fwd, [0, 0, 1])
        right /= max(np.linalg.norm(right), 1e-9)
        up = np.cross(right, fwd)
        return eye, fwd, right, up

    def _pack(self):
        """Group polygons by vertex count so projection runs vectorised."""
        groups = {}
        for i, poly in enumerate(self.mesh.polys):
            groups.setdefault(len(poly), []).append(i)
        self._groups = []
        for k, idx in groups.items():
            V = np.stack([self.mesh.polys[i] for i in idx])          # (n, k, 3)
            n = np.cross(V[:, 1] - V[:, 0], V[:, 2] - V[:, 0])
            norm = np.linalg.norm(n, axis=1)
            ok = norm > 1e-12
            n[ok] /= norm[ok][:, None]
            self._groups.append((np.array(idx)[ok], V[ok], n[ok]))
        self._alpha = np.array(self.mesh.alpha)
        self._layer = np.array(self.mesh.layer)
        self._rgb = np.array(self.mesh.colors, dtype=float)

    def paintEvent(self, e):
        if getattr(self, "_packed_for", None) is not self.mesh:
            self._pack()
            self._packed_for = self.mesh
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), QColor("#1b1f24") if self.dark else QColor("#eef1f4"))
        eye, fwd, right, up = self._basis()
        w, h = self.width(), self.height()
        f = 0.9 * min(w, h) / math.tan(math.radians(25))
        light = np.array([0.35, -0.55, 0.75])
        light /= np.linalg.norm(light)
        draw = []
        for idx, V, N in self._groups:
            rel = V - eye
            z = rel @ fwd                                   # (n, k)
            vis = (z > 0.05).all(axis=1)
            facing = np.einsum("ij,ij->i", N, eye - V[:, 0]) >= 0
            solid = (self._alpha[idx] == 255) & (self._layer[idx] == 1)
            vis &= facing | ~solid                          # cull back faces of solids
            if not vis.any():
                continue
            idx, rel, z, Nv, fac = idx[vis], rel[vis], z[vis], N[vis], facing[vis]
            Nv = np.where(fac[:, None], Nv, -Nv)
            x = (rel @ right) / z * f + w / 2
            y = -(rel @ up) / z * f + h / 2
            shade = 0.58 + 0.42 * np.clip(Nv @ light, 0, None)
            depth = -z.mean(axis=1)
            for j in range(len(idx)):
                draw.append((self._layer[idx[j]], depth[j], idx[j], x[j], y[j], shade[j]))
        draw.sort(key=lambda t: (t[0], t[1]))
        for layer, _, i, x, y, shade in draw:
            r, g, b = self._rgb[i] * shade
            c = QColor(int(r), int(g), int(b), int(self._alpha[i]))
            p.setPen(QPen(c, 0.8) if self._alpha[i] == 255 else Qt.NoPen)
            p.setBrush(QBrush(c))
            p.drawPolygon(QPolygonF([QPointF(px, py) for px, py in zip(x.tolist(), y.tolist())]))
        p.end()

    # -- mouse --
    def mousePressEvent(self, e):
        self._last = e.position()
        self._btn = e.button()

    def mouseMoveEvent(self, e):
        if not e.buttons():
            return
        d = e.position() - self._last
        self._last = e.position()
        if self._btn == Qt.LeftButton:
            self.yaw -= d.x() * 0.008
            self.pitch = min(math.radians(89), max(math.radians(5), self.pitch + d.y() * 0.008))
        else:
            _, _, right, up = self._basis()
            k = self.dist * 0.0015
            self.target = self.target - right * d.x() * k + up * d.y() * k
        self.update()

    def wheelEvent(self, e):
        self.dist *= 0.88 if e.angleDelta().y() > 0 else 1 / 0.88
        self.dist = min(max(self.dist, 2.0), 300.0)
        self.update()


class Viewer3DDialog(QDialog):
    def __init__(self, plan: Plan, library, lang: str, dark: bool, parent=None):
        super().__init__(parent)
        t = lambda k: tr(k, lang)
        self.plan, self.library = plan, library
        self.setWindowTitle(t("view3d"))
        self.resize(1100, 760)
        lay = QVBoxLayout(self)
        self.view = Viewer3D(plan, library, dark)
        lay.addWidget(self.view, 1)
        row = QHBoxLayout()
        for label, slot in ((t("v3_reset"), self.view.reset), (t("v3_top"), self.view.top),
                            (t("v3_external"), self.open_external)):
            b = QPushButton(label)
            b.clicked.connect(slot)
            row.addWidget(b)
        furn = QCheckBox(t("v3_furniture"))
        furn.setChecked(True)
        furn.toggled.connect(self._furniture)
        row.addWidget(furn)
        row.addWidget(QLabel(t("v3_walls")))
        self.cut = QSlider(Qt.Horizontal)
        self.cut.setRange(10, 100)
        self.cut.setValue(100)
        self.cut.setMaximumWidth(180)
        self.cut.valueChanged.connect(self._cut)
        row.addWidget(self.cut)
        row.addStretch(1)
        hint = QLabel(t("v3_hint"))
        hint.setObjectName("muted")
        row.addWidget(hint)
        lay.addLayout(row)

    def _furniture(self, on):
        self.view.show_furniture = on
        self.view.rebuild()

    def _cut(self, v):
        self.view.wall_scale = v / 100
        self.view.rebuild()

    def open_external(self):
        """Open the GLB in the default 3D app (Windows 3D Viewer, Blender...)."""
        from ..export import to_glb
        path = os.path.join(tempfile.gettempdir(), "floorplan_view.glb")
        to_glb(self.plan, path, self.library)
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
        QDesktopServices.openUrl(QUrl.fromLocalFile(path))

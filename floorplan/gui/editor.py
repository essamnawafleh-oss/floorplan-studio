"""Interactive editing + measuring on the plan view.

Tools: select (drag walls / openings / furniture), door, window, main_door,
block (place furniture), measure_len, measure_area. Every committed change
pushes an undo snapshot. Without edit mode only the measuring tools and room
selection are active.
"""

from __future__ import annotations

import math

from PySide6.QtCore import QObject, Qt, Signal

from .. import editing
from ..blocks import furniture_footprint
from ..models import Furniture, Plan

UNITS = {"m": (1.0, "m", 2), "cm": (100.0, "cm", 1), "mm": (1000.0, "mm", 0), "ft": (3.28084, "ft", 2)}
GRID = 0.05


def fmt_len(v: float, unit: str) -> str:
    k, sym, dec = UNITS[unit]
    return f"{v * k:.{dec}f} {sym}"


def fmt_area(v: float, unit: str) -> str:
    return f"{v * 10.7639:.2f} ft²" if unit == "ft" else f"{v:.2f} m²"


def _snap(v: float, on: bool) -> float:
    return round(v / GRID) * GRID if on else v


def _point_in_poly(x, y, pts) -> bool:
    inside = False
    j = len(pts) - 1
    for i in range(len(pts)):
        xi, yi = pts[i]
        xj, yj = pts[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi + 1e-12) + xi:
            inside = not inside
        j = i
    return inside


def polygon_area(pts) -> float:
    return abs(sum(x0 * y1 - x1 * y0 for (x0, y0), (x1, y1) in zip(pts, pts[1:] + pts[:1]))) / 2


class Editor(QObject):
    changed = Signal()            # geometry changed: redraw everything
    overlayChanged = Signal()     # only measurement / rubber band changed
    selectionChanged = Signal()
    message = Signal(str)

    def __init__(self, library, parent=None):
        super().__init__(parent)
        self.library = library
        self.plan: Plan | None = None
        self.enabled = False                # edit mode
        self.tool = "select"
        self.selection = None               # ("room", id) | ("wall", WallLine) | ("opening", i) | ("furniture", i)
        self.undo_stack: list[dict] = []
        self.redo_stack: list[dict] = []
        self.pending_block = None
        self.unit = "m"
        self.measures: list[dict] = []      # finished measurements
        self.points: list[tuple] = []       # measurement in progress
        self.cursor_pt = None
        self.snap_pt = None
        self._drag = None

    # -- state --
    def set_plan(self, plan: Plan | None, keep_history: bool = False):
        self.plan = plan
        if not keep_history:
            self.undo_stack.clear()
            self.redo_stack.clear()
        self.selection = None
        self.selectionChanged.emit()

    def set_tool(self, tool: str):
        self.tool = tool
        self.points = []
        self._drag = None
        self.overlayChanged.emit()

    def push_undo(self, snapshot: dict | None = None):
        self.undo_stack.append(snapshot or self.plan.to_dict())
        self.undo_stack = self.undo_stack[-100:]
        self.redo_stack.clear()

    def undo(self):
        if self.undo_stack and self.plan:
            self.redo_stack.append(self.plan.to_dict())
            self._restore(self.undo_stack.pop())

    def redo(self):
        if self.redo_stack and self.plan:
            self.undo_stack.append(self.plan.to_dict())
            self._restore(self.redo_stack.pop())

    def _restore(self, d):
        self.plan = Plan.from_dict(d)
        editing.refresh(self.plan)
        self.selection = None
        self.selectionChanged.emit()
        self.changed.emit()

    def apply(self, fn, select=None):
        """Run fn(plan) as one undoable edit."""
        if not self.plan:
            return
        snap = self.plan.to_dict()
        if fn(self.plan) is False:
            self.message.emit("✕")
            return
        editing.refresh(self.plan)
        self.push_undo(snap)
        if select is not None:
            self.selection = select
        self.selectionChanged.emit()
        self.changed.emit()

    # -- hit testing --
    def hit(self, x, y, tol):
        p = self.plan
        if not p:
            return None
        for i in range(len(p.furniture) - 1, -1, -1):
            b = self.library.get(p.furniture[i].block)
            if b and _point_in_poly(x, y, furniture_footprint(b, p.furniture[i])):
                return ("furniture", i)
        for i, o in enumerate(p.openings):
            g = o.gap_rect()
            if g.x0 - tol <= x <= g.x1 + tol and g.y0 - tol <= y <= g.y1 + tol:
                return ("opening", i)
        te, ti = p.settings["exterior_wall"], p.settings["interior_wall"]
        best = None
        for ln in editing.wall_lines(p):
            c = ln.coord + {"left": -te / 2, "bottom": -te / 2, "right": te / 2, "top": te / 2}.get(ln.side, 0)
            half = (te if ln.side else ti) / 2 + tol
            along, across = (y, x) if ln.orient == "v" else (x, y)
            if ln.s0 - tol <= along <= ln.s1 + tol and abs(across - c) <= half:
                dist = abs(across - c)
                if best is None or dist < best[0]:
                    best = (dist, ln)
        if best:
            return ("wall", best[1])
        for r in p.rooms:
            if r.rect.x0 <= x <= r.rect.x1 and r.rect.y0 <= y <= r.rect.y1:
                return ("room", r.id)
        return None

    def snap_point(self, x, y, tol, ortho_from=None):
        """Snap to room corners, opening ends and furniture corners."""
        p = self.plan
        best = None
        if p:
            cands = []
            for r in p.rooms:
                for rc in (r.net, r.rect):
                    cands += [(rc.x0, rc.y0), (rc.x1, rc.y0), (rc.x1, rc.y1), (rc.x0, rc.y1)]
            cands += [(0, 0), (p.width, 0), (p.width, p.depth), (0, p.depth)]
            for o in p.openings:
                g = o.gap_rect()
                cands += [(g.x0, g.y0), (g.x1, g.y0), (g.x1, g.y1), (g.x0, g.y1)]
            for f in p.furniture:
                b = self.library.get(f.block)
                if b:
                    cands += furniture_footprint(b, f)
            for cx, cy in cands:
                d = math.hypot(cx - x, cy - y)
                if d < tol * 1.5 and (best is None or d < best[0]):
                    best = (d, (cx, cy))
        if best:
            return best[1], True
        if ortho_from is not None:
            ox, oy = ortho_from
            return ((x, oy) if abs(x - ox) >= abs(y - oy) else (ox, y)), False
        return (x, y), False

    # -- events (called by PlanView; return True if handled) --
    def press(self, x, y, mods, tol) -> bool:
        if not self.plan:
            return False
        if self.tool in ("measure_len", "measure_area"):
            last = self.points[-1] if self.points else None
            pt, _ = self.snap_point(x, y, tol, last if mods & Qt.ShiftModifier else None)
            self.points.append(pt)
            self.overlayChanged.emit()
            return True
        if not self.enabled:
            h = self.hit(x, y, tol)
            if h and h[0] == "room":
                self.selection = h
                self.selectionChanged.emit()
                self.changed.emit()
            return False                                   # let the view pan
        if self.tool in ("door", "window", "main_door"):
            kind = self.tool
            self.apply(lambda p: editing.add_opening(p, kind, x, y) is not None,
                       select=("opening", len(self.plan.openings)))
            return True
        if self.tool == "block" and self.pending_block:
            b = self.library.get(self.pending_block)
            if b:
                fx, fy = _snap(x - b.width / 2, True), _snap(y - b.depth / 2, True)
                self.apply(lambda p: p.furniture.append(Furniture(b.id, fx, fy)),
                           select=("furniture", len(self.plan.furniture)))
            return True
        h = self.hit(x, y, tol)
        self.selection = h
        self.selectionChanged.emit()
        self.changed.emit()
        if h and h[0] in ("wall", "opening", "furniture"):
            self._drag = dict(kind=h[0], ref=h[1], start=(x, y), base=self.plan.to_dict(), moved=False)
            return True
        return h is not None

    def move(self, x, y, mods, tol, left_down):
        self.cursor_pt = (x, y)
        if self.tool in ("measure_len", "measure_area"):
            last = self.points[-1] if self.points else None
            pt, snapped = self.snap_point(x, y, tol, last if mods & Qt.ShiftModifier else None)
            self.snap_pt = pt if snapped else None
            self.cursor_pt = pt
            self.overlayChanged.emit()
            return Qt.CrossCursor
        if not self.enabled or not self.plan:
            return None
        if self._drag and left_down:
            self._drag_to(x, y, not (mods & Qt.AltModifier))
            return Qt.ClosedHandCursor
        if self.tool in ("door", "window", "main_door", "block"):
            return Qt.CrossCursor
        h = self.hit(x, y, tol)
        if h and h[0] == "wall":
            return Qt.SizeHorCursor if h[1].orient == "v" else Qt.SizeVerCursor
        if h and h[0] in ("opening", "furniture"):
            return Qt.SizeAllCursor
        return None

    def _drag_to(self, x, y, snap):
        d = self._drag
        sx, sy = d["start"]
        plan = Plan.from_dict(d["base"])
        ok = True
        if d["kind"] == "wall":
            ln = d["ref"]
            delta = (x - sx) if ln.orient == "v" else (y - sy)
            new = ln.coord + _snap(delta, snap)       # move in 5 cm steps
            ok = editing.move_wall(plan, ln, new)
            if ok:
                d["ref_now"] = editing.WallLine(ln.orient, new, ln.s0, ln.s1, ln.side)
        elif d["kind"] == "opening":
            o = plan.openings[d["ref"]]
            along = (x if o.seg.orient == "h" else y)
            start_along = (sx if o.seg.orient == "h" else sy)
            centre = (o.seg.s0 + o.seg.s1) / 2 + along - start_along
            editing.move_opening(plan, o, _snap(centre, snap))
        else:
            f = plan.furniture[d["ref"]]
            f.x, f.y = _snap(f.x + x - sx, snap), _snap(f.y + y - sy, snap)
        if ok:
            editing.refresh(plan)
            self.plan = plan
            d["moved"] = True
            if d["kind"] == "wall":
                self.selection = ("wall", d["ref_now"])
            self.changed.emit()

    def release(self, x, y):
        d, self._drag = self._drag, None
        if d and d["moved"]:
            self.push_undo(d["base"])
            self.selectionChanged.emit()

    def double(self, x, y):
        if self.tool in ("measure_len", "measure_area") and len(self.points) >= 2:
            self.finish_measure()

    def cancel_point(self) -> bool:
        """Right click while measuring: finish (or drop) the current measurement."""
        if self.tool in ("measure_len", "measure_area") and self.points:
            if len(self.points) >= 2:
                self.finish_measure()
            else:
                self.points = []
                self.overlayChanged.emit()
            return True
        return False

    def key(self, key, mods) -> bool:
        if key == Qt.Key_Escape:
            if self.points:
                self.points = []
            elif self.tool != "select":
                self.set_tool("select")
            else:
                self.selection = None
                self.selectionChanged.emit()
                self.changed.emit()
            self.overlayChanged.emit()
            return True
        if key in (Qt.Key_Return, Qt.Key_Enter) and len(self.points) >= 2:
            self.finish_measure()
            return True
        if not self.enabled:
            return False
        if key == Qt.Key_Delete:
            self.delete_selection()
            return True
        if key == Qt.Key_R and self.selection and self.selection[0] == "furniture":
            self.rotate_furniture(90)
            return True
        if key == Qt.Key_Z and mods & Qt.ControlModifier:
            self.redo() if mods & Qt.ShiftModifier else self.undo()
            return True
        if key == Qt.Key_Y and mods & Qt.ControlModifier:
            self.redo()
            return True
        return False

    # -- commands --
    def delete_selection(self):
        sel = self.selection
        if not sel or sel[0] not in ("opening", "furniture"):
            return
        idx = sel[1]
        self.selection = None
        self.apply(lambda p: (p.openings if sel[0] == "opening" else p.furniture).pop(idx) and None)

    def rotate_furniture(self, deg):
        sel = self.selection
        if sel and sel[0] == "furniture":
            def rot(p):
                f = p.furniture[sel[1]]
                b = self.library.get(f.block)
                cx = sum(x for x, _ in furniture_footprint(b, f)) / 4
                cy = sum(y for _, y in furniture_footprint(b, f)) / 4
                f.rotation = (f.rotation + deg) % 360
                nx = sum(x for x, _ in furniture_footprint(b, f)) / 4
                ny = sum(y for _, y in furniture_footprint(b, f)) / 4
                f.x, f.y = f.x + cx - nx, f.y + cy - ny          # rotate about the centre
            self.apply(rot, select=sel)

    # -- measuring --
    def finish_measure(self):
        pts = list(self.points)
        if len(pts) >= 2:
            self.measures.append(dict(kind=self.tool, pts=pts))
            self.message.emit(self.describe(self.measures[-1]))
        self.points = []
        self.overlayChanged.emit()

    def clear_measures(self):
        self.measures, self.points = [], []
        self.overlayChanged.emit()

    def describe(self, m) -> str:
        pts = m["pts"]
        length = sum(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(pts, pts[1:]))
        if m["kind"] == "measure_area" and len(pts) >= 3:
            perim = length + math.hypot(pts[0][0] - pts[-1][0], pts[0][1] - pts[-1][1])
            return f"{fmt_area(polygon_area(pts), self.unit)}  ·  P = {fmt_len(perim, self.unit)}"
        return fmt_len(length, self.unit)

    def overlay(self) -> list[dict]:
        shapes = []
        live = list(self.points) + ([self.cursor_pt] if self.points and self.cursor_pt else [])
        for m in self.measures + ([dict(kind=self.tool, pts=live)] if live else []):
            pts = m["pts"]
            labels = []
            for a, b in zip(pts, pts[1:]):
                seg = math.hypot(b[0] - a[0], b[1] - a[1])
                if seg > 0.05:
                    labels.append(((a[0] + b[0]) / 2, (a[1] + b[1]) / 2, fmt_len(seg, self.unit)))
            closed = m["kind"] == "measure_area" and len(pts) >= 3
            if closed:
                cx, cy = sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts)
                labels = [(cx, cy, self.describe(m))]
            elif len(pts) > 2:
                labels.append((pts[-1][0], pts[-1][1] + 0.35, "Σ " + self.describe(m)))
            shapes.append(dict(pts=pts, closed=closed, labels=labels))
        if self.snap_pt and self.tool in ("measure_len", "measure_area"):
            shapes.append(dict(pts=[], snap=self.snap_pt))
        return shapes

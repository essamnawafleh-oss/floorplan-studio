"""Analysis + scale -> an ordinary editable Plan.

The plan model is rectangles tiling the inside of a W x D footprint, so the
wall centrelines found on the drawing become a grid, every grid cell takes the
room that covers it, and each room's cells are cut into as few rectangles as
possible. Openings are read off the drawing (gaps in the walls; a door swing
in front of a gap on an outside wall makes it the entrance) or planned by the
app's own rules."""

from __future__ import annotations

import os
from dataclasses import dataclass

import numpy as np

from ..i18n import room_name
from ..models import Opening, Plan, Rect, Room, RoomSpec, Segment
from ..openings import MIN_MARGIN, WET, _normal_sign, exterior_segments, plan_doors, plan_windows, shared_segment
from ..rules import get_rules
from .detect import Analysis, Region

OUT = -1


@dataclass
class Options:
    openings: str = "detected"        # "detected" | "auto"
    snap: float = 0.05                # round wall positions (m); 0 = off
    walls_from_drawing: bool = True   # wall thicknesses measured on the drawing
    furniture: bool = True            # trace furniture lines onto layer A-FURN


# --- room types ----------------------------------------------------------------------
def guess_types(a: Analysis, scale: float) -> dict[int, str]:
    """Room type per region: the words written in it, else its size and shape."""
    out = {}
    areas = {r.label: r.area * scale * scale for r in a.regions}
    order = sorted(areas, key=lambda k: -areas[k])
    for r in a.regions:
        if r.guess:
            out[r.label] = r.guess
            continue
        w, h = (r.bbox[2] - r.bbox[0]) * scale, (r.bbox[3] - r.bbox[1]) * scale
        short, long_ = min(w, h), max(w, h)
        ar = areas[r.label]
        if short < 1.7 and long_ / max(short, 0.1) > 2.2:
            out[r.label] = "corridor"
        elif ar < 3.2:
            out[r.label] = "guest_wc"
        elif ar < 7.0 and short < 2.7:
            out[r.label] = "bathroom"
        elif r.label == order[0]:
            out[r.label] = "living"
        else:
            out[r.label] = "bedroom"
    if "kitchen" not in out.values():                       # one kitchen: the most kitchen-sized of the rest
        rest = [r for r in a.regions if not r.guess and out[r.label] == "bedroom" and 7 <= areas[r.label] <= 20]
        if rest:
            out[min(rest, key=lambda r: abs(areas[r.label] - 12)).label] = "kitchen"
    return out


# --- grid ------------------------------------------------------------------------------
def _cluster(vals: list[tuple[float, float]], tol: float) -> list[float]:
    out = []
    for v, w in sorted(vals):
        if out and v - out[-1][0] / out[-1][1] <= tol:
            out[-1][0] += v * w
            out[-1][1] += w
        else:
            out.append([v * w, w])
    return [s / w for s, w in out]


def _snap(v: float, step: float) -> float:
    return round(round(v / step) * step, 4) if step else v


def _grid(a: Analysis, s: float, W: float, D: float, te: float, ti: float, snap: float):
    x0, y0, x1, y1 = a.bbox
    xs, ys = [], []
    for ln in a.lines:
        ln_len = (ln.s1 - ln.s0) * s
        if ln.orient == "v":
            xs.append(((ln.coord - x0) * s, ln_len))
        else:
            ys.append(((y1 - ln.coord) * s, ln_len))
    tol = max(ti, 0.12)
    gx = [_snap(v, snap) for v in _cluster(xs, tol) if te + 0.3 < v < W - te - 0.3]
    gy = [_snap(v, snap) for v in _cluster(ys, tol) if te + 0.3 < v < D - te - 0.3]
    gx = [te] + sorted(set(gx)) + [W - te]
    gy = [te] + sorted(set(gy)) + [D - te]
    return gx, gy


def _px(a, s, x, y):
    return a.bbox[0] + x / s, a.bbox[3] - y / s


def _cell_labels(a: Analysis, s: float, gx, gy, ti) -> np.ndarray:
    nx, ny = len(gx) - 1, len(gy) - 1
    lab = np.zeros((nx, ny), np.int32)
    H, Wd = a.labels.shape
    for i in range(nx):
        for j in range(ny):
            px0, py1 = _px(a, s, gx[i], gy[j])
            px1, py0 = _px(a, s, gx[i + 1], gy[j + 1])
            px0, px1 = int(max(0, px0)), int(min(Wd, px1 + 1))
            py0, py1 = int(max(0, py0)), int(min(H, py1 + 1))
            if px1 <= px0 or py1 <= py0:
                continue
            win = a.labels[py0:py1, px0:px1]
            vals = win[win > 0]
            area = win.size
            if len(vals) >= 0.12 * area:
                lab[i, j] = np.bincount(vals).argmax()
            elif a.silhouette[py0:py1, px0:px1].mean() < 0.5:
                lab[i, j] = OUT
    return lab


def _neighbours(i, j, nx, ny):
    for di, dj in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        if 0 <= i + di < nx and 0 <= j + dj < ny:
            yield i + di, j + dj


def _fill_unknown(lab, gx, gy):
    nx, ny = lab.shape
    for _ in range(nx + ny):
        todo = [(i, j) for i in range(nx) for j in range(ny) if lab[i, j] == 0]
        if not todo:
            break
        for i, j in todo:
            best, bl = None, 0.0
            for a, b in _neighbours(i, j, nx, ny):
                if lab[a, b] > 0:
                    edge = (gy[j + 1] - gy[j]) if a != i else (gx[i + 1] - gx[i])
                    if edge > bl:
                        best, bl = lab[a, b], edge
            if best is not None:
                lab[i, j] = best
    lab[lab == 0] = OUT


def _rectangles(mask: np.ndarray, gx, gy) -> list[tuple[int, int, int, int]]:
    """Cover a cell mask with rectangles (i0, j0, i1, j1 exclusive), biggest first."""
    m = mask.copy()
    out = []
    wx = np.diff(gx)
    wy = np.diff(gy)
    nx, ny = m.shape
    while m.any():
        best, area = None, -1.0
        for i0 in range(nx):
            col = np.ones(ny, bool)
            for i1 in range(i0, nx):
                col &= m[i1]
                if not col.any():
                    break
                width = wx[i0:i1 + 1].sum()
                j = 0
                while j < ny:
                    if not col[j]:
                        j += 1
                        continue
                    k = j
                    while k < ny and col[k]:
                        k += 1
                    ar = width * wy[j:k].sum()
                    if ar > area:
                        best, area = (i0, j, i1 + 1, k), ar
                    j = k
        i0, j0, i1, j1 = best
        m[i0:i1, j0:j1] = False
        out.append(best)
    return out


def _merge_slivers(lab, gx, gy, min_side=0.6, min_area=1.6):
    """Thin leftovers of a room (from slightly offset walls) join the neighbour."""
    nx, ny = lab.shape
    for _ in range(3):
        changed = False
        for L in [v for v in np.unique(lab) if v != 0]:
            pieces = _rectangles(lab == L, gx, gy)
            for k, (i0, j0, i1, j1) in enumerate(pieces):
                w, h = gx[i1] - gx[i0], gy[j1] - gy[j0]
                small = min(w, h) < min_side or w * h < min_area
                if not small or (k == 0 and L != OUT):
                    continue
                votes = {}
                for i in range(i0, i1):
                    for j in range(j0, j1):
                        for a, b in _neighbours(i, j, nx, ny):
                            o = lab[a, b]
                            if o != L and not (i0 <= a < i1 and j0 <= b < j1) and o != OUT:
                                edge = (gy[b + 1] - gy[b]) if a != i else (gx[a + 1] - gx[a])
                                votes[o] = votes.get(o, 0) + edge
                if votes:
                    lab[i0:i1, j0:j1] = max(votes, key=votes.get)
                    changed = True
        if not changed:
            break


# --- openings --------------------------------------------------------------------------
def _free_runs(a: Analysis, s: float, seg: Segment, band: float) -> list[tuple[float, float]]:
    """Spans (model coords along seg) where the drawing has no wall on this line."""
    n = max(2, int((seg.s1 - seg.s0) / s))
    t = np.linspace(seg.s0, seg.s1, n)
    offs = np.linspace(-band, band, 3)
    H, Wd = a.walls.shape
    hit = np.zeros(n)
    for o in offs:
        if seg.orient == "h":
            px, py = _px(a, s, t, seg.coord + o)
        else:
            px, py = _px(a, s, seg.coord + o, t)
        px = np.clip(np.asarray(px).astype(int), 0, Wd - 1)
        py = np.clip(np.asarray(py).astype(int), 0, H - 1)
        hit += a.walls[py, px]
    free = hit < 1.5
    out, k = [], 0
    while k < n:
        if free[k]:
            e = k
            while e < n and free[e]:
                e += 1
            half = (t[1] - t[0]) / 2
            out.append((max(seg.s0, t[k] - half), min(seg.s1, t[e - 1] + half), k == 0, e == n))
            k = e
        else:
            k += 1
    return out


def _swing(a: Analysis, s: float, seg: Segment, s0: float, s1: float, side: int, t: float,
           ink: np.ndarray) -> tuple[float, int]:
    """How much of a door swing arc is drawn in front of an opening: (share of
    the quarter circle found, hinge end 0/1)."""
    w = s1 - s0
    face = seg.coord + side * t / 2
    th = np.radians(np.linspace(8, 82, 24))
    H, Wd = ink.shape
    best = (0.0, 0)
    for hinge in (0, 1):
        along = (s0 + w * np.cos(th)) if hinge == 0 else (s1 - w * np.cos(th))
        across = face + side * w * np.sin(th)
        px, py = _px(a, s, along, across) if seg.orient == "h" else _px(a, s, across, along)
        px, py = np.asarray(px).astype(int), np.asarray(py).astype(int)
        ok = (px >= 0) & (px < Wd) & (py >= 0) & (py < H)
        score = float(ink[py[ok], px[ok]].sum()) / len(th)
        best = max(best, (score, hinge))
    return best


def _detected_openings(a, s, plan, rules, st):
    te, ti = st["exterior_wall"], st["interior_wall"]
    rooms = plan.rooms
    W, D = plan.width, plan.depth
    out: list[Opening] = []
    for i, ra in enumerate(rooms):
        for rb in rooms[i + 1:]:
            seg = shared_segment(ra.rect, rb.rect)
            if not seg or seg.length < 0.7:
                continue
            same = ra.spec.id.split("_")[0] == rb.spec.id.split("_")[0]
            runs = _free_runs(a, s, seg, ti / 4)
            if same:                                   # one drawn room cut in two: leave it open wide
                w = min(seg.length - 2 * MIN_MARGIN, 2.4)
                runs = [(seg.s0 + (seg.length - w) / 2, seg.s0 + (seg.length + w) / 2, False, False)]
            for r0, r1, at0, at1 in runs:
                w = r1 - r0
                if w < 0.55 or (w > 2.6 and not same):
                    continue
                w = min(w, seg.length - 2 * MIN_MARGIN, 1.6 if not same else 2.4)
                if w < 0.55:
                    continue
                mid = min(max((r0 + r1) / 2, seg.s0 + MIN_MARGIN + w / 2), seg.s1 - MIN_MARGIN - w / 2)
                span = Segment(seg.orient, seg.coord, mid - w / 2, mid + w / 2)
                into_room = rb if ra.spec.type in ("corridor", "entrance", "living", "salon", "dining") else ra
                if rb.spec.type in ("corridor", "entrance") and ra.spec.type not in ("corridor", "entrance"):
                    into_room = ra
                out.append(Opening("door", span, ti, (ra.id, rb.id), _normal_sign(span, into_room.rect)))
    import cv2
    ink = cv2.dilate(a.thin.astype(np.uint8), np.ones((5, 5), np.uint8)).astype(bool)
    exterior = []
    for r in rooms:
        for side, seg in exterior_segments(r.rect, W, D, te).items():
            inward = _normal_sign(seg, r.rect)
            for r0, r1, _a, _b in _free_runs(a, s, seg, te / 4):
                w = min(r1 - r0, seg.length - 2 * MIN_MARGIN)
                if w < 0.4:
                    continue
                mid = min(max((r0 + r1) / 2, seg.s0 + MIN_MARGIN + w / 2), seg.s1 - MIN_MARGIN - w / 2)
                span = Segment(seg.orient, seg.coord, mid - w / 2, mid + w / 2)
                sw, hinge = _swing(a, s, seg, span.s0, span.s1, inward, te, ink) if 0.75 <= w <= 1.8 else (0, 0)
                exterior.append((sw, r, span, inward, hinge))
    doors = [e for e in exterior if e[0] >= 0.6]
    public = ("entrance", "living", "salon", "corridor", "dining")
    doors.sort(key=lambda e: (e[1].spec.type in public, e[0]), reverse=True)
    for e in exterior:
        sw, r, span, inward, hinge = e
        if doors and e is doors[0]:
            out.append(Opening("main_door", span, te, (r.id,), inward, hinge))
        elif any(d is e for d in doors[1:]) and r.spec.type not in WET:
            out.append(Opening("main_door", span, te, (r.id,), inward, hinge))   # second outside door
        else:
            wet = r.spec.type in WET
            out.append(Opening("window", span, te, (r.id,), sill=st["wet_window_sill"] if wet else st["window_sill"],
                               head=st["window_head"]))
    if not any(o.kind == "main_door" for o in out):                       # no entrance found: the app picks one
        auto, _ = plan_doors(rooms, W, D, st, rules)
        main = [o for o in auto if o.kind == "main_door"]
        if main:
            m = main[0]
            out = [o for o in out if not (o.kind == "window" and o.seg.orient == m.seg.orient and
                                          abs(o.seg.coord - m.seg.coord) < 1e-6 and
                                          o.seg.s0 < m.seg.s1 and m.seg.s0 < o.seg.s1)]
            out.append(m)
    return out


# --- furniture lines ------------------------------------------------------------------------
def trace_furniture(a: Analysis, s: float, max_items: int = 400) -> list[dict]:
    import cv2
    thin = a.thin & (a.labels > 0)
    k = max(1, int(round(0.4 * a.t_int)))
    near_wall = cv2.dilate(a.walls.astype(np.uint8), np.ones((2 * k + 1, 2 * k + 1), np.uint8)).astype(bool)
    m = cv2.morphologyEx(thin.astype(np.uint8), cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    n, lab, stats, _ = cv2.connectedComponentsWithStats(m, connectivity=8)
    out = []
    eps = max(1.0, 0.015 / s)
    x0, y1 = a.bbox[0], a.bbox[3]
    for i in np.argsort(-stats[:, cv2.CC_STAT_AREA]):
        if i == 0 or len(out) >= max_items:
            continue
        x, y, w, h, ar = stats[i]
        wm, hm = w * s, h * s
        if max(wm, hm) < 0.25:
            continue
        comp = (lab[y:y + h, x:x + w] == i)
        touches = near_wall[y:y + h, x:x + w][comp].any()
        if touches and 0.45 <= wm <= 1.4 and 0.45 <= hm <= 1.4 and abs(wm - hm) < 0.3:
            continue                                   # a door swing
        cs, hier = cv2.findContours(comp.astype(np.uint8), cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)
        if hier is None:
            continue
        hier = hier.reshape(-1, 4)
        for ci, c in enumerate(cs):
            parent = hier[ci][3]
            area = cv2.contourArea(c)
            if parent >= 0 and area >= 0.8 * cv2.contourArea(cs[parent]):
                continue                               # the inside edge of a closed stroke
            if cv2.arcLength(c, True) * s < 0.3:
                continue
            ap = cv2.approxPolyDP(c, eps, True).reshape(-1, 2)
            pts = [[round((px + x - x0) * s, 3), round((y1 - (py + y)) * s, 3)] for px, py in ap]
            if len(pts) >= 2:
                out.append({"t": "pline", "pts": pts, "closed": True, "layer": "A-FURN", "color": ""})
    return out


# --- plan --------------------------------------------------------------------------------------
def room_rows(a: Analysis, scale: float | None) -> list[dict]:
    types = guess_types(a, scale or 1.0)
    rows = []
    for r in a.regions:
        rows.append(dict(label=r.label, type=types[r.label], area=r.area * scale * scale if scale else None,
                         text=" · ".join(t.text for t in r.texts)[:60]))
    return rows


def to_plan(a: Analysis, scale: float, types: dict[int, str] | None = None, settings: dict | None = None,
            rules_name: str = "jordan", options: Options | None = None) -> Plan:
    from ..editing import refresh
    from ..layout import _net
    from ..rules.jordan import DEFAULT_SETTINGS
    opt = options or Options()
    s = float(scale)
    types = {**guess_types(a, s), **(types or {})}
    st = {**DEFAULT_SETTINGS, **(settings or {})}
    snap = opt.snap
    bx0, by0, bx1, by1 = a.bbox
    W, D = _snap((bx1 - bx0) * s, snap), _snap((by1 - by0) * s, snap)
    if opt.walls_from_drawing:
        st["exterior_wall"] = min(0.5, max(0.1, _snap(a.t_ext * s, 0.05)))
        st["interior_wall"] = min(0.4, max(0.1, _snap(a.t_int * s, 0.05)))
    te, ti = st["exterior_wall"], st["interior_wall"]
    gx, gy = _grid(a, s, W, D, te, ti, snap)
    lab = _cell_labels(a, s, gx, gy, ti)
    _fill_unknown(lab, gx, gy)
    _merge_slivers(lab, gx, gy)
    rooms: list[Room] = []
    counts: dict[str, int] = {}
    labels_present = [L for L in np.unique(lab) if L > 0]
    order = sorted(labels_present, key=lambda L: (-(lab == L).sum(), L))
    pieces_all = [(L, _rectangles(lab == L, gx, gy)) for L in order]
    if (lab == OUT).any():
        pieces_all.append((OUT, _rectangles(lab == OUT, gx, gy)))
    for L, pieces in pieces_all:
        rtype = "balcony" if L == OUT else types.get(int(L), "bedroom")
        counts[rtype] = counts.get(rtype, 0) + (1 if L != OUT else 0)
        for k, (i0, j0, i1, j1) in enumerate(pieces):
            if L == OUT:
                counts[rtype] += 1
            n = counts[rtype]
            rid = f"{rtype}{n}" + (f"_{k + 1}" if k and L != OUT else "")
            rect = Rect(gx[i0], gy[j0], gx[i1], gy[j1])
            net = _net(rect, W, D, te, ti)
            name_ar, name_en = room_name(rtype, "ar", n), room_name(rtype, "en", n)
            if k and L != OUT:
                name_ar, name_en = name_ar + f" ({k + 1})", name_en + f" ({k + 1})"
            rooms.append(Room(RoomSpec(rid, rtype, round(net.area, 2), 0, True, name_ar, name_en), rect, net))
    plan = Plan(W, D, rooms, [], st)
    rules = get_rules(rules_name)
    if opt.openings == "auto":
        doors, _ = plan_doors(rooms, W, D, st, rules)
        plan.openings = doors + plan_windows(rooms, W, D, st, rules, doors)
    else:
        plan.openings = _detected_openings(a, s, plan, rules, st)
    if opt.furniture:
        plan.drawing = trace_furniture(a, s)
    plan.project = os.path.splitext(os.path.basename(a.src.path))[0] if a.src.path else ""
    refresh(plan, rules_name, mark_edited=True)
    return plan

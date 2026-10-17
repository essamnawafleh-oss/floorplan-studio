"""2D drafting geometry (the 'mini AutoCAD' of edit mode).

Entities are plain dicts (saved in the project, exported to DXF):
  {"t": "line",   "p": [x1, y1, x2, y2]}
  {"t": "pline",  "pts": [[x, y], ...], "closed": bool}
  {"t": "circle", "c": [x, y], "r": r}
  {"t": "arc",    "c": [x, y], "r": r, "a0": deg, "a1": deg}     counter-clockwise a0 -> a1
  {"t": "text",   "p": [x, y], "h": height, "s": "text", "rot": deg}
  {"t": "dim",    "p1": [x, y], "p2": [x, y], "off": [x, y]}     aligned dimension
Every entity may carry "layer" and "color" (hex or "" = by layer).
Units are metres.
"""

from __future__ import annotations

import copy
import math

EPS = 1e-9

LAYERS = {"A-DRAW": "#3a3d42", "A-ANNO": "#b5651d", "A-DIMS": "#c92a2a", "A-HIDDEN": "#868e96", "A-FURN": "#5a5f66"}


# --- small vector helpers -----------------------------------------------------
def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1])


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1]


def _cross(a, b):
    return a[0] * b[1] - a[1] * b[0]


def _len(a):
    return math.hypot(a[0], a[1])


def _ang(c, p):
    return math.degrees(math.atan2(p[1] - c[1], p[0] - c[0])) % 360


def _on_arc(a, a0, a1, tol=1e-7):
    span = (a1 - a0) % 360 or 360
    return ((a - a0) % 360) <= span + tol


def dist(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


# --- entity -> primitive pieces -------------------------------------------------
def pieces(e):
    """Lines ('L', p, q) and arcs ('A', c, r, a0, a1) making up an entity."""
    t = e["t"]
    if t == "line":
        x1, y1, x2, y2 = e["p"]
        return [("L", (x1, y1), (x2, y2))]
    if t == "pline":
        pts = [tuple(p) for p in e["pts"]]
        if e.get("closed") and len(pts) > 2:
            pts = pts + [pts[0]]
        return [("L", a, b) for a, b in zip(pts, pts[1:]) if dist(a, b) > EPS]
    if t == "circle":
        return [("A", tuple(e["c"]), e["r"], 0.0, 360.0)]
    if t == "arc":
        return [("A", tuple(e["c"]), e["r"], e["a0"] % 360, e["a1"] % 360)]
    if t == "dim":
        return [("L", a, b) for a, b in dim_lines(e)]
    return []


def dim_lines(e):
    """Extension lines + dimension line of an aligned dimension."""
    p1, p2, off = tuple(e["p1"]), tuple(e["p2"]), tuple(e["off"])
    d = _sub(p2, p1)
    L = _len(d) or 1.0
    n = (-d[1] / L, d[0] / L)
    k = _dot(_sub(off, p1), n)
    q1 = (p1[0] + n[0] * k, p1[1] + n[1] * k)
    q2 = (p2[0] + n[0] * k, p2[1] + n[1] * k)
    ext = 0.08 * (1 if k >= 0 else -1)
    return [(p1, (q1[0] + n[0] * ext, q1[1] + n[1] * ext)), (p2, (q2[0] + n[0] * ext, q2[1] + n[1] * ext)), (q1, q2)]


def dim_value(e) -> float:
    return dist(e["p1"], e["p2"])


# --- intersections --------------------------------------------------------------
def _ll(p, q, r, s, seg1=True, seg2=True):
    """Line/segment intersection -> list of (point, t on pq)."""
    d1, d2 = _sub(q, p), _sub(s, r)
    den = _cross(d1, d2)
    if abs(den) < EPS:
        return []
    t = _cross(_sub(r, p), d2) / den
    u = _cross(_sub(r, p), d1) / den
    if (seg1 and not -1e-9 <= t <= 1 + 1e-9) or (seg2 and not -1e-9 <= u <= 1 + 1e-9):
        return []
    return [((p[0] + d1[0] * t, p[1] + d1[1] * t), t)]


def _lc(p, q, c, r, a0, a1, seg=True):
    d = _sub(q, p)
    f = _sub(p, c)
    A, B, C = _dot(d, d), 2 * _dot(f, d), _dot(f, f) - r * r
    disc = B * B - 4 * A * C
    if A < EPS or disc < 0:
        return []
    out = []
    for sgn in (-1, 1) if disc > 1e-12 else (1,):
        t = (-B + sgn * math.sqrt(disc)) / (2 * A)
        if seg and not -1e-9 <= t <= 1 + 1e-9:
            continue
        pt = (p[0] + d[0] * t, p[1] + d[1] * t)
        if _on_arc(_ang(c, pt), a0, a1):
            out.append((pt, t))
    return out


def _cc(c1, r1, a01, a11, c2, r2, a02, a12):
    d = dist(c1, c2)
    if d < EPS or d > r1 + r2 + 1e-9 or d < abs(r1 - r2) - 1e-9:
        return []
    a = (r1 * r1 - r2 * r2 + d * d) / (2 * d)
    h = math.sqrt(max(0.0, r1 * r1 - a * a))
    mx, my = c1[0] + a * (c2[0] - c1[0]) / d, c1[1] + a * (c2[1] - c1[1]) / d
    pts = {(round(mx + h * (c2[1] - c1[1]) / d, 9), round(my - h * (c2[0] - c1[0]) / d, 9)),
           (round(mx - h * (c2[1] - c1[1]) / d, 9), round(my + h * (c2[0] - c1[0]) / d, 9))}
    return [p for p in pts if _on_arc(_ang(c1, p), a01, a11) and _on_arc(_ang(c2, p), a02, a12)]


def piece_intersections(a, b):
    if a[0] == "L" and b[0] == "L":
        return [p for p, _ in _ll(a[1], a[2], b[1], b[2])]
    if a[0] == "L":
        return [p for p, _ in _lc(a[1], a[2], *b[1:])]
    if b[0] == "L":
        return [p for p, _ in _lc(b[1], b[2], *a[1:])]
    return _cc(*a[1:], *b[1:])


def intersections(e1, e2):
    out = []
    for a in pieces(e1):
        for b in pieces(e2):
            out += piece_intersections(a, b)
    return out


# --- measurements / hit testing ----------------------------------------------------
def _closest_on_piece(pc, pt):
    if pc[0] == "L":
        p, q = pc[1], pc[2]
        d = _sub(q, p)
        L2 = _dot(d, d)
        t = 0.0 if L2 < EPS else max(0.0, min(1.0, _dot(_sub(pt, p), d) / L2))
        return (p[0] + d[0] * t, p[1] + d[1] * t)
    c, r, a0, a1 = pc[1:]
    a = _ang(c, pt)
    if not _on_arc(a, a0, a1):
        e0 = (c[0] + r * math.cos(math.radians(a0)), c[1] + r * math.sin(math.radians(a0)))
        e1 = (c[0] + r * math.cos(math.radians(a1)), c[1] + r * math.sin(math.radians(a1)))
        return e0 if dist(e0, pt) < dist(e1, pt) else e1
    return (c[0] + r * math.cos(math.radians(a)), c[1] + r * math.sin(math.radians(a)))


def nearest_point(e, pt):
    best = None
    for pc in pieces(e):
        q = _closest_on_piece(pc, pt)
        if best is None or dist(q, pt) < dist(best, pt):
            best = q
    if e["t"] == "text":
        best = tuple(e["p"])
    return best


def distance_to(e, pt) -> float:
    if e["t"] == "text":
        x0, y0, x1, y1 = bbox(e)
        if x0 <= pt[0] <= x1 and y0 <= pt[1] <= y1:
            return 0.0
        return min(dist(pt, (x0, y0)), dist(pt, (x1, y1)))
    q = nearest_point(e, pt)
    return dist(q, pt) if q else float("inf")


def bbox(e):
    t = e["t"]
    if t == "text":
        x, y = e["p"]
        w = e["h"] * 0.6 * max(1, len(e["s"]))
        return (x, y, x + w, y + e["h"])
    pts = []
    for pc in pieces(e):
        if pc[0] == "L":
            pts += [pc[1], pc[2]]
        else:
            c, r = pc[1], pc[2]
            pts += [(c[0] - r, c[1] - r), (c[0] + r, c[1] + r)] if t == "circle" else \
                   [p for p in _arc_points(c, r, pc[3], pc[4], 24)]
    if not pts:
        return (0, 0, 0, 0)
    return (min(p[0] for p in pts), min(p[1] for p in pts), max(p[0] for p in pts), max(p[1] for p in pts))


def _arc_points(c, r, a0, a1, n=32):
    span = (a1 - a0) % 360 or 360
    n = max(4, int(n * span / 360) + 1)
    return [(c[0] + r * math.cos(math.radians(a0 + span * i / n)), c[1] + r * math.sin(math.radians(a0 + span * i / n)))
            for i in range(n + 1)]


def polylines(e):
    """Drawable polylines for rendering."""
    out = []
    for pc in pieces(e):
        if pc[0] == "L":
            out.append([pc[1], pc[2]])
        else:
            out.append(_arc_points(pc[1], pc[2], pc[3], pc[4], 72))
    return out


def in_window(e, x0, y0, x1, y1, crossing: bool) -> bool:
    """Window: fully inside. Crossing: inside or touching the rectangle."""
    bx0, by0, bx1, by1 = bbox(e)
    if bx0 >= x0 and bx1 <= x1 and by0 >= y0 and by1 <= y1:
        return True
    if not crossing:
        return False
    rect = {"t": "pline", "pts": [[x0, y0], [x1, y0], [x1, y1], [x0, y1]], "closed": True}
    if intersections(e, rect):
        return True
    return e["t"] == "text" and not (bx1 < x0 or bx0 > x1 or by1 < y0 or by0 > y1)


# --- snaps ---------------------------------------------------------------------------
def snap_points(e):
    """[(kind, point)] for endpoint / midpoint / center / quadrant."""
    t, out = e["t"], []
    if t == "line":
        x1, y1, x2, y2 = e["p"]
        out += [("end", (x1, y1)), ("end", (x2, y2)), ("mid", ((x1 + x2) / 2, (y1 + y2) / 2))]
    elif t == "pline":
        for a, b in [(pc[1], pc[2]) for pc in pieces(e)]:
            out += [("end", a), ("end", b), ("mid", ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2))]
    elif t in ("circle", "arc"):
        c, r = tuple(e["c"]), e["r"]
        out.append(("cen", c))
        if t == "circle":
            out += [("quad", (c[0] + r * math.cos(math.radians(a)), c[1] + r * math.sin(math.radians(a))))
                    for a in (0, 90, 180, 270)]
        else:
            a0, a1 = e["a0"], e["a1"]
            span = (a1 - a0) % 360 or 360
            for a in (a0, a1):
                out.append(("end", (c[0] + r * math.cos(math.radians(a)), c[1] + r * math.sin(math.radians(a)))))
            am = a0 + span / 2
            out.append(("mid", (c[0] + r * math.cos(math.radians(am)), c[1] + r * math.sin(math.radians(am)))))
    elif t == "text":
        out.append(("ins", tuple(e["p"])))
    elif t == "dim":
        out += [("end", tuple(e["p1"])), ("end", tuple(e["p2"]))]
    return out


def perpendicular_foot(e, base):
    """Foot of the perpendicular from `base` onto each piece (if it lands on it)."""
    out = []
    for pc in pieces(e):
        if pc[0] == "L":
            p, q = pc[1], pc[2]
            d = _sub(q, p)
            L2 = _dot(d, d)
            if L2 < EPS:
                continue
            t = _dot(_sub(base, p), d) / L2
            if 0 <= t <= 1:
                out.append((p[0] + d[0] * t, p[1] + d[1] * t))
        else:
            c, r = pc[1], pc[2]
            if dist(c, base) > EPS:
                a = _ang(c, base)
                if _on_arc(a, pc[3], pc[4]):
                    out.append((c[0] + r * math.cos(math.radians(a)), c[1] + r * math.sin(math.radians(a))))
    return out


def find_snap(entities, pt, tol, modes=("end", "mid", "cen", "int", "quad", "perp", "near", "ins"), base=None):
    """Best object snap near pt -> (kind, point) or None. Priority like AutoCAD:
    endpoint/intersection beat midpoint/center beat perpendicular beat nearest."""
    near = [e for e in entities if distance_to(e, pt) <= tol * 3 or e["t"] in ("circle", "arc")]
    cands = []
    for e in near:
        for kind, p in snap_points(e):
            if kind in modes and dist(p, pt) <= tol:
                cands.append((kind, p))
    if "int" in modes:
        close = [e for e in near if distance_to(e, pt) <= tol * 2]
        for i, a in enumerate(close):
            for b in close[i + 1:]:
                for p in intersections(a, b):
                    if dist(p, pt) <= tol:
                        cands.append(("int", p))
    if "perp" in modes and base is not None:
        for e in near:
            for p in perpendicular_foot(e, base):
                if dist(p, pt) <= tol:
                    cands.append(("perp", p))
    prio = {"end": 0, "int": 0, "ins": 0, "mid": 1, "cen": 1, "quad": 1, "perp": 2, "near": 3}
    if cands:
        return min(cands, key=lambda kp: (prio[kp[0]], dist(kp[1], pt)))
    if "near" in modes:
        best = None
        for e in near:
            q = nearest_point(e, pt)
            if q and dist(q, pt) <= tol and (best is None or dist(q, pt) < dist(best, pt)):
                best = q
        if best:
            return ("near", best)
    return None


# --- transforms ---------------------------------------------------------------------
def _map_points(e, fn, angle_fn=None, scale=1.0, mirror=False):
    e = copy.deepcopy(e)
    t = e["t"]
    if t == "line":
        x1, y1, x2, y2 = e["p"]
        e["p"] = [*fn((x1, y1)), *fn((x2, y2))]
    elif t == "pline":
        e["pts"] = [list(fn(tuple(p))) for p in e["pts"]]
    elif t in ("circle", "arc"):
        e["c"] = list(fn(tuple(e["c"])))
        e["r"] *= scale
        if t == "arc" and angle_fn:
            a0, a1 = angle_fn(e["a0"]), angle_fn(e["a1"])
            e["a0"], e["a1"] = (a1, a0) if mirror else (a0, a1)
    elif t == "text":
        e["p"] = list(fn(tuple(e["p"])))
        e["h"] *= scale
        if angle_fn and not mirror:
            e["rot"] = angle_fn(e.get("rot", 0))
    elif t == "dim":
        for k in ("p1", "p2", "off"):
            e[k] = list(fn(tuple(e[k])))
    return e


def move(e, dx, dy):
    return _map_points(e, lambda p: (p[0] + dx, p[1] + dy))


def rotate(e, base, deg):
    c, s = math.cos(math.radians(deg)), math.sin(math.radians(deg))
    bx, by = base
    fn = lambda p: (bx + (p[0] - bx) * c - (p[1] - by) * s, by + (p[0] - bx) * s + (p[1] - by) * c)
    return _map_points(e, fn, angle_fn=lambda a: (a + deg) % 360)


def scale(e, base, k):
    bx, by = base
    return _map_points(e, lambda p: (bx + (p[0] - bx) * k, by + (p[1] - by) * k), angle_fn=lambda a: a, scale=k)


def mirror(e, p1, p2):
    d = _sub(p2, p1)
    L2 = _dot(d, d) or 1.0
    def fn(p):
        t = _dot(_sub(p, p1), d) / L2
        f = (p1[0] + d[0] * t, p1[1] + d[1] * t)
        return (2 * f[0] - p[0], 2 * f[1] - p[1])
    axis = math.degrees(math.atan2(d[1], d[0]))
    return _map_points(e, fn, angle_fn=lambda a: (2 * axis - a) % 360, mirror=True)


# --- explode ---------------------------------------------------------------------------
def explode(e):
    """Polylines -> lines, dimensions -> lines + text. Others unchanged (returns [] if nothing to do)."""
    base = {k: v for k, v in e.items() if k in ("layer", "color")}
    if e["t"] == "pline":
        return [{**base, "t": "line", "p": [*pc[1], *pc[2]]} for pc in pieces(e)]
    if e["t"] == "dim":
        out = [{**base, "t": "line", "p": [*a, *b]} for a, b in dim_lines(e)]
        (q1, q2) = dim_lines(e)[2]
        out.append({**base, "t": "text", "p": [(q1[0] + q2[0]) / 2, (q1[1] + q2[1]) / 2], "h": 0.15,
                    "s": f"{dim_value(e):.2f}", "rot": 0})
        return out
    return []


def explode_polylines(lines, layer="A-FURN"):
    """Polylines from a block (furniture) -> line entities."""
    out = []
    for pl in lines:
        for a, b in zip(pl, pl[1:]):
            if dist(a, b) > EPS:
                out.append({"t": "line", "p": [a[0], a[1], b[0], b[1]], "layer": layer})
    return out


# --- offset ------------------------------------------------------------------------------
def offset(e, d, side_pt):
    """Copy of e at distance d on the side of side_pt (None if impossible)."""
    t = e["t"]
    base = {k: v for k, v in e.items() if k in ("layer", "color")}
    if t == "line":
        x1, y1, x2, y2 = e["p"]
        v = (x2 - x1, y2 - y1)
        L = _len(v)
        if L < EPS:
            return None
        n = (-v[1] / L, v[0] / L)
        sgn = 1 if _dot(_sub(side_pt, (x1, y1)), n) >= 0 else -1
        return {**base, "t": "line", "p": [x1 + n[0] * d * sgn, y1 + n[1] * d * sgn, x2 + n[0] * d * sgn, y2 + n[1] * d * sgn]}
    if t in ("circle", "arc"):
        c = tuple(e["c"])
        r = e["r"] + (d if dist(side_pt, c) > e["r"] else -d)
        if r <= EPS:
            return None
        out = copy.deepcopy(e)
        out["r"] = r
        return out
    if t == "pline":
        from shapely.geometry import LineString, Point, Polygon
        pts = [tuple(p) for p in e["pts"]]
        if e.get("closed") and len(pts) >= 3:
            poly = Polygon(pts)
            inside = poly.contains(Point(side_pt))
            g = poly.buffer(-d if inside else d, join_style=2)
            if g.is_empty or g.geom_type != "Polygon":
                return None
            ring = list(g.exterior.coords)[:-1]
            return {**base, "t": "pline", "pts": [list(p) for p in ring], "closed": True}
        ls = LineString(pts)
        best = None
        for sgn in (1, -1):
            g = ls.offset_curve(d * sgn, join_style=2)
            if g.is_empty or g.geom_type != "LineString":
                continue
            score = g.distance(Point(side_pt))
            if best is None or score < best[0]:
                best = (score, list(g.coords))
        if best is None:
            return None
        return {**base, "t": "pline", "pts": [list(p) for p in best[1]], "closed": False}
    return None


# --- trim / extend -------------------------------------------------------------------------
def _params_on_line(p, q, cutters):
    ts = []
    for c in cutters:
        for pc in pieces(c):
            if pc[0] == "L":
                ts += [t for _, t in _ll(p, q, pc[1], pc[2])]
            else:
                ts += [t for _, t in _lc(p, q, *pc[1:])]
    return sorted(t for t in ts if 1e-7 < t < 1 - 1e-7)


def _lerp(p, q, t):
    return (p[0] + (q[0] - p[0]) * t, p[1] + (q[1] - p[1]) * t)


def trim(e, pick, cutters):
    """AutoCAD quick-mode trim. Returns the replacement entities: [] erases e
    (when nothing cuts it), [e] means unchanged."""
    t = e["t"]
    base = {k: v for k, v in e.items() if k in ("layer", "color")}
    if t == "line":
        p, q = tuple(e["p"][:2]), tuple(e["p"][2:])
        ts = _params_on_line(p, q, cutters)
        if not ts:
            return []
        d = _sub(q, p)
        tp = _dot(_sub(pick, p), d) / (_dot(d, d) or 1)
        lo = max([x for x in ts if x < tp], default=0.0)
        hi = min([x for x in ts if x > tp], default=1.0)
        out = []
        if lo > 0:
            out.append({**base, "t": "line", "p": [*p, *_lerp(p, q, lo)]})
        if hi < 1:
            out.append({**base, "t": "line", "p": [*_lerp(p, q, hi), *q]})
        return out
    if t in ("circle", "arc"):
        c, r = tuple(e["c"]), e["r"]
        a0 = e.get("a0", 0.0) % 360
        span = ((e.get("a1", 360.0) - a0) % 360 or 360) if t == "arc" else 360.0
        angs = []
        for cut in cutters:
            for pt in intersections(e, cut):
                u = (_ang(c, pt) - a0) % 360
                if 1e-6 < u < span - 1e-6 or t == "circle":
                    angs.append(u)
        angs = sorted(set(round(a, 7) for a in angs))
        if t == "circle":
            if len(angs) < 2:
                return [e] if angs else []
            up = (_ang(c, pick) - a0) % 360
            lo = max([a for a in angs if a < up], default=angs[-1] - 360)
            hi = min([a for a in angs if a > up], default=angs[0] + 360)
            return [{**base, "t": "arc", "c": list(c), "r": r, "a0": (a0 + hi) % 360, "a1": (a0 + lo) % 360}]
        if not angs:
            return []
        up = (_ang(c, pick) - a0) % 360
        lo = max([a for a in angs if a < up], default=0.0)
        hi = min([a for a in angs if a > up], default=span)
        out = []
        if lo > 0:
            out.append({**base, "t": "arc", "c": list(c), "r": r, "a0": a0, "a1": (a0 + lo) % 360})
        if hi < span:
            out.append({**base, "t": "arc", "c": list(c), "r": r, "a0": (a0 + hi) % 360, "a1": (a0 + span) % 360})
        return out
    if t == "pline":
        pts = [tuple(p) for p in e["pts"]]
        closed = bool(e.get("closed")) and len(pts) > 2
        ring = pts + [pts[0]] if closed else pts
        segs = list(zip(ring, ring[1:]))
        lengths = [dist(a, b) for a, b in segs]
        total = sum(lengths)
        if total < EPS:
            return [e]
        cuts = []
        acc = 0.0
        best = (float("inf"), 0.0)
        for (a, b), L in zip(segs, lengths):
            for tt in _params_on_line(a, b, cutters):
                cuts.append(acc + tt * L)
            d = _sub(b, a)
            tp = max(0.0, min(1.0, _dot(_sub(pick, a), d) / (_dot(d, d) or 1)))
            dd = dist(_lerp(a, b, tp), pick)
            if dd < best[0]:
                best = (dd, acc + tp * L)
            acc += L
        cuts = sorted(set(round(c, 9) for c in cuts))
        if not cuts:
            return []
        sp = best[1]

        if closed:                    # walk the ring twice so a kept part can wrap around
            segs, lengths = segs + segs, lengths + lengths
        span_total = sum(lengths)

        def point_at(s):
            s = max(0.0, min(span_total, s))
            a = 0.0
            for (p, q), L in zip(segs, lengths):
                if s <= a + L + 1e-12:
                    return _lerp(p, q, (s - a) / L if L else 0)
                a += L
            return segs[-1][1]

        def sub_path(s0, s1):
            out = [point_at(s0)]
            a = 0.0
            for (p, q), L in zip(segs, lengths):
                end = a + L
                if s0 < end - 1e-12 and end < s1 - 1e-12:
                    out.append(q)
                a = end
            out.append(point_at(s1))
            return [list(x) for x in out]

        if closed:
            if len(cuts) < 2:
                return [e]
            lo = max([c for c in cuts if c < sp], default=cuts[-1] - total)
            hi = min([c for c in cuts if c > sp], default=cuts[0] + total)
            if lo < 0:
                lo, hi = lo + total, hi + total
            start = hi % total if hi >= total else hi
            end = lo + total if lo + total > start else lo + 2 * total
            return [{**base, "t": "pline", "pts": sub_path(start, end), "closed": False}]
        lo = max([c for c in cuts if c < sp], default=0.0)
        hi = min([c for c in cuts if c > sp], default=total)
        out = []
        if lo > 0:
            out.append({**base, "t": "pline", "pts": sub_path(0, lo), "closed": False})
        if hi < total:
            out.append({**base, "t": "pline", "pts": sub_path(hi, total), "closed": False})
        return out
    return [e]


def extend(e, pick, boundaries):
    """Extend the end of a line / open polyline nearest to pick up to the
    nearest boundary. Returns the new entity or None if no boundary is hit."""
    t = e["t"]
    if t == "line":
        p, q = tuple(e["p"][:2]), tuple(e["p"][2:])
        start = dist(pick, p) < dist(pick, q)
        a, b = (q, p) if start else (p, q)          # extend from a through b
        new = _ray_hit(a, b, boundaries, exclude=e)
        if new is None:
            return None
        out = copy.deepcopy(e)
        out["p"] = [*new, *q] if start else [*p, *new]
        return out
    if t == "pline" and not e.get("closed") and len(e["pts"]) >= 2:
        pts = [tuple(p) for p in e["pts"]]
        start = dist(pick, pts[0]) < dist(pick, pts[-1])
        a, b = (pts[1], pts[0]) if start else (pts[-2], pts[-1])
        new = _ray_hit(a, b, boundaries, exclude=e)
        if new is None:
            return None
        out = copy.deepcopy(e)
        if start:
            out["pts"][0] = list(new)
        else:
            out["pts"][-1] = list(new)
        return out
    return None


def _ray_hit(a, b, boundaries, exclude=None):
    """First point beyond b on the ray a->b that hits a boundary."""
    best = None
    far = (b[0] + (b[0] - a[0]) * 1e4, b[1] + (b[1] - a[1]) * 1e4)
    for bd in boundaries:
        if bd is exclude:
            continue
        for pc in pieces(bd):
            hits = _ll(a, far, pc[1], pc[2]) if pc[0] == "L" else _lc(a, far, *pc[1:])
            for pt, _ in hits:
                if _dot(_sub(pt, b), _sub(b, a)) > 1e-9:
                    if best is None or dist(pt, b) < dist(best, b):
                        best = pt
    return best


# --- input parsing (command line) ----------------------------------------------------------
def parse_point(text: str, last=None, unit_k: float = 1.0):
    """'x,y'  '@dx,dy'  '@d<ang'  'd<ang' (from last point) -> (x, y) in metres, or None.
    unit_k: metres per typed unit."""
    s = text.strip().replace(" ", "")
    rel = s.startswith("@")
    if rel:
        s = s[1:]
    try:
        if "<" in s:
            d, a = s.split("<", 1)
            d, a = float(d) * unit_k, math.radians(float(a))
            ox, oy = last if last is not None else (0.0, 0.0)
            return (ox + d * math.cos(a), oy + d * math.sin(a))
        if "," in s:
            x, y = (float(v) * unit_k for v in s.split(",", 1))
            if rel:
                ox, oy = last if last is not None else (0.0, 0.0)
                return (ox + x, oy + y)
            return (x, y)
    except ValueError:
        return None
    return None

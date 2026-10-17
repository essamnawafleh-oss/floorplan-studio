"""Block library: furniture, sanitary, door and window symbols.

A block is 2D line work in metres with its base point at (0, 0):
  furniture / sanitary / kitchen: drawn in [0, width] x [0, depth]
  door:   drawn for a 1 m wide door, hinge at (0, 0), closed leaf along +x,
          swinging into +y. Scaled to the real door width.
  window: drawn along +x from 0 to 1, across the wall from y=-0.5 to 0.5.
          Scaled to the window width and wall thickness.
Primitives: {"t": "line", "p": [x1, y1, x2, y2]}, {"t": "poly", "pts": [[x, y], ...], "closed": bool},
            {"t": "arc", "c": [x, y], "r": r, "a0": deg, "a1": deg}, {"t": "circle", "c": [x, y], "r": r}
Arcs go counter-clockwise from a0 to a1.

Built-in blocks have ids "std/..."; user blocks are JSON files in the user
library folder and can be imported from DXF (one block per DXF block definition
or the whole drawing).
"""

from __future__ import annotations

import json
import math
import os
import re
from dataclasses import asdict, dataclass, field

CATEGORIES = {
    "furniture": ("أثاث", "Furniture"),
    "sanitary": ("صحي", "Sanitary"),
    "kitchen": ("مطبخ", "Kitchen"),
    "door": ("أبواب", "Doors"),
    "window": ("شبابيك", "Windows"),
}


@dataclass
class Block:
    id: str
    name_ar: str
    name_en: str
    category: str
    width: float
    depth: float
    height: float = 0.75          # for the 3D model
    prims: list = field(default_factory=list)

    def to_json(self) -> dict:
        return asdict(self)


def _rect(x0, y0, x1, y1):
    return {"t": "poly", "pts": [[x0, y0], [x1, y0], [x1, y1], [x0, y1]], "closed": True}


def _line(x1, y1, x2, y2):
    return {"t": "line", "p": [x1, y1, x2, y2]}


def _circle(x, y, r):
    return {"t": "circle", "c": [x, y], "r": r}


def _arc(x, y, r, a0, a1):
    return {"t": "arc", "c": [x, y], "r": r, "a0": a0, "a1": a1}


def _rrect(x0, y0, x1, y1, r):
    """Rounded rectangle as polyline."""
    pts = []
    for cx, cy, a in ((x1 - r, y0 + r, -90), (x1 - r, y1 - r, 0), (x0 + r, y1 - r, 90), (x0 + r, y0 + r, 180)):
        for i in range(5):
            t = math.radians(a + 90 * i / 4)
            pts.append([cx + r * math.cos(t), cy + r * math.sin(t)])
    return {"t": "poly", "pts": pts, "closed": True}


def _builtin() -> list[Block]:
    B = []

    def add(bid, ar, en, cat, w, d, h, prims):
        B.append(Block("std/" + bid, ar, en, cat, w, d, h, prims))

    # furniture
    add("bed_double", "سرير مزدوج", "Double bed", "furniture", 1.6, 2.0, 0.55,
        [_rect(0, 0, 1.6, 2.0), _rrect(0.12, 1.55, 0.74, 1.9, 0.06), _rrect(0.86, 1.55, 1.48, 1.9, 0.06),
         _line(0, 1.4, 1.6, 1.4)])
    add("bed_single", "سرير مفرد", "Single bed", "furniture", 0.9, 1.9, 0.55,
        [_rect(0, 0, 0.9, 1.9), _rrect(0.12, 1.45, 0.78, 1.8, 0.06), _line(0, 1.3, 0.9, 1.3)])
    add("wardrobe", "خزانة ملابس", "Wardrobe", "furniture", 1.8, 0.6, 2.2,
        [_rect(0, 0, 1.8, 0.6), _line(0.9, 0, 0.9, 0.6), _line(0.05, 0.3, 1.75, 0.3)])
    add("sofa3", "كنب 3 مقاعد", "3-seat sofa", "furniture", 2.1, 0.9, 0.8,
        [_rrect(0, 0, 2.1, 0.9, 0.08), _rect(0.18, 0, 1.92, 0.68), _line(0.76, 0, 0.76, 0.68),
         _line(1.34, 0, 1.34, 0.68)])
    add("armchair", "كرسي فردي", "Armchair", "furniture", 0.85, 0.85, 0.8,
        [_rrect(0, 0, 0.85, 0.85, 0.08), _rect(0.15, 0, 0.7, 0.65)])
    add("coffee_table", "طاولة وسط", "Coffee table", "furniture", 1.1, 0.6, 0.45,
        [_rrect(0, 0, 1.1, 0.6, 0.05)])
    add("tv_unit", "طاولة تلفزيون", "TV unit", "furniture", 1.8, 0.45, 0.5,
        [_rect(0, 0, 1.8, 0.45), _rect(0.4, 0.3, 1.4, 0.38)])
    add("dining6", "سفرة 6 كراسي", "Dining table (6)", "furniture", 1.8, 1.7, 0.75,
        [_rect(0.0, 0.4, 1.8, 1.3)] + [_rrect(x, y, x + 0.42, y + 0.36, 0.05)
                                         for x in (0.15, 0.69, 1.23) for y in (0.0, 1.34)])
    add("desk", "مكتب", "Desk", "furniture", 1.2, 0.6, 0.75,
        [_rect(0, 0, 1.2, 0.6), _rrect(0.38, 0.62, 0.82, 1.0, 0.08)])
    # sanitary
    add("wc", "مرحاض إفرنجي", "WC", "sanitary", 0.4, 0.7, 0.4,
        [_rect(0, 0.5, 0.4, 0.7), {"t": "poly", "closed": True, "pts": [
            [0.2 + 0.18 * math.cos(math.radians(a)), 0.27 + 0.24 * math.sin(math.radians(a))] for a in range(0, 360, 20)]}])
    add("basin", "مغسلة", "Washbasin", "sanitary", 0.55, 0.45, 0.85,
        [_rect(0, 0, 0.55, 0.45), _rrect(0.08, 0.06, 0.47, 0.36, 0.1), _circle(0.275, 0.4, 0.02)])
    add("shower", "دوش", "Shower tray", "sanitary", 0.9, 0.9, 0.05,
        [_rect(0, 0, 0.9, 0.9), _line(0, 0, 0.9, 0.9), _line(0.9, 0, 0, 0.9), _circle(0.45, 0.45, 0.04)])
    add("bathtub", "بانيو", "Bathtub", "sanitary", 1.7, 0.75, 0.55,
        [_rect(0, 0, 1.7, 0.75), _rrect(0.08, 0.08, 1.62, 0.67, 0.25), _circle(1.45, 0.375, 0.03)])
    # kitchen
    add("counter_sink", "مجلى + رخامة", "Counter with sink", "kitchen", 2.4, 0.6, 0.9,
        [_rect(0, 0, 2.4, 0.6), _rrect(0.3, 0.1, 1.1, 0.5, 0.05), _line(0.7, 0.1, 0.7, 0.5)])
    add("counter_hob", "رخامة + غاز", "Counter with hob", "kitchen", 1.8, 0.6, 0.9,
        [_rect(0, 0, 1.8, 0.6)] + [_circle(x, y, 0.09) for x in (0.95, 1.35) for y in (0.17, 0.43)])
    add("fridge", "ثلاجة", "Fridge", "kitchen", 0.75, 0.7, 1.8,
        [_rect(0, 0, 0.75, 0.7), _line(0.05, 0.05, 0.7, 0.05), {"t": "line", "p": [0.1, 0.65, 0.65, 0.65]}])
    # doors (1 m wide, hinge at origin)
    add("door_single", "باب مفرد", "Single swing door", "door", 1.0, 1.0, 2.1,
        [_line(0, 0, 0, 1), _arc(0, 0, 1, 0, 90)])
    add("door_double", "باب دبل", "Double door", "door", 1.0, 0.5, 2.1,
        [_line(0, 0, 0, 0.5), _arc(0, 0, 0.5, 0, 90), _line(1, 0, 1, 0.5), _arc(1, 0, 0.5, 90, 180)])
    add("door_sliding", "باب جرار", "Sliding door", "door", 1.0, 0.1, 2.1,
        [_rect(0, -0.04, 0.55, 0.0), _rect(0.45, 0.0, 1.0, 0.04)])
    # windows (along +x, across wall y in [-0.5, 0.5])
    add("win_single", "شباك عادي", "Window", "window", 1.0, 1.0, 1.3,
        [_rect(0, -0.5, 1, 0.5), _line(0, 0, 1, 0)])
    add("win_double", "شباك زجاج مزدوج", "Double glazed", "window", 1.0, 1.0, 1.3,
        [_rect(0, -0.5, 1, 0.5), _line(0, -0.12, 1, -0.12), _line(0, 0.12, 1, 0.12)])
    add("win_sliding", "شباك جرار", "Sliding window", "window", 1.0, 1.0, 1.3,
        [_rect(0, -0.5, 1, 0.5), _line(0, -0.1, 0.55, -0.1), _line(0.45, 0.1, 1, 0.1)])
    return B


BUILTIN = {b.id: b for b in _builtin()}


# --- transforms --------------------------------------------------------------
def transform_prims(prims: list, fn) -> list:
    """Apply a point function fn(x, y) -> (x, y). Arcs/circles become polylines
    so non-uniform scaling and rotation stay exact."""
    out = []
    for p in prims:
        t = p["t"]
        if t == "line":
            x1, y1, x2, y2 = p["p"]
            out.append([fn(x1, y1), fn(x2, y2)])
        elif t == "poly":
            pts = [fn(x, y) for x, y in p["pts"]]
            out.append(pts + [pts[0]] if p.get("closed") else pts)
        elif t in ("arc", "circle"):
            (cx, cy), r = p["c"], p["r"]
            a0, a1 = (p["a0"], p["a1"]) if t == "arc" else (0.0, 360.0)
            span = (a1 - a0) % 360 or 360
            n = max(8, int(span / 10))
            out.append([fn(cx + r * math.cos(math.radians(a0 + span * i / n)),
                           cy + r * math.sin(math.radians(a0 + span * i / n))) for i in range(n + 1)])
    return out


def furniture_polylines(block: Block, x: float, y: float, rotation: float, scale: float) -> list:
    c, s = math.cos(math.radians(rotation)), math.sin(math.radians(rotation))
    return transform_prims(block.prims, lambda px, py: (x + scale * (px * c - py * s), y + scale * (px * s + py * c)))


def opening_polylines(block: Block, o) -> list:
    """Map a door/window block onto an opening (see module docstring)."""
    seg, w = o.seg, o.width
    if block.category == "window":
        along = lambda px, py: (seg.s0 + px * w, seg.coord + py * o.thickness)
    else:
        face = seg.coord + o.into * o.thickness / 2
        hinge = seg.s0 if o.hinge == 0 else seg.s1
        dirn = 1 if o.hinge == 0 else -1
        along = lambda px, py: (hinge + dirn * px * w, face + o.into * py * w)
    if seg.orient == "h":
        fn = along
    else:
        fn = lambda px, py: tuple(reversed(along(px, py)))
    return transform_prims(block.prims, fn)


def furniture_footprint(block: Block, f) -> list[tuple[float, float]]:
    pts = [(0, 0), (block.width, 0), (block.width, block.depth), (0, block.depth)]
    c, s = math.cos(math.radians(f.rotation)), math.sin(math.radians(f.rotation))
    return [(f.x + f.scale * (px * c - py * s), f.y + f.scale * (px * s + py * c)) for px, py in pts]


# --- DXF import -------------------------------------------------------------
UNIT_SCALE = {0: 1.0, 1: 0.0254, 2: 0.3048, 4: 0.001, 5: 0.01, 6: 1.0}


def _slug(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9_\-]+", "_", text).strip("_") or "block"


def _entities_to_prims(entities, k: float) -> list:
    prims = []
    for e in entities:
        t = e.dxftype()
        try:
            if t == "LINE":
                prims.append(_line(e.dxf.start.x * k, e.dxf.start.y * k, e.dxf.end.x * k, e.dxf.end.y * k))
            elif t == "CIRCLE":
                prims.append(_circle(e.dxf.center.x * k, e.dxf.center.y * k, e.dxf.radius * k))
            elif t == "ARC":
                prims.append(_arc(e.dxf.center.x * k, e.dxf.center.y * k, e.dxf.radius * k,
                                  e.dxf.start_angle, e.dxf.end_angle))
            elif t in ("LWPOLYLINE", "POLYLINE", "SPLINE", "ELLIPSE"):
                if t == "LWPOLYLINE" and not any(v[4] for v in e.get_points("xyseb")):
                    pts = [[x * k, y * k] for x, y in e.get_points("xy")]
                    closed = bool(e.closed)
                else:      # bulges, splines, ellipses: flatten
                    pts = [[p.x * k, p.y * k] for p in e.flattening(0.01 / max(k, 1e-9))]
                    closed = False
                if len(pts) > 1:
                    prims.append({"t": "poly", "pts": pts, "closed": closed})
            elif t == "INSERT":
                prims += _entities_to_prims(list(e.virtual_entities()), k)
        except Exception:
            continue          # skip anything we cannot read rather than fail the import
    return prims


def _normalise(prims: list, category: str) -> tuple[list, float, float]:
    pts = [pt for pl in transform_prims(prims, lambda x, y: (x, y)) for pt in pl]
    if not pts:
        return prims, 0.0, 0.0
    x0, y0 = min(p[0] for p in pts), min(p[1] for p in pts)
    x1, y1 = max(p[0] for p in pts), max(p[1] for p in pts)
    w, d = x1 - x0, y1 - y0
    if category in ("door", "window"):
        # doors/windows: scale so the width is 1 (base point = left end)
        k = 1.0 / w if w > 0 else 1.0
        dy = -(y0 + y1) / 2 if category == "window" else -y0
        ky = (1.0 / d if d > 0 else 1.0) if category == "window" else k
        fn = lambda x, y: ((x - x0) * k, (y + dy) * ky)
    else:
        fn = lambda x, y: (x - x0, y - y0)
    out = [{"t": "poly", "pts": [list(p) for p in pl], "closed": False}
           for pl in transform_prims(prims, fn)]
    return out, (1.0 if category in ("door", "window") else w), (1.0 if category in ("door", "window") else d)


def blocks_from_dxf(path: str, category: str = "furniture", unit: float | None = None,
                    whole_drawing: bool = False) -> list[Block]:
    """Read DXF block definitions (or the whole modelspace) as library blocks.
    unit: metres per drawing unit; default from the DXF header ($INSUNITS),
    falling back to millimetres when the drawing looks like mm."""
    import ezdxf
    doc = ezdxf.readfile(path)
    k = unit or UNIT_SCALE.get(doc.header.get("$INSUNITS", 0), 1.0)
    groups = []
    if not whole_drawing:
        for blk in doc.blocks:
            name = blk.name
            if name.startswith("*") or name.upper().startswith(("A$", "_")) or blk.is_any_layout:
                continue
            ents = list(blk)
            if ents:
                groups.append((name, ents))
    if whole_drawing or not groups:
        groups = [(os.path.splitext(os.path.basename(path))[0], list(doc.modelspace()))]
    out = []
    for name, ents in groups:
        prims = _entities_to_prims(ents, k)
        if unit is None and prims:          # unitless drawings that are obviously in mm
            pts = [pt for pl in transform_prims(prims, lambda x, y: (x, y)) for pt in pl]
            size = max(max(p[0] for p in pts) - min(p[0] for p in pts), max(p[1] for p in pts) - min(p[1] for p in pts))
            if size > 30 and k == 1.0:
                prims = _entities_to_prims(ents, 0.001)
        prims, w, d = _normalise(prims, category)
        if not prims:
            continue
        height = {"door": 2.1, "window": 1.3}.get(category, 0.75)
        out.append(Block(f"user/{_slug(name)}", name, name, category, round(w, 4), round(d, 4), height, prims))
    return out


# --- library ---------------------------------------------------------------------
class BlockLibrary:
    def __init__(self, user_dir: str | None = None):
        self.user_dir = user_dir
        self.blocks: dict[str, Block] = dict(BUILTIN)
        if user_dir:
            os.makedirs(user_dir, exist_ok=True)
            for fn in sorted(os.listdir(user_dir)):
                if fn.endswith(".json"):
                    try:
                        with open(os.path.join(user_dir, fn), encoding="utf-8") as f:
                            b = Block(**json.load(f))
                        self.blocks[b.id] = b
                    except Exception:
                        continue

    def get(self, bid: str) -> Block | None:
        return self.blocks.get(bid)

    def by_category(self, category: str) -> list[Block]:
        return [b for b in self.blocks.values() if b.category == category]

    def add(self, block: Block) -> Block:
        base, n = block.id, 2
        while block.id in self.blocks:       # never overwrite an existing block
            block.id = f"{base}_{n}"
            n += 1
        self.blocks[block.id] = block
        if self.user_dir:
            with open(os.path.join(self.user_dir, block.id.split("/", 1)[1] + ".json"), "w", encoding="utf-8") as f:
                json.dump(block.to_json(), f, ensure_ascii=False)
        return block

    def remove(self, bid: str) -> None:
        if bid.startswith("user/") and bid in self.blocks:
            del self.blocks[bid]
            if self.user_dir:
                p = os.path.join(self.user_dir, bid.split("/", 1)[1] + ".json")
                if os.path.exists(p):
                    os.remove(p)

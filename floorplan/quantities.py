"""Simple bill of quantities: blocks (masonry), floor tiles, paint.

All inputs are in metres. Defaults follow common Jordanian practice and can be
changed: 40x20 cm hollow blocks with 1 cm joints; exterior walls count the
block leaf behind the stone/concrete facing.
"""

from __future__ import annotations

import math

from .editing import wall_lines
from .models import Plan

TILE_PRESETS = [(0.20, 0.20), (0.25, 0.25), (0.30, 0.30), (0.40, 0.40), (0.45, 0.45),
                (0.60, 0.60), (0.60, 1.20), (0.80, 0.80), (0.20, 1.20)]

DEFAULTS = dict(
    wall_height=None,           # None = plan setting
    block_l=0.40, block_h=0.20, joint=0.01, block_waste=0.05,
    tile_l=0.60, tile_w=0.60, tile_joint=0.003, tile_waste=0.10, box_m2=1.44,
    skip_wet_tiles=False,       # wet rooms often get a different tile
    paint_coverage=10.0,        # m² per litre per coat
    coats=2, paint_waste=0.05, gallon_l=3.785, ceilings=True,
)


def _opening_area(o) -> float:
    return o.width * ((o.head - o.sill) if o.kind == "window" else o.head)


def compute(plan: Plan, opts: dict | None = None) -> dict:
    o = {**DEFAULTS, **(opts or {})}
    st = plan.settings
    H = o["wall_height"] or st["wall_height"]
    te = st["exterior_wall"]

    # --- walls ---
    int_len = sum(ln.length for ln in wall_lines(plan) if not ln.side)
    ext_len = 2 * ((plan.width - te) + (plan.depth - te))        # centre line
    ext_open = sum(_opening_area(op) for op in plan.openings if len(op.rooms) == 1)
    int_open = sum(_opening_area(op) for op in plan.openings if len(op.rooms) == 2)
    ext_wall = max(0.0, ext_len * H - ext_open)
    int_wall = max(0.0, int_len * H - int_open)
    per_m2 = 1.0 / ((o["block_l"] + o["joint"]) * (o["block_h"] + o["joint"]))
    blocks = dict(
        per_m2=per_m2,
        ext_length=ext_len, ext_area=ext_wall, ext_count=math.ceil(ext_wall * per_m2 * (1 + o["block_waste"])),
        int_length=int_len, int_area=int_wall, int_count=math.ceil(int_wall * per_m2 * (1 + o["block_waste"])),
    )
    blocks["total"] = blocks["ext_count"] + blocks["int_count"]

    # --- tiles ---
    tile_area = (o["tile_l"] + o["tile_joint"]) * (o["tile_w"] + o["tile_joint"])
    rooms = []
    t_area = t_count = 0
    for r in plan.rooms:
        if o["skip_wet_tiles"] and r.spec.type in ("bathroom", "ensuite", "guest_wc", "laundry"):
            continue
        a = r.net.area
        n = math.ceil(a / tile_area * (1 + o["tile_waste"]))
        rooms.append(dict(id=r.id, name_ar=r.spec.name_ar, name_en=r.spec.name_en, area=a, tiles=n))
        t_area += a
        t_count += n
    tiles = dict(tile=(o["tile_l"], o["tile_w"]), rooms=rooms, area=t_area, count=t_count,
                 m2_with_waste=t_area * (1 + o["tile_waste"]),
                 boxes=math.ceil(t_area * (1 + o["tile_waste"]) / o["box_m2"]) if o["box_m2"] else 0)

    # --- paint ---
    litres = lambda area: area * o["coats"] / o["paint_coverage"] * (1 + o["paint_waste"])
    facade = max(0.0, 2 * (plan.width + plan.depth) * H - ext_open)
    p_rooms = []
    for r in plan.rooms:
        n = r.net
        walls_area = 2 * (n.w + n.h) * H
        walls_area -= sum(_opening_area(op) for op in plan.openings if r.id in op.rooms)
        walls_area = max(0.0, walls_area)
        ceiling = n.area if o["ceilings"] else 0.0
        p_rooms.append(dict(id=r.id, name_ar=r.spec.name_ar, name_en=r.spec.name_en,
                            walls=walls_area, ceiling=ceiling, litres=litres(walls_area + ceiling)))
    interior = sum(x["walls"] + x["ceiling"] for x in p_rooms)
    paint = dict(facade_area=facade, facade_litres=litres(facade), rooms=p_rooms,
                 interior_area=interior, interior_litres=litres(interior))
    paint["facade_gallons"] = paint["facade_litres"] / o["gallon_l"]
    paint["interior_gallons"] = paint["interior_litres"] / o["gallon_l"]
    return dict(options=o, height=H, blocks=blocks, tiles=tiles, paint=paint)


def to_csv(result: dict, lang: str = "en") -> str:
    """Spreadsheet-friendly summary (UTF-8, opens in Excel)."""
    b, t, p = result["blocks"], result["tiles"], result["paint"]
    name = (lambda r: r["name_ar"]) if lang == "ar" else (lambda r: r["name_en"])
    rows = [["Item", "Quantity", "Unit"],
            ["Exterior walls (block leaf)", f"{b['ext_area']:.2f}", "m²"],
            ["Exterior blocks", b["ext_count"], "pcs"],
            ["Interior walls", f"{b['int_area']:.2f}", "m²"],
            ["Interior blocks", b["int_count"], "pcs"],
            ["Blocks total", b["total"], "pcs"],
            [], [f"Tiles {t['tile'][0] * 100:.0f}x{t['tile'][1] * 100:.0f} cm", "", ""]]
    rows += [[name(r), f"{r['area']:.2f} m² / {r['tiles']} pcs", ""] for r in t["rooms"]]
    rows += [["Tiles total", t["count"], "pcs"], ["Tile area incl. waste", f"{t['m2_with_waste']:.2f}", "m²"],
             ["Tile boxes", t["boxes"], "boxes"], [],
             ["Facade paint area", f"{p['facade_area']:.2f}", "m²"],
             ["Facade paint", f"{p['facade_litres']:.1f}", "L"],
             ["Interior paint area", f"{p['interior_area']:.2f}", "m²"],
             ["Interior paint", f"{p['interior_litres']:.1f}", "L"]]
    rows += [[name(r), f"{r['walls'] + r['ceiling']:.2f} m² / {r['litres']:.1f} L", ""] for r in p["rooms"]]
    out = []
    for row in rows:
        out.append(",".join(f'"{c}"' if "," in str(c) else str(c) for c in row))
    return "﻿" + "\n".join(out) + "\n"

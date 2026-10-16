"""CAD export (DXF, opens in AutoCAD / BricsCAD / LibreCAD). Units: metres."""

from __future__ import annotations

import math

import ezdxf
from ezdxf.enums import TextEntityAlignment

from ..geometry import door_geometry, walls
from ..models import Plan

LAYERS = {
    "A-WALL": 7, "A-WALL-HATCH": 8, "A-DOOR": 3, "A-GLAZ": 5,
    "A-AREA": 9, "A-ANNO-TEXT": 2, "A-ANNO-DIMS": 1,
}


def to_dxf(plan: Plan, path: str, lang: str = "en") -> None:
    """lang 'en' is safest for AutoCAD; 'ar'/'both' need an Arabic-capable font."""
    doc = ezdxf.new("R2010", setup=True)
    doc.units = ezdxf.units.M
    doc.header["$MEASUREMENT"] = 1
    for name, color in LAYERS.items():
        doc.layers.add(name, color=color)
    doc.styles.add("PLAN", font="arial.ttf")
    msp = doc.modelspace()

    for p in walls(plan):
        hatch = msp.add_hatch(color=8, dxfattribs={"layer": "A-WALL-HATCH"})
        hatch.paths.add_polyline_path(list(p.exterior.coords)[:-1], is_closed=True, flags=1)
        for ring in p.interiors:
            hatch.paths.add_polyline_path(list(ring.coords)[:-1], is_closed=True)
        for ring in [p.exterior, *p.interiors]:
            msp.add_lwpolyline(list(ring.coords)[:-1], close=True, dxfattribs={"layer": "A-WALL"})

    for o in plan.openings:
        g = o.gap_rect()
        if o.kind == "window":
            msp.add_lwpolyline([(g.x0, g.y0), (g.x1, g.y0), (g.x1, g.y1), (g.x0, g.y1)], close=True,
                               dxfattribs={"layer": "A-GLAZ"})
            if o.seg.orient == "h":
                yc = (g.y0 + g.y1) / 2
                msp.add_line((g.x0, yc), (g.x1, yc), dxfattribs={"layer": "A-GLAZ"})
            else:
                xc = (g.x0 + g.x1) / 2
                msp.add_line((xc, g.y0), (xc, g.y1), dxfattribs={"layer": "A-GLAZ"})
            continue
        hinge, leaf, closed, w = door_geometry(o)
        msp.add_line(hinge, leaf, dxfattribs={"layer": "A-DOOR"})
        a_leaf = math.degrees(math.atan2(leaf[1] - hinge[1], leaf[0] - hinge[0]))
        a_closed = math.degrees(math.atan2(closed[1] - hinge[1], closed[0] - hinge[0]))
        start, end = (a_leaf, a_closed) if (a_closed - a_leaf) % 360 <= 180 else (a_closed, a_leaf)
        msp.add_arc(hinge, w, start, end, dxfattribs={"layer": "A-DOOR"})

    for r in plan.rooms:
        n = r.net
        msp.add_lwpolyline([(n.x0, n.y0), (n.x1, n.y0), (n.x1, n.y1), (n.x0, n.y1)], close=True,
                           dxfattribs={"layer": "A-AREA"})
        name = r.spec.name_ar if lang == "ar" else r.spec.name_en if lang == "en" else f"{r.spec.name_en} / {r.spec.name_ar}"
        cx, cy = n.center
        h = 0.18 if n.short > 2 else 0.12
        msp.add_text(name, height=h, dxfattribs={"layer": "A-ANNO-TEXT", "style": "PLAN"}) \
           .set_placement((cx, cy + h * 0.8), align=TextEntityAlignment.MIDDLE_CENTER)
        if r.spec.type != "corridor":
            msp.add_text(f"{n.area:.2f} m2  ({n.w:.2f}x{n.h:.2f})", height=h * 0.7,
                         dxfattribs={"layer": "A-ANNO-TEXT", "style": "PLAN"}) \
               .set_placement((cx, cy - h * 0.6), align=TextEntityAlignment.MIDDLE_CENTER)

    dim_attr = {"layer": "A-ANNO-DIMS"}
    override = {"dimtxt": 0.15, "dimasz": 0.1, "dimexe": 0.05, "dimexo": 0.05, "dimdec": 2}
    msp.add_linear_dim(base=(0, -1.0), p1=(0, 0), p2=(plan.width, 0), dimstyle="EZDXF",
                       override=override, dxfattribs=dim_attr).render()
    msp.add_linear_dim(base=(-1.0, 0), p1=(0, 0), p2=(0, plan.depth), angle=90, dimstyle="EZDXF",
                       override=override, dxfattribs=dim_attr).render()
    from .svg import _chain
    xs = _chain(plan, "front")
    for a, b in zip(xs, xs[1:]):
        msp.add_linear_dim(base=(0, -0.5), p1=(a, 0), p2=(b, 0), dimstyle="EZDXF",
                           override=override, dxfattribs=dim_attr).render()
    ys = _chain(plan, "left")
    for a, b in zip(ys, ys[1:]):
        msp.add_linear_dim(base=(-0.5, 0), p1=(0, a), p2=(0, b), angle=90, dimstyle="EZDXF",
                           override=override, dxfattribs=dim_attr).render()
    doc.saveas(path)

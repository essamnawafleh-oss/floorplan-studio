"""CAD export (DXF, opens in AutoCAD / BricsCAD / LibreCAD). Units: metres."""

from __future__ import annotations

import math

import ezdxf
from ezdxf.enums import TextEntityAlignment

from ..geometry import door_geometry, walls
from ..models import Plan

LAYERS = {
    "A-WALL": 7, "A-WALL-HATCH": 8, "A-DOOR": 3, "A-GLAZ": 5,
    "A-AREA": 9, "A-ANNO-TEXT": 2, "A-ANNO-DIMS": 1, "A-FURN": 30,
}


def to_dxf(plan: Plan, path: str, lang: str = "en", library=None) -> None:
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

    from ..blocks import BUILTIN, opening_polylines
    blocks = library.blocks if library else BUILTIN
    for o in plan.openings:
        g = o.gap_rect()
        block = blocks.get(o.block) if o.block else None
        if block:      # custom symbol: drawn exploded so it follows the opening size
            layer = "A-GLAZ" if o.kind == "window" else "A-DOOR"
            if o.kind == "window":
                msp.add_lwpolyline([(g.x0, g.y0), (g.x1, g.y0), (g.x1, g.y1), (g.x0, g.y1)], close=True,
                                   dxfattribs={"layer": layer})
            for pl in opening_polylines(block, o):
                msp.add_lwpolyline(pl, dxfattribs={"layer": layer})
            continue
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

    _furniture(doc, msp, plan, blocks)
    _drawing(doc, msp, plan)

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


def _furniture(doc, msp, plan, blocks):
    """Furniture as real DXF blocks (INSERT), so CAD users can move/swap them."""
    defined = {}
    for f in plan.furniture:
        b = blocks.get(f.block)
        if not b:
            continue
        name = defined.get(b.id)
        if name is None:
            name = "FP_" + "".join(ch if ch.isalnum() else "_" for ch in b.id.split("/", 1)[-1]).upper()
            if name not in doc.blocks:
                blk = doc.blocks.new(name)
                for p in b.prims:
                    attr = {"layer": "0"}
                    if p["t"] == "line":
                        blk.add_line(p["p"][:2], p["p"][2:], dxfattribs=attr)
                    elif p["t"] == "poly":
                        blk.add_lwpolyline(p["pts"], close=bool(p.get("closed")), dxfattribs=attr)
                    elif p["t"] == "circle":
                        blk.add_circle(p["c"], p["r"], dxfattribs=attr)
                    elif p["t"] == "arc":
                        blk.add_arc(p["c"], p["r"], p["a0"], p["a1"], dxfattribs=attr)
            defined[b.id] = name
        msp.add_blockref(name, (f.x, f.y), dxfattribs={"layer": "A-FURN", "rotation": f.rotation,
                                                         "xscale": f.scale, "yscale": f.scale})


def _drawing(doc, msp, plan):
    """Free CAD entities drawn in edit mode, on their own layers."""
    from ezdxf import colors
    from .. import cad
    hex2rgb = lambda h: (int(h[1:3], 16), int(h[3:5], 16), int(h[5:7], 16))
    for name, hexcol in cad.LAYERS.items():
        if name not in doc.layers:
            lay = doc.layers.add(name)
            lay.rgb = hex2rgb(hexcol)
    for e in plan.drawing:
        attr = {"layer": e.get("layer") or "A-DRAW"}
        if attr["layer"] not in doc.layers:
            doc.layers.add(attr["layer"])
        if e.get("color"):
            attr["true_color"] = colors.rgb2int(hex2rgb(e["color"]))
        t = e["t"]
        if t == "line":
            msp.add_line(e["p"][:2], e["p"][2:], dxfattribs=attr)
        elif t == "pline":
            msp.add_lwpolyline(e["pts"], close=bool(e.get("closed")), dxfattribs=attr)
        elif t == "circle":
            msp.add_circle(e["c"], e["r"], dxfattribs=attr)
        elif t == "arc":
            msp.add_arc(e["c"], e["r"], e["a0"], e["a1"], dxfattribs=attr)
        elif t == "text":
            msp.add_text(e["s"], height=e["h"], rotation=e.get("rot", 0),
                         dxfattribs={**attr, "style": "PLAN"}).set_placement(e["p"])
        elif t == "dim":
            p1, p2, off = e["p1"], e["p2"], e["off"]
            dx, dy = p2[0] - p1[0], p2[1] - p1[1]
            L = math.hypot(dx, dy) or 1.0
            k = ((off[0] - p1[0]) * -dy + (off[1] - p1[1]) * dx) / L
            msp.add_aligned_dim(p1=p1, p2=p2, distance=k, dimstyle="EZDXF",
                                override={"dimtxt": 0.15, "dimasz": 0.1, "dimdec": 2}, dxfattribs=attr).render()

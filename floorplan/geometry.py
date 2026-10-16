"""Wall solids (shapely) shared by all exporters."""

from __future__ import annotations

from shapely.geometry import MultiPolygon, Polygon, box
from shapely.ops import unary_union

from .models import Opening, Plan, Rect


def rect_poly(r: Rect) -> Polygon:
    return box(r.x0, r.y0, r.x1, r.y1)


def walls(plan: Plan, with_openings: bool = True, kinds: tuple[str, ...] = ("door", "main_door", "window")):
    """Wall polygons = footprint minus the net room areas (minus opening gaps)."""
    solid = box(0, 0, plan.width, plan.depth).difference(unary_union([rect_poly(r.net) for r in plan.rooms]))
    if with_openings:
        gaps = [rect_poly(o.gap_rect()) for o in plan.openings if o.kind in kinds]
        if gaps:
            solid = solid.difference(unary_union(gaps))
    return polygons(solid)


def polygons(geom) -> list[Polygon]:
    if geom.is_empty:
        return []
    if isinstance(geom, Polygon):
        return [geom]
    if isinstance(geom, MultiPolygon):
        return list(geom.geoms)
    return [g for g in getattr(geom, "geoms", []) if isinstance(g, Polygon)]


def door_geometry(o: Opening) -> tuple[tuple[float, float], tuple[float, float], tuple[float, float], float]:
    """hinge point, open-leaf end, closed-leaf end, radius - on the face of the
    wall on the side the door swings to."""
    s, w = o.seg, o.width
    face = s.coord + o.into * o.thickness / 2
    h_s = s.s0 if o.hinge == 0 else s.s1
    other = s.s1 if o.hinge == 0 else s.s0
    if s.orient == "h":
        hinge, closed, leaf = (h_s, face), (other, face), (h_s, face + o.into * w)
    else:
        hinge, closed, leaf = (face, h_s), (face, other), (face + o.into * w, h_s)
    return hinge, leaf, closed, w

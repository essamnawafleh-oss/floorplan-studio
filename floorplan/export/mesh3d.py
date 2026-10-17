"""3D model: walls with door/window openings, lintels, sills, floors, glass.
Exports GLB (Blender, Windows 3D Viewer, web) and OBJ."""

from __future__ import annotations

import trimesh
from trimesh.exchange.obj import export_obj
from shapely.geometry import box

from ..geometry import rect_poly, walls
from ..models import Plan, Rect

COLORS = {
    "wall": [235, 232, 226, 255], "slab": [180, 180, 178, 255], "glass": [140, 190, 230, 110],
    "door": [140, 98, 62, 255], "furniture": [186, 160, 128, 255],
    "public": [214, 190, 150, 255], "service": [190, 205, 190, 255],
    "private": [190, 200, 220, 255], "circulation": [215, 215, 210, 255],
}


def _paint(mesh: trimesh.Trimesh, rgba) -> trimesh.Trimesh:
    mat = trimesh.visual.material.PBRMaterial(
        baseColorFactor=rgba, metallicFactor=0.0, roughnessFactor=0.9,
        alphaMode="BLEND" if rgba[3] < 255 else "OPAQUE")
    mesh.visual = trimesh.visual.TextureVisuals(material=mat)
    return mesh


def _prism(r: Rect, z0: float, z1: float, color) -> trimesh.Trimesh:
    m = trimesh.creation.box(extents=(r.w, r.h, z1 - z0))
    m.apply_translation((r.x0 + r.w / 2, r.y0 + r.h / 2, (z0 + z1) / 2))
    return _paint(m, color)


def build_scene(plan: Plan, library=None) -> trimesh.Scene:
    st = plan.settings
    H = st["wall_height"]
    scene = trimesh.Scene()

    for i, p in enumerate(walls(plan)):
        m = trimesh.creation.extrude_polygon(p, H)
        scene.add_geometry(_paint(m, COLORS["wall"]), node_name=f"wall_{i}", geom_name=f"wall_{i}")

    for i, o in enumerate(plan.openings):
        g = o.gap_rect()
        if o.head < H:
            scene.add_geometry(_prism(g, o.head, H, COLORS["wall"]), geom_name=f"lintel_{i}")
        if o.kind == "window":
            scene.add_geometry(_prism(g, 0.0, o.sill, COLORS["wall"]), geom_name=f"sill_{i}")
            pane = Rect(g.x0, g.y0, g.x1, g.y1)
            th = 0.02
            if o.seg.orient == "h":
                pane = Rect(g.x0, o.seg.coord - th, g.x1, o.seg.coord + th)
            else:
                pane = Rect(o.seg.coord - th, g.y0, o.seg.coord + th, g.y1)
            scene.add_geometry(_prism(pane, o.sill, o.head, COLORS["glass"]), geom_name=f"glass_{i}")

    from ..blocks import BUILTIN, furniture_footprint
    from shapely.geometry import Polygon
    blocks = library.blocks if library else BUILTIN
    for i, f in enumerate(plan.furniture):
        b = blocks.get(f.block)
        if b:
            m = trimesh.creation.extrude_polygon(Polygon(furniture_footprint(b, f)), b.height)
            scene.add_geometry(_paint(m, COLORS["furniture"]), geom_name=f"furniture_{i}")

    slab = trimesh.creation.extrude_polygon(box(0, 0, plan.width, plan.depth), 0.2)
    slab.apply_translation((0, 0, -0.2))
    scene.add_geometry(_paint(slab, COLORS["slab"]), geom_name="slab")
    for r in plan.rooms:
        f = trimesh.creation.extrude_polygon(rect_poly(r.net), 0.02)
        scene.add_geometry(_paint(f, COLORS.get(r.spec.zone, COLORS["slab"])), geom_name=f"floor_{r.id}")
    return scene


def to_glb(plan: Plan, path: str, library=None) -> None:
    build_scene(plan, library).export(path)


def to_obj(plan: Plan, path: str, library=None) -> None:
    """Plain geometry (no material files) - colours live in the GLB."""
    mesh = trimesh.util.concatenate(list(build_scene(plan, library).dump()))
    with open(path, "w", encoding="utf-8") as f:
        f.write(export_obj(mesh, include_texture=False, include_color=False))

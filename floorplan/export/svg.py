"""2D plan as SVG: walls, doors with swing, windows, labels, dimensions."""

from __future__ import annotations

import math
from xml.sax.saxutils import escape

from ..geometry import door_geometry, walls
from ..i18n import text
from ..models import Plan

ZONE_FILL = {"public": "#f6ead7", "service": "#e3efe4", "private": "#e4ebf6", "circulation": "#f1f1ef"}
WALL = "#26282c"
INK = "#3a3d42"
FONT = "'Noto Naskh Arabic','Segoe UI','Tahoma','Arial',sans-serif"


class _T:
    """metres -> svg px, y flipped."""
    def __init__(self, plan: Plan, s: float, m: float, top: float):
        self.s, self.m, self.top, self.D = s, m, top, plan.depth

    def __call__(self, x: float, y: float) -> tuple[float, float]:
        return self.m + x * self.s, self.top + (self.D - y) * self.s


def _ring(t, coords) -> str:
    pts = [t(x, y) for x, y in coords]
    return "M" + " L".join(f"{x:.1f},{y:.1f}" for x, y in pts) + " Z"


def _dim(t, out, a, b, offset, orient, label):
    """Linear dimension between a and b (metres along x or y), offset in metres."""
    if orient == "h":
        (x0, y0), (x1, _) = t(a, offset), t(b, offset)
        out.append(f'<line x1="{x0:.1f}" y1="{y0:.1f}" x2="{x1:.1f}" y2="{y0:.1f}" class="dim"/>')
        for x in (x0, x1):
            out.append(f'<line x1="{x - 4:.1f}" y1="{y0 + 4:.1f}" x2="{x + 4:.1f}" y2="{y0 - 4:.1f}" class="tick"/>')
        out.append(f'<text x="{(x0 + x1) / 2:.1f}" y="{y0 - 5:.1f}" class="dimt">{label}</text>')
    else:
        (x0, y0), (_, y1) = t(offset, a), t(offset, b)
        out.append(f'<line x1="{x0:.1f}" y1="{y0:.1f}" x2="{x0:.1f}" y2="{y1:.1f}" class="dim"/>')
        for y in (y0, y1):
            out.append(f'<line x1="{x0 - 4:.1f}" y1="{y + 4:.1f}" x2="{x0 + 4:.1f}" y2="{y - 4:.1f}" class="tick"/>')
        cy = (y0 + y1) / 2
        out.append(f'<text x="{x0 - 6:.1f}" y="{cy:.1f}" class="dimt" transform="rotate(-90 {x0 - 6:.1f} {cy:.1f})">{label}</text>')


def _chain(plan: Plan, side: str) -> list[float]:
    """Partition coordinates of rooms along the front (x) or left (y) wall."""
    te = plan.settings["exterior_wall"]
    if side == "front":
        cuts = {r.rect.x0 for r in plan.rooms if abs(r.rect.y0 - te) < 1e-6} | \
               {r.rect.x1 for r in plan.rooms if abs(r.rect.y0 - te) < 1e-6}
        return sorted({0.0, plan.width} | {c for c in cuts if te + 0.05 < c < plan.width - te - 0.05})
    cuts = {r.rect.y0 for r in plan.rooms if abs(r.rect.x0 - te) < 1e-6} | \
           {r.rect.y1 for r in plan.rooms if abs(r.rect.x0 - te) < 1e-6}
    return sorted({0.0, plan.depth} | {c for c in cuts if te + 0.05 < c < plan.depth - te - 0.05})


def to_svg(plan: Plan, lang: str = "both", scale: float = 60.0, library=None) -> str:
    from ..blocks import BUILTIN, furniture_polylines, opening_polylines
    blocks = library.blocks if library else BUILTIN

    def polys(lines, cls):
        for pl in lines:
            out.append('<polyline points="' + " ".join("%.1f,%.1f" % t(x, y) for x, y in pl) + f'" class="{cls}"/>')

    s, m, top = scale, 110.0, 90.0
    t = _T(plan, s, m, top)
    W, H = plan.width * s + 2 * m, plan.depth * s + top + 140
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W:.0f} {H:.0f}" width="{W:.0f}" height="{H:.0f}">',
           f"""<style>
  .wall{{fill:{WALL};fill-rule:evenodd}}
  .room{{stroke:none}}
  .door{{fill:none;stroke:{INK};stroke-width:1.4}}
  .swing{{fill:none;stroke:{INK};stroke-width:0.8;stroke-dasharray:4 3}}
  .win{{fill:#ffffff;stroke:{INK};stroke-width:1}}
  .glass{{stroke:#4a7fb5;stroke-width:1.2}}
  .glassb{{fill:none;stroke:#4a7fb5;stroke-width:1.1}}
  .furn{{fill:none;stroke:#5a5f66;stroke-width:1}}
  .name{{font-family:{FONT};font-weight:700;fill:#22252a;text-anchor:middle}}
  .area{{font-family:{FONT};fill:#555a62;text-anchor:middle}}
  .dim{{stroke:#7a7f87;stroke-width:0.8}}
  .tick{{stroke:#7a7f87;stroke-width:1.2}}
  .dimt{{font-family:{FONT};font-size:12px;fill:#4a4f57;text-anchor:middle}}
  .title{{font-family:{FONT};font-size:18px;font-weight:700;fill:#22252a}}
  .meta{{font-family:{FONT};font-size:12px;fill:#666b73}}
</style>""",
           f'<rect width="100%" height="100%" fill="#ffffff"/>']

    for r in plan.rooms:
        (x0, y1), (x1, y0) = t(r.net.x0, r.net.y0), t(r.net.x1, r.net.y1)
        out.append(f'<rect x="{x0:.1f}" y="{y0:.1f}" width="{x1 - x0:.1f}" height="{y1 - y0:.1f}" '
                   f'fill="{ZONE_FILL.get(r.spec.zone, "#eee")}" class="room"/>')

    for p in walls(plan):
        d = _ring(t, p.exterior.coords) + "".join(_ring(t, h.coords) for h in p.interiors)
        out.append(f'<path d="{d}" class="wall"/>')

    for o in plan.openings:
        g = o.gap_rect()
        block = blocks.get(o.block) if o.block else None
        if o.kind == "window":
            (x0, y1), (x1, y0) = t(g.x0, g.y0), t(g.x1, g.y1)
            out.append(f'<rect x="{x0:.1f}" y="{y0:.1f}" width="{x1 - x0:.1f}" height="{y1 - y0:.1f}" class="win"/>')
            if block:
                polys(opening_polylines(block, o), "glassb")
            elif o.seg.orient == "h":
                yc = (y0 + y1) / 2
                out.append(f'<line x1="{x0:.1f}" y1="{yc:.1f}" x2="{x1:.1f}" y2="{yc:.1f}" class="glass"/>')
            else:
                xc = (x0 + x1) / 2
                out.append(f'<line x1="{xc:.1f}" y1="{y0:.1f}" x2="{xc:.1f}" y2="{y1:.1f}" class="glass"/>')
        elif block:
            polys(opening_polylines(block, o), "door")
        else:
            hinge, leaf, closed, w = door_geometry(o)
            hx, hy = t(*hinge)
            lx, ly = t(*leaf)
            pts = []
            a0 = math.atan2(leaf[1] - hinge[1], leaf[0] - hinge[0])
            a1 = math.atan2(closed[1] - hinge[1], closed[0] - hinge[0])
            da = (a1 - a0 + math.pi) % (2 * math.pi) - math.pi
            for i in range(17):
                a = a0 + da * i / 16
                pts.append(t(hinge[0] + w * math.cos(a), hinge[1] + w * math.sin(a)))
            out.append(f'<line x1="{hx:.1f}" y1="{hy:.1f}" x2="{lx:.1f}" y2="{ly:.1f}" class="door"/>')
            out.append('<polyline points="' + " ".join(f"{x:.1f},{y:.1f}" for x, y in pts) + '" class="swing"/>')

    for f in plan.furniture:
        b = blocks.get(f.block)
        if b:
            polys(furniture_polylines(b, f.x, f.y, f.rotation, f.scale), "furn")

    from .. import cad
    for e in plan.drawing:
        col = e.get("color") or cad.LAYERS.get(e.get("layer", ""), "#3a3d42")
        if e["t"] == "text":
            x, y = t(*e["p"])
            out.append(f'<text x="{x:.1f}" y="{y:.1f}" font-size="{e["h"] * scale:.1f}" fill="{col}" '
                       f'transform="rotate({-e.get("rot", 0):.1f} {x:.1f} {y:.1f})" font-family="Arial">{escape(e["s"])}</text>')
            continue
        for pl in cad.polylines(e):
            out.append('<polyline points="' + " ".join("%.1f,%.1f" % t(px, py) for px, py in pl)
                       + f'" fill="none" stroke="{col}" stroke-width="1.2"/>')
        if e["t"] == "dim":
            q1, q2 = cad.dim_lines(e)[2]
            x, y = t((q1[0] + q2[0]) / 2, (q1[1] + q2[1]) / 2)
            out.append(f'<text x="{x:.1f}" y="{y - 4:.1f}" class="dimt" fill="{col}">{cad.dim_value(e):.2f}</text>')

    for r in plan.rooms:
        cx, cy = t(*r.net.center)
        names = [r.spec.name_ar] if lang == "ar" else [r.spec.name_en] if lang == "en" else [r.spec.name_ar, r.spec.name_en]
        if r.spec.type == "corridor":
            names = names[:1]
        width_px = r.net.w * s
        fs = max(8.0, min(15.0, width_px / (max(len(n) for n in names) * 0.62)))
        lines = [(n, "name", fs) for n in names]
        if r.spec.type != "corridor":
            lines.append((f"{r.net.area:.1f} m²", "area", fs * 0.8))
            lines.append((f"{r.net.w:.2f} × {r.net.h:.2f}", "area", fs * 0.72))
        total = sum(f * 1.25 for _, _, f in lines)
        y = cy - total / 2
        for txt, cls, f in lines:
            y += f * 1.25
            direction = ' direction="rtl"' if any("؀" <= ch <= "ۿ" for ch in txt) else ""
            out.append(f'<text x="{cx:.1f}" y="{y - f * 0.25:.1f}" class="{cls}" font-size="{f:.1f}"{direction}>{escape(txt)}</text>')

    xs = _chain(plan, "front")
    for a, b in zip(xs, xs[1:]):
        _dim(t, out, a, b, -0.55, "h", f"{b - a:.2f}")
    _dim(t, out, 0, plan.width, -1.15, "h", f"{plan.width:.2f}")
    ys = _chain(plan, "left")
    for a, b in zip(ys, ys[1:]):
        _dim(t, out, a, b, -0.55, "v", f"{b - a:.2f}")
    _dim(t, out, 0, plan.depth, -1.15, "v", f"{plan.depth:.2f}")

    tl = "ar" if lang == "ar" else "en"
    title = escape(plan.project or "Floor plan")
    out.append(f'<text x="{m:.0f}" y="34" class="title">{title}</text>')
    out.append(f'<text x="{m:.0f}" y="56" class="meta">{text("total_area", tl)}: {plan.gross_area:.1f} m²   ·   '
               f'{text("net_area", tl)}: {plan.net_area:.1f} m²   ·   {text("seed", tl)}: {plan.seed}</text>')
    fx, fy = t(plan.width / 2, 0)
    out.append(f'<text x="{fx:.0f}" y="{fy + 105:.0f}" class="meta" text-anchor="middle">▲ FRONT / الواجهة الأمامية</text>')
    out.append("</svg>")
    return "\n".join(out)

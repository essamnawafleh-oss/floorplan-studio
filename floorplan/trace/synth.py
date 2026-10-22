"""A raster drawing of a Plan, like a screenshot of a plan: used by the tests and
the self-test to check that tracing gives the plan back."""

from __future__ import annotations

import math

import numpy as np

from ..geometry import door_geometry, walls
from ..models import Plan


def render(plan: Plan, ppm: float = 60, margin: float = 1.5, labels: bool = True, dims: bool = True,
           outline: bool = False, furniture: bool = True) -> np.ndarray:
    import cv2
    W, D = plan.width, plan.depth
    w, h = int((W + 2 * margin) * ppm), int((D + 2 * margin) * ppm)
    img = np.full((h, w), 255, np.uint8)

    def P(x, y):
        return int(round((x + margin) * ppm)), int(round((D - y + margin) * ppm))

    for poly in walls(plan):
        for ring, fill in [(poly.exterior, 0)] + [(i, 255) for i in poly.interiors]:
            pts = np.array([P(x, y) for x, y in ring.coords], np.int32)
            if outline:
                cv2.polylines(img, [pts], True, 0, 2)
            else:
                cv2.fillPoly(img, [pts], fill)
    lw = max(1, int(ppm / 40))
    for o in plan.openings:
        s, t = o.seg, o.thickness / 2
        if o.kind == "window":
            for off in (-t, -t / 3, t / 3, t):
                a, b = ((s.s0, s.coord + off), (s.s1, s.coord + off)) if s.orient == "h" else \
                    ((s.coord + off, s.s0), (s.coord + off, s.s1))
                cv2.line(img, P(*a), P(*b), 0, lw)
            continue
        hinge, leaf, _closed, r = door_geometry(o)
        cv2.line(img, P(*hinge), P(*leaf), 0, lw)
        c = P(*hinge)
        a0 = math.degrees(math.atan2(-(leaf[1] - hinge[1]), leaf[0] - hinge[0]))
        a1 = math.degrees(math.atan2(-(_closed[1] - hinge[1]), _closed[0] - hinge[0]))
        if (a1 - a0) % 360 > 180:
            a0, a1 = a1, a0
        cv2.ellipse(img, c, (int(r * ppm), int(r * ppm)), 0, a0, a0 + (a1 - a0) % 360, 0, lw)
    if furniture:
        for r in plan.rooms:
            if r.spec.type in ("bedroom", "master"):
                n = r.net
                cv2.rectangle(img, P(n.x0 + 0.3, n.y1 - 0.2), P(n.x0 + 1.9, n.y1 - 2.2), 0, lw)
    if labels:
        for r in plan.rooms:
            cx, cy = r.net.center
            txt = r.spec.name_en.upper() or r.spec.type.upper()
            fs = ppm / 90
            (tw, th), _ = cv2.getTextSize(txt, cv2.FONT_HERSHEY_SIMPLEX, fs, 2)
            x, y = P(cx, cy)
            cv2.putText(img, txt, (x - tw // 2, y), cv2.FONT_HERSHEY_SIMPLEX, fs, 0, 2)
    if dims:
        x, y = P(0, -0.8)
        x2, _ = P(W, 0)
        cv2.line(img, (x, y), (x2, y), 0, 1)
        txt = f"{W:.2f}"
        (tw, th), _ = cv2.getTextSize(txt, cv2.FONT_HERSHEY_SIMPLEX, ppm / 70, 2)
        cv2.putText(img, txt, ((x + x2 - tw) // 2, y - 6), cv2.FONT_HERSHEY_SIMPLEX, ppm / 70, 0, 2)
    return img

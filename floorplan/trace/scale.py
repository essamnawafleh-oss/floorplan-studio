"""Metres per pixel, from what the drawing tells us.

Every number we can read proposes scales (a length between the walls that
bracket it, a room's 'W x L', a room area, the overall size, a '1:100' note on
a PDF); door openings propose door width / gap. The scale most candidates
agree on (within 3 %) wins - one misread number cannot move it."""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from .detect import Analysis, readings

TOL = 0.03


@dataclass
class Vote:
    scale: float                 # metres per pixel
    weight: float
    why: str
    text: str = ""


@dataclass
class ScaleResult:
    scale: float | None
    support: int
    votes: list[Vote] = field(default_factory=list)
    agreeing: list[Vote] = field(default_factory=list)


def _bracket(coords: list[float], c: float) -> tuple[float, float] | None:
    lo = [x for x in coords if x < c]
    hi = [x for x in coords if x > c]
    return (max(lo), min(hi)) if lo and hi else None


def dimension_votes(a: Analysis) -> list[Vote]:
    votes = []
    x0, y0, x1, y1 = a.bbox
    vx = sorted({ln.coord for ln in a.lines if ln.orient == "v"} | {x0 + a.t_ext / 2, x1 - a.t_ext / 2})
    hy = sorted({ln.coord for ln in a.lines if ln.orient == "h"} | {y0 + a.t_ext / 2, y1 - a.t_ext / 2})
    inside = a.silhouette
    region_of = {id(t): r for r in a.regions for t in r.texts}
    for tok, rd in readings(a):
        cx, cy = tok.center
        r = region_of.get(id(tok))
        if rd.kind == "scale" and a.src.dpi:
            votes.append(Vote(rd.values[0] * 0.0254 / a.src.dpi, 3.0, "scale", tok.text))
        elif rd.kind == "area" and r is not None:
            votes.append(Vote(math.sqrt(rd.values[0] / r.area), 1.5, "area", tok.text))
        elif rd.kind == "pair" and r is not None:
            w = r.bbox[2] - r.bbox[0]
            h = r.bbox[3] - r.bbox[1]
            p, q = rd.values
            for va, vb in ((p, q), (q, p)):
                sa, sb = va / w, vb / h
                if abs(sa - sb) / max(sa, sb) < 0.06:          # both sides agree: strong evidence
                    votes.append(Vote((sa + sb) / 2, 2.5, "room", tok.text))
        elif rd.kind == "len":
            v = rd.values[0]
            horizontal = not tok.vertical and (tok.box[2] - tok.box[0]) >= (tok.box[3] - tok.box[1])
            coords, c = (vx, cx) if horizontal else (hy, cy)
            ix, iy = int(min(max(cx, 0), inside.shape[1] - 1)), int(min(max(cy, 0), inside.shape[0] - 1))
            outside = not inside[iy, ix]
            b = _bracket(coords, c)
            if b:
                span = b[1] - b[0]
                for px, why in ((span, "axis"), (span - a.t_int, "clear"), (span + a.t_int, "outer")):
                    if px > 4 * a.t_int:
                        votes.append(Vote(v / px, 1.0, why, tok.text))
            if outside:                                          # overall dimension outside the building
                total = (x1 - x0) if horizontal else (y1 - y0)
                votes.append(Vote(v / total, 1.2, "overall", tok.text))
            if r is not None:                                    # a single number inside a room: its width/length
                w, h = r.bbox[2] - r.bbox[0], r.bbox[3] - r.bbox[1]
                for px in (w, h):
                    votes.append(Vote(v / px, 0.4, "room side", tok.text))
    return [vt for vt in votes if 1e-5 < vt.scale < 1.0]


def door_gaps(a: Analysis) -> list[float]:
    """Widths (px) of openings in interior walls: runs of free pixels along
    wall lines between wall pieces."""
    out = []
    W = a.walls
    x0, y0, x1, y1 = a.bbox
    for ln in a.lines:
        edge = (x0, x1) if ln.orient == "v" else (y0, y1)
        if min(abs(ln.coord - e) for e in edge) < 1.5 * a.t_ext:      # exterior walls: windows
            continue
        c = int(round(ln.coord))
        lo, hi = int(ln.s0), int(ln.s1)
        if ln.orient == "v":
            if not (0 <= c < W.shape[1]):
                continue
            prof = W[lo:hi, c]
        else:
            if not (0 <= c < W.shape[0]):
                continue
            prof = W[c, lo:hi]
        p = np.concatenate([[1], prof.astype(np.int8), [1]])
        d = np.diff(p)
        st, en = np.nonzero(d == -1)[0], np.nonzero(d == 1)[0]
        for s, e in zip(st, en):
            g = e - s
            if 2.5 * a.t_int <= g <= 8 * a.t_int:
                out.append(float(g))
    return out


def best(votes: list[Vote]) -> ScaleResult:
    if not votes:
        return ScaleResult(None, 0, votes)
    logs = np.log([v.scale for v in votes])
    wts = np.array([v.weight for v in votes])
    tol = math.log(1 + TOL)
    score = [(wts[np.abs(logs - lv) <= tol].sum(), i) for i, lv in enumerate(logs)]
    sc, i = max(score)
    agree = [votes[j] for j in range(len(votes)) if abs(logs[j] - logs[i]) <= tol]
    texts = {(v.text, v.why) for v in agree}
    scale = float(np.exp(np.average([math.log(v.scale) for v in agree], weights=[v.weight for v in agree])))
    return ScaleResult(scale, len({t for t, _ in texts}), votes, agree)


def from_dimensions(a: Analysis) -> ScaleResult:
    return best(dimension_votes(a))


def from_door(a: Analysis, door_m: float = 0.9) -> ScaleResult:
    gaps = door_gaps(a)
    if not gaps:
        return ScaleResult(None, 0)
    g = float(np.median(gaps))
    return ScaleResult(door_m / g, len(gaps), [Vote(door_m / x, 1.0, "door") for x in gaps])


def from_line(px_len: float, metres: float) -> float | None:
    return metres / px_len if px_len > 0 and metres > 0 else None

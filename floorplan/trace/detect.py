"""Finding walls and rooms on a raster drawing (OpenCV + numpy, pixels only).

Walls are the thick dark strokes: an opening with a square kernel removes
the thin lines (furniture, door swings, window glass, dimension lines) and
the text boxes are blanked first. Drawings with walls as two thin lines
("outline" style) are filled between the lines before that. Door gaps are
bridged along the wall direction only, so they close without merging rooms;
the free space left inside the building silhouette is the rooms."""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from .labels import parse, room_type_from_text
from .source import Source, TextToken


@dataclass
class Region:
    label: int
    area: int                                   # pixels
    bbox: tuple[int, int, int, int]             # x0, y0, x1, y1 (exclusive)
    centroid: tuple[float, float]
    texts: list[TextToken] = field(default_factory=list)
    guess: str = ""                             # room type read from the words inside
    shape: np.ndarray | None = None             # bool mask cropped to bbox (net room area)


@dataclass
class WallLine:
    orient: str                                 # "v": x = coord ; "h": y = coord
    coord: float
    s0: float
    s1: float
    thick: float


@dataclass
class Analysis:
    src: Source
    gray: np.ndarray
    angle: float                                # deskew applied (degrees)
    dark: np.ndarray
    walls: np.ndarray
    barrier: np.ndarray                         # walls with door gaps bridged
    silhouette: np.ndarray
    labels: np.ndarray                          # room label per pixel (0 = none)
    regions: list[Region]
    lines: list[WallLine]
    bbox: tuple[int, int, int, int]             # building outline (outer faces), pixels
    t_int: float                                # interior wall thickness, pixels
    t_ext: float                                # exterior wall thickness, pixels
    style: str                                  # "filled" | "outline"
    texts: list[TextToken]
    quality: float

    @property
    def thin(self) -> np.ndarray:
        """Thin strokes inside the building: furniture, fixtures, door swings."""
        return self.dark & ~self.walls & self.silhouette


# --- numpy helpers ---------------------------------------------------------------------
def run_lengths(m: np.ndarray, axis: int = 1) -> np.ndarray:
    """Length of the run of True each pixel belongs to, along rows (axis=1) or columns."""
    if axis == 0:
        return run_lengths(m.T, 1).T
    h, w = m.shape
    p = np.zeros((h, w + 2), np.int8)
    p[:, 1:-1] = m
    d = np.diff(p, axis=1)
    st = np.argwhere(d == 1)
    en = np.argwhere(d == -1)
    out = np.zeros((h, w), np.int32)
    if not len(st):
        return out
    ln = en[:, 1] - st[:, 1]
    rows = np.repeat(st[:, 0], ln)
    offs = np.arange(ln.sum()) - np.repeat(np.cumsum(ln) - ln, ln)
    out[rows, np.repeat(st[:, 1], ln) + offs] = np.repeat(ln, ln)
    return out


def _close_line(m: np.ndarray, g: int, axis: int) -> np.ndarray:
    import cv2
    g = max(1, int(g))
    k = np.ones((1, g) if axis == 1 else (g, 1), np.uint8)
    pad = ((0, 0), (g, g)) if axis == 1 else ((g, g), (0, 0))   # nothing is closed against the paper edge
    out = cv2.morphologyEx(np.pad(m.astype(np.uint8), pad), cv2.MORPH_CLOSE, k)
    return (out[:, g:-g] if axis == 1 else out[g:-g, :]).astype(bool)


def _fill_holes(m: np.ndarray) -> np.ndarray:
    import cv2
    h, w = m.shape
    pad = np.zeros((h + 2, w + 2), np.uint8)
    pad[1:-1, 1:-1] = m
    flood = pad.copy()
    mask = np.zeros((h + 4, w + 4), np.uint8)
    cv2.floodFill(flood, mask, (0, 0), 1)
    return (flood == 0)[1:-1, 1:-1] | m.astype(bool)


def _drop_small(m: np.ndarray, min_area: float) -> np.ndarray:
    import cv2
    n, lab, stats, _ = cv2.connectedComponentsWithStats(m.astype(np.uint8), connectivity=8)
    keep = np.zeros(n, bool)
    keep[1:] = stats[1:, cv2.CC_STAT_AREA] >= min_area
    return keep[lab]


# --- steps ---------------------------------------------------------------------------------
def binarize(gray: np.ndarray, threshold: int = 0) -> np.ndarray:
    import cv2
    if threshold:
        return gray < threshold
    t, _ = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return gray <= min(t, 235)


def deskew_angle(dark: np.ndarray) -> float:
    """Small rotation of a scanned/photographed plan (degrees), 0 if straight."""
    import cv2
    m = cv2.morphologyEx(dark.astype(np.uint8) * 255, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    lines = cv2.HoughLinesP(m, 1, np.pi / 720, 80, minLineLength=max(40, min(m.shape) // 12), maxLineGap=4)
    if lines is None:
        return 0.0
    angs, wts = [], []
    for x1, y1, x2, y2 in lines.reshape(-1, 4):
        a = math.degrees(math.atan2(y2 - y1, x2 - x1))
        a = (a + 45) % 90 - 45                     # deviation from the nearest axis
        angs.append(a)
        wts.append(math.hypot(x2 - x1, y2 - y1))
    order = np.argsort(angs)
    cum = np.cumsum(np.asarray(wts)[order])
    a = float(np.asarray(angs)[order][np.searchsorted(cum, cum[-1] / 2)])
    if not 0.15 < abs(a) < 15:
        return 0.0
    # refine: straight walls make the row/column ink profiles sharpest
    f = min(1.0, 1000 / max(m.shape))
    small = cv2.resize(m, None, fx=f, fy=f, interpolation=cv2.INTER_AREA).astype(np.float32)
    h, w = small.shape

    def sharp(ang):
        M = cv2.getRotationMatrix2D((w / 2, h / 2), ang, 1.0)
        r = cv2.warpAffine(small, M, (w, h))
        return float((r.sum(1) ** 2).sum() + (r.sum(0) ** 2).sum())

    best = max(np.arange(a - 0.6, a + 0.6, 0.05), key=sharp)
    return float(best) if 0.15 < abs(best) < 15 else 0.0


def rotate(gray: np.ndarray, texts: list[TextToken], angle: float):
    import cv2
    if not angle:
        return gray, texts
    h, w = gray.shape
    M = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
    out = cv2.warpAffine(gray, M, (w, h), flags=cv2.INTER_LINEAR, borderValue=255)
    moved = []
    for t in texts:
        cx, cy = t.center
        nx, ny = M @ np.array([cx, cy, 1.0])
        hw, hh = (t.box[2] - t.box[0]) / 2, (t.box[3] - t.box[1]) / 2
        moved.append(TextToken(t.text, (nx - hw, ny - hh, nx + hw, ny + hh), t.source, t.score, t.vertical))
    return out, moved


def thickness_histogram(m: np.ndarray) -> np.ndarray:
    hr, vr = run_lengths(m, 1), run_lengths(m, 0)
    th = np.minimum(hr, vr)
    ln = np.maximum(hr, vr)
    sel = m & (th >= 1) & (ln >= 3 * th)          # elongated strokes only
    hist = np.bincount(np.minimum(th[sel], 300), minlength=301).astype(float)
    return np.convolve(hist, [0.25, 0.5, 0.25], mode="same")


def wall_thickness(m: np.ndarray) -> float:
    """Most common thickness of the thick strokes (pixels)."""
    hist = thickness_histogram(m)
    hist[:3] = 0
    if hist.sum() == 0:
        return 3.0
    return float(np.argmax(hist))


def stroke_classes(m: np.ndarray) -> tuple[float, float]:
    """(thin line width, thinnest wall thickness) in pixels."""
    hist = thickness_histogram(m)
    hist[0] = 0
    t_dom = wall_thickness(m)
    lim = max(2, min(int(t_dom * 0.35), 6))      # thin lines are a few pixels at most
    line = float(np.argmax(hist[:lim + 1])) if hist[:lim + 1].any() else 1.0
    peak = hist[int(t_dom)]
    t_min = t_dom
    for t in range(int(line) + 2, int(t_dom)):
        if hist[t] >= 0.12 * peak and hist[t] >= hist[t - 1] and hist[t] >= hist[t + 1]:
            t_min = float(t)
            break
    return line, t_min


def fill_outline_walls(dark: np.ndarray, half: float) -> np.ndarray:
    """Fill long narrow enclosed spaces (between the two lines of a wall)."""
    import cv2
    free = (~dark).astype(np.uint8)
    n, lab, stats, _ = cv2.connectedComponentsWithStats(free, connectivity=4)
    dt = cv2.distanceTransform(free, cv2.DIST_L2, 3)
    mx = np.zeros(n, np.float32)
    np.maximum.at(mx, lab.ravel(), dt.ravel())
    w, h = stats[:, cv2.CC_STAT_WIDTH], stats[:, cv2.CC_STAT_HEIGHT]
    fill = (mx <= half) & (np.maximum(w, h) >= 8 * half) & (stats[:, cv2.CC_STAT_AREA] >= 6 * half * half)
    fill[0] = False
    big = np.argmax(stats[1:, cv2.CC_STAT_AREA]) + 1 if n > 1 else 0
    fill[big] = False                             # the paper around the drawing
    return dark | fill[lab]


def _wall_lines(barrier_h: np.ndarray, barrier_v: np.ndarray, t: float) -> list[WallLine]:
    import cv2
    out = []
    for orient, m in (("v", barrier_v), ("h", barrier_h)):
        n, lab, stats, cent = cv2.connectedComponentsWithStats(m.astype(np.uint8), connectivity=8)
        for i in range(1, n):
            x, y, w, h, a = stats[i]
            length, thick = (h, a / max(1, h)) if orient == "v" else (w, a / max(1, w))
            if length < 2.5 * t or thick < 0.4 * t:
                continue
            c = cent[i][0] if orient == "v" else cent[i][1]
            s0, s1 = (y, y + h) if orient == "v" else (x, x + w)
            out.append(WallLine(orient, float(c), float(s0), float(s1), float(thick)))
    return out


def _segment(dark, texts, t_hint: float, door_gap: float, window_gap: float):
    """walls -> silhouette -> rooms, for one wall mask."""
    import cv2
    line, t_min = stroke_classes(dark)
    t = t_hint or t_min
    k = max(2, int(line) + 1, int(math.ceil(0.6 * t_hint)) if t_hint else int(math.ceil(0.55 * t_min)))
    walls = cv2.morphologyEx(dark.astype(np.uint8), cv2.MORPH_OPEN, np.ones((k, k), np.uint8)).astype(bool)
    walls = _drop_small(walls, 4 * t * t)
    if not t_hint:
        t = max(2.0, wall_thickness(walls))
    hr, vr = run_lengths(walls, 1), run_lengths(walls, 0)
    hm, vm = walls & (hr >= vr), walls & (vr > hr)
    shell = walls | _close_line(hm, window_gap * t, 1) | _close_line(vm, window_gap * t, 0)
    sil = _fill_holes(shell)
    sil = _drop_small(sil, 0.05 * sil.sum()) if sil.any() else sil
    bh, bv = _close_line(hm, door_gap * t, 1), _close_line(vm, door_gap * t, 0)
    barrier = shell | bh | bv
    free = sil & ~barrier
    n, lab, stats, cent = cv2.connectedComponentsWithStats(free.astype(np.uint8), connectivity=4)
    dt = cv2.distanceTransform(free.astype(np.uint8), cv2.DIST_L2, 3)
    rad = np.zeros(n, np.float32)                     # inscribed radius of every free piece
    np.maximum.at(rad, lab.ravel(), dt.ravel())
    rad[0] = 0
    min_area = max(30 * t * t, 0.002 * sil.sum())
    H, Wd = free.shape
    cand = []
    for i in range(1, n):
        x, y, w, h, a = stats[i]
        if a < min_area or x == 0 or y == 0 or x + w >= Wd or y + h >= H:
            continue
        if min(w, h) < 2.5 * t or rad[i] < 1.2 * t:  # slivers and pockets inside double wall lines
            continue
        cand.append(i)
    rmax = max((rad[i] for i in cand), default=0)
    junk = [i for i in cand if rad[i] < 0.1 * rmax]
    regions, keep = [], np.zeros(n, np.int32)
    for i in cand:
        if i in junk:
            continue
        x, y, w, h, a = stats[i]
        keep[i] = len(regions) + 1
        regions.append(Region(len(regions) + 1, int(a), (int(x), int(y), int(x + w), int(y + h)),
                              (float(cent[i][0]), float(cent[i][1]))))
    labels = keep[lab]
    junk = len(junk) / max(1, len(cand))
    for r in regions:
        x0, y0, x1, y1 = r.bbox
        r.shape = labels[y0:y1, x0:x1] == r.label
    cover = sum(r.area for r in regions) / max(1, sil.sum())
    quality = cover * min(1.0, len(regions) / 3) * (1 - junk)
    ys, xs = np.nonzero(sil)
    bbox = (int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1) if len(xs) else (0, 0, Wd, H)
    # exterior wall thickness: wall pixels in a band along the silhouette edge
    import cv2 as _cv
    inner = _cv.erode(sil.astype(np.uint8), np.ones((3, 3), np.uint8), iterations=max(1, int(2.5 * t)))
    ring = walls & ~inner.astype(bool)
    t_ext = wall_thickness(ring) if ring.sum() > 50 else t
    if not (0.6 * t <= t_ext <= 2.5 * t):
        t_ext = t
    inner_walls = walls & inner.astype(bool)
    t_int = wall_thickness(inner_walls) if inner_walls.sum() > 50 else t
    if not (0.4 * t <= t_int <= 1.6 * t):
        t_int = t
    lines = _wall_lines(hm | bh, vm | bv, t_int)
    lines = [ln for ln in lines if (ln.orient == "v" and (ln.s1 - ln.s0) > ln.thick * 2.0) or
             (ln.orient == "h" and (ln.s1 - ln.s0) > ln.thick * 2.0)]
    return dict(walls=walls, barrier=barrier, silhouette=sil, labels=labels, regions=regions, lines=lines,
                bbox=bbox, t_int=float(t_int), t_ext=float(t_ext), quality=quality)


def analyse(src: Source, wall_style: str = "auto", wall_px: float = 0, threshold: int = 0,
            door_gap: float = 7.0, window_gap: float = 22.0, deskew: bool = True) -> Analysis:
    """wall_px: wall thickness in pixels (0 = measure it). door_gap/window_gap:
    the widest opening bridged, in wall thicknesses."""
    texts = [t for t in src.texts]
    gray = src.gray
    dark = binarize(gray, threshold)
    angle = deskew_angle(dark) if deskew else 0.0
    if angle:
        gray, texts = rotate(gray, texts, angle)
        dark = binarize(gray, threshold)
    for t in texts:                                   # words are not walls
        x0, y0, x1, y1 = (int(round(v)) for v in t.box)
        dark[max(0, y0 - 1):y1 + 2, max(0, x0 - 1):x1 + 2] = False
    tries = []
    if wall_style in ("auto", "filled"):
        tries.append(("filled", _segment(dark, texts, wall_px, door_gap, window_gap)))
    line, t_min = stroke_classes(dark)
    if wall_style == "outline" or (wall_style == "auto" and (tries[0][1]["quality"] < 0.6 or t_min <= 2 * line + 2)):
        halves = [wall_px / 2] if wall_px else [2, 3, 4, 6, 8, 11, 15, 20, 26]
        for half in halves:
            filled = fill_outline_walls(dark, half)
            seg = _segment(filled, texts, wall_px, door_gap, window_gap)
            seg["dark_used"] = filled
            tries.append(("outline", seg))
    style, best = max(tries, key=lambda s: s[1]["quality"])
    used_dark = best.pop("dark_used", dark)
    a = Analysis(src, gray, angle, used_dark, texts=texts, style=style, **best)
    _attach_texts(a)
    return a


def _attach_texts(a: Analysis) -> None:
    h, w = a.labels.shape
    for t in a.texts:
        cx, cy = (int(round(v)) for v in t.center)
        if not (0 <= cx < w and 0 <= cy < h):
            continue
        lab = int(a.labels[cy, cx])
        if not lab:                                   # text sits on furniture lines: nearest room pixel
            x0, y0 = max(0, cx - 6), max(0, cy - 6)
            win = a.labels[y0:cy + 7, x0:cx + 7]
            vals = win[win > 0]
            lab = int(np.bincount(vals).argmax()) if len(vals) else 0
        if lab:
            r = a.regions[lab - 1]
            r.texts.append(t)
    for r in a.regions:
        for t in sorted(r.texts, key=lambda t: -len(t.text)):
            g = room_type_from_text(t.text)
            if g:
                r.guess = g
                break


def readings(a: Analysis):
    """(token, Reading) for every text that is a number we understand."""
    out = []
    for t in a.texts:
        r = parse(t.text)
        if r:
            out.append((t, r))
    return out

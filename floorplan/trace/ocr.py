"""Local OCR (no internet): RapidOCR (PaddleOCR models on onnxruntime, bundled)
or Tesseract when it is installed (it adds Arabic with the 'ara' language)."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile

import numpy as np

from .source import TextToken

TILE = 1600
OVERLAP = 200
_rapid = None


def tesseract_path() -> str | None:
    p = shutil.which("tesseract")
    if p:
        return p
    for base in (os.environ.get("ProgramFiles", r"C:\Program Files"),
                 os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
                 os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs")):
        p = os.path.join(base, "Tesseract-OCR", "tesseract.exe")
        if os.path.exists(p):
            return p
    return None


def has_rapidocr() -> bool:
    try:
        import onnxruntime  # noqa: F401
        import rapidocr  # noqa: F401
        return True
    except Exception:
        return False


def engines() -> list[str]:
    out = []
    if has_rapidocr():
        out.append("rapidocr")
    if tesseract_path():
        out.append("tesseract")
    return out


def run(gray: np.ndarray, engine: str = "auto", progress=None, cancelled=None) -> list[TextToken]:
    """Text on the drawing, horizontal and vertical (dimension strings on the sides)."""
    avail = engines()
    if engine == "auto":
        engine = avail[0] if avail else "none"
    if engine not in avail:
        return []
    fn = _rapid_tokens if engine == "rapidocr" else _tesseract_tokens
    import cv2
    out = fn(gray, progress, cancelled, 0.0, 0.6)
    rot = cv2.rotate(gray, cv2.ROTATE_90_CLOCKWISE)        # vertical text reads left-to-right here
    h = gray.shape[0]
    for t in fn(rot, progress, cancelled, 0.6, 1.0):
        x0, y0, x1, y1 = t.box                             # back to the original image
        out.append(TextToken(t.text, (y0, h - 1 - x1, y1, h - 1 - x0), t.source, t.score))
    for t in out:                                          # the box shape says how the text runs
        t.vertical = bool(len(t.text) > 1 and (t.box[3] - t.box[1]) > 1.3 * (t.box[2] - t.box[0]))
    return _dedupe(out)


def _dedupe(tokens: list[TextToken]) -> list[TextToken]:
    def iou(a, b):
        ix = max(0, min(a[2], b[2]) - max(a[0], b[0]))
        iy = max(0, min(a[3], b[3]) - max(a[1], b[1]))
        inter = ix * iy
        ua = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
        return inter / ua if ua > 0 else 0

    out: list[TextToken] = []
    for t in sorted(tokens, key=lambda t: -t.score):      # the same words read twice (both passes)
        if any(iou(o.box, t.box) > 0.4 for o in out):
            continue
        out.append(t)
    return out


def _tiles(gray):
    h, w = gray.shape
    step = TILE - OVERLAP
    for y in range(0, max(1, h - OVERLAP), step):
        for x in range(0, max(1, w - OVERLAP), step):
            yield x, y, gray[y:y + TILE, x:x + TILE]


def _rapid_tokens(gray, progress, cancelled, p0, p1) -> list[TextToken]:
    global _rapid
    if _rapid is None:
        import logging
        from rapidocr import RapidOCR
        _rapid = RapidOCR(params={"Global.log_level": "error"})
        logging.getLogger("RapidOCR").setLevel(logging.ERROR)
    import cv2
    tiles = list(_tiles(gray))
    out = []
    for i, (x, y, tile) in enumerate(tiles):
        if cancelled and cancelled():
            break
        if progress:
            progress(p0 + (p1 - p0) * i / len(tiles))
        if tile.min() > 200:                                # blank paper
            continue
        r = _rapid(cv2.cvtColor(tile, cv2.COLOR_GRAY2BGR))
        if r is None or r.boxes is None:
            continue
        for box, txt, sc in zip(r.boxes, r.txts, r.scores):
            b = np.asarray(box)
            out.append(TextToken(str(txt), (x + b[:, 0].min(), y + b[:, 1].min(), x + b[:, 0].max(),
                                            y + b[:, 1].max()), "ocr", float(sc)))
    return out


def _tesseract_tokens(gray, progress, cancelled, p0, p1) -> list[TextToken]:
    import cv2
    exe = tesseract_path()
    langs = "eng"
    try:
        lst = subprocess.run([exe, "--list-langs"], capture_output=True, text=True, timeout=20,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout
        if "ara" in lst.split():
            langs = "eng+ara"
    except Exception:
        pass
    if progress:
        progress(p0)
    with tempfile.TemporaryDirectory() as d:
        img = os.path.join(d, "page.png")
        cv2.imwrite(img, gray)
        res = subprocess.run([exe, img, "stdout", "-l", langs, "--psm", "11", "tsv"], capture_output=True,
                             text=True, encoding="utf-8", timeout=300,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    out = []
    for line in res.stdout.splitlines()[1:]:
        f = line.split("\t")
        if len(f) < 12 or not f[11].strip():
            continue
        x, y, w, h, conf = int(f[6]), int(f[7]), int(f[8]), int(f[9]), float(f[10])
        if conf >= 40:
            out.append(TextToken(f[11].strip(), (x, y, x + w, y + h), "ocr", conf / 100))
    if progress:
        progress(p1)
    return out

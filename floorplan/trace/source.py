"""Loading a drawing: PNG/JPG/BMP/TIFF/WebP images and PDF pages.

PDF pages are rendered with pdfium and their text is read directly (exact
numbers and Arabic names, no OCR needed for vector PDFs)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field

import numpy as np

IMAGE_EXT = (".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp")
MAX_SIDE = 5000          # bigger images are scaled down (detail beyond this is noise)


@dataclass
class TextToken:
    text: str
    box: tuple[float, float, float, float]   # x0, y0, x1, y1 in image pixels
    source: str = "ocr"                      # "pdf" | "ocr"
    score: float = 1.0
    vertical: bool = False

    @property
    def center(self) -> tuple[float, float]:
        return (self.box[0] + self.box[2]) / 2, (self.box[1] + self.box[3]) / 2


@dataclass
class Source:
    gray: np.ndarray                         # uint8, 255 = paper
    path: str = ""
    page: int = 0
    pages: int = 1
    dpi: float | None = None                 # known for PDFs: lets "1:100" give the scale
    texts: list[TextToken] = field(default_factory=list)

    @property
    def size(self) -> tuple[int, int]:
        return self.gray.shape[1], self.gray.shape[0]

    def crop(self, x0: int, y0: int, x1: int, y1: int) -> "Source":
        x0, y0 = max(0, int(x0)), max(0, int(y0))
        x1, y1 = min(self.size[0], int(x1)), min(self.size[1], int(y1))
        texts = [TextToken(t.text, (t.box[0] - x0, t.box[1] - y0, t.box[2] - x0, t.box[3] - y0),
                           t.source, t.score, t.vertical)
                 for t in self.texts if x0 <= t.center[0] <= x1 and y0 <= t.center[1] <= y1]
        return Source(self.gray[y0:y1, x0:x1].copy(), self.path, self.page, self.pages, self.dpi, texts)


def _to_gray(img: np.ndarray) -> np.ndarray:
    import cv2
    if img.ndim == 2:
        return img.astype(np.uint8)
    if img.shape[2] == 4:                     # transparent screenshots: put them on white paper
        a = img[:, :, 3:4].astype(np.float32) / 255
        img = (img[:, :, :3].astype(np.float32) * a + 255 * (1 - a)).astype(np.uint8)
    return cv2.cvtColor(img[:, :, :3], cv2.COLOR_BGR2GRAY)


def _limit(gray: np.ndarray) -> tuple[np.ndarray, float]:
    import cv2
    h, w = gray.shape
    f = min(1.0, MAX_SIDE / max(h, w))
    if f < 1.0:
        gray = cv2.resize(gray, (int(w * f), int(h * f)), interpolation=cv2.INTER_AREA)
    return gray, f


def from_array(img: np.ndarray, path: str = "") -> Source:
    gray, _ = _limit(_to_gray(img))
    return Source(gray, path)


def page_count(path: str) -> int:
    if not path.lower().endswith(".pdf"):
        return 1
    import pypdfium2 as pdfium
    pdf = pdfium.PdfDocument(path)
    try:
        return len(pdf)
    finally:
        pdf.close()


def load(path: str, page: int = 0, dpi: float = 200) -> Source:
    if path.lower().endswith(".pdf"):
        return _load_pdf(path, page, dpi)
    import cv2
    data = np.fromfile(path, np.uint8)               # cv2.imread cannot open non-ASCII paths on Windows
    img = cv2.imdecode(data, cv2.IMREAD_UNCHANGED)
    if img is None:
        raise ValueError(f"cannot read image: {os.path.basename(path)}")
    if img.dtype != np.uint8:
        img = (img / max(1, img.max()) * 255).astype(np.uint8)
    src = from_array(img, path)
    return src


def _load_pdf(path: str, page: int, dpi: float) -> Source:
    import pypdfium2 as pdfium
    pdf = pdfium.PdfDocument(path)
    try:
        n = len(pdf)
        pg = pdf[max(0, min(page, n - 1))]
        pw, ph = pg.get_size()
        scale = dpi / 72
        if max(pw, ph) * scale > MAX_SIDE:
            scale = MAX_SIDE / max(pw, ph)
        img = pg.render(scale=scale, grayscale=True).to_numpy()
        gray = _to_gray(img)
        texts = []
        tp = pg.get_textpage()
        for i in range(tp.count_rects()):
            l, b, r, t = tp.get_rect(i)
            s = tp.get_text_bounded(l, b, r, t).strip()
            if s:
                texts.append(TextToken(s, (l * scale, (ph - t) * scale, r * scale, (ph - b) * scale), "pdf",
                                       1.0, (t - b) > 2.5 * (r - l) and len(s) > 1))
        tp.close()
        pg.close()
        return Source(gray, path, page, n, scale * 72, texts)
    finally:
        pdf.close()

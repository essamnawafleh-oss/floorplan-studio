"""Image / PDF -> editable plan ("تحويل الصورة إلى مخطط").

    src = load("plan.pdf")            # or load("shot.png"), from_array(numpy_image)
    a = read(src)                     # OCR (when needed) + walls + rooms
    s = auto_scale(a)                 # metres per pixel (dimensions, else doors)
    plan = to_plan(a, s.scale)        # an ordinary Plan: edit mode, 3D, quantities, exports
"""

from __future__ import annotations

from .build import Options, guess_types, room_rows, to_plan
from .detect import Analysis, analyse
from .scale import ScaleResult, from_dimensions, from_door, from_line
from .source import IMAGE_EXT, Source, from_array, load, page_count

__all__ = ["Analysis", "IMAGE_EXT", "Options", "ScaleResult", "Source", "analyse", "auto_scale", "from_array",
           "from_dimensions", "from_door", "from_line", "guess_types", "load", "page_count", "read", "room_rows",
           "to_plan"]


def read(src: Source, ocr_engine: str = "auto", progress=None, cancelled=None, **kw) -> Analysis:
    """OCR runs when the source has no text of its own (images, scanned PDFs);
    ocr_engine='off' skips it, 'always' runs it even on a PDF with text."""
    from . import ocr
    if ocr_engine != "off" and (ocr_engine == "always" or not src.texts):
        eng = "auto" if ocr_engine == "always" else ocr_engine
        src.texts = list(src.texts) + ocr.run(src.gray, eng, progress=progress, cancelled=cancelled)
    return analyse(src, **kw)


def auto_scale(a: Analysis, door_m: float = 0.9) -> tuple[str, ScaleResult]:
    """('dims' | 'door' | 'none', result)."""
    d = from_dimensions(a)
    strong = sum(v.weight for v in d.agreeing)
    if d.scale and (d.support >= 2 or strong >= 1.2):
        return "dims", d
    door = from_door(a, door_m)
    if door.scale and door.support >= 2:
        return "door", door
    if d.scale:
        return "dims", d
    return "none", door

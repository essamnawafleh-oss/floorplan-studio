"""Reading the words on a drawing: dimension numbers, areas, room names."""

from __future__ import annotations

import re
from dataclasses import dataclass

# room type <- words found inside the room (English / Arabic, lower case)
KEYWORDS = [
    ("ensuite",  ["master bath", "m.bath", "m. bath", "ensuite", "en-suite", "en suite", "حمام رئيسي", "حمام ماستر"]),
    ("guest_wc", ["w.c", "wc", "powder", "guest toilet", "guest wo", "تواليت", "مغسلة", "حمام ضيوف"]),
    ("master",   ["master", "m.bed", "m. bed", "mbr", "ماستر", "نوم رئيسية", "رئيسية"]),
    ("bathroom", ["bath", "toilet", "shower", "حمام", "دورة مياه"]),
    ("kitchen",  ["kitchen", "kit.", "pantry", "مطبخ"]),
    ("dining",   ["dining", "سفرة", "طعام"]),
    ("salon",    ["salon", "reception", "majlis", "guest", "صالون", "ضيوف", "استقبال", "مجلس"]),
    ("living",   ["living", "family", "lounge", "sitting", "معيشة", "جلوس", "صالة"]),
    ("laundry",  ["laundry", "washing", "غسيل"]),
    ("storage",  ["store", "storage", "closet", "مخزن", "خزين", "مستودع"]),
    ("maid",     ["maid", "خادمة"]),
    ("office",   ["office", "study", "مكتب"]),
    ("entrance", ["entrance", "entry", "foyer", "مدخل"]),
    ("corridor", ["corridor", "hall", "passage", "lobby", "ممر", "موزع"]),
    ("balcony",  ["balcony", "terrace", "veranda", "شرفة", "برندة", "بلكونة", "تراس", "فراغ"]),
    ("bedroom",  ["bedroom", "bed", "b.r", "غرفة نوم", "نوم"]),
]

_NUM = r"\d+(?:[.,]\d+)?"
_AREA = re.compile(rf"({_NUM})\s*(?:m2|m²|sqm|sq\.?\s*m|م2|م²|متر مربع)", re.I)
_PAIR = re.compile(rf"({_NUM})\s*[x×X*]\s*({_NUM})")
_FEET = re.compile(r"(\d+)\s*['’]\s*-?\s*(\d+(?:\.\d+)?)?\s*(?:\"|”|'')?")
_SCALE = re.compile(r"1\s*[:/]\s*(\d{2,4})")
_LEN = re.compile(rf"^\s*({_NUM})\s*(m|cm|mm|م|سم)?\s*$", re.I)


@dataclass
class Reading:
    kind: str            # "len" | "pair" | "area" | "scale"
    values: tuple        # metres (len, pair), m² (area), denominator (scale)


def _num(s: str) -> float:
    return float(s.replace(",", "."))


def _metres(s: str, unit: str | None) -> float | None:
    v = _num(s)
    unit = (unit or "").lower()
    if unit in ("m", "م"):
        return v
    if unit in ("cm", "سم"):
        return v / 100
    if unit == "mm":
        return v / 1000
    if "." in s or "," in s:
        return v                                  # 4.20 -> metres
    if 1000 <= v <= 60000:
        return v / 1000                           # 4200 -> millimetres
    if 40 <= v < 1000:
        return v / 100                            # 420 -> centimetres
    return None                                   # small integers are room numbers, not lengths


def parse(text: str) -> Reading | None:
    """Turn one text item into a dimension, a room size, an area or a drawing scale."""
    t = text.strip().replace("O", "0") if re.fullmatch(r"[\dO.,]+", text.strip()) else text.strip()
    m = _SCALE.search(t)
    if m and ("scale" in t.lower() or "مقياس" in t or re.fullmatch(r"\s*1\s*[:/]\s*\d+\s*", t)):
        return Reading("scale", (int(m.group(1)),))
    m = _AREA.search(t)
    if m:
        v = _num(m.group(1))
        return Reading("area", (v,)) if 0.5 <= v <= 2000 else None
    m = _PAIR.search(t)
    if m:
        a, b = _metres(m.group(1), None), _metres(m.group(2), None)
        if a and b and 0.5 <= a <= 60 and 0.5 <= b <= 60:
            return Reading("pair", (a, b))
    m = _LEN.match(t)
    if m:
        v = _metres(m.group(1), m.group(2))
        if v and 0.3 <= v <= 120:
            return Reading("len", (v,))
    m = _FEET.fullmatch(t.strip())
    if m:
        v = int(m.group(1)) * 0.3048 + float(m.group(2) or 0) * 0.0254
        if 0.3 <= v <= 120:
            return Reading("len", (v,))
    return None


def room_type_from_text(text: str) -> str | None:
    t = " " + text.lower().strip() + " "
    for _ in range(2):                            # OCR reads "BEDR00M"
        t = re.sub(r"(?<=[a-z])0|0(?=[a-z])", "o", t)
    for rtype, words in KEYWORDS:
        for w in words:
            if re.search(r"[a-z]", w):
                if re.search(r"(?<![a-z])" + re.escape(w) + r"(?![a-z])", t):
                    return rtype
            elif w in t:
                return rtype
    return None

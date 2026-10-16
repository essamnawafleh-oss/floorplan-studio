"""Arabic / English labels."""

ROOM_NAMES = {
    "entrance": ("مدخل", "Entrance"),
    "salon":    ("صالون ضيوف", "Guest Salon"),
    "living":   ("معيشة", "Living"),
    "dining":   ("سفرة", "Dining"),
    "kitchen":  ("مطبخ", "Kitchen"),
    "guest_wc": ("حمام ضيوف", "Guest WC"),
    "laundry":  ("غسيل", "Laundry"),
    "storage":  ("مخزن", "Storage"),
    "maid":     ("غرفة خادمة", "Maid Room"),
    "master":   ("نوم رئيسية", "Master Bedroom"),
    "ensuite":  ("حمام رئيسي", "Master Bath"),
    "bedroom":  ("غرفة نوم", "Bedroom"),
    "bathroom": ("حمام", "Bathroom"),
    "office":   ("مكتب", "Office"),
    "corridor": ("ممر", "Corridor"),
}

TEXT = {
    "total_area": ("المساحة الإجمالية", "Gross area"),
    "net_area": ("المساحة الصافية", "Net area"),
    "seed": ("البذرة", "Seed"),
    "scale": ("مقياس", "Scale"),
}


def room_name(room_type: str, lang: str, number: int | None = None) -> str:
    ar, en = ROOM_NAMES.get(room_type, (room_type, room_type))
    name = ar if lang == "ar" else en
    return f"{name} {number}" if number else name


def text(key: str, lang: str) -> str:
    ar, en = TEXT[key]
    return ar if lang == "ar" else en

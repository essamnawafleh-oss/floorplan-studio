"""Space programme: project config -> list of RoomSpec + footprint size."""

from __future__ import annotations

import math
from collections import Counter

from .i18n import room_name
from .models import RoomSpec
from .rules import get_rules


def build_program(config: dict) -> list[RoomSpec]:
    """Rooms come from config['rooms'] if given, else from config['household']."""
    rules = get_rules(config.get("rules", "jordan"))
    hh = config.get("household", {})
    parents = bool(hh.get("parents", True))
    sons, daughters, others = int(hh.get("sons", 0)), int(hh.get("daughters", 0)), int(hh.get("others", 0))
    guests = int(hh.get("guests", 0))
    residents = (2 if parents else 0) + sons + daughters + others

    raw = config.get("rooms") or rules.household_program(
        parents, sons, daughters, others, guests,
        office=bool(hh.get("office", False)), maid=bool(hh.get("maid", False)))

    totals = Counter(r["type"] for r in raw)
    counters: Counter = Counter()
    specs = []
    for r in raw:
        rtype = r["type"]
        if rtype not in rules.ROOM_TYPES:
            raise ValueError(f"Unknown room type: {rtype}")
        counters[rtype] += 1
        num = counters[rtype] if totals[rtype] > 1 else None
        occ = int(r.get("occupants", 0))
        area = r.get("area")
        fixed = area is not None and bool(r.get("fixed", True))
        if area is None:
            area = rules.area_for(rtype, occ, residents, guests)
        specs.append(RoomSpec(
            id=f"{rtype}{counters[rtype]}", type=rtype, area=float(area), occupants=occ, fixed=fixed,
            name_ar=r.get("name_ar") or room_name(rtype, "ar", num),
            name_en=r.get("name_en") or room_name(rtype, "en", num)))
    return specs


def buildable_envelope(plot: dict, rules) -> tuple[float, float, dict]:
    """Max building rectangle on a rectangular plot after setbacks + coverage."""
    preset = dict(rules.ZONING_PRESETS.get(plot.get("zoning", ""), {}))
    preset.update({k: plot[k] for k in ("front", "side", "rear", "coverage") if k in plot})
    pw, pd = float(plot["width"]), float(plot["depth"])
    w = pw - 2 * preset.get("side", 0.0)
    d = pd - preset.get("front", 0.0) - preset.get("rear", 0.0)
    if w <= 0 or d <= 0:
        raise ValueError("Setbacks leave no buildable area on this plot")
    max_area = preset.get("coverage", 1.0) * pw * pd
    if w * d > max_area:          # shrink keeping proportions to respect coverage
        k = math.sqrt(max_area / (w * d))
        w, d = w * k, d * k
    info = dict(plot_area=pw * pd, max_footprint=max_area, setbacks=preset,
                min_plot_ok=pw * pd >= preset.get("min_plot", 0))
    return round(w, 2), round(d, 2), info


def resolve_footprint(config: dict, specs: list[RoomSpec], settings: dict) -> tuple[float, float, list[str], str | None]:
    """Footprint from config['footprint'], or plot+zoning, or estimated from areas.
    Last value says which dimension was estimated ('width', 'depth', 'both' or None)."""
    rules = get_rules(config.get("rules", "jordan"))
    notes: list[str] = []
    fp = config.get("footprint", {})
    if "width" in fp and "depth" in fp:
        return float(fp["width"]), float(fp["depth"]), notes, None

    # inside area needed: rooms + corridor share of bedrooms + interior walls (~7 %)
    te, c = settings["exterior_wall"], settings["corridor"]
    night = sum(sp.area for sp in specs if sp.zone == "private")
    inner = (sum(sp.area for sp in specs) - night + night * (1 + c / 4.0)) / 0.93
    need = inner
    limit_w = limit_d = None
    if "plot" in config:
        limit_w, limit_d, info = buildable_envelope(config["plot"], rules)
        notes.append(f"Buildable envelope {limit_w} x {limit_d} m (max footprint {info['max_footprint']:.0f} m²)")
        if not info["min_plot_ok"]:
            notes.append("Plot is smaller than the zoning minimum")
        if need > limit_w * limit_d:
            notes.append(f"Programme needs ~{need:.0f} m² but only {limit_w * limit_d:.0f} m² fit: consider another floor")
    free = "both"
    if "width" in fp:
        free = "depth"
        w = float(fp["width"])
        d = inner / (w - 2 * te) + 2 * te
    elif "depth" in fp:
        free = "width"
        d = float(fp["depth"])
        w = inner / (d - 2 * te) + 2 * te
    else:
        ratio = float(fp.get("aspect", 1.35))
        d = math.sqrt(inner / ratio) + 2 * te
        w = (d - 2 * te) * ratio + 2 * te
    if limit_w:
        w, d = min(w, limit_w), min(d, limit_d)
    return math.ceil(w * 20) / 20, math.ceil(d * 20) / 20, notes, free

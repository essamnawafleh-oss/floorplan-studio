import copy
import types

from . import jordan

RULESETS = {"jordan": jordan}


def get_rules(name: str = "jordan"):
    return RULESETS[name]


def with_overrides(base, overrides: dict | None):
    """A rules object like `base` with per-project changes; `base` is not touched.

    overrides = {
      "room_types":  {"bedroom": {"min_width": 3.0, "max_aspect": 1.6}, ...},
      "adjacency":   [["kitchen", "dining", 6.0], ["salon", "entrance", 0]],   # set weight (0 = off) or add
      "access_from": {"office": ["entrance", "corridor"]},
    }
    A room type's zone cannot be changed (the generator reads it from the
    built-in table)."""
    if not overrides:
        return base
    ns = types.SimpleNamespace(**{k: getattr(base, k) for k in dir(base) if not k.startswith("__")})
    ns.__name__ = getattr(base, "__name__", "rules") + "+overrides"
    room_types = copy.deepcopy(base.ROOM_TYPES)
    for rtype, vals in (overrides.get("room_types") or {}).items():
        if rtype not in room_types:
            raise ValueError(f"Unknown room type: {rtype}")
        bad = set(vals) - {"min_area", "min_width", "max_aspect", "habitable", "window"}
        if bad:
            raise ValueError(f"Cannot override {sorted(bad)} for {rtype}")
        room_types[rtype].update(vals)
    ns.ROOM_TYPES = room_types
    wishes = {(a, b): w for a, b, w in base.ADJACENCY_WISHES}
    for a, b, w in overrides.get("adjacency") or []:
        if a not in room_types or b not in room_types:
            raise ValueError(f"Unknown room type in adjacency: {a}, {b}")
        wishes[(a, b)] = float(w)
    ns.ADJACENCY_WISHES = [(a, b, w) for (a, b), w in wishes.items() if w > 0]
    access = copy.deepcopy(base.ACCESS_FROM)
    access.update({k: list(v) for k, v in (overrides.get("access_from") or {}).items()})
    ns.ACCESS_FROM = access
    return ns

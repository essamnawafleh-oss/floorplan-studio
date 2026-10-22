"""Default design rules for Jordan (residential).

IMPORTANT: these numbers are practical defaults to get started. They must be
checked against the regulations in force (e.g. Amman building & zoning
regulations / the municipality concerned) before relying on them for real
projects. Every value can be overridden from the project file.
"""

from __future__ import annotations

import math

# --- Room types -------------------------------------------------------------
# zone:       public / service / private / circulation
# min_area:   m², minimum net area
# min_width:  m, minimum short side
# max_aspect: maximum long/short side ratio before the layout is penalised
# habitable:  needs a window on an exterior wall
# window:     required glazing as a fraction of floor area
ROOM_TYPES: dict[str, dict] = {
    "entrance":  dict(zone="public",      min_area=4.0,  min_width=1.6, max_aspect=2.5, habitable=False, window=0.0),
    "salon":     dict(zone="public",      min_area=16.0, min_width=3.5, max_aspect=1.8, habitable=True,  window=0.10),
    "living":    dict(zone="public",      min_area=16.0, min_width=3.5, max_aspect=1.8, habitable=True,  window=0.10),
    "dining":    dict(zone="public",      min_area=9.0,  min_width=2.8, max_aspect=1.8, habitable=True,  window=0.10),
    "kitchen":   dict(zone="service",     min_area=8.0,  min_width=2.4, max_aspect=2.2, habitable=True,  window=0.10),
    "guest_wc":  dict(zone="service",     min_area=2.0,  min_width=1.2, max_aspect=2.5, habitable=False, window=0.0),
    "laundry":   dict(zone="service",     min_area=3.0,  min_width=1.5, max_aspect=2.5, habitable=False, window=0.0),
    "storage":   dict(zone="service",     min_area=2.0,  min_width=1.2, max_aspect=3.0, habitable=False, window=0.0),
    "maid":      dict(zone="service",     min_area=7.5,  min_width=2.4, max_aspect=2.0, habitable=True,  window=0.10),
    "master":    dict(zone="private",     min_area=14.0, min_width=3.2, max_aspect=1.8, habitable=True,  window=0.10),
    "ensuite":   dict(zone="private",     min_area=3.5,  min_width=1.5, max_aspect=2.6, habitable=False, window=0.0),
    "bedroom":   dict(zone="private",     min_area=9.0,  min_width=2.7, max_aspect=1.8, habitable=True,  window=0.10),
    "bathroom":  dict(zone="private",     min_area=3.0,  min_width=1.5, max_aspect=2.6, habitable=False, window=0.0),
    "office":    dict(zone="private",     min_area=9.0,  min_width=2.7, max_aspect=1.8, habitable=True,  window=0.10),
    "corridor":  dict(zone="circulation", min_area=0.0,  min_width=1.1, max_aspect=99,  habitable=False, window=0.0),
    # never generated: balconies / open areas of traced drawings
    "balcony":   dict(zone="outdoor",     min_area=0.0,  min_width=0.8, max_aspect=99,  habitable=False, window=0.0),
}

# Which rooms a room prefers to be entered from (first = best).
ACCESS_FROM: dict[str, list[str]] = {
    "entrance": [],
    "salon":    ["entrance", "living"],
    "living":   ["entrance", "salon", "dining"],
    "dining":   ["living", "salon", "kitchen", "entrance"],
    "kitchen":  ["dining", "living", "entrance"],
    "guest_wc": ["entrance", "salon", "living"],
    "laundry":  ["kitchen", "corridor", "living"],
    "storage":  ["kitchen", "corridor", "entrance", "living"],
    "maid":     ["kitchen", "laundry", "living"],
    "corridor": ["living", "entrance", "dining", "salon"],
    "balcony":  ["living", "salon", "master", "bedroom", "kitchen", "dining", "corridor"],
    "master":   ["corridor", "living"],
    "ensuite":  ["master"],
    "bedroom":  ["corridor", "living"],
    "bathroom": ["corridor", "living"],
    "office":   ["corridor", "living", "entrance"],
}

# Rooms that should be next to each other (soft rule, weight).
ADJACENCY_WISHES: list[tuple[str, str, float]] = [
    ("kitchen", "dining", 3.0),
    ("dining", "living", 2.0),
    ("salon", "entrance", 3.0),
    ("living", "entrance", 1.5),
    ("guest_wc", "entrance", 1.5),
    ("master", "ensuite", 10.0),
]

# Rooms the user may drop from a household programme
OPTIONAL_ROOMS = ["entrance", "salon", "guest_wc", "dining", "laundry", "ensuite"]

# Building defaults (m)
DEFAULT_SETTINGS = dict(
    exterior_wall=0.30,   # stone + concrete + insulation + block
    interior_wall=0.15,   # 10 cm block + plaster
    corridor=1.20,
    wall_height=3.00,
    door_height=2.10,
    main_door_width=1.20,
    door_width=0.90,
    wet_door_width=0.80,
    window_sill=0.90,
    window_head=2.20,
    wet_window_sill=1.60,
)

# --- Zoning presets (Amman, residential) -------------------------------------
# Approximate values for quick checks only - VERIFY against the current
# regulations. setbacks: front / side / rear (m), coverage: max ratio.
ZONING_PRESETS: dict[str, dict] = {
    "amman_res_a": dict(label_ar="سكن أ", label_en="Residential A", min_plot=1000, front=5.0, side=5.0, rear=7.0, coverage=0.39),
    "amman_res_b": dict(label_ar="سكن ب", label_en="Residential B", min_plot=750,  front=4.0, side=4.0, rear=6.0, coverage=0.45),
    "amman_res_c": dict(label_ar="سكن ج", label_en="Residential C", min_plot=500,  front=4.0, side=3.0, rear=4.0, coverage=0.51),
    "amman_res_d": dict(label_ar="سكن د", label_en="Residential D", min_plot=250,  front=3.0, side=2.5, rear=3.0, coverage=0.55),
}


# --- Space programme rules ----------------------------------------------------
def bedroom_area(occupants: int) -> float:
    """Net bedroom area for a number of people (1 -> 11 m², +3 m² per extra)."""
    occupants = max(1, occupants)
    return 11.0 + 3.0 * (occupants - 1)


def area_for(room_type: str, occupants: int, residents: int, guests: int) -> float:
    """Recommended net area for a room type."""
    if room_type == "bedroom":
        return bedroom_area(occupants)
    if room_type == "master":
        return 16.0 + 2.0 * max(0, occupants - 2)
    if room_type == "salon":
        return max(16.0, 2.0 * (occupants or guests or 8))
    if room_type == "living":
        return max(16.0, 12.0 + 2.5 * (occupants or residents))
    if room_type == "dining":
        return max(9.0, 1.6 * ((occupants or residents) + 2))
    if room_type == "kitchen":
        return max(9.0, 8.0 + 0.8 * residents)
    defaults = dict(entrance=6.0, guest_wc=3.0, laundry=4.0, storage=3.0,
                    maid=8.0, ensuite=5.0, bathroom=5.0, office=10.0)
    return max(defaults.get(room_type, 9.0), ROOM_TYPES[room_type]["min_area"])


def household_program(parents: bool, sons: int, daughters: int, others: int,
                      guests: int, office: bool = False, maid: bool = False) -> list[dict]:
    """Turn a household description into a list of rooms (type, occupants).

    Jordanian habit: boys and girls get separate rooms, up to 2 per room.
    """
    residents = (2 if parents else 0) + sons + daughters + others
    rooms: list[dict] = []
    if guests > 0:
        rooms += [dict(type="entrance"), dict(type="salon", occupants=guests), dict(type="guest_wc")]
    rooms.append(dict(type="living", occupants=residents))
    if residents >= 3:
        rooms.append(dict(type="dining", occupants=residents))
    rooms.append(dict(type="kitchen"))
    if residents >= 4:
        rooms.append(dict(type="laundry"))
    if maid:
        rooms.append(dict(type="maid", occupants=1))
    if parents:
        rooms += [dict(type="master", occupants=2), dict(type="ensuite")]
    secondary = 0
    for count in (sons, daughters):
        n_rooms = math.ceil(count / 2)
        for i in range(n_rooms):
            occ = 2 if (i + 1) * 2 <= count else count - i * 2
            rooms.append(dict(type="bedroom", occupants=occ))
            secondary += 1
    for _ in range(others):
        rooms.append(dict(type="bedroom", occupants=1))
        secondary += 1
    if office:
        rooms.append(dict(type="office", occupants=1))
    if secondary > 0 or not parents:
        for _ in range(max(1, math.ceil(secondary / 2.5))):
            rooms.append(dict(type="bathroom"))
    return rooms

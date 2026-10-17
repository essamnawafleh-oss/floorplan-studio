"""Puts basic furniture in every room (beds, sofas, WC...)."""

from floorplan.models import Furniture

ADDON = {"name": "Auto furnish", "description": "Adds standard furniture to each room (undo with Ctrl+Z)", "version": "1.0"}

# room type -> list of (block id, place) ; place = where in the room
SETS = {
    "master": [("std/bed_double", "back"), ("std/wardrobe", "front")],
    "bedroom": [("std/bed_single", "back"), ("std/desk", "front")],
    "living": [("std/sofa3", "back"), ("std/coffee_table", "center"), ("std/tv_unit", "front")],
    "salon": [("std/sofa3", "back"), ("std/armchair", "left"), ("std/armchair", "right"), ("std/coffee_table", "center")],
    "dining": [("std/dining6", "center")],
    "kitchen": [("std/counter_sink", "back"), ("std/fridge", "front")],
    "bathroom": [("std/wc", "back"), ("std/basin", "front")],
    "ensuite": [("std/wc", "back"), ("std/shower", "front")],
    "guest_wc": [("std/wc", "back"), ("std/basin", "front")],
}


def register(api):
    api.add_action("Auto furnish rooms", lambda: api.edit(lambda plan: furnish(api, plan)))


def furnish(api, plan):
    for room in plan.rooms:
        n = room.net
        for bid, place in SETS.get(room.spec.type, []):
            b = api.library.get(bid)
            if not b or b.width > n.w - 0.1 or b.depth > n.h - 0.1:
                continue
            cx = n.x0 + (n.w - b.width) / 2
            x = {"left": n.x0 + 0.1, "right": n.x1 - b.width - 0.1}.get(place, cx)
            y = {"back": n.y1 - b.depth - 0.05, "front": n.y0 + 0.05}.get(place, n.y0 + (n.h - b.depth) / 2)
            plan.furniture.append(Furniture(bid, x, y))

import math

from floorplan.models import Opening, Plan, Rect, Room, RoomSpec, Segment
from floorplan.quantities import compute, to_csv


def two_rooms():
    st = dict(exterior_wall=0.3, interior_wall=0.15, wall_height=3.0)
    a = Room(RoomSpec("a", "bedroom", 12), Rect(0.3, 0.3, 4.3, 4.3), Rect(0.3, 0.3, 4.225, 4.3))
    b = Room(RoomSpec("b", "living", 12), Rect(4.3, 0.3, 8.3, 4.3), Rect(4.375, 0.3, 8.3, 4.3))
    door = Opening("door", Segment("v", 4.3, 1.0, 1.9), 0.15, ("a", "b"), head=2.1)
    win = Opening("window", Segment("h", 0.15, 1.0, 2.0), 0.3, ("a",), sill=0.9, head=2.2)
    return Plan(8.6, 4.6, [a, b], [door, win], st)


def test_quantities_simple_box():
    q = compute(two_rooms(), {"tile_l": 0.5, "tile_w": 0.5, "tile_joint": 0, "tile_waste": 0, "block_waste": 0,
                              "paint_waste": 0, "coats": 1, "paint_coverage": 10, "ceilings": False})
    b = q["blocks"]
    assert math.isclose(b["int_length"], 4.0)
    assert math.isclose(b["int_area"], 4.0 * 3 - 0.9 * 2.1)
    assert math.isclose(b["ext_length"], 2 * (8.3 + 4.3))
    assert math.isclose(b["ext_area"], 2 * (8.3 + 4.3) * 3 - 1.0 * 1.3)
    assert math.isclose(b["per_m2"], 1 / (0.41 * 0.21))
    t = q["tiles"]
    a_net = 3.925 * 4.0
    assert t["rooms"][0]["tiles"] == math.ceil(a_net / 0.25)
    p = q["paint"]
    assert math.isclose(p["facade_area"], 2 * (8.6 + 4.6) * 3 - 1.3)
    assert math.isclose(p["rooms"][0]["walls"], 2 * (3.925 + 4.0) * 3 - 0.9 * 2.1 - 1.3)
    assert "Tiles total" in to_csv(q)

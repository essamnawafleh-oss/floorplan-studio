import json
from pathlib import Path

import ezdxf
import pytest

from floorplan import build_program, design
from floorplan.export import to_dxf, to_glb, to_svg
from floorplan.rules import jordan

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"


def load(name):
    return json.loads((EXAMPLES / name).read_text(encoding="utf-8"))


def signature(plan):
    return [(r.id, round(r.rect.x0, 4), round(r.rect.y0, 4), round(r.rect.x1, 4), round(r.rect.y1, 4))
            for r in plan.rooms]


def test_household_program_jordan():
    rooms = jordan.household_program(parents=True, sons=3, daughters=1, others=0, guests=8)
    types = [r["type"] for r in rooms]
    assert types.count("master") == 1 and types.count("ensuite") == 1
    assert types.count("bedroom") == 3          # 2 rooms for 3 boys + 1 for the girl
    assert "salon" in types and "guest_wc" in types
    assert types.count("bathroom") >= 1


def test_bedroom_area_grows_with_occupants():
    assert jordan.bedroom_area(2) > jordan.bedroom_area(1)


def test_same_seed_same_plan():
    cfg = load("family.json")
    assert signature(design(cfg, seed=7, candidates=60)) == signature(design(cfg, seed=7, candidates=60))


def test_different_seeds_keep_footprint_but_change_layout():
    cfg = load("family.json")
    a, b = design(cfg, seed=1, candidates=60), design(cfg, seed=2, candidates=60)
    assert (a.width, a.depth) == (b.width, b.depth) == (18.0, 13.0)
    assert signature(a) != signature(b)


@pytest.mark.parametrize("name", ["family.json", "fixed_rooms.json"])
@pytest.mark.parametrize("seed", [1, 2, 3])
def test_rooms_tile_the_inside_without_overlap(name, seed):
    plan = design(load(name), seed=seed, candidates=60)
    te = plan.settings["exterior_wall"]
    inner = (plan.width - 2 * te) * (plan.depth - 2 * te)
    assert sum(r.rect.area for r in plan.rooms) == pytest.approx(inner, rel=1e-6)
    for i, a in enumerate(plan.rooms):
        for b in plan.rooms[i + 1:]:
            ox = min(a.rect.x1, b.rect.x1) - max(a.rect.x0, b.rect.x0)
            oy = min(a.rect.y1, b.rect.y1) - max(a.rect.y0, b.rect.y0)
            assert ox <= 1e-6 or oy <= 1e-6, (a.id, b.id)


@pytest.mark.parametrize("seed", [1, 2, 3, 4])
def test_every_room_reachable_and_main_door_in_front(seed):
    plan = design(load("family.json"), seed=seed)
    assert plan._stats["unreached"] == []
    assert plan._stats["main_side"] == "front"
    assert sum(o.kind == "main_door" for o in plan.openings) == 1


def test_fixed_areas_are_close_to_target():
    plan = design(load("fixed_rooms.json"), seed=1)
    for r in plan.rooms:
        if r.spec.fixed:
            assert r.net.area == pytest.approx(r.spec.area, rel=0.2), r.id


def test_exports(tmp_path):
    plan = design(load("family.json"), seed=1, candidates=60)
    svg = to_svg(plan, lang="both")
    assert svg.startswith("<svg") and "معيشة" in svg and "Living" in svg
    to_dxf(plan, str(tmp_path / "p.dxf"))
    doc = ezdxf.readfile(str(tmp_path / "p.dxf"))
    layers = {e.dxf.layer for e in doc.modelspace()}
    assert {"A-WALL", "A-DOOR", "A-GLAZ", "A-AREA", "A-ANNO-TEXT"} <= layers
    to_glb(plan, str(tmp_path / "p.glb"))
    assert (tmp_path / "p.glb").stat().st_size > 1000


def test_plot_and_zoning_envelope():
    cfg = {"plot": {"width": 25, "depth": 32, "zoning": "amman_res_c"},
           "household": {"parents": True, "sons": 1, "daughters": 1, "guests": 6}}
    plan = design(cfg, seed=1, candidates=60)
    assert plan.width <= 25 - 2 * 3.0 + 1e-6
    assert plan.width * plan.depth <= 0.51 * 25 * 32 + 1e-6


def test_exclude_optional_rooms():
    cfg = load("family.json")
    cfg["household"]["exclude"] = ["laundry", "guest_wc", "master"]
    types = {s.type for s in build_program(cfg)}
    assert not types & {"laundry", "guest_wc", "master", "ensuite"}
    assert "kitchen" in types


def test_strict_mode_meets_hard_rules():
    cfg = load("fixed_rooms.json")
    cfg["strict"] = True
    plan = design(cfg, seed=1)
    assert plan._hard == 0

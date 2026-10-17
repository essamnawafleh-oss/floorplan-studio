import json
from pathlib import Path

import pytest

from floorplan import design
from floorplan.editing import (add_opening, move_wall, refresh, set_opening_width, set_room_size, wall_lines)
from floorplan.models import Plan

EX = Path(__file__).resolve().parent.parent / "examples"


@pytest.fixture
def plan():
    return design(json.loads((EX / "family.json").read_text(encoding="utf-8")), seed=4, candidates=80)


def tiles(plan):
    te = plan.settings["exterior_wall"]
    inner = (plan.width - 2 * te) * (plan.depth - 2 * te)
    assert sum(r.rect.area for r in plan.rooms) == pytest.approx(inner, rel=1e-6)
    for r in plan.rooms:
        assert r.rect.x0 >= te - 1e-6 and r.rect.x1 <= plan.width - te + 1e-6
        assert r.rect.y0 >= te - 1e-6 and r.rect.y1 <= plan.depth - te + 1e-6


def openings_on_walls(plan):
    from floorplan.editing import _host_segment
    for o in plan.openings:
        host = _host_segment(plan, o)
        assert host is not None, o
        assert host.s0 - 1e-6 <= o.seg.s0 and o.seg.s1 <= host.s1 + 1e-6


def test_move_every_interior_wall_keeps_tiling(plan):
    for line in [ln for ln in wall_lines(plan) if not ln.side]:
        lines = [ln for ln in wall_lines(plan) if ln.orient == line.orient and abs(ln.coord - line.coord) < 1e-4
                 and abs(ln.s0 - line.s0) < 1e-4]
        if lines and move_wall(plan, lines[0], lines[0].coord + 0.2):
            refresh(plan)
            tiles(plan)
            openings_on_walls(plan)


@pytest.mark.parametrize("side,delta", [("right", 1.0), ("top", -0.8), ("left", 0.5), ("bottom", -0.6)])
def test_move_exterior_walls(plan, side, delta):
    w, d = plan.width, plan.depth
    n_open = len(plan.openings)
    line = next(ln for ln in wall_lines(plan) if ln.side == side)
    assert move_wall(plan, line, line.coord + delta)
    refresh(plan)
    tiles(plan)
    openings_on_walls(plan)
    grow = {"right": delta, "left": -delta, "top": delta, "bottom": -delta}[side]
    if side in ("right", "left"):
        assert plan.width == pytest.approx(w + grow)
    else:
        assert plan.depth == pytest.approx(d + grow)
    assert len(plan.openings) == n_open


def test_wall_move_rejected_when_room_too_small(plan):
    line = next(ln for ln in wall_lines(plan) if not ln.side)
    before = Plan.to_dict(plan)
    assert not move_wall(plan, line, line.coord + 100)
    assert Plan.to_dict(plan) == before


def test_room_size_and_openings(plan):
    room = next(r for r in plan.rooms if r.spec.type == "bedroom")
    assert set_room_size(plan, room, width=room.net.w + 0.3)
    refresh(plan)
    tiles(plan)
    n = len(plan.openings)
    cx, _ = room.rect.center
    o = add_opening(plan, "window", cx, plan.depth - plan.settings["exterior_wall"] / 2) or \
        add_opening(plan, "window", cx, plan.settings["exterior_wall"] / 2)
    assert o is not None and len(plan.openings) == n + 1
    set_opening_width(plan, o, 50)          # clamped to its wall
    openings_on_walls(plan)


def test_round_trip_after_edits(plan):
    line = next(ln for ln in wall_lines(plan) if ln.side == "right")
    move_wall(plan, line, line.coord + 0.5)
    refresh(plan)
    q = Plan.from_dict(plan.to_dict())
    assert q.to_dict() == plan.to_dict() and q.edited


def test_fixed_flag_survives_round_trip_and_old_files():
    cfg = json.loads((EX / "fixed_rooms.json").read_text(encoding="utf-8"))
    p = design(cfg, seed=1, candidates=40)
    assert any(r.spec.fixed for r in p.rooms)
    q = Plan.from_dict(p.to_dict())
    assert [r.spec.fixed for r in q.rooms] == [r.spec.fixed for r in p.rooms]
    old = p.to_dict()
    for r in old["rooms"]:
        r.pop("fixed")                      # file written before the fix
    assert not any(r.spec.fixed for r in Plan.from_dict(old).rooms)


def test_refresh_can_skip_edited_flag(plan):
    refresh(plan, mark_edited=False)
    assert not plan.edited
    refresh(plan)
    assert plan.edited

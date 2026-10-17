import math

import pytest

from floorplan import cad


def L(x1, y1, x2, y2):
    return {"t": "line", "p": [x1, y1, x2, y2]}


def close(a, b, tol=1e-6):
    return all(abs(x - y) < tol for x, y in zip(a, b))


def test_intersections():
    assert close(cad.intersections(L(0, 0, 4, 4), L(0, 4, 4, 0))[0], (2, 2))
    pts = cad.intersections(L(-5, 0, 5, 0), {"t": "circle", "c": [0, 0], "r": 2})
    assert sorted(round(p[0], 6) for p in pts) == [-2, 2]
    arc = {"t": "arc", "c": [0, 0], "r": 2, "a0": 0, "a1": 90}
    assert len(cad.intersections(L(-5, 0.5, 5, 0.5), arc)) == 1
    assert len(cad.intersections({"t": "circle", "c": [0, 0], "r": 2}, {"t": "circle", "c": [3, 0], "r": 2})) == 2


def test_trim_line_between_two_cutters():
    out = cad.trim(L(0, 0, 10, 0), (5, 0), [L(3, -1, 3, 1), L(7, -1, 7, 1)])
    assert len(out) == 2
    assert close(out[0]["p"], [0, 0, 3, 0]) and close(out[1]["p"], [7, 0, 10, 0])
    out = cad.trim(L(0, 0, 10, 0), (9, 0), [L(3, -1, 3, 1), L(7, -1, 7, 1)])
    assert len(out) == 1 and close(out[0]["p"], [0, 0, 7, 0])
    assert cad.trim(L(0, 0, 10, 0), (5, 0), []) == []      # nothing cuts it -> erased (quick mode)


def test_trim_circle_and_closed_pline():
    c = {"t": "circle", "c": [0, 0], "r": 2}
    out = cad.trim(c, (0, 2), [L(-5, 0, 5, 0)])            # remove top half
    assert out[0]["t"] == "arc" and round(out[0]["a0"]) == 180 and round(out[0]["a1"]) == 0
    sq = {"t": "pline", "pts": [[0, 0], [4, 0], [4, 4], [0, 4]], "closed": True}
    out = cad.trim(sq, (4, 2), [L(2, -1, 2, 5)])           # cut away right half
    assert len(out) == 1 and not out[0]["closed"]
    xs = [p[0] for p in out[0]["pts"]]
    assert max(xs) <= 2 + 1e-6


def test_extend():
    e = cad.extend(L(0, 0, 2, 0), (1.9, 0), [L(5, -1, 5, 1)])
    assert close(e["p"], [0, 0, 5, 0])
    e = cad.extend(L(0, 0, 2, 0), (0.1, 0), [L(-3, -1, -3, 1), L(5, -1, 5, 1)])
    assert close(e["p"], [-3, 0, 2, 0])
    assert cad.extend(L(0, 0, 2, 0), (1.9, 0), [L(5, 1, 6, 1)]) is None


def test_offset():
    o = cad.offset(L(0, 0, 4, 0), 1.0, (2, 5))
    assert close(o["p"], [0, 1, 4, 1])
    o = cad.offset({"t": "circle", "c": [0, 0], "r": 2}, 0.5, (0, 0.1))
    assert o["r"] == pytest.approx(1.5)
    sq = {"t": "pline", "pts": [[0, 0], [4, 0], [4, 4], [0, 4]], "closed": True}
    o = cad.offset(sq, 1, (10, 10))
    xs = [p[0] for p in o["pts"]]
    assert min(xs) == pytest.approx(-1) and max(xs) == pytest.approx(5)   # mitred corners


def test_explode_transforms_and_snaps():
    sq = {"t": "pline", "pts": [[0, 0], [4, 0], [4, 4], [0, 4]], "closed": True, "layer": "A-DRAW"}
    lines = cad.explode(sq)
    assert len(lines) == 4 and all(l["layer"] == "A-DRAW" for l in lines)
    r = cad.rotate(L(1, 0, 2, 0), (0, 0), 90)
    assert close(r["p"], [0, 1, 0, 2])
    m = cad.mirror(L(1, 1, 2, 1), (0, 0), (0, 1))
    assert close(m["p"], [-1, 1, -2, 1])
    s = cad.scale({"t": "circle", "c": [1, 0], "r": 1}, (0, 0), 2)
    assert s["r"] == 2 and close(s["c"], [2, 0])
    kind, p = cad.find_snap([L(0, 0, 4, 0), L(2, -2, 2, 2)], (2.03, 0.02), 0.1)
    assert kind == "int" and close(p, (2, 0))
    kind, p = cad.find_snap([L(0, 0, 4, 0)], (3.95, 0.03), 0.1)
    assert kind == "end" and close(p, (4, 0))
    kind, p = cad.find_snap([L(0, 0, 4, 0)], (2.0, 0.05), 0.1)
    assert kind == "mid"
    kind, p = cad.find_snap([L(0, 0, 4, 0)], (3.0, 0.05), 0.1, base=(3, 3))
    assert kind == "perp" and close(p, (3, 0))


def test_parse_point():
    assert cad.parse_point("2,3") == (2, 3)
    assert close(cad.parse_point("@1,1", (2, 2)), (3, 3))
    assert close(cad.parse_point("@2<90", (1, 1)), (1, 3))
    assert close(cad.parse_point("100,0", unit_k=0.01), (1, 0))
    assert cad.parse_point("abc") is None


def test_window_and_crossing():
    e = L(1, 1, 3, 1)
    assert cad.in_window(e, 0, 0, 4, 2, crossing=False)
    assert not cad.in_window(e, 2, 0, 4, 2, crossing=False)
    assert cad.in_window(e, 2, 0, 4, 2, crossing=True)


def test_drawing_exports(tmp_path):
    import json
    from pathlib import Path
    import ezdxf
    from floorplan import design
    from floorplan.export import to_dxf, to_svg
    from floorplan.models import Plan
    cfg = json.loads((Path(__file__).resolve().parent.parent / "examples" / "family.json").read_text(encoding="utf-8"))
    plan = design(cfg, seed=1, candidates=40)
    plan.drawing = [L(0, -3, 5, -3), {"t": "circle", "c": [2, -5], "r": 1, "color": "#ff0000"},
                    {"t": "arc", "c": [6, -5], "r": 1, "a0": 0, "a1": 180},
                    {"t": "pline", "pts": [[0, -8], [3, -8], [3, -9]], "closed": False},
                    {"t": "text", "p": [0, -10], "h": 0.3, "s": "Note", "rot": 0, "layer": "A-ANNO"},
                    {"t": "dim", "p1": [0, -12], "p2": [4, -12], "off": [2, -12.5], "layer": "A-DIMS"}]
    assert Plan.from_dict(plan.to_dict()).drawing == plan.drawing
    to_dxf(plan, str(tmp_path / "d.dxf"))
    msp = ezdxf.readfile(str(tmp_path / "d.dxf")).modelspace()
    types = {e.dxftype() for e in msp if e.dxf.layer in ("A-DRAW", "A-ANNO", "A-DIMS")}
    assert {"LINE", "CIRCLE", "ARC", "LWPOLYLINE", "TEXT", "DIMENSION"} <= types
    assert "Note" in to_svg(plan)

"""The generator must keep producing exactly the plans it produced before the
parametric extensions (snapshot taken from commit 943a742)."""
import json
from pathlib import Path

import pytest

from floorplan import design

ROOT = Path(__file__).resolve().parent
BASE = json.loads((ROOT / "data" / "baseline_generator.json").read_text())


@pytest.mark.parametrize("key", sorted(BASE))
def test_generator_output_unchanged(key):
    name, strict, seed = key.split("|")
    cfg = json.loads((ROOT.parent / "examples" / f"{name}.json").read_text(encoding="utf-8"))
    cfg["strict"] = strict == "True"
    p = design(cfg, seed=int(seed), candidates=60)
    exp = BASE[key]
    assert [p.width, p.depth] == exp["size"]
    assert round(p.score, 6) == exp["score"] and p._hard == exp["hard"]
    assert [[r.id, round(r.rect.x0, 6), round(r.rect.y0, 6), round(r.rect.x1, 6), round(r.rect.y1, 6)]
            for r in p.rooms] == exp["rooms"]
    assert [[o.kind, list(o.rooms), round(o.seg.coord, 6), round(o.seg.s0, 6), round(o.seg.s1, 6)]
            for o in p.openings] == exp["openings"]

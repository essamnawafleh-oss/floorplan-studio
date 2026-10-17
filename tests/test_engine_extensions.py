import copy
import json
from pathlib import Path

import pytest

from floorplan import design
from floorplan.layout import signature
from floorplan.rules import get_rules, jordan, with_overrides

EX = Path(__file__).resolve().parent.parent / "examples"


def load(name):
    return json.loads((EX / name).read_text(encoding="utf-8"))


def test_with_overrides_does_not_touch_builtin_rules():
    before = copy.deepcopy(jordan.ROOM_TYPES), list(jordan.ADJACENCY_WISHES)
    r = with_overrides(jordan, {"room_types": {"bedroom": {"min_width": 3.4}},
                                "adjacency": [["kitchen", "dining", 9], ["salon", "entrance", 0], ["office", "living", 2]]})
    assert r.ROOM_TYPES["bedroom"]["min_width"] == 3.4
    assert ("kitchen", "dining", 9.0) in r.ADJACENCY_WISHES
    assert not any(a == "salon" and b == "entrance" for a, b, _ in r.ADJACENCY_WISHES)
    assert ("office", "living", 2.0) in r.ADJACENCY_WISHES
    assert (copy.deepcopy(jordan.ROOM_TYPES), list(jordan.ADJACENCY_WISHES)) == before
    assert with_overrides(jordan, None) is jordan
    with pytest.raises(ValueError):
        with_overrides(jordan, {"room_types": {"bedroom": {"zone": "public"}}})
    with pytest.raises(ValueError):
        with_overrides(jordan, {"room_types": {"garage": {"min_width": 3}}})


def test_keep_returns_distinct_best_first_and_matches_generate():
    cfg = load("family.json")
    plans = design(cfg, seed=2, candidates=60, keep=5)
    single = design(cfg, seed=2, candidates=60)
    assert 1 < len(plans) <= 5
    assert signature(plans[0]) == signature(single) and plans[0].score == single.score
    assert [p.score for p in plans] == sorted(p.score for p in plans)
    assert len({signature(p) for p in plans}) == len(plans)


def test_score_terms_add_up():
    p = design(load("family.json"), seed=3, candidates=60)
    assert sum(p._terms.values()) == pytest.approx(p.score)


def test_rule_override_changes_evaluation_and_cache_key():
    cfg = load("fixed_rooms.json")
    base = design(cfg, seed=1, candidates=60)
    strict_cfg = dict(cfg, rule_overrides={"room_types": {"bedroom": {"min_width": 4.5}}})
    tough = design(strict_cfg, seed=1, candidates=60)
    assert any("Bedroom" in w["en"] and "width" in w["en"] for w in tough.warnings)
    assert not any("Bedroom" in w["en"] and "below minimum" in w["en"] for w in base.warnings)
    assert design(cfg, seed=1, candidates=60).score == base.score    # override did not leak

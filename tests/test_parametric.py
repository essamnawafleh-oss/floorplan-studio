import copy
import json
from pathlib import Path

import pytest

from floorplan import design
from floorplan.layout import signature
from floorplan.parametric import ParametricStudy, derived_config, programme, refine, run_study

EX = Path(__file__).resolve().parent.parent / "examples"


def load(name):
    return json.loads((EX / name).read_text(encoding="utf-8"))


def small(cfg, **kw):
    kw.setdefault("seeds", [1, 2])
    kw.setdefault("candidates", 60)
    kw.setdefault("keep", 2)
    kw.setdefault("refine_passes", 1)
    return ParametricStudy(base_config=cfg, **kw)


def test_derived_config_does_not_touch_base_and_matches_original_generation():
    cfg = load("family.json")
    cfg["plan"] = {"anything": 1}                     # project keys are ignored by the study
    before = copy.deepcopy(cfg)
    study = small(cfg)
    dcfg = derived_config(study)
    assert cfg == before
    assert "plan" not in dcfg and dcfg["rooms"]
    base = dict(before)
    base.pop("plan")
    a, b = design(base, seed=3, candidates=60), design(dcfg, seed=3, candidates=60)
    assert signature(a) == signature(b) and a.score == b.score


def test_room_override_changes_target_and_result():
    cfg = load("family.json")
    rooms = programme(small(cfg))
    living = next(r for r in rooms if r["type"] == "living")
    study = small(cfg, room_overrides={living["id"]: {"area": living["area"] + 12, "fixed": True}})
    assert next(r for r in programme(study) if r["id"] == living["id"])["area"] == pytest.approx(living["area"] + 12)
    base_best = run_study(small(cfg, refine_passes=0))[0]
    new_best = run_study(study)[0]
    area = lambda c: next(r for r in c.plan.rooms if r.id == living["id"]).net.area
    assert area(new_best) > area(base_best)


def test_unknown_room_id_is_rejected():
    with pytest.raises(ValueError):
        derived_config(small(load("family.json"), room_overrides={"garage1": {"area": 20}}))


def test_run_is_reproducible_ranked_and_distinct():
    study = small(load("fixed_rooms.json"))
    a, b = run_study(study), run_study(study)
    assert [signature(c.plan) for c in a] == [signature(c.plan) for c in b]
    assert [c.score for c in a] == [c.score for c in b]
    keys = [(c.hard, c.score) for c in a]
    assert keys == sorted(keys)
    assert len({signature(c.plan) for c in a}) == len(a)
    assert [c.rank for c in a] == list(range(1, len(a) + 1))
    for c in a:
        assert c.metrics["rooms"] and sum(c.terms.values()) == pytest.approx(c.score)


def test_refine_never_worse_and_keeps_rules():
    cfg = load("fixed_rooms.json")
    dcfg = derived_config(small(cfg))
    p = design(dcfg, seed=2, candidates=40)
    r = refine(p, dcfg, passes=2)
    assert (r._hard, r.score) <= (p._hard, p.score)
    te = r.settings["exterior_wall"]
    inner = (r.width - 2 * te) * (r.depth - 2 * te)
    assert sum(x.rect.area for x in r.rooms) == pytest.approx(inner, rel=1e-6)
    assert r._stats["unreached"] == []
    assert signature(refine(p, dcfg, passes=2)) == signature(r)      # deterministic


def test_constraint_override_reaches_the_search():
    cfg = load("fixed_rooms.json")
    study = small(cfg, rule_overrides={"room_types": {"bedroom": {"min_width": 4.5}}}, refine_passes=0)
    best = run_study(study)[0]
    assert any("Bedroom" in w["en"] and "width" in w["en"] for w in best.plan.warnings)


def test_study_round_trip_and_cancel():
    study = small(load("family.json"), room_overrides={"living1": {"area": 30}}, strict=True)
    again = ParametricStudy.from_dict(json.loads(json.dumps(study.to_dict())))
    assert again == study
    assert run_study(study, cancelled=lambda: True) == []

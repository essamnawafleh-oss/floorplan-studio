"""Parametric studies: change design parameters / constraints, search for
revised layouts, compare them.

A study never modifies the project it starts from. It derives a new config
(explicit room list + overrides), runs the normal generator for several seeds
keeping the best distinct layouts of each (layout.generate_many), optionally
refines them by moving interior walls (same tiling rule as edit mode, same
door planning and scoring as generation), then ranks everything by
(hard-rule violations, score).
"""

from __future__ import annotations

import copy
from dataclasses import asdict, dataclass, field

from . import design
from .editing import move_wall, wall_lines
from .layout import build_from_rects, signature
from .models import Plan, Rect, Room
from .program import build_program, resolve_footprint
from .rules import get_rules, with_overrides

REFINE_STEPS = (0.20, -0.20, 0.10, -0.10, 0.05, -0.05)
PROJECT_KEYS_NOT_IN_STUDY = ("plan", "parametric", "seed")


@dataclass
class ParametricStudy:
    base_config: dict
    room_overrides: dict = field(default_factory=dict)    # room id -> {"area": m², "fixed": bool}
    rule_overrides: dict = field(default_factory=dict)    # see rules.with_overrides
    strict: bool | None = None                            # None = as in the base config
    seeds: list = field(default_factory=lambda: [1, 2, 3, 4])
    candidates: int = 300                                 # layouts tried per seed
    keep: int = 3                                         # best distinct layouts kept per seed
    refine_passes: int = 2                                # 0 = no wall refinement
    max_results: int = 8

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "ParametricStudy":
        known = {k: v for k, v in d.items() if k in cls.__dataclass_fields__}
        return cls(**copy.deepcopy(known))


@dataclass
class Candidate:
    plan: Plan
    seed: int
    rank: int
    hard: int
    score: float
    terms: dict
    metrics: dict
    refined: bool = False


# --- config ------------------------------------------------------------------------
def explicit_rooms(config: dict) -> list[dict]:
    """The config's programme as an explicit room list (ids follow build_program)."""
    out = []
    for s in build_program(config):
        out.append(dict(type=s.type, occupants=s.occupants, area=round(s.area, 3), fixed=s.fixed,
                        name_ar=s.name_ar, name_en=s.name_en))
    return out


def programme(study: ParametricStudy) -> list[dict]:
    """Rooms the study works on: [{"id", "type", "name_ar", "name_en", "area", "fixed"}] incl. overrides."""
    cfg = derived_config(study)
    return [dict(id=s.id, type=s.type, name_ar=s.name_ar, name_en=s.name_en, area=s.area, fixed=s.fixed)
            for s in build_program(cfg)]


def derived_config(study: ParametricStudy) -> dict:
    """New config = base config + overrides. The base config is not modified."""
    cfg = copy.deepcopy(study.base_config)
    for k in PROJECT_KEYS_NOT_IN_STUDY:
        cfg.pop(k, None)
    rooms = explicit_rooms(cfg)
    ids = [s.id for s in build_program(cfg)]
    for rid, ov in (study.room_overrides or {}).items():
        if rid not in ids:
            raise ValueError(f"Unknown room id in study: {rid}")
        r = rooms[ids.index(rid)]
        if "area" in ov and ov["area"] is not None:
            r["area"] = float(ov["area"])
        if "fixed" in ov:
            r["fixed"] = bool(ov["fixed"])
    cfg["rooms"] = rooms
    merged = copy.deepcopy(cfg.get("rule_overrides") or {})
    for k, v in (study.rule_overrides or {}).items():
        if k == "room_types":
            rt = merged.setdefault("room_types", {})
            for t, vals in v.items():
                rt.setdefault(t, {}).update(vals)
        elif k == "adjacency":
            merged["adjacency"] = list(merged.get("adjacency", [])) + [list(x) for x in v]
        else:
            merged[k] = copy.deepcopy(v)
    if merged:
        cfg["rule_overrides"] = merged
    if study.strict is not None:
        cfg["strict"] = bool(study.strict)
    return cfg


def _rules_for(cfg: dict):
    return with_overrides(get_rules(cfg.get("rules", "jordan")), cfg.get("rule_overrides"))


# --- refinement --------------------------------------------------------------------
def _rects_plan(plan: Plan) -> Plan:
    """Rooms only (openings are re-planned by build_from_rects)."""
    rooms = [Room(r.spec, Rect(r.rect.x0, r.rect.y0, r.rect.x1, r.rect.y1), r.net) for r in plan.rooms]
    return Plan(plan.width, plan.depth, rooms, [], plan.settings)


def refine(plan: Plan, config: dict, passes: int = 2) -> Plan:
    """Greedy wall-position search on interior walls (5-20 cm moves). Accepts a
    move only if (hard violations, score) improves. Deterministic."""
    rules = _rules_for(config)
    specs = build_program(config)
    key = lambda p: (p._hard, round(p.score, 9))
    best = plan
    for _ in range(passes):
        improved = False
        base = _rects_plan(best)
        lines = [ln for ln in wall_lines(base) if not ln.side]
        for ln in lines:
            for d in REFINE_STEPS:
                trial = _rects_plan(best)
                if not move_wall(trial, ln, ln.coord + d):
                    continue
                cand = build_from_rects(specs, {r.id: r.rect for r in trial.rooms}, best.width, best.depth,
                                        best.settings, rules)
                if key(cand) < key(best):
                    cand.seed, cand.project = best.seed, best.project
                    best = cand
                    improved = True
                    break
        if not improved:
            break
    return best


# --- metrics + run -------------------------------------------------------------------
def metrics(plan: Plan) -> dict:
    """Comparison numbers. Fixed rooms are compared with their target area;
    flexible rooms with their target scaled to the space they share (the
    generator scales flexible rooms to fill the footprint)."""
    rooms_ = [r for r in plan.rooms if r.spec.type != "corridor"]
    flex = [r for r in rooms_ if not r.spec.fixed]
    t_flex = sum(r.spec.area for r in flex)
    k = sum(r.net.area for r in flex) / t_flex if t_flex else 1.0
    rooms = []
    for r in rooms_:
        target = r.spec.area if r.spec.fixed else r.spec.area * k
        dev = (r.net.area - target) / target * 100 if target else 0.0
        rooms.append(dict(id=r.id, type=r.spec.type, name_ar=r.spec.name_ar, name_en=r.spec.name_en,
                          target=round(r.spec.area, 2), expected=round(target, 2), actual=round(r.net.area, 2),
                          dev_pct=round(dev, 1), width=round(r.net.w, 2), length=round(r.net.h, 2),
                          fixed=r.spec.fixed))
    devs = [abs(x["dev_pct"]) for x in rooms] or [0.0]
    corridor = sum(r.net.area for r in plan.rooms if r.spec.type == "corridor")
    return dict(size=[plan.width, plan.depth], gross=round(plan.gross_area, 2), net=round(plan.net_area, 2),
                flex_scale=round(k, 3), corridor=round(corridor, 2),
                corridor_pct=round(100 * corridor / plan.net_area, 1) if plan.net_area else 0,
                mean_dev_pct=round(sum(devs) / len(devs), 1), max_dev_pct=round(max(devs), 1),
                within_5pct=sum(1 for d in devs if d <= 5), rooms=rooms, warnings=len(plan.warnings))


def run_study(study: ParametricStudy, progress=None, cancelled=None) -> list[Candidate]:
    """progress(done, total) and cancelled() -> bool are optional callbacks."""
    cfg = derived_config(study)
    rules_name = cfg.get("rules", "jordan")
    settings = {**get_rules(rules_name).DEFAULT_SETTINGS, **cfg.get("settings", {})}
    notes = [dict(ar=n, en=n) for n in resolve_footprint(cfg, build_program(cfg), settings)[2]]
    seeds = list(study.seeds)
    total = len(seeds) * (1 + (study.keep if study.refine_passes else 0))
    done = 0
    pool: dict[tuple, tuple] = {}
    for seed in seeds:
        if cancelled and cancelled():
            break
        plans = design(cfg, seed=seed, candidates=study.candidates, keep=study.keep)
        done += 1
        if progress:
            progress(done, total)
        for p in plans:
            refined = False
            if study.refine_passes:
                if cancelled and cancelled():
                    break
                r = refine(p, cfg, study.refine_passes)
                refined = r is not p
                if refined:
                    r.warnings = notes + r.warnings
                p = r
                done += 1
                if progress:
                    progress(done, total)
            sig = signature(p)
            if sig not in pool or (p._hard, p.score) < (pool[sig][0]._hard, pool[sig][0].score):
                pool[sig] = (p, seed, refined)
    ranked = sorted(pool.values(), key=lambda t: (t[0]._hard, t[0].score, t[1]))[:study.max_results]
    out = []
    for i, (p, seed, refined) in enumerate(ranked):
        out.append(Candidate(plan=p, seed=seed, rank=i + 1, hard=p._hard, score=p.score,
                             terms=dict(getattr(p, "_terms", {})), metrics=metrics(p), refined=refined))
    return out

"""Floor Plan Studio - rule-based floor plan generator."""

from .layout import generate
from .program import build_program, resolve_footprint

__version__ = "0.3.0"
__all__ = ["generate", "build_program", "resolve_footprint", "design"]


_CALIBRATED: dict[str, tuple[float, float]] = {}   # same inputs -> same footprint, computed once


def design(config: dict, seed: int = 0, candidates: int = 400, keep: int | None = None):
    """Config dict -> Plan (the one call most callers need).
    config["rule_overrides"] (optional) changes rules for this project only
    (see rules.with_overrides). keep=N returns the N best distinct plans."""
    from .layout import generate_many
    from .rules import get_rules, with_overrides
    rules_name = config.get("rules", "jordan")
    rules = with_overrides(get_rules(rules_name), config.get("rule_overrides"))
    settings = {**get_rules(rules_name).DEFAULT_SETTINGS, **config.get("settings", {})}
    specs = build_program(config)
    w, d, notes, free = resolve_footprint(config, specs, settings)
    if free:
        import json
        key = json.dumps([config.get(k) for k in ("footprint", "plot", "rooms", "household", "settings", "rules",
                                                    "rule_overrides")], sort_keys=True, default=str)
        if key not in _CALIBRATED:
            _CALIBRATED[key] = calibrate(specs, w, d, free, settings, rules_name, rules=rules)
        w, d = _CALIBRATED[key]
    plans = generate_many(specs, w, d, seed=seed, settings=settings, rules_name=rules_name,
                          candidates=candidates, project=config.get("project", ""),
                          strict=bool(config.get("strict", False)), rules=rules, keep=keep or 1)
    for plan in plans:
        plan.warnings = [dict(ar=n, en=n) for n in notes] + plan.warnings
    return plans if keep else plans[0]


def calibrate(specs, w, d, free, settings, rules_name, rounds=4, rules=None):
    """Adjust the estimated dimension(s) until the net room areas match the
    targets. Uses fixed probe seeds so every seed gets the same footprint."""
    import math
    te = settings["exterior_wall"]
    target = sum(s.area for s in specs)
    for _ in range(rounds):
        nets = []
        for probe in (101, 102, 103):
            p = generate(specs, w, d, seed=probe, settings=settings, rules_name=rules_name, candidates=80, rules=rules)
            nets.append(sum(r.net.area for r in p.rooms if r.spec.type != "corridor"))
        ratio = target / (sum(nets) / len(nets))
        if abs(ratio - 1) < 0.01:
            break
        if free == "depth":
            d = 2 * te + (d - 2 * te) * ratio
        elif free == "width":
            w = 2 * te + (w - 2 * te) * ratio
        else:
            k = math.sqrt(ratio)
            w, d = 2 * te + (w - 2 * te) * k, 2 * te + (d - 2 * te) * k
        w, d = round(w * 20) / 20, round(d * 20) / 20
    return w, d

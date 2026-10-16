"""Floor Plan Studio - rule-based floor plan generator."""

from .layout import generate
from .program import build_program, resolve_footprint

__version__ = "0.1.0"
__all__ = ["generate", "build_program", "resolve_footprint", "design"]


def design(config: dict, seed: int = 0, candidates: int = 400):
    """Config dict -> Plan (the one call most callers need)."""
    from .rules import get_rules
    rules_name = config.get("rules", "jordan")
    settings = {**get_rules(rules_name).DEFAULT_SETTINGS, **config.get("settings", {})}
    specs = build_program(config)
    w, d, notes, free = resolve_footprint(config, specs, settings)
    if free:
        w, d = calibrate(specs, w, d, free, settings, rules_name)
    plan = generate(specs, w, d, seed=seed, settings=settings, rules_name=rules_name,
                    candidates=candidates, project=config.get("project", ""))
    plan.warnings = [dict(ar=n, en=n) for n in notes] + plan.warnings
    return plan


def calibrate(specs, w, d, free, settings, rules_name, rounds=4):
    """Adjust the estimated dimension(s) until the net room areas match the
    targets. Uses fixed probe seeds so every seed gets the same footprint."""
    import math
    te = settings["exterior_wall"]
    target = sum(s.area for s in specs)
    for _ in range(rounds):
        nets = []
        for probe in (101, 102, 103):
            p = generate(specs, w, d, seed=probe, settings=settings, rules_name=rules_name, candidates=80)
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

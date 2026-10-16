"""Seeded floor-plan generator.

The footprint (outer width x depth) is fixed. The seed only changes the
arrangement: which side the bedrooms go, how rooms are grouped, the order
along the corridor, where cuts fall... For each seed we try many candidates
and keep the one that best satisfies the rules (see `evaluate`).
"""

from __future__ import annotations

import random

from .models import EPS, Plan, Rect, Room, RoomSpec
from .openings import exterior_segments, plan_doors, plan_windows, WET
from .rules import get_rules

MIN_ROW = 2.8          # minimum depth of a bedroom row (m)


def generate(specs: list[RoomSpec], width: float, depth: float, seed: int = 0,
             settings: dict | None = None, rules_name: str = "jordan",
             candidates: int = 400, project: str = "") -> Plan:
    rules = get_rules(rules_name)
    st = {**rules.DEFAULT_SETTINGS, **(settings or {})}
    rng = random.Random(seed)
    best: Plan | None = None
    for _ in range(candidates):
        rects = _candidate(specs, width, depth, st, rng)
        if rects is None:
            continue
        plan = _build(specs, rects, width, depth, st, rules)
        plan.score, plan.warnings = evaluate(plan, rules)
        if best is None or plan.score < best.score:
            best = plan
    if best is None:
        raise ValueError("Could not lay out this programme in the given footprint")
    best.seed, best.project = seed, project
    return best


# --- candidate generation ----------------------------------------------------
NIGHT = "__night__"


def _candidate(specs, W, D, st, rng) -> dict[str, Rect] | None:
    """One random layout. It is built up to 3 times with the same random
    choices, correcting the corridor allowance so room areas come out right."""
    sub_seed = rng.random()
    k = 1.0 + st["corridor"] / 4.0       # first guess: corridor = 30 % of bedroom wing
    rects = None
    for _ in range(3):
        rects = _attempt(specs, W, D, st, random.Random(sub_seed), k)
        if rects is None or "corridor1" not in rects:
            return rects
        night_area = sum(rects[s.id].area for s in specs if s.zone == "private")
        k_real = (night_area + rects["corridor1"].area) / night_area
        if abs(k_real - k) < 0.005:
            break
        k = k_real
    return rects


def _attempt(specs, W, D, st, rng, k) -> dict[str, Rect] | None:
    te, c = st["exterior_wall"], st["corridor"]
    iw, idp = W - 2 * te, D - 2 * te
    swap = idp > iw                      # work with the long side along x
    L, S = (idp, iw) if swap else (iw, idp)
    day = [s for s in specs if s.zone in ("public", "service")]
    night = [s for s in specs if s.zone == "private"]

    eff = lambda s: s.area * (k if s in night else 1.0)   # bedrooms also "pay" for the corridor
    fixed = sum(eff(s) for s in specs if s.fixed)
    flex = sum(eff(s) for s in specs if not s.fixed)
    scale = (L * S - fixed) / flex if flex > 0 else 1.0
    if scale <= 0:
        return None
    area = {s.id: s.area * (1.0 if s.fixed else scale) for s in specs}

    bounds = Rect(0.0, 0.0, L, S)
    items = _day_items(day, area, rng)
    if night:
        items.append((NIGHT, sum(area[s.id] for s in night) * k))
    rects: dict[str, Rect] = {}
    _slice(bounds, items, rng, rects)
    if NIGHT in rects:
        block = _night_block(rects.pop(NIGHT), bounds, night, area, c, rng, has_day=bool(day))
        if block is None:
            return None
        rects.update(block)

    out = {}
    for rid, r in rects.items():
        if swap:
            r = r.swapped()
        out[rid] = r.moved(te, te)
    return out


# small rooms that are usually grouped with a host room
CLUSTERS = [("entrance", ("guest_wc",)), ("kitchen", ("laundry", "storage", "maid"))]


def _day_items(day, area, rng) -> list[tuple]:
    """Slice items for the day zone; clusters keep small rooms next to their
    host and stop them from becoming long strips."""
    used, items = set(), []
    for host_type, guest_types in CLUSTERS:
        hosts = [s for s in day if s.type == host_type and s.id not in used]
        if not hosts or rng.random() < 0.25:
            continue
        members = [hosts[0]] + [s for s in day if s.type in guest_types and s.id not in used]
        if len(members) > 1:
            used.update(m.id for m in members)
            sub = [(m.id, area[m.id]) for m in members]
            items.append((sub, sum(a for _, a in sub)))
    return items + [(s.id, area[s.id]) for s in day if s.id not in used]


def _night_units(night, rng) -> list[list[list[RoomSpec]]]:
    """Units of slots. A slot is [room touching corridor, optional room behind].
    Master + ensuite stay together; a shared bathroom may be stacked with the
    ensuite (bathroom on the corridor side, ensuite behind, entered from master)."""
    masters = [s for s in night if s.type == "master"]
    ensuites = [s for s in night if s.type == "ensuite"]
    baths = [s for s in night if s.type == "bathroom"]
    units = []
    for i, m in enumerate(masters):
        u = [[m]]
        if i < len(ensuites):
            if baths and rng.random() < 0.6:
                u.append([baths.pop(), ensuites[i]])
            else:
                u.append([ensuites[i]])
        if rng.random() < 0.5:
            u.reverse()
        units.append(u)
    units += [[[e]] for e in ensuites[len(masters):]]
    units += [[[b]] for b in baths]
    units += [[[s]] for s in night if s.type not in ("master", "ensuite", "bathroom")]
    return units


def _night_block(R: Rect, bounds: Rect, night, area, c, rng, has_day: bool) -> dict[str, Rect] | None:
    """Lay bedrooms in one or two rows along a corridor inside block R. The
    corridor always touches a side of R that faces the day zone."""
    sides = {"bottom": R.y0 > bounds.y0 + EPS, "top": R.y1 < bounds.y1 - EPS,
             "left": R.x0 > bounds.x0 + EPS, "right": R.x1 < bounds.x1 - EPS}
    interior = [k for k, v in sides.items() if v] if has_day else list(sides)
    options = []
    for side in interior:
        horiz = side in ("bottom", "top")
        depth = R.h if horiz else R.w           # single-loaded: corridor along this side
        if MIN_ROW <= depth - c <= 6.5:
            options.append(("single", side))
        across = R.w if horiz else R.h          # double-loaded: corridor ends on this side
        if across - c >= 2 * MIN_ROW:
            options.append(("double", side))
    if not options:
        return None
    mode, side = rng.choice(options)
    horiz = side in ("bottom", "top")
    # local frame: u along the corridor, v across it
    run_x = horiz if mode == "single" else not horiz
    u0, u1, v0, v1 = (R.x0, R.x1, R.y0, R.y1) if run_x else (R.y0, R.y1, R.x0, R.x1)
    to_rect = (lambda a, b, p, q: Rect(a, p, b, q)) if run_x else (lambda a, b, p, q: Rect(p, a, q, b))

    units = _night_units(night, rng)
    nrows = 2 if mode == "double" and len(units) >= 2 else 1
    rows: list[list] = [[] for _ in range(nrows)]
    loads = [0.0] * nrows
    u_area = lambda u: sum(area[s.id] for slot in u for s in slot)
    for u in sorted(units, key=lambda u: -u_area(u) * rng.uniform(0.6, 1.4)):
        i = min(range(nrows), key=lambda j: loads[j] + rng.uniform(0, 3))
        rows[i].append(u)
        loads[i] += u_area(u)

    out: dict[str, Rect] = {}
    if nrows == 2:
        d0 = (v1 - v0 - c) * loads[0] / sum(loads)
        d0 = min(max(d0, MIN_ROW), v1 - v0 - c - MIN_ROW)
        cv = v0 + d0
        bands = [(v0, cv, "hi"), (cv + c, v1, "lo")]
    else:
        low = side in ("bottom", "left") if mode == "single" else rng.random() < 0.5
        cv = v0 if low else v1 - c
        bands = [(v0 + c, v1, "lo")] if low else [(v0, v1 - c, "hi")]
    out["corridor1"] = to_rect(u0, u1, cv, cv + c)

    for row, (b0, b1, corr) in zip(rows, bands):
        rng.shuffle(row)
        slots = [slot for u in row for slot in u]
        total = sum(area[s.id] for slot in slots for s in slot)
        x = u0
        for i, slot in enumerate(slots):
            sa = sum(area[s.id] for s in slot)
            nx = u1 if i == len(slots) - 1 else x + (u1 - u0) * sa / total
            if len(slot) == 1:
                out[slot[0].id] = to_rect(x, nx, b0, b1)
            else:
                near, far = slot
                dn = (b1 - b0) * area[near.id] / sa
                if corr == "lo":
                    out[near.id], out[far.id] = to_rect(x, nx, b0, b0 + dn), to_rect(x, nx, b0 + dn, b1)
                else:
                    out[near.id], out[far.id] = to_rect(x, nx, b1 - dn, b1), to_rect(x, nx, b0, b1 - dn)
            x = nx
    return out


def _slice(rect: Rect, items: list[tuple], rng, out: dict[str, Rect]) -> None:
    """Recursive guillotine cut, cut positions proportional to areas.
    An item is (room_id, area) or ([items...], area) for a cluster."""
    if len(items) == 1:
        key = items[0][0]
        if isinstance(key, list):
            _slice(rect, key, rng, out)
        else:
            out[key] = rect
        return
    items = items[:]
    rng.shuffle(items)
    total = sum(a for _, a in items)
    options, acc = [], 0.0
    for k in range(1, len(items)):
        acc += items[k - 1][1]
        options.append((abs(acc - total / 2), k, acc))
    options.sort()
    _, k, acc = options[min(len(options) - 1, int(rng.random() ** 2 * len(options)))]
    t = acc / total
    cut_x = rect.w >= rect.h
    if rng.random() < 0.2:
        cut_x = not cut_x
    if cut_x:
        xm = rect.x0 + t * rect.w
        a, b = Rect(rect.x0, rect.y0, xm, rect.y1), Rect(xm, rect.y0, rect.x1, rect.y1)
    else:
        ym = rect.y0 + t * rect.h
        a, b = Rect(rect.x0, rect.y0, rect.x1, ym), Rect(rect.x0, ym, rect.x1, rect.y1)
    _slice(a, items[:k], rng, out)
    _slice(b, items[k:], rng, out)


# --- assembling a plan -----------------------------------------------------
def _net(r: Rect, W, D, te, ti) -> Rect:
    h = ti / 2
    return Rect(r.x0 + (0 if abs(r.x0 - te) < EPS else h), r.y0 + (0 if abs(r.y0 - te) < EPS else h),
                r.x1 - (0 if abs(r.x1 - (W - te)) < EPS else h), r.y1 - (0 if abs(r.y1 - (D - te)) < EPS else h))


def _build(specs, rects, W, D, st, rules) -> Plan:
    te, ti = st["exterior_wall"], st["interior_wall"]
    all_specs = list(specs)
    if "corridor1" in rects:
        cr = rects["corridor1"]
        all_specs.append(RoomSpec("corridor1", "corridor", cr.area, name_ar="ممر", name_en="Corridor"))
    rooms = [Room(s, rects[s.id], _net(rects[s.id], W, D, te, ti)) for s in all_specs]
    plan = Plan(W, D, rooms, [], st)
    doors, stats = plan_doors(rooms, W, D, st, rules)
    plan.openings = doors + plan_windows(rooms, W, D, st, rules, doors)
    plan._stats = stats  # used by evaluate
    return plan


# --- scoring -----------------------------------------------------------------
def evaluate(plan: Plan, rules) -> tuple[float, list[dict]]:
    """Lower is better. Also returns human readable warnings (ar/en)."""
    st, stats = plan.settings, plan._stats
    te = st["exterior_wall"]
    score, warn = 0.0, []
    windows = {o.rooms[0] for o in plan.openings if o.kind == "window"}
    types = {r.spec.type for r in plan.rooms}

    for r in plan.rooms:
        info = rules.ROOM_TYPES[r.spec.type]
        n = r.net
        ar_name, en_name = r.spec.name_ar, r.spec.name_en
        if r.spec.type == "corridor":
            continue
        dev = abs(n.area - r.spec.area) / r.spec.area
        score += dev * (8 if r.spec.fixed else 2)
        if r.spec.fixed and dev > 0.05:
            warn.append(dict(ar=f"{ar_name}: المساحة {n.area:.1f} م² بدل {r.spec.area:.1f} م² المطلوبة",
                             en=f"{en_name}: {n.area:.1f} m² instead of the fixed {r.spec.area:.1f} m²"))
        if n.aspect > info["max_aspect"]:
            score += (n.aspect - info["max_aspect"]) * 4
            if n.aspect > info["max_aspect"] + 0.3:
                warn.append(dict(ar=f"{ar_name}: الغرفة طويلة وضيقة ({n.w:.2f}×{n.h:.2f})",
                                 en=f"{en_name}: long and narrow ({n.w:.2f}x{n.h:.2f})"))
        if n.short < info["min_width"]:
            score += (info["min_width"] - n.short) * 15
            warn.append(dict(ar=f"{ar_name}: العرض {n.short:.2f} م أقل من الحد الأدنى {info['min_width']} م",
                             en=f"{en_name}: width {n.short:.2f} m below minimum {info['min_width']} m"))
        if n.area < info["min_area"]:
            score += (info["min_area"] - n.area) / info["min_area"] * 15
            warn.append(dict(ar=f"{ar_name}: المساحة {n.area:.1f} م² أقل من الحد الأدنى {info['min_area']} م²",
                             en=f"{en_name}: {n.area:.1f} m² below minimum {info['min_area']} m²"))
        if info["habitable"] and r.id not in windows:
            score += 15
            warn.append(dict(ar=f"{ar_name}: ما في شباك على واجهة خارجية",
                             en=f"{en_name}: no window on an exterior wall"))
        elif r.spec.type in WET and r.id not in windows:
            score += 1.0
            warn.append(dict(ar=f"{ar_name}: بدون شباك - بحاجة لتهوية ميكانيكية",
                             en=f"{en_name}: no window - needs mechanical ventilation"))

    for rid in stats["unreached"]:
        r = plan.room(rid)
        score += 100
        warn.append(dict(ar=f"{r.spec.name_ar}: ما في طريق للوصول إليها", en=f"{r.spec.name_en}: not reachable"))
    score += stats["detours"] * 7 + stats["through_private"] * 25
    if stats["through_private"]:
        warn.append(dict(ar="في غرفة الدخول إلها من خلال غرفة نوم", en="A room is reached through a bedroom"))

    adj = stats.get("adjacency", {})
    first = {}
    for r in plan.rooms:
        first.setdefault(r.spec.type, r.id)
    for a, b, wgt in rules.ADJACENCY_WISHES:
        if a in first and b in first and first[b] not in adj.get(first[a], {}):
            score += wgt
    if "entrance" in types and stats.get("main_in") != "entrance":
        score += 18
        warn.append(dict(ar="الباب الرئيسي مش داخل على المدخل", en="Main door does not open into the entrance"))
    if stats.get("main_side") != "front":
        score += 10
        warn.append(dict(ar="الباب الرئيسي مش على الواجهة الأمامية", en="Main door is not on the front"))
    if "salon" in first and "front" not in exterior_segments(plan.room(first["salon"]).rect, plan.width, plan.depth, te):
        score += 3
    return score, warn

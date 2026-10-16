"""Doors and windows: circulation tree from the main door + exterior glazing."""

from __future__ import annotations

from .models import EPS, Opening, Rect, Room, Segment

WET = {"bathroom", "ensuite", "guest_wc", "laundry"}
NO_PASS = WET | {"storage"}               # never walk through these
PRIVATE_PASS = {"bedroom", "master", "maid", "office"}  # walk-through allowed but bad
DOOR_MARGIN = 0.20                        # door edge to wall corner
MIN_MARGIN = 0.10                         # ... in tight spots


def shared_segment(a: Rect, b: Rect) -> Segment | None:
    if abs(a.x1 - b.x0) < EPS or abs(b.x1 - a.x0) < EPS:
        x = a.x1 if abs(a.x1 - b.x0) < EPS else a.x0
        s0, s1 = max(a.y0, b.y0), min(a.y1, b.y1)
        if s1 - s0 > EPS:
            return Segment("v", x, s0, s1)
    if abs(a.y1 - b.y0) < EPS or abs(b.y1 - a.y0) < EPS:
        y = a.y1 if abs(a.y1 - b.y0) < EPS else a.y0
        s0, s1 = max(a.x0, b.x0), min(a.x1, b.x1)
        if s1 - s0 > EPS:
            return Segment("h", y, s0, s1)
    return None


def exterior_segments(r: Rect, W: float, D: float, te: float) -> dict[str, Segment]:
    """Exterior wall centreline segments of a room, keyed by side."""
    out = {}
    if abs(r.y0 - te) < EPS:
        out["front"] = Segment("h", te / 2, r.x0, r.x1)
    if abs(r.y1 - (D - te)) < EPS:
        out["back"] = Segment("h", D - te / 2, r.x0, r.x1)
    if abs(r.x0 - te) < EPS:
        out["left"] = Segment("v", te / 2, r.y0, r.y1)
    if abs(r.x1 - (W - te)) < EPS:
        out["right"] = Segment("v", W - te / 2, r.y0, r.y1)
    return out


def _normal_sign(seg: Segment, toward: Rect) -> int:
    cx, cy = toward.center
    return 1 if (cy if seg.orient == "h" else cx) > seg.coord else -1


def _place_on(seg: Segment, width: float, prefer: float | None) -> tuple[Segment, int] | None:
    """Door span near the segment end closest to `prefer` (a coordinate)."""
    if not door_fits(seg, width):
        return None
    m = min(DOOR_MARGIN, (seg.length - width) / 2)   # tight spots (corridor ends) get a smaller margin
    mid = (seg.s0 + seg.s1) / 2
    if prefer is not None and prefer > mid:
        return Segment(seg.orient, seg.coord, seg.s1 - m - width, seg.s1 - m), 1
    return Segment(seg.orient, seg.coord, seg.s0 + m, seg.s0 + m + width), 0


def door_fits(seg: Segment, width: float) -> bool:
    return seg.length >= width + 2 * MIN_MARGIN


def door_width(room_type: str, st: dict) -> float:
    return st["wet_door_width"] if room_type in WET else st["door_width"]


def plan_doors(rooms: list[Room], W: float, D: float, st: dict, rules) -> tuple[list[Opening], dict]:
    """Build a door tree from the main entrance. Returns openings and stats."""
    te, ti = st["exterior_wall"], st["interior_wall"]
    by_id = {r.id: r for r in rooms}
    adj: dict[str, dict[str, Segment]] = {r.id: {} for r in rooms}
    for i, a in enumerate(rooms):
        for b in rooms[i + 1:]:
            seg = shared_segment(a.rect, b.rect)
            if seg:
                adj[a.id][b.id] = seg
                adj[b.id][a.id] = seg

    openings: list[Opening] = []
    stats = dict(unreached=[], detours=0, through_private=0, main_in=None)

    # main door: front wall, preferred room types in order
    order = ["entrance", "living", "salon", "corridor", "dining"]
    main = None
    for side in ("front", "left", "right", "back"):
        for t in order + [r.spec.type for r in rooms]:
            for r in rooms:
                if r.spec.type != t or r.spec.type in NO_PASS:
                    continue
                seg = exterior_segments(r.rect, W, D, te).get(side)
                if seg:
                    placed = _place_on(seg, st["main_door_width"], None)
                    if placed:
                        span, _ = placed
                        mid = (seg.s0 + seg.s1 - span.length) / 2   # centre main door
                        span = Segment(seg.orient, seg.coord, mid, mid + span.length)
                        main = (r, span, side)
                        break
            if main:
                break
        if main:
            break
    if main is None:
        stats["unreached"] = [r.id for r in rooms]
        return openings, stats
    r0, span, side = main
    openings.append(Opening("main_door", span, te, (r0.id,), into=_normal_sign(span, r0.rect),
                            hinge=0, head=st["door_height"]))
    stats["main_in"] = r0.spec.type
    stats["main_side"] = side

    def priority(r: Room, p: Room) -> int | None:
        """How good it is to enter room r from room p (lower = better)."""
        if p.spec.type in NO_PASS:
            return None
        prefs = rules.ACCESS_FROM.get(r.spec.type, [])
        if p.spec.type in prefs:
            return prefs.index(p.spec.type)
        if r.spec.type == "ensuite":
            return None
        return 50 if p.spec.type in PRIVATE_PASS else 10

    def options(r: Room):
        for pid, seg in adj[r.id].items():
            pri = priority(r, by_id[pid])
            if pri is not None and door_fits(seg, door_width(r.spec.type, st)):
                yield pri, pid

    # 1) grow a tree from the main door, always taking the best available door
    parent: dict[str, tuple[str, int]] = {}
    reached = {r0.id}
    while True:
        best = None
        for r in rooms:
            if r.id in reached:
                continue
            for pri, pid in options(r):
                if pid in reached and (best is None or pri < best[0]):
                    best = (pri, r.id, pid)
        if best is None:
            break
        pri, rid, pid = best
        parent[rid] = (pid, pri)
        reached.add(rid)

    # 2) now that everything is reachable, re-attach rooms to a better neighbour
    def ancestors(rid):
        while rid in parent:
            rid = parent[rid][0]
            yield rid

    changed = True
    while changed:
        changed = False
        for rid in list(parent):
            for pri, pid in options(by_id[rid]):
                if pri < parent[rid][1] and pid in reached and rid not in ancestors(pid) and pid != rid:
                    parent[rid] = (pid, pri)
                    changed = True

    for rid, (pid, pri) in parent.items():
        r, p, seg = by_id[rid], by_id[pid], adj[rid][pid]
        pc = p.rect.center[0 if seg.orient == "h" else 1]
        span, hinge = _place_on(seg, door_width(r.spec.type, st), pc)
        openings.append(Opening("door", span, ti, (pid, rid), into=_normal_sign(span, r.rect),
                                hinge=hinge, head=st["door_height"]))
        if pri >= 50:
            stats["through_private"] += 1
        elif pri >= 10:
            stats["detours"] += 1
    stats["unreached"] = [r.id for r in rooms if r.id not in reached]
    stats["adjacency"] = adj
    stats["parent"] = parent
    return openings, stats


def _free_intervals(seg: Segment, taken: list[Segment], margin: float) -> list[tuple[float, float]]:
    free = [(seg.s0 + margin, seg.s1 - margin)]
    for t in taken:
        if t.orient != seg.orient or abs(t.coord - seg.coord) > EPS:
            continue
        nxt = []
        for a, b in free:
            lo, hi = t.s0 - margin, t.s1 + margin
            if hi <= a or lo >= b:
                nxt.append((a, b))
                continue
            if lo > a:
                nxt.append((a, lo))
            if hi < b:
                nxt.append((hi, b))
        free = nxt
    return [(a, b) for a, b in free if b - a > EPS]


def plan_windows(rooms: list[Room], W: float, D: float, st: dict, rules, taken: list[Opening]) -> list[Opening]:
    te = st["exterior_wall"]
    used = [o.seg for o in taken if o.kind == "main_door"]
    out: list[Opening] = []
    for r in rooms:
        info = rules.ROOM_TYPES[r.spec.type]
        ext = exterior_segments(r.rect, W, D, te)
        if not ext or r.spec.type == "entrance":
            continue
        sill, head = st["window_sill"], st["window_head"]
        if info["habitable"]:
            width = max(1.0, min(2.4, info["window"] * r.net.area / (head - sill)))
        elif r.spec.type in WET or r.spec.type == "storage":
            width, sill = 0.6, st["wet_window_sill"]
        else:          # corridor
            width = 0.9
        segs = sorted(ext.values(), key=lambda s: -s.length)
        count = 2 if info["habitable"] and r.net.area > 20 and len(segs) > 1 else 1
        for seg in segs[:count]:
            free = _free_intervals(seg, used, 0.4)
            if not free:
                continue
            a, b = max(free, key=lambda ab: ab[1] - ab[0])
            w = min(width, b - a)
            if w < 0.5:
                continue
            mid = (a + b) / 2
            span = Segment(seg.orient, seg.coord, mid - w / 2, mid + w / 2)
            used.append(span)
            out.append(Opening("window", span, te, (r.id,), sill=sill, head=head))
    return out

"""Manual edits on a Plan (used by the edit mode).

Rooms always tile the inside of the building, so walls are edited as lines:
moving a line moves every room edge that lies on it. Openings are kept on
their walls (clamped, or dropped when their wall disappears). All functions
change the plan in place; call `refresh` afterwards (the GUI does).
"""

from __future__ import annotations

from dataclasses import dataclass

from .models import EPS, Opening, Plan, Rect, Room, RoomSpec, Segment
from .openings import exterior_segments, shared_segment, door_width, WET
from .rules import get_rules

MIN_ROOM = 0.6          # smallest room side allowed while dragging (m)
TOL = 1e-4


@dataclass
class WallLine:
    """orient 'v': x = coord, spans y in [s0, s1]; 'h': y = coord, spans x.
    side is '' for interior walls, else left/right/bottom/top (coord is then
    the inside face of the exterior wall)."""
    orient: str
    coord: float
    s0: float
    s1: float
    side: str = ""

    @property
    def length(self) -> float:
        return self.s1 - self.s0


def _close(a, b, tol=TOL):
    return abs(a - b) < tol


def _merge(intervals):
    out = []
    for a, b in sorted(intervals):
        if out and a <= out[-1][1] + TOL:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return out


def wall_lines(plan: Plan) -> list[WallLine]:
    te = plan.settings["exterior_wall"]
    W, D = plan.width, plan.depth
    v, h = {}, {}
    for r in plan.rooms:
        x0, y0, x1, y1 = r.rect.x0, r.rect.y0, r.rect.x1, r.rect.y1
        for x in (x0, x1):
            if not (_close(x, te) or _close(x, W - te)):
                v.setdefault(round(x, 5), []).append((y0, y1))
        for y in (y0, y1):
            if not (_close(y, te) or _close(y, D - te)):
                h.setdefault(round(y, 5), []).append((x0, x1))
    lines = []
    for c, iv in v.items():
        lines += [WallLine("v", c, a, b) for a, b in _merge(iv)]
    for c, iv in h.items():
        lines += [WallLine("h", c, a, b) for a, b in _merge(iv)]
    lines += [WallLine("v", te, te, D - te, "left"), WallLine("v", W - te, te, D - te, "right"),
              WallLine("h", te, te, W - te, "bottom"), WallLine("h", D - te, te, W - te, "top")]
    return lines


def _on_line(line: WallLine, lo: float, hi: float) -> bool:
    return lo >= line.s0 - TOL and hi <= line.s1 + TOL


def move_wall(plan: Plan, line: WallLine, new: float) -> bool:
    """Move a wall line to `new` (same meaning as line.coord). Returns False
    (and changes nothing) if a room would become thinner than MIN_ROOM."""
    te = plan.settings["exterior_wall"]
    d = new - line.coord
    if abs(d) < 1e-9:
        return True
    if line.orient == "v":
        before = [r for r in plan.rooms if _close(r.rect.x1, line.coord) and _on_line(line, r.rect.y0, r.rect.y1)]
        after = [r for r in plan.rooms if _close(r.rect.x0, line.coord) and _on_line(line, r.rect.y0, r.rect.y1)]
        if any(new - r.rect.x0 < MIN_ROOM for r in before) or any(r.rect.x1 - new < MIN_ROOM for r in after):
            return False
        for r in before:
            r.rect.x1 = new
        for r in after:
            r.rect.x0 = new
    else:
        before = [r for r in plan.rooms if _close(r.rect.y1, line.coord) and _on_line(line, r.rect.x0, r.rect.x1)]
        after = [r for r in plan.rooms if _close(r.rect.y0, line.coord) and _on_line(line, r.rect.x0, r.rect.x1)]
        if any(new - r.rect.y0 < MIN_ROOM for r in before) or any(r.rect.y1 - new < MIN_ROOM for r in after):
            return False
        for r in before:
            r.rect.y1 = new
        for r in after:
            r.rect.y0 = new

    if line.side in ("left", "bottom"):
        pass                     # handled by the shift below (that wall stays at the origin)
    else:
        for o in plan.openings:  # openings sitting on the moved wall follow it
            if o.seg.orient != line.orient:
                continue
            if line.side == "right":
                on = _close(o.seg.coord, plan.width - te / 2)
            elif line.side == "top":
                on = _close(o.seg.coord, plan.depth - te / 2)
            else:
                on = _close(o.seg.coord, line.coord) and _on_line(line, o.seg.s0, o.seg.s1)
            if on:
                o.seg.coord += d

    if line.side == "right":
        plan.width += d
    elif line.side == "top":
        plan.depth += d
    elif line.side in ("left", "bottom"):
        _shift(plan, -d if line.side == "left" else 0.0, -d if line.side == "bottom" else 0.0)
        if line.side == "left":
            plan.width -= d
        else:
            plan.depth -= d
    fix_openings(plan)
    return True


def _shift(plan: Plan, dx: float, dy: float) -> None:
    """Translate rooms/openings/furniture. Openings on the left (dx) or bottom
    (dy) exterior wall stay where they are: that wall stays at the origin."""
    te = plan.settings["exterior_wall"]
    for r in plan.rooms:
        r.rect = r.rect.moved(dx, dy)
    for o in plan.openings:
        s = o.seg
        if s.orient == "v":
            if not (dx and _close(s.coord, te / 2)):
                s.coord += dx
            s.s0, s.s1 = s.s0 + dy, s.s1 + dy
        else:
            if not (dy and _close(s.coord, te / 2)):
                s.coord += dy
            s.s0, s.s1 = s.s0 + dx, s.s1 + dx
    for f in plan.furniture:
        f.x += dx
        f.y += dy


def _host_segment(plan: Plan, o: Opening) -> Segment | None:
    te = plan.settings["exterior_wall"]
    rooms = {r.id: r for r in plan.rooms}
    if len(o.rooms) == 2:
        a, b = rooms.get(o.rooms[0]), rooms.get(o.rooms[1])
        if not a or not b:
            return None
        seg = shared_segment(a.rect, b.rect)
        return seg if seg and seg.orient == o.seg.orient else None
    r = rooms.get(o.rooms[0])
    if not r:
        return None
    for seg in exterior_segments(r.rect, plan.width, plan.depth, te).values():
        if seg.orient == o.seg.orient and abs(seg.coord - o.seg.coord) < 0.05:
            return seg
    return None


def clamp_opening(o: Opening, host: Segment, margin: float = 0.1) -> bool:
    room = host.length - 2 * margin
    if room < 0.4:
        return False
    w = min(o.width, room)
    c = (o.seg.s0 + o.seg.s1) / 2
    c = min(max(c, host.s0 + margin + w / 2), host.s1 - margin - w / 2)
    o.seg = Segment(host.orient, host.coord, c - w / 2, c + w / 2)
    return True


def fix_openings(plan: Plan) -> list[Opening]:
    """Keep every opening on its wall; returns the ones that had to be removed."""
    keep, dropped = [], []
    for o in plan.openings:
        host = _host_segment(plan, o)
        if host and clamp_opening(o, host):
            keep.append(o)
        else:
            dropped.append(o)
    plan.openings = keep
    return dropped


# --- openings -----------------------------------------------------------------
def nearest_wall(plan: Plan, x: float, y: float, exterior: bool, tol: float = 0.4):
    """Closest wall segment to a point: (rooms tuple, Segment, thickness) or None."""
    st = plan.settings
    best = None
    if exterior:
        for r in plan.rooms:
            for seg in exterior_segments(r.rect, plan.width, plan.depth, st["exterior_wall"]).values():
                cand = _dist(seg, x, y)
                if cand is not None and cand < tol and (best is None or cand < best[0]):
                    best = (cand, (r.id,), seg, st["exterior_wall"])
    else:
        for i, a in enumerate(plan.rooms):
            for b in plan.rooms[i + 1:]:
                seg = shared_segment(a.rect, b.rect)
                if not seg:
                    continue
                cand = _dist(seg, x, y)
                if cand is not None and cand < tol and (best is None or cand < best[0]):
                    best = (cand, (a.id, b.id), seg, st["interior_wall"])
    return best[1:] if best else None


def _dist(seg: Segment, x: float, y: float):
    along, across = (x, y) if seg.orient == "h" else (y, x)
    if seg.s0 - 0.05 <= along <= seg.s1 + 0.05:
        return abs(across - seg.coord)
    return None


def add_opening(plan: Plan, kind: str, x: float, y: float) -> Opening | None:
    """Add a door ('door') on the interior wall, or a window / main door on the
    exterior wall nearest to (x, y)."""
    st = plan.settings
    hit = nearest_wall(plan, x, y, exterior=kind in ("window", "main_door"))
    if not hit:
        return None
    rooms, seg, thick = hit
    by_id = {r.id: r for r in plan.rooms}
    if kind == "window":
        w, sill, head = 1.2, st["window_sill"], st["window_head"]
        if by_id[rooms[0]].spec.type in WET:
            w, sill = 0.6, st["wet_window_sill"]
    elif kind == "main_door":
        w, sill, head = st["main_door_width"], 0.0, st["door_height"]
    else:
        w = min(door_width(by_id[rooms[1]].spec.type, st), door_width(by_id[rooms[0]].spec.type, st))
        sill, head = 0.0, st["door_height"]
    along = x if seg.orient == "h" else y
    target = by_id[rooms[-1]].rect
    cx, cy = target.center
    into = 1 if (cy if seg.orient == "h" else cx) > seg.coord else -1
    o = Opening(kind, Segment(seg.orient, seg.coord, along - w / 2, along + w / 2), thick, rooms,
                into=into, hinge=0, sill=sill, head=head)
    if not clamp_opening(o, seg):
        return None
    plan.openings.append(o)
    return o


def move_opening(plan: Plan, o: Opening, along: float) -> None:
    host = _host_segment(plan, o)
    if host:
        w = o.width
        o.seg = Segment(o.seg.orient, o.seg.coord, along - w / 2, along + w / 2)
        clamp_opening(o, host)


def set_opening_width(plan: Plan, o: Opening, width: float) -> None:
    c = (o.seg.s0 + o.seg.s1) / 2
    o.seg = Segment(o.seg.orient, o.seg.coord, c - width / 2, c + width / 2)
    host = _host_segment(plan, o)
    if host:
        clamp_opening(o, host)


# --- rooms ------------------------------------------------------------------------
def set_room_size(plan: Plan, room: Room, width: float | None = None, length: float | None = None) -> bool:
    """Set the net width (x) / length (y) of a room by moving its right / top wall."""
    ok = True
    for value, orient in ((width, "v"), (length, "h")):
        if value is None:
            continue
        r = room.rect
        if orient == "v":
            edge, extra, lo, hi = r.x1, r.w - room.net.w, r.y0, r.y1
            new = r.x0 + value + extra
        else:
            edge, extra, lo, hi = r.y1, r.h - room.net.h, r.x0, r.x1
            new = r.y0 + value + extra
        line = next((ln for ln in wall_lines(plan) if ln.orient == orient and _close(ln.coord, edge)
                     and _on_line(ln, lo, hi)), None)
        ok = ok and line is not None and move_wall(plan, line, new)
        refresh_geometry(plan)
    return ok


def set_room_type(plan: Plan, room: Room, rtype: str) -> None:
    from .i18n import room_name
    old = room.spec
    room.spec = RoomSpec(old.id, rtype, old.area, old.occupants, old.fixed,
                         room_name(rtype, "ar"), room_name(rtype, "en"))


# --- refresh ----------------------------------------------------------------------
def refresh_geometry(plan: Plan) -> None:
    from .layout import _net
    st = plan.settings
    for r in plan.rooms:
        r.net = _net(r.rect, plan.width, plan.depth, st["exterior_wall"], st["interior_wall"])


def door_stats(plan: Plan) -> dict:
    """Reachability etc. from the openings that exist now (for evaluate)."""
    te = plan.settings["exterior_wall"]
    adj = {r.id: {} for r in plan.rooms}
    for i, a in enumerate(plan.rooms):
        for b in plan.rooms[i + 1:]:
            seg = shared_segment(a.rect, b.rect)
            if seg:
                adj[a.id][b.id] = adj[b.id][a.id] = seg
    links = {r.id: set() for r in plan.rooms}
    main = [o for o in plan.openings if o.kind == "main_door"]
    for o in plan.openings:
        if o.kind == "door" and all(rid in links for rid in o.rooms):
            a, b = o.rooms
            links[a].add(b)
            links[b].add(a)
    reached = set()
    stack = [o.rooms[0] for o in main if o.rooms[0] in links]
    while stack:
        rid = stack.pop()
        if rid in reached:
            continue
        reached.add(rid)
        stack += list(links[rid] - reached)
    by_id = {r.id: r for r in plan.rooms}
    side = ""
    if main:
        s = main[0].seg
        side = ("front" if _close(s.coord, te / 2, 0.01) else "back") if s.orient == "h" else "side"
    return dict(unreached=[r.id for r in plan.rooms if r.id not in reached], detours=0, through_private=0,
                main_in=by_id[main[0].rooms[0]].spec.type if main and main[0].rooms[0] in by_id else None,
                main_side=side, adjacency=adj)


def refresh(plan: Plan, rules_name: str = "jordan", mark_edited: bool = True) -> None:
    """Recompute net areas, score and warnings after edits. mark_edited=False
    re-evaluates without flagging the plan as changed by hand."""
    from .layout import evaluate
    refresh_geometry(plan)
    plan._stats = door_stats(plan)
    plan.score, plan.warnings = evaluate(plan, get_rules(rules_name))
    if mark_edited:
        plan.edited = True

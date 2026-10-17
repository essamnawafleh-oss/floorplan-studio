"""Core data structures. Units are metres, origin at the bottom-left outer
corner of the building, x to the right, y up. The front (street) side is y=0."""

from __future__ import annotations

from dataclasses import dataclass, field, asdict

EPS = 1e-6


@dataclass
class Rect:
    x0: float
    y0: float
    x1: float
    y1: float

    @property
    def w(self) -> float:
        return self.x1 - self.x0

    @property
    def h(self) -> float:
        return self.y1 - self.y0

    @property
    def area(self) -> float:
        return self.w * self.h

    @property
    def short(self) -> float:
        return min(self.w, self.h)

    @property
    def aspect(self) -> float:
        return max(self.w, self.h) / max(self.short, EPS)

    @property
    def center(self) -> tuple[float, float]:
        return ((self.x0 + self.x1) / 2, (self.y0 + self.y1) / 2)

    def swapped(self) -> "Rect":
        return Rect(self.y0, self.x0, self.y1, self.x1)

    def moved(self, dx: float, dy: float) -> "Rect":
        return Rect(self.x0 + dx, self.y0 + dy, self.x1 + dx, self.y1 + dy)


@dataclass
class Segment:
    """Part of a wall. orient 'h': horizontal wall at y=coord spanning x in
    [s0, s1]; 'v': vertical wall at x=coord spanning y in [s0, s1]."""
    orient: str
    coord: float
    s0: float
    s1: float

    @property
    def length(self) -> float:
        return self.s1 - self.s0


@dataclass
class RoomSpec:
    id: str
    type: str
    area: float               # target net area (m²)
    occupants: int = 0
    fixed: bool = False       # user fixed the area: never scaled
    name_ar: str = ""
    name_en: str = ""

    @property
    def zone(self) -> str:
        from .rules.jordan import ROOM_TYPES
        return ROOM_TYPES[self.type]["zone"]


@dataclass
class Room:
    spec: RoomSpec
    rect: Rect                # wall-centreline rectangle
    net: Rect                 # inside faces of walls

    @property
    def id(self) -> str:
        return self.spec.id


@dataclass
class Opening:
    kind: str                 # 'door' | 'main_door' | 'window'
    seg: Segment              # wall centreline + span of the opening
    thickness: float          # wall thickness at the opening
    rooms: tuple[str, ...]    # room ids (1 for exterior openings)
    into: int = 1             # door swings to +normal (1) or -normal (-1)
    hinge: int = 0            # hinge at s0 (0) or s1 (1)
    sill: float = 0.0
    head: float = 2.1
    block: str = ""           # optional library block drawn instead of the default symbol

    @property
    def width(self) -> float:
        return self.seg.length

    def gap_rect(self) -> Rect:
        t = self.thickness / 2
        s = self.seg
        if s.orient == "h":
            return Rect(s.s0, s.coord - t, s.s1, s.coord + t)
        return Rect(s.coord - t, s.s0, s.coord + t, s.s1)


@dataclass
class Furniture:
    """A library block placed on the plan. (x, y) is the block's base point."""
    block: str
    x: float
    y: float
    rotation: float = 0.0     # degrees, counter-clockwise
    scale: float = 1.0
    id: str = ""


@dataclass
class Plan:
    width: float
    depth: float
    rooms: list[Room]
    openings: list[Opening]
    settings: dict
    seed: int = 0
    score: float = 0.0
    warnings: list[str] = field(default_factory=list)
    project: str = ""
    furniture: list[Furniture] = field(default_factory=list)
    edited: bool = False      # changed by hand in edit mode
    drawing: list[dict] = field(default_factory=list)   # free CAD entities (see cad.py)

    def room(self, room_id: str) -> Room:
        return next(r for r in self.rooms if r.id == room_id)

    @property
    def gross_area(self) -> float:
        return self.width * self.depth

    @property
    def net_area(self) -> float:
        return sum(r.net.area for r in self.rooms)

    def to_dict(self) -> dict:
        return dict(
            project=self.project, width=self.width, depth=self.depth, seed=self.seed,
            score=round(self.score, 3), gross_area=round(self.gross_area, 2),
            net_area=round(self.net_area, 2), settings=self.settings, warnings=self.warnings,
            rooms=[dict(id=r.id, type=r.spec.type, name_ar=r.spec.name_ar, name_en=r.spec.name_en,
                        occupants=r.spec.occupants, target_area=round(r.spec.area, 2), fixed=r.spec.fixed,
                        net_area=round(r.net.area, 2), width=round(r.net.w, 2), length=round(r.net.h, 2),
                        rect=asdict(r.rect), net=asdict(r.net)) for r in self.rooms],
            openings=[dict(kind=o.kind, rooms=list(o.rooms), width=round(o.width, 2),
                           seg=asdict(o.seg), thickness=o.thickness, into=o.into, hinge=o.hinge,
                           sill=o.sill, head=o.head, block=o.block) for o in self.openings],
            furniture=[asdict(f) for f in self.furniture],
            edited=self.edited,
            drawing=[dict(e) for e in self.drawing],
        )

    @classmethod
    def from_dict(cls, d: dict) -> "Plan":
        rooms = []
        for r in d["rooms"]:
            spec = RoomSpec(r["id"], r["type"], r.get("target_area", r["net_area"]), r.get("occupants", 0),
                            fixed=bool(r.get("fixed", False)),   # older files have no "fixed"
                            name_ar=r.get("name_ar", ""), name_en=r.get("name_en", ""))
            rooms.append(Room(spec, Rect(**r["rect"]), Rect(**r["net"])))
        openings = [Opening(o["kind"], Segment(**o["seg"]), o["thickness"], tuple(o["rooms"]),
                            o.get("into", 1), o.get("hinge", 0), o.get("sill", 0.0), o.get("head", 2.1),
                            o.get("block", "")) for o in d.get("openings", [])]
        plan = cls(d["width"], d["depth"], rooms, openings, dict(d.get("settings", {})),
                   seed=d.get("seed", 0), score=d.get("score", 0.0), warnings=list(d.get("warnings", [])),
                   project=d.get("project", ""),
                   furniture=[Furniture(**f) for f in d.get("furniture", [])],
                   edited=d.get("edited", False),
                   drawing=[dict(e) for e in d.get("drawing", [])])
        return plan

    def copy(self) -> "Plan":
        return Plan.from_dict(self.to_dict())

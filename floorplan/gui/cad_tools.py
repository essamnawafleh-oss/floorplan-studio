"""AutoCAD-style drafting inside edit mode: command line, object snaps,
ortho/grid, window/crossing selection, grips and the draw/modify commands.

The controller (`Cad`) is owned by the Editor. Commands are small state
machines: they receive points (clicks or typed coordinates) and values (typed
text) and finish by committing an undoable edit on plan.drawing.
"""

from __future__ import annotations

import math

from PySide6.QtCore import QObject, Qt, Signal

from .. import cad
from ..blocks import furniture_polylines
from ..geometry import walls

# alias -> command class name
ALIASES = {
    "L": "Line", "LINE": "Line", "PL": "Pline", "PLINE": "Pline", "REC": "Rect", "RECTANG": "Rect",
    "C": "Circle", "CIRCLE": "Circle", "A": "Arc", "ARC": "Arc", "T": "Text", "DT": "Text", "TEXT": "Text",
    "DLI": "Dim", "DAL": "Dim", "DIM": "Dim", "O": "Offset", "OFFSET": "Offset", "TR": "Trim", "TRIM": "Trim",
    "EX": "Extend", "EXTEND": "Extend", "X": "Explode", "EXPLODE": "Explode", "E": "Erase", "ERASE": "Erase",
    "M": "Move", "MOVE": "Move", "CO": "Copy", "CP": "Copy", "COPY": "Copy", "RO": "Rotate", "ROTATE": "Rotate",
    "SC": "Scale", "SCALE": "Scale", "MI": "Mirror", "MIRROR": "Mirror",
}

SNAP_NAMES = {"end": ("نهاية", "Endpoint"), "mid": ("منتصف", "Midpoint"), "cen": ("مركز", "Center"),
              "int": ("تقاطع", "Intersection"), "perp": ("عمودي", "Perpendicular"), "near": ("أقرب", "Nearest"),
              "quad": ("ربع", "Quadrant"), "ins": ("إدراج", "Insertion"), "grid": ("شبكة", "Grid")}

P = {  # prompts (ar, en)
    "cmd": ("اكتب أمر (L, PL, REC, C, A, T, DIM, O, TR, EX, X, M, CO, RO, SC, MI, E)",
            "Type a command (L, PL, REC, C, A, T, DIM, O, TR, EX, X, M, CO, RO, SC, MI, E)"),
    "first": ("حدد النقطة الأولى", "Specify first point"),
    "next": ("النقطة التالية أو [Close/Undo]", "Specify next point or [Close/Undo]"),
    "pnext": ("النقطة التالية أو [Close/Undo] · Enter للإنهاء", "Next point or [Close/Undo] · Enter to finish"),
    "corner1": ("حدد الزاوية الأولى", "Specify first corner"),
    "corner2": ("الزاوية الثانية أو @عرض,طول", "Specify other corner or @width,height"),
    "center": ("حدد المركز", "Specify center point"),
    "radius": ("نصف القطر أو [Diameter]", "Specify radius or [Diameter]"),
    "diameter": ("القطر", "Specify diameter"),
    "arc1": ("نقطة بداية القوس", "Specify start point of arc"),
    "arc2": ("نقطة ثانية على القوس", "Specify second point of arc"),
    "arc3": ("نقطة نهاية القوس", "Specify end point of arc"),
    "tpos": ("نقطة بداية النص", "Specify start point of text"),
    "theight": ("ارتفاع النص <{h}>", "Specify height <{h}>"),
    "tstring": ("اكتب النص", "Enter text"),
    "dim1": ("أول نقطة للبعد", "Specify first extension line origin"),
    "dim2": ("ثاني نقطة", "Specify second extension line origin"),
    "dim3": ("مكان خط البعد", "Specify dimension line location"),
    "odist": ("مسافة الأوفست <{d}>", "Specify offset distance <{d}>"),
    "osel": ("اختار العنصر للأوفست · Enter للإنهاء", "Select object to offset · Enter to exit"),
    "oside": ("حدد الجهة", "Specify point on side to offset"),
    "trim": ("اختار الجزء اللي بدك تقصه · Shift = تمديد · Enter للإنهاء", "Select object to trim · Shift = extend · Enter to exit"),
    "extend": ("اختار طرف العنصر للتمديد · Shift = قص · Enter للإنهاء", "Select object to extend · Shift = trim · Enter to exit"),
    "select": ("اختار العناصر (كبسة أو صندوق) وبعدين Enter", "Select objects (click or box), then Enter"),
    "base": ("حدد نقطة الأساس", "Specify base point"),
    "second": ("حدد النقطة الثانية أو مسافة", "Specify second point or distance"),
    "angle": ("زاوية الدوران (درجات)", "Specify rotation angle (degrees)"),
    "factor": ("معامل التكبير", "Specify scale factor"),
    "mir1": ("أول نقطة على خط المرآة", "Specify first point of mirror line"),
    "mir2": ("ثاني نقطة على خط المرآة", "Specify second point of mirror line"),
    "mirdel": ("حذف الأصل؟ [Yes/No] <No>", "Erase source objects? [Yes/No] <No>"),
    "nothing": ("ما في عناصر محددة", "Nothing selected"),
    "unknown": ("أمر غير معروف", "Unknown command"),
    "no_bound": ("ما في حد للتمديد", "No boundary to extend to"),
}


def plan_refs(plan, library) -> list[dict]:
    """Plan geometry as entities: used for snapping and as trim/extend edges."""
    if plan is None:
        return []
    out = []
    for poly in walls(plan):
        for ring in [poly.exterior, *poly.interiors]:
            out.append({"t": "pline", "pts": [list(p) for p in list(ring.coords)[:-1]], "closed": True, "_ref": 1})
    if library:
        for f in plan.furniture:
            b = library.get(f.block)
            if b:
                for pl in furniture_polylines(b, f.x, f.y, f.rotation, f.scale):
                    out.append({"t": "pline", "pts": [list(p) for p in pl], "closed": False, "_ref": 1})
    return out


def _arc3(p1, p2, p3):
    """Arc through three points -> entity or None."""
    ax, ay = p1
    bx, by = p2
    cx, cy = p3
    d = 2 * (ax * (by - cy) + bx * (cy - ay) + cx * (ay - by))
    if abs(d) < 1e-12:
        return None
    ux = ((ax * ax + ay * ay) * (by - cy) + (bx * bx + by * by) * (cy - ay) + (cx * cx + cy * cy) * (ay - by)) / d
    uy = ((ax * ax + ay * ay) * (cx - bx) + (bx * bx + by * by) * (ax - cx) + (cx * cx + cy * cy) * (bx - ax)) / d
    r = math.hypot(ax - ux, ay - uy)
    a1, a2, a3 = (math.degrees(math.atan2(y - uy, x - ux)) % 360 for x, y in (p1, p2, p3))
    if (a2 - a1) % 360 <= (a3 - a1) % 360:      # counter-clockwise p1 -> p2 -> p3
        return {"t": "arc", "c": [ux, uy], "r": r, "a0": a1, "a1": a3}
    return {"t": "arc", "c": [ux, uy], "r": r, "a0": a3, "a1": a1}


# ------------------------------------------------------------------------- commands
class Command:
    needs_selection = False

    def __init__(self, ctl: "Cad"):
        self.ctl = ctl
        self.step = "start"

    def t(self, key, **kw):
        ar, en = P[key]
        return (ar if self.ctl.lang == "ar" else en).format(**kw)

    def prompt(self) -> str:
        return ""

    def point(self, pt):
        pass

    def value(self, text: str) -> bool:
        """Typed input that is not a point. Return False if not understood."""
        return False

    def enter(self):
        self.ctl.finish()

    def preview(self, cur) -> list[dict]:
        return []

    @property
    def last(self):
        return None

    def add(self, *ents):
        layer = self.ctl.layer
        self.ctl.commit(lambda p: p.drawing.extend({**e, "layer": e.get("layer", layer)} for e in ents))


class Line(Command):
    def __init__(self, ctl):
        super().__init__(ctl)
        self.pts, self.added = [], 0

    @property
    def last(self):
        return self.pts[-1] if self.pts else None

    def prompt(self):
        return self.t("first") if not self.pts else self.t("next")

    def point(self, pt):
        if self.pts:
            a = self.pts[-1]
            self.add({"t": "line", "p": [a[0], a[1], pt[0], pt[1]]})
            self.added += 1
        self.pts.append(pt)

    def value(self, text):
        s = text.strip().upper()
        if s in ("C", "CLOSE") and len(self.pts) >= 3:
            self.point(self.pts[0])
            self.ctl.finish()
            return True
        if s in ("U", "UNDO") and self.added:
            self.ctl.editor.undo()
            self.pts.pop()
            self.added -= 1
            return True
        return False

    def preview(self, cur):
        return [{"t": "line", "p": [*self.pts[-1], *cur]}] if self.pts and cur else []


class Pline(Line):
    def prompt(self):
        return self.t("first") if not self.pts else self.t("pnext")

    def point(self, pt):
        self.pts.append(pt)

    def _commit(self, closed=False):
        if len(self.pts) >= 2:
            self.add({"t": "pline", "pts": [list(p) for p in self.pts], "closed": closed})
        self.ctl.finish()

    def value(self, text):
        s = text.strip().upper()
        if s in ("C", "CLOSE") and len(self.pts) >= 3:
            self._commit(True)
            return True
        if s in ("U", "UNDO") and self.pts:
            self.pts.pop()
            return True
        return False

    def enter(self):
        self._commit()

    def preview(self, cur):
        pts = self.pts + ([cur] if cur else [])
        return [{"t": "pline", "pts": [list(p) for p in pts], "closed": False}] if len(pts) >= 2 else []


class Rect(Command):
    def __init__(self, ctl):
        super().__init__(ctl)
        self.c1 = None

    @property
    def last(self):
        return self.c1

    def prompt(self):
        return self.t("corner1") if self.c1 is None else self.t("corner2")

    @staticmethod
    def _rect(a, b):
        return {"t": "pline", "pts": [[a[0], a[1]], [b[0], a[1]], [b[0], b[1]], [a[0], b[1]]], "closed": True}

    def point(self, pt):
        if self.c1 is None:
            self.c1 = pt
        else:
            self.add(self._rect(self.c1, pt))
            self.ctl.finish()

    def preview(self, cur):
        return [self._rect(self.c1, cur)] if self.c1 and cur else []


class Circle(Command):
    def __init__(self, ctl):
        super().__init__(ctl)
        self.c, self.diam = None, False

    @property
    def last(self):
        return self.c

    def prompt(self):
        return self.t("center") if self.c is None else self.t("diameter" if self.diam else "radius")

    def point(self, pt):
        if self.c is None:
            self.c = pt
        else:
            r = cad.dist(self.c, pt) / (2 if self.diam else 1)
            self._make(r)

    def _make(self, r):
        if r > 1e-6:
            self.add({"t": "circle", "c": list(self.c), "r": r})
        self.ctl.finish()

    def value(self, text):
        if self.c is None:
            return False
        if text.strip().upper() in ("D", "DIAMETER"):
            self.diam = True
            return True
        v = self.ctl.number(text)
        if v is not None:
            self._make(v / (2 if self.diam else 1))
            return True
        return False

    def preview(self, cur):
        if self.c and cur:
            return [{"t": "circle", "c": list(self.c), "r": max(cad.dist(self.c, cur) / (2 if self.diam else 1), 1e-6)}]
        return []


class Arc(Command):
    def __init__(self, ctl):
        super().__init__(ctl)
        self.pts = []

    @property
    def last(self):
        return self.pts[-1] if self.pts else None

    def prompt(self):
        return self.t(("arc1", "arc2", "arc3")[len(self.pts)])

    def point(self, pt):
        self.pts.append(pt)
        if len(self.pts) == 3:
            a = _arc3(*self.pts)
            if a:
                self.add(a)
            self.ctl.finish()

    def preview(self, cur):
        if len(self.pts) == 2 and cur:
            a = _arc3(self.pts[0], self.pts[1], cur)
            return [a] if a else []
        if len(self.pts) == 1 and cur:
            return [{"t": "line", "p": [*self.pts[0], *cur]}]
        return []


class Text(Command):
    def __init__(self, ctl):
        super().__init__(ctl)
        self.pos, self.h = None, ctl.text_height
        self.step = "pos"

    def prompt(self):
        if self.step == "pos":
            return self.t("tpos")
        if self.step == "height":
            return self.t("theight", h=self.ctl.fmt(self.h))
        return self.t("tstring")

    def point(self, pt):
        if self.step == "pos":
            self.pos, self.step = pt, "height"
        elif self.step == "height":
            self.h = max(0.02, cad.dist(self.pos, pt))
            self.step = "text"

    def value(self, text):
        if self.step == "height":
            v = self.ctl.number(text)
            if v is None:
                return False
            self.h, self.step = max(0.02, v), "text"
            return True
        if self.step == "text":
            if text:
                self.ctl.text_height = self.h
                self.add({"t": "text", "p": list(self.pos), "h": self.h, "s": text, "rot": 0, "layer": "A-ANNO"})
            self.ctl.finish()
            return True
        return False

    def enter(self):
        if self.step == "height":
            self.step = "text"
        else:
            self.ctl.finish()


class Dim(Command):
    def __init__(self, ctl):
        super().__init__(ctl)
        self.pts = []

    @property
    def last(self):
        return self.pts[-1] if self.pts else None

    def prompt(self):
        return self.t(("dim1", "dim2", "dim3")[len(self.pts)])

    def point(self, pt):
        self.pts.append(pt)
        if len(self.pts) == 3:
            self.add({"t": "dim", "p1": list(self.pts[0]), "p2": list(self.pts[1]), "off": list(pt), "layer": "A-DIMS"})
            self.ctl.finish()

    def preview(self, cur):
        if len(self.pts) == 2 and cur:
            return [{"t": "dim", "p1": list(self.pts[0]), "p2": list(self.pts[1]), "off": list(cur)}]
        if len(self.pts) == 1 and cur:
            return [{"t": "line", "p": [*self.pts[0], *cur]}]
        return []


class Offset(Command):
    def __init__(self, ctl):
        super().__init__(ctl)
        self.step, self.d, self.target = "dist", ctl.offset_dist, None
        self._p1 = None

    @property
    def last(self):
        return self._p1

    def prompt(self):
        if self.step == "dist":
            return self.t("odist", d=self.ctl.fmt(self.d))
        return self.t("osel") if self.target is None else self.t("oside")

    def value(self, text):
        if self.step == "dist":
            v = self.ctl.number(text)
            if v is None or v <= 0:
                return False
            self.d, self.step = v, "pick"
            self.ctl.offset_dist = v
            return True
        return False

    def enter(self):
        if self.step == "dist":
            self.step = "pick"
        else:
            self.ctl.finish()

    def point(self, pt):
        if self.step == "dist":                # distance by two points
            if self._p1 is None:
                self._p1 = pt
            else:
                self.d = cad.dist(self._p1, pt)
                self.ctl.offset_dist = self.d
                self.step = "pick"
            return
        if self.target is None:
            self.target = self.ctl.pick_entity(pt)
            self.ctl.highlight = [self.target] if self.target is not None else []
            return
        e = self.ctl.plan.drawing[self.target]
        new = cad.offset(e, self.d, pt)
        if new:
            self.add(new)
        self.target = None
        self.ctl.highlight = []

    def preview(self, cur):
        if self.step == "pick" and self.target is not None and cur:
            e = self.ctl.plan.drawing[self.target]
            new = cad.offset(e, self.d, cur)
            return [new] if new else []
        return []


class Trim(Command):
    mode = "trim"

    def prompt(self):
        return self.t(self.mode)

    def point(self, pt):
        shift = bool(self.ctl.mods & Qt.ShiftModifier)
        mode = ("extend" if self.mode == "trim" else "trim") if shift else self.mode
        i = self.ctl.pick_entity(pt)
        if i is None:
            return
        plan = self.ctl.plan
        others = [e for j, e in enumerate(plan.drawing) if j != i] + self.ctl.refs()
        e = plan.drawing[i]
        if mode == "trim":
            out = cad.trim(e, pt, others)
            if out == [e]:
                return
            self.ctl.commit(lambda p: p.drawing.__setitem__(slice(i, i + 1), out))
        else:
            new = cad.extend(e, pt, others)
            if new is None:
                self.ctl.message(self.t("no_bound"))
                return
            self.ctl.commit(lambda p: p.drawing.__setitem__(i, new))


class Extend(Trim):
    mode = "extend"


class Selecting(Command):
    """Base for verb commands: select objects first (unless pre-selected)."""
    needs_selection = True

    def __init__(self, ctl):
        super().__init__(ctl)
        self.step = "do" if ctl.sel else "select"
        if self.step == "do":
            self.start()

    def prompt(self):
        return self.t("select") if self.step == "select" else self.do_prompt()

    def do_prompt(self):
        return ""

    def point(self, pt):
        if self.step == "select":
            i = self.ctl.pick_entity(pt)
            if i is not None:
                self.ctl.sel.symmetric_difference_update({i})
                self.ctl.changed()
            else:
                self.ctl.begin_box(pt)
            return
        self.do_point(pt)

    def enter(self):
        if self.step == "select":
            if not self.ctl.sel and self.ctl.furniture_selected() is None:
                self.ctl.message(self.t("nothing"))
                self.ctl.finish()
                return
            self.step = "do"
            self.start()
        else:
            self.ctl.finish()

    def start(self):
        pass

    def do_point(self, pt):
        pass

    def selected(self):
        return [self.ctl.plan.drawing[i] for i in sorted(self.ctl.sel)]


class Erase(Selecting):
    def start(self):
        idx = sorted(self.ctl.sel, reverse=True)
        def fn(p):
            for i in idx:
                p.drawing.pop(i)
        self.ctl.sel.clear()
        self.ctl.commit(fn)
        self.ctl.finish()


class Explode(Selecting):
    def __init__(self, ctl):
        if ctl.furniture_selected() is not None:
            ctl.sel.add(-1)          # marker so we skip the select step
        super().__init__(ctl)

    def start(self):
        self.ctl.sel.discard(-1)
        fi = self.ctl.furniture_selected()
        idx = sorted(self.ctl.sel, reverse=True)
        lib = self.ctl.editor.library

        def fn(p):
            for i in idx:
                parts = cad.explode(p.drawing[i])
                if parts:
                    p.drawing[i:i + 1] = parts
            if fi is not None:
                f = p.furniture.pop(fi)
                b = lib.get(f.block)
                if b:
                    p.drawing += cad.explode_polylines(furniture_polylines(b, f.x, f.y, f.rotation, f.scale))
        self.ctl.sel.clear()
        if fi is not None:
            self.ctl.editor.selection = None
        self.ctl.commit(fn)
        self.ctl.finish()


class Move(Selecting):
    copy_mode = False

    def start(self):
        self.base = None

    @property
    def last(self):
        return getattr(self, "base", None)

    def do_prompt(self):
        return self.t("base") if self.base is None else self.t("second")

    def _apply(self, d):
        idx = sorted(self.ctl.sel)
        copy_mode = self.copy_mode

        def fn(p):
            moved = [cad.move(p.drawing[i], *d) for i in idx]
            if copy_mode:
                p.drawing.extend(moved)
            else:
                for i, e in zip(idx, moved):
                    p.drawing[i] = e
        self.ctl.commit(fn)

    def do_point(self, pt):
        if self.base is None:
            self.base = pt
            return
        self._apply((pt[0] - self.base[0], pt[1] - self.base[1]))
        if not self.copy_mode:
            self.ctl.finish()

    def value(self, text):
        if self.step == "do" and self.base is not None:
            v = self.ctl.number(text)
            if v is not None and self.ctl.cursor:           # direct distance entry
                cx, cy = self.ctl.cursor
                L = math.hypot(cx - self.base[0], cy - self.base[1]) or 1
                self.do_point((self.base[0] + (cx - self.base[0]) / L * v, self.base[1] + (cy - self.base[1]) / L * v))
                return True
        return False

    def preview(self, cur):
        if self.step == "do" and self.base is not None and cur:
            d = (cur[0] - self.base[0], cur[1] - self.base[1])
            return [cad.move(e, *d) for e in self.selected()] + [{"t": "line", "p": [*self.base, *cur]}]
        return []


class Copy(Move):
    copy_mode = True


class Rotate(Selecting):
    def start(self):
        self.base = None

    @property
    def last(self):
        return getattr(self, "base", None)

    def do_prompt(self):
        return self.t("base") if self.base is None else self.t("angle")

    def _apply(self, deg):
        idx = sorted(self.ctl.sel)
        base = self.base
        self.ctl.commit(lambda p: [p.drawing.__setitem__(i, cad.rotate(p.drawing[i], base, deg)) for i in idx])
        self.ctl.finish()

    def do_point(self, pt):
        if self.base is None:
            self.base = pt
        else:
            self._apply(math.degrees(math.atan2(pt[1] - self.base[1], pt[0] - self.base[0])))

    def value(self, text):
        if self.step == "do" and self.base is not None:
            try:
                self._apply(float(text))
                return True
            except ValueError:
                return False
        return False

    def preview(self, cur):
        if self.step == "do" and self.base is not None and cur:
            a = math.degrees(math.atan2(cur[1] - self.base[1], cur[0] - self.base[0]))
            return [cad.rotate(e, self.base, a) for e in self.selected()]
        return []


class Scale(Rotate):
    def do_prompt(self):
        return self.t("base") if self.base is None else self.t("factor")

    def _apply(self, k):
        if k <= 0:
            return
        idx = sorted(self.ctl.sel)
        base = self.base
        self.ctl.commit(lambda p: [p.drawing.__setitem__(i, cad.scale(p.drawing[i], base, k)) for i in idx])
        self.ctl.finish()

    def do_point(self, pt):
        if self.base is None:
            self.base = pt
        else:
            self._apply(cad.dist(self.base, pt) / self.ctl.unit_k)

    def preview(self, cur):
        if self.step == "do" and self.base is not None and cur:
            k = max(cad.dist(self.base, cur) / self.ctl.unit_k, 1e-3)
            return [cad.scale(e, self.base, k) for e in self.selected()]
        return []


class Mirror(Selecting):
    def start(self):
        self.p1 = self.p2 = None

    @property
    def last(self):
        return getattr(self, "p1", None)

    def do_prompt(self):
        if self.p1 is None:
            return self.t("mir1")
        return self.t("mir2") if self.p2 is None else self.t("mirdel")

    def do_point(self, pt):
        if self.p1 is None:
            self.p1 = pt
        elif self.p2 is None:
            self.p2 = pt

    def _apply(self, erase):
        idx = sorted(self.ctl.sel)
        p1, p2 = self.p1, self.p2

        def fn(p):
            new = [cad.mirror(p.drawing[i], p1, p2) for i in idx]
            if erase:
                for i, e in zip(idx, new):
                    p.drawing[i] = e
            else:
                p.drawing.extend(new)
        self.ctl.commit(fn)
        self.ctl.finish()

    def value(self, text):
        if self.p2 is not None:
            self._apply(text.strip().upper().startswith("Y"))
            return True
        return False

    def enter(self):
        if self.step == "do" and self.p2 is not None:
            self._apply(False)
        else:
            super().enter()

    def preview(self, cur):
        if self.step == "do" and self.p1 is not None and self.p2 is None and cur:
            return [cad.mirror(e, self.p1, cur) for e in self.selected()] + [{"t": "line", "p": [*self.p1, *cur]}]
        return []


COMMANDS = {c.__name__: c for c in (Line, Pline, Rect, Circle, Arc, Text, Dim, Offset, Trim, Extend, Erase,
                                     Explode, Move, Copy, Rotate, Scale, Mirror)}


# ------------------------------------------------------------------------- controller
class Cad(QObject):
    promptChanged = Signal(str)
    log = Signal(str)

    def __init__(self, editor):
        super().__init__(editor)
        self.editor = editor
        self.cmd: Command | None = None
        self.last_alias = ""
        self.sel: set[int] = set()
        self.highlight: list[int] = []
        self.osnap, self.ortho, self.grid = True, False, False
        self.grid_step = 0.05
        self.layer = "A-DRAW"
        self.text_height = 0.25
        self.offset_dist = 0.15
        self.cursor = None
        self.snap = None            # (kind, point)
        self.box = None             # (start, current)
        self.grip = None            # (entity index, key, base dict)
        self.mods = Qt.NoModifier
        self._tol = 0.1
        self._refs = None
        editor.changed.connect(self._invalidate)

    # -- helpers --
    @property
    def plan(self):
        return self.editor.plan

    @property
    def lang(self):
        return getattr(self.editor, "lang", "ar")

    @property
    def unit_k(self) -> float:
        from .editor import UNITS
        return 1.0 / UNITS[self.editor.unit][0]

    def fmt(self, v_m: float) -> str:
        from .editor import fmt_len
        return fmt_len(v_m, self.editor.unit)

    def number(self, text):
        try:
            return float(text.strip()) * self.unit_k
        except ValueError:
            return None

    def message(self, text):
        self.log.emit(text)

    def _invalidate(self):
        self._refs = None

    def refs(self):
        if self._refs is None:
            self._refs = plan_refs(self.plan, self.editor.library)
        return self._refs

    def snap_entities(self):
        return list(self.plan.drawing) + self.refs() if self.plan else []

    def commit(self, fn):
        self.editor.apply(lambda p: (fn(p), None)[1])

    def changed(self):
        self.editor.changed.emit()

    def furniture_selected(self):
        s = self.editor.selection
        return s[1] if s and s[0] == "furniture" else None

    def pick_entity(self, pt, tol=None):
        tol = tol or self._tol
        best = None
        for i, e in enumerate(self.plan.drawing):
            d = cad.distance_to(e, pt)
            if d <= tol and (best is None or d < best[0]):
                best = (d, i)
        return best[1] if best else None

    # -- command flow --
    def prompt_text(self) -> str:
        if self.cmd is None:
            ar, en = P["cmd"]
            return ar if self.lang == "ar" else en
        return f"{type(self.cmd).__name__.upper()}: {self.cmd.prompt()}"

    def _prompt(self):
        self.promptChanged.emit(self.prompt_text())
        self.editor.overlayChanged.emit()

    def start(self, name: str):
        if self.plan is None:
            return
        self.cancel(quiet=True)
        self.box = None
        self.last_alias = name
        self.editor.tool = "cad"
        self._done = False
        cmd = COMMANDS[name](self)          # may finish right away (pre-selected objects)
        if not self._done:
            self.cmd = cmd
            self._prompt()

    def finish(self):
        self._done = True
        self.cmd = None
        self.highlight = []
        self.editor.tool = "select"
        self._prompt()
        self.changed()

    def cancel(self, quiet=False):
        had = self.cmd is not None or self.sel or self.box
        self.cmd, self.box, self.grip = None, None, None
        self.highlight = []
        if not quiet:
            self.sel.clear()
            if self.editor.tool == "cad":
                self.editor.tool = "select"
            self._prompt()
            self.changed()
        return bool(had)

    def submit(self, text: str):
        """Command line Enter."""
        text = text.strip()
        if self.cmd is None:
            if not text:
                if self.last_alias:
                    self.start(self.last_alias)
                return
            name = ALIASES.get(text.upper())
            if name is None:
                self.message(f"{text}: " + (P["unknown"][0] if self.lang == "ar" else P["unknown"][1]))
                return
            self.log.emit(f"> {text.upper()}")
            self.start(name)
            return
        self.log.emit(f"  {text}" if text else "  ↵")
        cmd = self.cmd
        if not text:
            cmd.enter()
        elif not cmd.value(text):
            pt = cad.parse_point(text, cmd.last, self.unit_k)
            if pt is None and cmd.last is not None and self.cursor is not None:
                v = self.number(text)               # direct distance entry along the cursor direction
                if v is not None:
                    lx, ly = cmd.last
                    cx, cy = self.cursor
                    L = math.hypot(cx - lx, cy - ly)
                    if L > 1e-9:
                        pt = (lx + (cx - lx) / L * v, ly + (cy - ly) / L * v)
            if pt is not None:
                cmd.point(pt)
            else:
                self.message("?")
        if self.cmd is cmd:
            self._prompt()

    # -- point input --
    def resolve(self, x, y, tol, mods):
        """Apply object snap, ortho and grid to a cursor position."""
        self._tol = tol
        self.mods = mods
        base = self.cmd.last if self.cmd else (self.grip[3] if self.grip else None)
        snap = None
        if self.osnap and self.plan is not None:
            snap = cad.find_snap(self.snap_entities(), (x, y), tol * 1.4, base=base)
        if snap:
            self.snap = snap
            return snap[1]
        self.snap = None
        if self.ortho and base is not None:
            bx, by = base
            x, y = (x, by) if abs(x - bx) >= abs(y - by) else (bx, y)
        if self.grid:
            g = self.grid_step
            x, y = round(x / g) * g, round(y / g) * g
            self.snap = ("grid", (x, y))
        return (x, y)

    def grips(self):
        out = []
        for i in sorted(self.sel):
            if 0 <= i < len(self.plan.drawing):
                out += [(i, k, p) for k, p in self._grip_points(self.plan.drawing[i])]
        return out

    @staticmethod
    def _grip_points(e):
        t = e["t"]
        if t == "line":
            return [("p0", tuple(e["p"][:2])), ("p1", tuple(e["p"][2:]))]
        if t == "pline":
            return [(f"v{j}", tuple(p)) for j, p in enumerate(e["pts"])]
        if t in ("circle", "arc"):
            c = tuple(e["c"])
            return [("c", c), ("r", (c[0] + e["r"], c[1]))] if t == "circle" else [("c", c)]
        if t == "text":
            return [("p", tuple(e["p"]))]
        if t == "dim":
            return [("p1", tuple(e["p1"])), ("p2", tuple(e["p2"])), ("off", tuple(e["off"]))]
        return []

    @staticmethod
    def _apply_grip(e, key, pt):
        import copy
        e = copy.deepcopy(e)
        t = e["t"]
        if t == "line":
            if key == "p0":
                e["p"][:2] = list(pt)
            else:
                e["p"][2:] = list(pt)
        elif t == "pline":
            e["pts"][int(key[1:])] = list(pt)
        elif t in ("circle", "arc"):
            if key == "c":
                e["c"] = list(pt)
            else:
                e["r"] = max(1e-3, cad.dist(e["c"], pt))
        elif t == "text":
            e["p"] = list(pt)
        elif t == "dim":
            e[key] = list(pt)
        return e

    def press(self, x, y, mods, tol) -> bool:
        if self.plan is None:
            return False
        pt = self.resolve(x, y, tol, mods)
        if self.cmd is not None:
            self.cmd.point(pt)
            if self.cmd is not None:
                self._prompt()
            return True
        if self.grip:                                   # second click drops a grip
            i, key, base, _ = self.grip
            self.grip = None
            self.commit(lambda p: p.drawing.__setitem__(i, self._apply_grip(p.drawing[i], key, pt)))
            return True
        for i, key, gp in self.grips():
            if cad.dist(gp, (x, y)) <= tol:
                self.grip = (i, key, self.plan.drawing[i], gp)
                self._prompt()
                return True
        i = self.pick_entity((x, y), tol)
        if i is not None:
            if mods & Qt.ShiftModifier:
                self.sel.discard(i)
            else:
                self.sel.add(i)
            self.editor.selection = None
            self.editor.selectionChanged.emit()
            self.changed()
            return True
        return False

    def begin_box(self, pt):
        self.box = (pt, pt)
        self.editor.overlayChanged.emit()

    def move(self, x, y, mods, tol) -> bool:
        self._tol = tol
        if self.box is not None:
            self.box = (self.box[0], (x, y))
            self.editor.overlayChanged.emit()
            return True
        if self.cmd is not None or self.grip:
            self.cursor = self.resolve(x, y, tol, mods)
            self.editor.overlayChanged.emit()
            return True
        self.cursor = (x, y)
        return False

    def release(self, x, y) -> bool:
        if self.box is None:
            return False
        (x0, y0), (x1, y1) = self.box
        self.box = None
        if abs(x1 - x0) < 1e-6 and abs(y1 - y0) < 1e-6:
            self.editor.overlayChanged.emit()
            return True
        crossing = x1 < x0                              # right-to-left = crossing (AutoCAD)
        lo_x, hi_x, lo_y, hi_y = min(x0, x1), max(x0, x1), min(y0, y1), max(y0, y1)
        for i, e in enumerate(self.plan.drawing):
            if cad.in_window(e, lo_x, lo_y, hi_x, hi_y, crossing):
                self.sel.add(i)
        self.editor.selectionChanged.emit()
        self.changed()
        return True

    # -- drawing data for the scene --
    def overlay(self):
        shapes = []
        if self.cmd is not None:
            prev = self.cmd.preview(self.cursor)
            if prev:
                shapes.append(dict(ents=prev))
        if self.grip and self.cursor:
            i, key, base, _ = self.grip
            shapes.append(dict(ents=[self._apply_grip(base, key, self.cursor)]))
        if self.box:
            (x0, y0), (x1, y1) = self.box
            shapes.append(dict(box=(x0, y0, x1, y1), crossing=x1 < x0))
        if self.snap and (self.cmd is not None or self.grip):
            kind, p = self.snap
            ar, en = SNAP_NAMES.get(kind, (kind, kind))
            shapes.append(dict(marker=kind, at=p, label=ar if self.lang == "ar" else en))
        if self.sel:
            shapes.append(dict(grips=[gp for _, _, gp in self.grips()]))
        return shapes

import json
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QtWidgets = pytest.importorskip("PySide6.QtWidgets")
from PySide6.QtCore import Qt  # noqa: E402

from floorplan import design  # noqa: E402
from floorplan.blocks import BlockLibrary  # noqa: E402
from floorplan.gui.editor import Editor  # noqa: E402

EX = os.path.join(os.path.dirname(__file__), "..", "examples")
T = 0.05


@pytest.fixture(scope="module")
def app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


@pytest.fixture
def ed(app):
    e = Editor(BlockLibrary(None))
    plan = design(json.load(open(os.path.join(EX, "family.json"), encoding="utf-8")), seed=4, candidates=60)
    e.set_plan(plan)
    e.enabled = True
    e.cad.osnap = False          # exact typed input in tests
    return e


def run(ed, *inputs):
    for x in inputs:
        if isinstance(x, tuple):
            ed.press(x[0], x[1], Qt.ShiftModifier if len(x) > 2 else Qt.NoModifier, T)
        else:
            ed.cad.submit(x)


def ents(ed):
    return ed.plan.drawing


def test_line_with_typed_coordinates_and_close(ed):
    run(ed, "L", "20,0", "@4,0", "@0,3", "c")
    assert len(ents(ed)) == 3
    assert ents(ed)[2]["p"] == pytest.approx([24, 3, 20, 0])
    assert ed.cad.cmd is None
    ed.undo()
    assert len(ents(ed)) == 2


def test_direct_distance_entry(ed):
    run(ed, "L", "20,0")
    ed.move(25, 0, Qt.NoModifier, T, False)          # cursor gives the direction
    run(ed, "2.5", "")
    assert ents(ed)[0]["p"] == pytest.approx([20, 0, 22.5, 0])


def test_rect_offset_trim_extend_explode(ed):
    run(ed, "REC", "30,0", "@4,2")
    assert ents(ed)[0]["closed"]
    run(ed, "O", "0.5", (30, 1), (40, 40), "")       # offset outside
    xs = [p[0] for p in ents(ed)[1]["pts"]]
    assert min(xs) == pytest.approx(29.5) and max(xs) == pytest.approx(34.5)
    run(ed, "X")                                     # nothing pre-selected -> select step
    run(ed, (30, 1), "")                              # pick inner rect, Enter
    assert sum(e["t"] == "line" for e in ents(ed)) == 4
    run(ed, "L", "32,-1", "@0,4", "")                # cutter through the rectangle
    n = len(ents(ed))
    bottom = next(i for i, e in enumerate(ents(ed)) if e["t"] == "line" and e["p"][1] == pytest.approx(0) and e["p"][3] == pytest.approx(0))
    run(ed, "TR", (33, 0), "")                       # trim right half of bottom edge
    assert len(ents(ed)) == n
    seg = [e for e in ents(ed) if e["t"] == "line" and e["p"][1] == pytest.approx(0) and e["p"][3] == pytest.approx(0)]
    assert any(max(e["p"][0], e["p"][2]) == pytest.approx(32) for e in seg)
    run(ed, "L", "36,1", "@1,0", "")                 # short line right of the shape
    run(ed, "EX", (36.05, 1), "")                    # extend its left end to the offset rectangle edge
    assert ents(ed)[-1]["p"][0] == pytest.approx(34.5)


def test_move_copy_rotate_mirror_erase(ed):
    run(ed, "L", "40,0", "@2,0", "")
    ed.cad.sel = {0}
    run(ed, "M", "40,0", "@0,1")
    assert ents(ed)[0]["p"] == pytest.approx([40, 1, 42, 1])
    ed.cad.sel = {0}
    run(ed, "CO", "40,1", "@0,1", "@0,2", "")
    assert len(ents(ed)) == 3
    ed.cad.sel = {0}
    run(ed, "RO", "40,1", "90")
    assert ents(ed)[0]["p"] == pytest.approx([40, 1, 40, 3])
    ed.cad.sel = {1}
    run(ed, "MI", "45,0", "@0,1", "N")
    assert len(ents(ed)) == 4
    ed.cad.sel = {0, 1, 2, 3}
    run(ed, "E")
    assert ents(ed) == []


def test_window_vs_crossing_and_snap(ed):
    run(ed, "L", "50,0", "@2,0", "")
    run(ed, "L", "51,-1", "@0,2", "")
    ed.cad.sel.clear()
    ed.cad.begin_box((49, -0.5))
    ed.cad.move(52.5, 0.5, Qt.NoModifier, T)
    ed.cad.release(52.5, 0.5)                        # left->right window: only the horizontal line
    assert ed.cad.sel == {0}
    ed.cad.sel.clear()
    ed.cad.begin_box((52.5, 0.5))
    ed.cad.move(50.8, -0.5, Qt.NoModifier, T)
    ed.cad.release(50.8, -0.5)                       # right->left crossing: both
    assert ed.cad.sel == {0, 1}
    ed.cad.osnap = True
    ed.cad.start("Line")
    pt = ed.cad.resolve(51.02, 0.03, T, Qt.NoModifier)
    assert ed.cad.snap[0] == "int" and pt == pytest.approx((51, 0))


def test_explode_furniture_and_grips(ed):
    from floorplan.models import Furniture
    ed.plan.furniture.append(Furniture("std/bed_single", 60, 0))
    ed.selection = ("furniture", len(ed.plan.furniture) - 1)
    n = len(ed.plan.furniture)
    run(ed, "X")
    assert len(ed.plan.furniture) == n - 1 and len(ents(ed)) > 4
    ed.plan.drawing = [{"t": "line", "p": [0, 0, 1, 0]}]
    ed.cad.sel = {0}
    ed.cad.press(1, 0, Qt.NoModifier, T)             # grab end grip
    ed.cad.press(1, 1, Qt.NoModifier, T)             # drop it
    assert ents(ed)[0]["p"] == pytest.approx([0, 0, 1, 1])

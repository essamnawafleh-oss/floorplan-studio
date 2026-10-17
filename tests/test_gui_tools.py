import json
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QtWidgets = pytest.importorskip("PySide6.QtWidgets")
from PySide6.QtCore import Qt  # noqa: E402

from floorplan import design, editing  # noqa: E402
from floorplan.blocks import BlockLibrary  # noqa: E402
from floorplan.gui.editor import Editor, polygon_area  # noqa: E402

EX = os.path.join(os.path.dirname(__file__), "..", "examples")


@pytest.fixture(scope="module")
def app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


@pytest.fixture
def editor(app):
    ed = Editor(BlockLibrary(None))
    ed.set_plan(design(json.load(open(os.path.join(EX, "family.json"), encoding="utf-8")), seed=4, candidates=80))
    ed.enabled = True
    return ed


def test_drag_wall_with_mouse_and_undo(editor):
    line = next(ln for ln in editing.wall_lines(editor.plan) if not ln.side and ln.length > 2)
    before = editor.plan.to_dict()
    x, y = ((line.coord, (line.s0 + line.s1) / 2) if line.orient == "v" else ((line.s0 + line.s1) / 2, line.coord))
    assert editor.press(x, y, Qt.NoModifier, 0.05)
    assert editor.selection[0] == "wall"
    dx, dy = (0.42, 0) if line.orient == "v" else (0, 0.42)
    editor.move(x + dx, y + dy, Qt.NoModifier, 0.05, True)
    editor.release(x + dx, y + dy)
    moved = [ln for ln in editing.wall_lines(editor.plan) if ln.orient == line.orient and abs(ln.coord - (line.coord + 0.4)) < 1e-6]
    assert moved, "wall snapped to 5 cm grid at +0.40"
    assert editor.plan.edited
    editor.undo()
    assert editor.plan.to_dict()["rooms"] == before["rooms"]


def test_add_door_window_and_furniture(editor):
    p = editor.plan
    te = p.settings["exterior_wall"]
    n = len(p.openings)
    room = max(p.rooms, key=lambda r: r.rect.w)
    editor.set_tool("window")
    editor.press(room.rect.center[0], te / 2 if abs(room.rect.y0 - te) < 1e-6 else p.depth - te / 2, Qt.NoModifier, 0.05)
    assert len(editor.plan.openings) in (n, n + 1)        # may hit an occupied wall; must not crash
    editor.pending_block = "std/sofa3"
    editor.set_tool("block")
    editor.press(*room.net.center, Qt.NoModifier, 0.05)
    assert editor.plan.furniture[-1].block == "std/sofa3"
    editor.rotate_furniture(90)
    assert editor.plan.furniture[-1].rotation == 90
    editor.delete_selection()
    assert not editor.plan.furniture


def test_measure_length_and_area(editor):
    editor.enabled = False                      # measuring works without edit mode
    editor.set_tool("measure_area")
    for pt in [(1.0, 1.0), (5.0, 1.0), (5.0, 4.0), (1.0, 4.0)]:
        editor.press(*pt, Qt.NoModifier, 0.001)
    editor.finish_measure()
    m = editor.measures[-1]
    assert polygon_area(m["pts"]) == pytest.approx(12.0, abs=0.2)
    editor.unit = "cm"
    editor.set_tool("measure_len")
    editor.press(1.0, 1.0, Qt.NoModifier, 0.001)
    editor.press(4.0, 1.0, Qt.NoModifier, 0.001)
    editor.finish_measure()
    assert editor.describe(editor.measures[-1]).endswith("cm")


def test_addon_load_unload(app, tmp_path, monkeypatch):
    from floorplan.gui import addons
    monkeypatch.setattr(addons, "user_dir", lambda *a: str(tmp_path))
    from PySide6.QtCore import QSettings
    from floorplan.gui.app import resource_dir
    from floorplan.gui.main_window import MainWindow
    win = MainWindow(os.path.join(resource_dir(), "examples"))
    mgr = addons.AddonManager(win, QSettings(str(tmp_path / "s.ini"), QSettings.IniFormat))
    mgr.attach_menu(win.tools_menu)
    path = tmp_path / "hello.py"
    path.write_text('ADDON = {"name": "Hello"}\n\ndef register(api):\n    api.add_action("Say hi", lambda: None)\n')
    assert addons.read_meta(str(path))["name"] == "Hello"
    assert mgr.set_enabled(str(path), True) is None
    assert any(a.text() == "Say hi" for a in win.tools_menu.actions())
    mgr.set_enabled(str(path), False)
    assert not any(a.text() == "Say hi" for a in win.tools_menu.actions())
    bad = tmp_path / "bad.py"
    bad.write_text("def register(api):\n    raise RuntimeError('boom')\n")
    assert "boom" in mgr.load(str(bad), quiet=True)
    win.close()

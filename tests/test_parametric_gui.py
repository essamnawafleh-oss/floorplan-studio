import json
import os
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QtWidgets = pytest.importorskip("PySide6.QtWidgets")


@pytest.fixture(scope="module")
def app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def wait_for(app, cond, timeout=60):
    t = time.time()
    while not cond() and time.time() - t < timeout:
        app.processEvents()
        time.sleep(0.02)
    return cond()


@pytest.fixture
def win(app):
    from floorplan.gui.app import resource_dir
    from floorplan.gui.main_window import MainWindow
    w = MainWindow(os.path.join(resource_dir(), "examples"))
    assert wait_for(app, lambda: w.plan is not None)
    yield w
    w.close()


def small_search(panel):
    panel.n_seeds.setValue(2)
    panel.cands.setValue(40)
    panel.keep.setValue(2)
    panel.passes.setValue(1)


def run_and_wait(app, win):
    p = win.param_panel
    small_search(p)
    p.run()
    assert wait_for(app, lambda: p.run_btn.isEnabled() and p.candidates)
    return p


def test_parametric_does_not_touch_project_until_apply(app, win):
    from floorplan.editing import refresh
    win.set_edit_mode(True)
    win.editor.apply(lambda p: p.drawing.append({"t": "line", "p": [0, -2, 3, -2]}))   # a manual edit
    before, undo_len, edited = win.plan.to_dict(), len(win.editor.undo_stack), win.plan.edited
    win.enter_parametric()
    assert win.workspace == "parametric" and not win.editor.enabled
    p = win.param_panel
    living = next(r for r in range(p.rooms_table.rowCount()) if "living" in p.rooms_table.item(r, 0).data(0x0100))
    p.rooms_table.cellWidget(living, 2).setValue(p.rooms_table.cellWidget(living, 2).value() + 10)
    run_and_wait(app, win)
    win.panel.sons.setValue(win.panel.sons.value() + 1)     # input change must not regenerate the project
    win.regenerate()
    app.processEvents()
    win.leave_parametric()
    assert win.plan.to_dict() == before
    assert win.plan.edited == edited and len(win.editor.undo_stack) == undo_len
    assert win.study.room_overrides                          # the study kept the parameter change


def test_apply_is_one_undoable_step(app, win):
    before = win.plan.to_dict()
    win.enter_parametric()
    p = run_and_wait(app, win)
    p.select(len(p.candidates) - 1)
    chosen = p.selected
    p._apply()
    assert win.workspace == "design" and win.editor.enabled
    assert [r.rect for r in win.plan.rooms] == [r.rect for r in chosen.plan.rooms]
    assert win.plan is not chosen.plan                       # a copy, the candidate list stays intact
    assert win.plan.edited
    win.editor.undo()
    assert win.plan.to_dict()["rooms"] == before["rooms"]


def test_study_saved_with_project_and_old_projects_still_load(app, win, tmp_path):
    win.enter_parametric()
    p = win.param_panel
    p.rooms_table.cellWidget(0, 2).setValue(p.rooms_table.cellWidget(0, 2).value() + 2)
    win.leave_parametric()
    proj = win.project_dict()
    assert "parametric" in proj and "base_config" not in proj["parametric"]
    assert proj["parametric"]["room_overrides"]
    json.dumps(proj)                                         # serialisable
    win.open_config(json.loads(json.dumps(proj)))
    assert win.study is not None and win.study.room_overrides == proj["parametric"]["room_overrides"]
    old = {k: v for k, v in proj.items() if k != "parametric"}
    req = win.req
    win.open_config(old)
    assert win.study is None and win.req == req + 1          # old file: regenerates as before


def test_language_switch_keeps_parametric_workspace(app, win):
    win.enter_parametric()
    run_and_wait(app, win)
    n = len(win.param_candidates)
    win.toggle_language()
    assert win.workspace == "parametric" and win.param_panel.grid.count() == n
    win.toggle_language()

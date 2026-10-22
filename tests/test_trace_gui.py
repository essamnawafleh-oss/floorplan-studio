import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QtWidgets = pytest.importorskip("PySide6.QtWidgets")
cv2 = pytest.importorskip("cv2")

from tests.test_parametric_gui import app, wait_for, win  # noqa: F401,E402


def test_trace_workspace_creates_plan(win, app, tmp_path):
    from floorplan.trace import synth
    img = synth.render(win.plan, 60, labels=False, dims=False)
    path = str(tmp_path / "shot.png")
    cv2.imwrite(path, img)
    before = win.plan.to_dict()
    win.enter_trace()
    assert win.workspace == "trace" and win.trace_action.isChecked()
    panel = win.trace_panel
    panel.ocr.setCurrentIndex(panel.ocr.findData("off"))
    panel.load_path(path)
    assert wait_for(app, lambda: panel.state.get("analysis") is not None)
    assert abs(panel.table.rowCount() - len(win.plan.rooms)) <= 1
    assert win.plan.to_dict() == before                    # nothing applied yet
    panel.r_line.setChecked(True)
    panel._line_drawn(__import__("PySide6.QtCore", fromlist=["QPointF"]).QPointF(0, 0),
                      __import__("PySide6.QtCore", fromlist=["QPointF"]).QPointF(120, 0))
    panel.line_m.setValue(2.0)
    assert panel.preview_plan is not None
    combo = panel.table.cellWidget(0, 1)
    combo.setCurrentIndex(combo.findData("office"))
    assert any(r.spec.type == "office" for r in panel.preview_plan.rooms)
    win.toggle_language()                                  # rebuilds the page from the kept state
    assert win.workspace == "trace" and win.trace_panel.state.get("analysis") is not None
    win.trace_panel._apply()
    assert win.workspace == "design" and win.editor.enabled
    assert win.plan.edited and any(r.spec.type == "office" for r in win.plan.rooms)
    win.editor.undo()
    assert win.plan.to_dict()["rooms"] == before["rooms"]

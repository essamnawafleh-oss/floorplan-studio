import os
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QtWidgets = pytest.importorskip("PySide6.QtWidgets")


@pytest.fixture(scope="module")
def app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def wait_for(app, cond, timeout=30):
    t = time.time()
    while not cond() and time.time() - t < timeout:
        app.processEvents()
        time.sleep(0.02)
    return cond()


def test_window_generates_plan_and_switches_language(app, tmp_path):
    from floorplan.gui.app import resource_dir
    from floorplan.gui.main_window import MainWindow
    win = MainWindow(os.path.join(resource_dir(), "examples"))
    assert wait_for(app, lambda: win.plan is not None)
    assert win.rooms_table.rowCount() == len(win.plan.rooms)
    first = win.plan
    win.panel.seed.setValue(win.panel.seed.value() + 1)
    win.regenerate()
    assert wait_for(app, lambda: win.plan is not first)
    for ext in ("svg", "png", "pdf", "dxf", "glb", "obj", "json"):
        win._write(ext, str(tmp_path / f"p.{ext}"))
        assert (tmp_path / f"p.{ext}").stat().st_size > 100, ext
    win.toggle_language()
    win.toggle_language()
    win.close()


def test_custom_rooms_round_trip(app):
    from floorplan.gui.panels import InputPanel
    p = InputPanel("en")
    cfg = {"footprint": {"width": 14}, "rooms": [{"type": "salon", "area": 22, "fixed": True},
                                                 {"type": "bedroom", "occupants": 2}]}
    p.set_config(cfg)
    out = p.get_config()
    assert out["footprint"] == {"width": 14.0}
    assert out["rooms"] == [{"type": "salon", "area": 22.0, "fixed": True},
                            {"type": "bedroom", "occupants": 2}]

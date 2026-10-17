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
        win.write_file(ext, str(tmp_path / f"p.{ext}"))
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


def test_themes_apply_and_custom_file(app, tmp_path):
    from floorplan.gui import theme
    for name in ["system", *theme.BUILTIN]:
        t = theme.apply(app, {"theme": name, "font_family": "DejaVu Sans", "font_size": 11})
        assert app.palette().color(app.palette().ColorRole.Window).name() == t["window"]
    assert app.font().pointSize() == 11
    custom = theme.load_theme_file(os.path.join(os.path.dirname(__file__), "..", "docs", "theme_example.json"))
    t = theme.apply(app, {"theme": "custom", "custom_theme": custom, "accent": "#ff0000"})
    assert t["window"] == "#101418" and t["accent"] == "#ff0000"
    assert theme.plan_colors(t, "match")["paper"] == theme.PLAN["dark"]["paper"]
    assert theme.plan_colors(t, "light")["paper"] == "#ffffff"


def test_prefs_round_trip(app, tmp_path):
    from PySide6.QtCore import QSettings
    from floorplan.gui.settings_dialog import load_prefs, save_prefs
    st = QSettings(str(tmp_path / "s.ini"), QSettings.IniFormat)
    save_prefs(st, {"theme": "custom", "accent": "#123456", "font_family": "X", "font_size": 12,
                    "plan_theme": "dark", "custom_theme": {"window": "#000000"}})
    p = load_prefs(st)
    assert p["theme"] == "custom" and p["font_size"] == 12 and p["custom_theme"] == {"window": "#000000"}

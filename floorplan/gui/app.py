"""Entry point for the desktop app (also used by the Windows .exe)."""

from __future__ import annotations

import os
import sys

STYLE = """
QWidget { font-size: 13px; }
QMainWindow, QScrollArea, QScrollArea > QWidget > QWidget { background: #f6f7f9; }
QGroupBox { background: #ffffff; border: 1px solid #e1e4e8; border-radius: 8px; margin-top: 14px;
            padding: 12px 8px 8px 8px; font-weight: 600; }
QGroupBox::title { subcontrol-origin: margin; subcontrol-position: top left; left: 10px; right: 10px;
                   padding: 0 4px; color: #2b3440; }
QPushButton { background: #ffffff; border: 1px solid #cfd5dc; border-radius: 6px; padding: 5px 10px; }
QPushButton:hover { background: #f0f3f7; }
QPushButton#primary { background: #2f6fd6; color: white; border: none; font-weight: 600; padding: 9px; }
QPushButton#primary:hover { background: #2a62bf; }
QPushButton#primary:disabled { background: #9db8e6; }
QToolButton#variant { background: #ffffff; border: 1px solid #e1e4e8; border-radius: 8px; padding: 4px; }
QToolButton#variant:hover { border-color: #2f6fd6; }
QToolBar { background: #ffffff; border-bottom: 1px solid #e1e4e8; spacing: 6px; padding: 4px; }
QToolButton { padding: 5px 10px; border-radius: 6px; }
QToolButton:hover { background: #eef2f7; }
QLabel#summary { color: #2b3440; }
QLabel#status { color: #666b73; padding: 4px 10px; background: #ffffff; border-top: 1px solid #e1e4e8; }
QTabWidget::pane { border: 1px solid #e1e4e8; background: #ffffff; }
QTableWidget { background: #ffffff; gridline-color: #eceef1; }
QLineEdit { padding: 3px 6px; border: 1px solid #cfd5dc; border-radius: 5px; background: #ffffff; min-height: 22px; }
QSpinBox, QDoubleSpinBox, QComboBox { min-height: 24px; }
"""


def resource_dir() -> str:
    """Folder with bundled data (examples) - works from source and from the .exe."""
    if getattr(sys, "frozen", False):
        return getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def selftest(out_dir: str) -> int:
    """Headless check used by the build: engine + exports + window creation."""
    import json
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from floorplan import design
    from floorplan.export import to_dxf, to_glb, to_obj, to_svg
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(resource_dir(), "examples", "family.json"), encoding="utf-8") as f:
        cfg = json.load(f)
    plan = design(cfg, seed=1, candidates=80)
    with open(os.path.join(out_dir, "test.svg"), "w", encoding="utf-8") as f:
        f.write(to_svg(plan))
    to_dxf(plan, os.path.join(out_dir, "test.dxf"))
    to_glb(plan, os.path.join(out_dir, "test.glb"))
    to_obj(plan, os.path.join(out_dir, "test.obj"))
    from PySide6.QtWidgets import QApplication
    from floorplan.gui.main_window import MainWindow
    from floorplan.gui.plan_view import render_pixmap
    app = QApplication.instance() or QApplication(sys.argv[:1])
    win = MainWindow(os.path.join(resource_dir(), "examples"))
    render_pixmap(plan, 800, 600).save(os.path.join(out_dir, "test.png"))
    win.close()
    with open(os.path.join(out_dir, "selftest_ok.txt"), "w") as f:
        f.write("ok\n")
    return 0


def main() -> int:
    if len(sys.argv) >= 2 and sys.argv[1] == "--selftest":
        return selftest(sys.argv[2] if len(sys.argv) > 2 else "selftest_out")
    from PySide6.QtGui import QFont, QIcon
    from PySide6.QtWidgets import QApplication
    from floorplan.gui.main_window import MainWindow
    app = QApplication(sys.argv)
    app.setApplicationName("Floor Plan Studio")
    app.setStyle("Fusion")
    app.setStyleSheet(STYLE)
    font = QFont("Segoe UI", 10)
    app.setFont(font)
    icon = os.path.join(resource_dir(), "assets", "icon.ico")
    if os.path.exists(icon):
        app.setWindowIcon(QIcon(icon))
    win = MainWindow(os.path.join(resource_dir(), "examples"))
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())

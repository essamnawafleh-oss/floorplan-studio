"""Entry point for the desktop app (also used by the Windows .exe)."""

from __future__ import annotations

import os
import sys

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
    from floorplan.gui.quantities_dialog import QuantitiesDialog
    from floorplan.gui.viewer3d import Viewer3D
    v = Viewer3D(plan, win.library)
    v.resize(400, 300)
    v.grab().save(os.path.join(out_dir, "test3d.png"))
    QuantitiesDialog(plan, "en", win.settings).recalc()
    win.close()
    with open(os.path.join(out_dir, "selftest_ok.txt"), "w") as f:
        f.write("ok\n")
    return 0


def main() -> int:
    if len(sys.argv) >= 2 and sys.argv[1] == "--selftest":
        return selftest(sys.argv[2] if len(sys.argv) > 2 else "selftest_out")
    from PySide6.QtGui import QIcon
    from PySide6.QtWidgets import QApplication
    from floorplan.gui.main_window import MainWindow
    app = QApplication(sys.argv)
    app.setApplicationName("Floor Plan Studio")
    app.setStyle("Fusion")       # theme colours are applied by MainWindow
    icon = os.path.join(resource_dir(), "assets", "icon.ico")
    if os.path.exists(icon):
        app.setWindowIcon(QIcon(icon))
    win = MainWindow(os.path.join(resource_dir(), "examples"))
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())

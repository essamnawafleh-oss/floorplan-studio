"""Entry point for the desktop app (also used by the Windows .exe)."""

from __future__ import annotations

import os
import sys

def resource_dir() -> str:
    """Folder with bundled data (examples) - works from source and from the .exe."""
    if getattr(sys, "frozen", False):
        return getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def isolate_qt() -> None:
    """Make the frozen .exe use only its bundled Qt.

    Other software (QGIS, Anaconda, some CAD tools) sets global Qt variables or
    puts its own Qt DLLs on PATH; Qt then loads the wrong platform plugin and
    fails with "no Qt platform plugin could be initialized".
    """
    if not getattr(sys, "frozen", False):
        return
    for var in ("QT_PLUGIN_PATH", "QT_QPA_PLATFORM_PLUGIN_PATH", "QT_QPA_PLATFORM",
                "QML2_IMPORT_PATH", "QT_QPA_FONTDIR", "QT_DEBUG_PLUGINS"):
        if var == "QT_QPA_PLATFORM" and "--selftest" in sys.argv:
            continue
        os.environ.pop(var, None)
    base = os.path.join(resource_dir(), "PySide6")
    for plugins in (os.path.join(base, "plugins"), os.path.join(base, "Qt", "plugins")):
        if os.path.isdir(os.path.join(plugins, "platforms")):
            os.environ["QT_PLUGIN_PATH"] = plugins
            os.environ["QT_QPA_PLATFORM_PLUGIN_PATH"] = os.path.join(plugins, "platforms")
            break
    if os.name == "nt":
        # bundled DLLs first, and drop foreign Qt folders from PATH
        os.environ["PATH"] = os.pathsep.join(
            [base, resource_dir()] + [p for p in os.environ.get("PATH", "").split(os.pathsep)
                                      if p and not os.path.exists(os.path.join(p, "Qt6Core.dll"))])
        for d in (base, resource_dir()):
            if os.path.isdir(d):
                try:
                    os.add_dll_directory(d)
                except OSError:
                    pass


def log_startup_error() -> str:
    """Write the traceback to %APPDATA%/FloorPlanStudio/startup_error.log."""
    import traceback
    folder = os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"), "FloorPlanStudio")
    path = os.path.join(folder, "startup_error.log")
    try:
        os.makedirs(folder, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(traceback.format_exc())
            f.write("\npython %s  frozen=%s\n" % (sys.version, getattr(sys, "frozen", False)))
    except OSError:
        pass
    return path


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
    from floorplan.parametric import ParametricStudy, run_study
    cands = run_study(ParametricStudy(base_config=cfg, seeds=[1], candidates=30, keep=2, refine_passes=1))
    win.enter_parametric()
    win.param_candidates[:] = cands
    win.param_panel._show_candidates()
    win.leave_parametric()
    # image -> plan: trace a drawing of the plan back, OCR on its labels (bundled models)
    from floorplan.trace import analyse, from_array, ocr, synth, to_plan
    img = synth.render(plan, 50, labels=True, dims=True)
    traced = to_plan(analyse(from_array(img)), 1 / 50)
    if abs(len(traced.rooms) - len(plan.rooms)) > 1:
        raise RuntimeError(f"trace: {len(traced.rooms)} rooms, expected {len(plan.rooms)}")
    words = ocr.run(img[: img.shape[0] // 2, : img.shape[1] // 2])
    with open(os.path.join(out_dir, "trace.txt"), "w", encoding="utf-8") as f:
        f.write(f"rooms {len(traced.rooms)} / {len(plan.rooms)}\nocr {ocr.engines()} {[t.text for t in words]}\n")
    if not words:
        raise RuntimeError("OCR read nothing")
    win.enter_trace()
    win.leave_trace()
    win.close()
    with open(os.path.join(out_dir, "selftest_ok.txt"), "w") as f:
        f.write("ok\n")
    return 0


def main() -> int:
    isolate_qt()
    try:
        return _main()
    except Exception:
        path = log_startup_error()
        if os.name == "nt" and getattr(sys, "frozen", False):
            import ctypes
            ctypes.windll.user32.MessageBoxW(
                None, "Floor Plan Studio could not start.\nDetails: " + path,
                "Floor Plan Studio", 0x10)
        raise


def _main() -> int:
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

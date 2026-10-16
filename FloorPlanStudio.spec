# PyInstaller build file:  pyinstaller FloorPlanStudio.spec --noconfirm
import sys
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

datas = [("examples", "examples"), ("assets", "assets")]
datas += collect_data_files("trimesh")
datas += collect_data_files("ezdxf")
hidden = collect_submodules("ezdxf.fonts") + ["shapely", "mapbox_earcut"]

a = Analysis(
    ["FloorPlanStudio.py"],
    datas=datas,
    hiddenimports=hidden,
    excludes=["matplotlib", "tkinter", "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets",
              "PySide6.Qt3DCore", "PySide6.QtQuick", "PySide6.QtQml", "PySide6.QtMultimedia",
              "PySide6.QtCharts", "PySide6.QtDataVisualization", "PySide6.QtPdf", "pytest", "IPython"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, a.binaries, a.datas, [],
    name="FloorPlanStudio",
    console=False,
    icon="assets/icon.ico",
    upx=False,
)

# PyInstaller build file:  pyinstaller FloorPlanStudio.spec --noconfirm
import sys
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

datas = [("examples", "examples"), ("assets", "assets")]
datas += collect_data_files("trimesh")
datas += collect_data_files("ezdxf")
hidden = collect_submodules("ezdxf.fonts") + ["shapely", "mapbox_earcut"]
# standard modules that user add-ons commonly import (the exe only bundles what it uses itself)
hidden += ["csv", "statistics", "datetime", "decimal", "fractions", "itertools", "collections", "functools",
           "pathlib", "random", "string", "textwrap", "uuid", "zipfile", "sqlite3", "xml.etree.ElementTree",
           "urllib.request", "html", "pprint", "copy", "dataclasses", "enum", "typing"]

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
# One-folder build (no self-extracting single file): far fewer antivirus false positives.
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="FloorPlanStudio",
    console=False,
    icon="assets/icon.ico",
    version="assets/version_info.txt",
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name="FloorPlanStudio", upx=False)

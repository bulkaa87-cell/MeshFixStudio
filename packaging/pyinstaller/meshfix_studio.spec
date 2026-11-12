# PyInstaller spec of MeshFix Studio: one folder (dist/MeshFix Studio/).
#
#   pyinstaller --noconfirm packaging/pyinstaller/meshfix_studio.spec
#
# Install the packages first (the wheels of meshfix-core and foamview, and
# the app folder on the path). The same spec makes the Windows folder, the
# macOS .app (BUNDLE) and the Linux folder for the AppImage.

import os
import sys

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

ROOT = os.path.abspath(os.path.join(SPECPATH, "..", ".."))
APP = os.path.join(ROOT, "app")
NAME = "MeshFix Studio"

datas = []
for pkg in ("meshfix", "foamview"):
    datas += collect_data_files(pkg, includes=["i18n/**/*.json"])
datas += [(os.path.join(APP, "meshfix_studio", "i18n"),
           os.path.join("meshfix_studio", "i18n")),
          (os.path.join(APP, "meshfix_studio", "icons"),
           os.path.join("meshfix_studio", "icons"))]

hidden = ["meshfix._native", "foamview._native", "pyvistaqt",
          "vtkmodules.util.numpy_support",
          "vtkmodules.qt.QVTKRenderWindowInteractor"]
if sys.platform == "win32":
    # The Windows repair service (meshfix.winfix) imports these at run time.
    hidden += collect_submodules("winrt")

# Big packages that the program does not use. matplotlib stays: VTK, the
# fallback renderer of the 3D view, imports pyvista.plotting, and that
# needs matplotlib (colour maps).
excludes = ["tkinter", "IPython", "jupyter", "notebook",
            "pytest", "scipy", "pandas", "trame", "trame_client",
            "trame_server", "trame_vtk", "trame_vuetify",
            "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets",
            "PySide6.QtQuick", "PySide6.QtQml", "PySide6.Qt3DCore",
            "PySide6.QtMultimedia", "PySide6.QtPdf", "PySide6.QtCharts",
            "PySide6.QtDataVisualization", "PySide6.QtGraphs",
            "PySide6.QtLocation", "PySide6.QtPositioning",
            "PySide6.QtBluetooth", "PySide6.QtNfc", "PySide6.QtSensors",
            "PySide6.QtSerialPort", "PySide6.QtWebSockets",
            "PySide6.QtDesigner", "PySide6.QtHelp", "PySide6.QtSql",
            "PySide6.QtTest", "PySide6.QtSvgWidgets", "PySide6.QtQuickWidgets"]

a = Analysis(
    [os.path.join(SPECPATH, "entry.py")],
    pathex=[APP],
    binaries=[],
    datas=datas,
    hiddenimports=hidden,
    hookspath=[],
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
)
pyz = PYZ(a.pure)

# The icon files are in git (packaging/icons/make_icons.py makes them).
# Linux: no icon in the program; the AppImage has the PNG files.
icon = None
if sys.platform in ("win32", "darwin"):
    icon = os.path.join(ROOT, "packaging", "icons",
                        "meshfix-studio.ico" if sys.platform == "win32"
                        else "meshfix-studio.icns")

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=NAME,
    debug=False,
    strip=False,
    upx=False,
    console=False,
    icon=icon,
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name=NAME)

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name=NAME + ".app",
        icon=icon,
        bundle_identifier="io.github.bulkaa87-cell.meshfixstudio",
        info_plist={
            "CFBundleShortVersionString": "0.1.2",
            "NSHighResolutionCapable": True,
            "CFBundleDocumentTypes": [{
                "CFBundleTypeName": "STL mesh",
                "CFBundleTypeRole": "Editor",
                "LSItemContentTypes": ["public.standard-tesselated-geometry-format"],
                "CFBundleTypeExtensions": ["stl", "obj", "ply"],
            }],
        },
    )

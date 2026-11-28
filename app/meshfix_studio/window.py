"""MeshFix Studio: a small program that repairs one surface mesh.

Open a mesh (STL, 3MF, OBJ, PLY, OFF, glTF, VTK), look at its problems in
3D, repair it, export it in one of these formats. Start it with
«meshfix-studio [file]» or «python -m meshfix_studio [file]».

NO SECOND COPY OF THE REPAIR. The repair, the method list, the check and
the 3D view are the shared packages of this repository. OpenFOAM Studio
uses the same packages:
- meshfix.methods: the methods (meshfix, alpha wrap, Windows, volume
  rebuild) and repair_meshes(); the «Repair» button of OpenFOAM Studio
  calls the same function;
- meshfix.repair + meshfix._native (crates/meshfix): the repair itself;
- meshfix.check: reading the file, the check (diagnose) and the problem
  layers;
- foamview.viewport.Viewport: the 3D view (foamview with the fallbacks
  GPU -> WARP/lavapipe/llvmpipe -> VTK -> CPU), with its problem layers;
- meshfix.qt.RepairWorker and end_process: the worker thread and a safe
  end of the process while a repair still runs.

UNITS. Most mesh files have no units. The program guesses them from the
size (meshfix.check.guess_scale), and the person can change them in
«Units». A 3MF or glTF file gives its unit. The repair works in metres
(its tolerances are in mm). The export writes a format without a unit in
the units of the input file, 3MF in mm and glTF in m.

BODIES. A file can have several bodies (3MF objects, OBJ objects, ASCII
STL solids, glTF nodes). The repair repairs each body alone, and the
export keeps them where the format can (meshfix.formats).

STL-SAFE OUTPUT. The repair here does not run the step stl_safe_output.
The export applies it to the file coordinates, only for STL and glTF
(float32 coordinates): meshfix.check.save_mesh.

LANGUAGE. English by default. «View → Language» selects Ukrainian; FS_LANG
overrides the setting. The texts are English keys of meshfix.i18n
(meshfix_studio/i18n/uk/meshfix_studio.json).
"""

from __future__ import annotations

import math
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import _compat  # noqa: F401  — first (six + PySide6 fix)

import numpy as np
from PySide6 import QtCore, QtGui, QtWidgets

from foamview import viewport as vp
from meshfix import __version__ as CORE_VERSION
from meshfix import check as geo
from meshfix import i18n as fs_i18n
from meshfix import methods as fs_repair
from meshfix import repair as fs_meshfix
from meshfix import cad
from meshfix.i18n import tr
from meshfix.qt import RepairWorker, end_process

from . import __version__
from . import update

APP_NAME = "MeshFix Studio"
SETTINGS_ORG = "MeshFix Studio"
SETTINGS_APP = "ui"
DEFAULT_LANGUAGE = "en"
I18N_DIR = Path(__file__).resolve().with_name("i18n")
ICON_DIR = Path(__file__).resolve().with_name("icons")
APP_USER_MODEL_ID = "MeshFixStudio.MeshFixStudio"
# The file types that the window opens: the reader table of meshfix.check.
SUFFIXES = tuple(geo.READERS)
SOURCE_URL = "https://github.com/bulkaa87-cell/MeshFixStudio"
HISTORY = 10            # undo steps that the program keeps
CLOSE_GRACE_MS = 1500   # wait for a running repair at the end, then exit

# Units of a mesh file: (key, label, metres per unit).
UNITS = (("mm", "mm", 0.001), ("cm", "cm", 0.01), ("m", "m", 1.0),
         ("in", "in", 0.0254), ("km", "km", 1000.0))

def app_icon() -> QtGui.QIcon:
    """The logo in each size of meshfix_studio/icons/ (packaging/icons/
    make_icons.py writes them). An empty icon when the files are missing."""
    icon = QtGui.QIcon()
    for path in sorted(ICON_DIR.glob("meshfix-studio-*.png")):
        icon.addFile(str(path))
    return icon


def own_taskbar_button() -> None:
    """Windows, a start with python(w).exe: without an own app id, the
    taskbar shows the button of Python with the icon of Python. The frozen
    program has the icon in its exe, and the shortcuts of the installer have
    no app id: there an id would make a second taskbar button."""
    if sys.platform != "win32" or getattr(sys, "frozen", False):
        return
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            APP_USER_MODEL_ID)
    except (AttributeError, OSError):
        pass


def open_settings() -> QtCore.QSettings:
    """The settings of the program. MESHFIX_SETTINGS_DIR (the tests, a
    portable copy) puts them in an INI file in that folder; else the
    usual place of the system (the registry on Windows)."""
    folder = os.environ.get("MESHFIX_SETTINGS_DIR")
    if folder:
        return QtCore.QSettings(os.path.join(folder, "meshfix-studio.ini"),
                                QtCore.QSettings.IniFormat)
    return QtCore.QSettings(SETTINGS_ORG, SETTINGS_APP)


def _num(n) -> str:
    """A whole number with groups of three digits."""
    text = f"{int(n):,}"
    return text.replace(",", " ") if fs_i18n.language() == "uk" else text


def _real(x: float) -> str:
    """About 4 significant digits, without an exponent for usual sizes."""
    a = abs(x)
    if a == 0:
        return "0"
    if not 1e-3 <= a < 1e12:
        return f"{x:.4g}"
    digits = max(0, 3 - math.floor(math.log10(a)))
    text = f"{x:,.{digits}f}"
    return text.replace(",", " ") if fs_i18n.language() == "uk" else text


def _seconds(sec: float) -> str:
    return f"{sec:.2f}" if sec < 10 else f"{sec:.1f}" if sec < 100 else f"{sec:.0f}"


@dataclass
class State:
    """One version of the mesh: the mesh (m), its check and what the 3D view
    shows. The view data is kept, so Undo does not compute it again."""
    mesh: object
    diag: object
    display: object
    layers: dict = field(default_factory=dict)


def _state_of(mesh) -> State:
    """Check a mesh and prepare it for the view. Worker thread."""
    diag = geo.diagnose(mesh)
    return State(mesh, diag, geo.display_mesh(mesh),
                 geo.problem_layers(mesh, diag))


# The colours of the bodies (soft, so the problem layers stay visible).
BODY_COLORS = ("#9fb7d4", "#e0b07a", "#9fd0a4", "#d49fc4", "#d4cf8f",
               "#8fcfd0", "#c4a88f", "#b0a4e0")


def body_color(i: int, n: int) -> str:
    """The colour of body i of n in the 3D view (one body: the usual
    colour of the model)."""
    return vp.COL_BODY if n <= 1 else BODY_COLORS[i % len(BODY_COLORS)]


COL_SELECTED = "#ff9500"     # the selected bodies (as in OpenFOAM Studio)
COL_SECTION = "#33d1ff"      # the cut line of the section view


def pick_ray(cam, w: float, h: float, x: float, y: float):
    """The ray (origin, unit direction) of the pixel (x, y) of a view of
    w x h pixels (y down), for a camera with the VTK methods (VTK and
    foamview have them). The view angle is vertical, the parallel scale is
    half the height (as in VTK)."""
    pos = np.asarray(cam.GetPosition(), float)
    foc = np.asarray(cam.GetFocalPoint(), float)
    up = np.asarray(cam.GetViewUp(), float)
    f = foc - pos
    f /= np.linalg.norm(f) or 1.0
    r = np.cross(f, up)
    r /= np.linalg.norm(r) or 1.0
    u = np.cross(r, f)
    nx = 2.0 * x / max(w, 1) - 1.0
    ny = 1.0 - 2.0 * y / max(h, 1)
    aspect = w / max(h, 1)
    if cam.GetParallelProjection():
        half = float(cam.GetParallelScale())
        return pos + (nx * half * aspect) * r + (ny * half) * u, f
    t = math.tan(math.radians(float(cam.GetViewAngle())) / 2.0)
    d = f + (nx * t * aspect) * r + (ny * t) * u
    return pos, d / np.linalg.norm(d)


def first_hit(v0, e1, e2, origin, d) -> int:
    """The index of the first triangle that the ray hits (-1: none).
    Moller-Trumbore for all triangles at once; both sides count."""
    if not len(v0):
        return -1
    p = np.cross(d, e2)
    det = np.einsum("ij,ij->i", e1, p)
    ok = np.abs(det) > 1e-18
    inv = np.zeros_like(det)
    inv[ok] = 1.0 / det[ok]
    tv = origin - v0
    uu = np.einsum("ij,ij->i", tv, p) * inv
    q = np.cross(tv, e1)
    vv = (q @ d) * inv
    t = np.einsum("ij,ij->i", e2, q) * inv
    hit = ok & (uu >= 0) & (vv >= 0) & (uu + vv <= 1) & (t > 0)
    if not hit.any():
        return -1
    idx = np.nonzero(hit)[0]
    return int(idx[np.argmin(t[idx])])


class MeshViewport(vp.Viewport):
    """The shared «3D» view, without the «All» button (there is only the
    model here)."""

    FIT_ALL = False

    def __init__(self, parent=None):
        super().__init__(parent)
        self.to_model_requested.connect(self.fit_body)
        # The number of bodies of the whole model (the window sets it). A
        # body keeps its colour when the view shows only some bodies.
        self.n_bodies = 0

    def body_style(self, mesh) -> dict:
        """One colour for each body when the mesh has more than one (for
        example after «Split»). The list «Bodies to export» uses the same
        colours (body_color)."""
        if geo.BODY in mesh.cell_data:
            ids = np.asarray(mesh.cell_data[geo.BODY])
            n = max(int(ids.max()) + 1 if ids.size else 0, self.n_bodies)
            if n > 1:
                k = min(n, 256)              # the size limit of the colour table
                colors = [body_color(i, n) for i in range(k)]
                return {"scalars": geo.BODY, "preference": "cell",
                        "cmap": colors, "clim": (-0.5, n - 0.5),
                        "n_colors": k, "show_scalar_bar": False}
        return super().body_style(mesh)

    def set_visible(self, key: str, visible: bool):
        super().set_visible(key, visible)
        if key == "body":               # the highlight goes with the body
            super().set_visible("selected", visible)

    def show_selected(self, mesh) -> None:
        """Highlight the selected bodies: an orange, half-transparent copy
        a little outside the surface (along the normals: two layers on the
        same triangles flicker). None: no highlight."""
        self._drop("selected")
        if mesh is not None and mesh.n_cells:
            m = mesh.copy()
            if "Normals" not in m.point_data:
                m = geo.display_mesh(m)
            nrm = m.point_data.get("Normals")
            if nrm is not None:
                m.points = (np.asarray(m.points)
                            + np.asarray(nrm) * (0.002 * max(m.length, 1e-12)))
            self.actors["selected"] = self.plotter.add_mesh(
                m, color=COL_SELECTED, opacity=0.6, smooth_shading=False,
                show_edges=False, name="selected", reset_camera=False)
            super().set_visible("selected", self.chk["body"].isChecked())
        self.plotter.render()


class MeshFixWindow(QtWidgets.QMainWindow):
    def __init__(self):
        fs_i18n.install()
        super().__init__()
        self.setObjectName("MeshFixStudio")
        self.setWindowIcon(app_icon())
        self.setAcceptDrops(True)
        self.store = open_settings()
        # The detail of the triangles of a STEP file (meshfix.cad.DETAILS).
        level = str(self.store.value("step_detail", cad.DEFAULT_DETAIL))
        cad.detail = level if level in cad.DETAILS else cad.DEFAULT_DETAIL

        self.path: Path | None = None
        self.factor = 1.0               # metres per unit of the file
        self.unit_note = ""
        self.loaded: State | None = None
        self.state: State | None = None
        self.history: list[State] = []
        self.repaired: dict | None = None     # the last repair, for the info
        self.export_check = None              # Diagnosis of the written file
        self.export_checks: list = []         # each file of the last export
        self.export_info = None               # meshfix.check.SaveInfo
        self.unit_given = False               # the file gives its unit
        self._spots: list = []
        self._spot_at = -1

        self._thread: QtCore.QThread | None = None
        self._worker = None
        self._job = ""
        self._closing = False
        self._t0 = 0.0

        self._build()
        fs_i18n.on_language_changed(self._language_changed)
        self._update_title()
        self._sync()
        geom = self.store.value("geometry")
        if geom is not None:
            self.restoreGeometry(geom)
        else:
            self.resize(1280, 800)

    # ------------------------------------------------------------- the window
    def _build(self):
        bar = QtWidgets.QToolBar("Main")
        bar.setObjectName("main_bar")
        bar.setMovable(False)
        self.addToolBar(bar)

        self.btn_open = QtWidgets.QPushButton("Open…")
        self.btn_open.setToolTip("Open a mesh file: STL, 3MF, OBJ, PLY, OFF, "
                                 "glTF, VTP, VTK, or a STEP file (.step, "
                                 ".stp) from a CAD program. You can also "
                                 "drop a file on the window. Several files "
                                 "become one model with a body for each "
                                 "file.")
        self.btn_open.clicked.connect(self.open_dialog)
        bar.addWidget(self.btn_open)
        bar.addSeparator()

        bar.addWidget(QtWidgets.QLabel(" Units "))
        self.cmb_units = QtWidgets.QComboBox()
        for key, text, _factor in UNITS:
            self.cmb_units.addItem(text, key)
        self.cmb_units.setToolTip(
            "Units of the numbers in the file. The program guesses them from "
            "the size (a 3MF or glTF file gives its unit). The repair "
            "tolerances are in mm, thus the units must be correct. The "
            "export keeps these units; 3MF is always in mm, glTF in m.")
        self.cmb_units.activated.connect(self._units_chosen)
        bar.addWidget(self.cmb_units)
        bar.addSeparator()

        bar.addWidget(QtWidgets.QLabel(" Method "))
        self.cmb_method = QtWidgets.QComboBox()
        self.cmb_method.setSizeAdjustPolicy(
            QtWidgets.QComboBox.AdjustToContents)
        self._fill_methods()
        self.cmb_method.currentIndexChanged.connect(self._method_changed)
        bar.addWidget(self.cmb_method)

        self.btn_repair = QtWidgets.QPushButton("Repair")
        self.btn_repair.setToolTip("Repair the mesh with the selected method")
        self.btn_repair.clicked.connect(lambda _=False: self.repair())
        bar.addWidget(self.btn_repair)
        self.btn_split = QtWidgets.QPushButton("Split")
        self.btn_split.setToolTip(
            "Split each body into its separate parts: each part becomes a "
            "body of its own. Solids that only touch (on a face, an edge or "
            "a vertex) become separate bodies too. A cavity stays in the "
            "body around it. 3MF, OBJ, ASCII STL, glTF and VTK keep the "
            "bodies apart.")
        self.btn_split.clicked.connect(lambda _=False: self.split_parts())
        bar.addWidget(self.btn_split)
        bar.addSeparator()

        self.btn_export = QtWidgets.QPushButton("Export…")
        self.btn_export.setToolTip(
            "Save the mesh: STL, 3MF, OBJ, PLY, OFF, glTF or VTK. The "
            "extension selects the format. A format without a unit gets the "
            "units of the input file; 3MF is in mm, glTF in m. 3MF, OBJ, "
            "ASCII STL, glTF and VTK keep the bodies apart; the other "
            "formats merge them.\nOnly for STL and glTF (float32 "
            "coordinates): the program first moves the points that the "
            "rounding would join or make into a flat triangle, by about "
            "0.001 mm (the step «STL-safe output»).")
        self.btn_export.clicked.connect(self.export_dialog)
        bar.addWidget(self.btn_export)
        bar.addSeparator()

        self.btn_undo = QtWidgets.QPushButton("Undo")
        self.btn_undo.setToolTip("Go back one step (Ctrl+Z)")
        self.btn_undo.clicked.connect(self.undo)
        bar.addWidget(self.btn_undo)
        self.btn_reset = QtWidgets.QPushButton("Reset")
        self.btn_reset.setToolTip("Go back to the mesh as it was loaded")
        self.btn_reset.clicked.connect(self.reset)
        bar.addWidget(self.btn_reset)

        split = QtWidgets.QSplitter(QtCore.Qt.Horizontal)
        self.split = split
        self.view = MeshViewport()
        # A click (no drag) on a body selects it in the list (Ctrl: add or
        # remove). A drag still turns the camera.
        self._press_at = None
        self._pick_cache = None
        self.view.plotter.interactor.installEventFilter(self)
        self.view.btn_spot.clicked.connect(self.next_problem)
        left = QtWidgets.QWidget()
        lv = QtWidgets.QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)
        lv.setSpacing(0)
        lv.addWidget(self.view, 1)
        lv.addWidget(self._build_section())
        split.addWidget(left)
        split.addWidget(self._build_info())
        split.setStretchFactor(0, 1)
        split.setStretchFactor(1, 0)
        split.setSizes([920, 360])
        self.setCentralWidget(split)

        sb = self.statusBar()
        self.lbl_step = QtWidgets.QLabel("")
        self.busy = QtWidgets.QProgressBar()
        self.busy.setRange(0, 0)
        self.busy.setMaximumWidth(160)
        self.busy.setTextVisible(False)
        self.busy.hide()
        sb.addWidget(self.busy)
        sb.addWidget(self.lbl_step, 1)
        self.lbl_3d = QtWidgets.QLabel("")
        sb.addPermanentWidget(self.lbl_3d)
        self._show_level()
        self.view.level_changed.connect(lambda *_a: self._show_level())
        self.tick = QtCore.QTimer(self)
        self.tick.setInterval(1000)
        self.tick.timeout.connect(self._tick)

        self._build_menu()
        # The version and «Update to X» in the corner of the menu bar
        # (update.py): one click downloads and installs the new version.
        self.update_badge = update.add_badge(
            self, app_name=APP_NAME, version=__version__,
            repo=SOURCE_URL.split("github.com/")[1])

    def _build_info(self) -> QtWidgets.QWidget:
        box = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(box)
        lay.setContentsMargins(8, 6, 8, 6)
        form = QtWidgets.QFormLayout()
        form.setLabelAlignment(QtCore.Qt.AlignLeft)
        self.info: dict[str, QtWidgets.QLabel] = {}
        colours = {"open_edges": vp.COL_HOLE, "flipped_faces": vp.COL_FLIP,
                   "non_manifold_edges": vp.COL_NM,
                   "degenerate": vp.COL_DEGEN}
        rows = [("file", "File"), ("units", "Units"), ("size", "Size"),
                ("triangles", "Triangles"), ("bodies", "Bodies"),
                ("parts", "Parts"), ("closed", "Closed")]
        rows += list(fs_repair.COUNTS)
        rows += [("volume", "Volume"), ("method", "Method"),
                 ("time", "Repair time")]
        for key, text in rows:
            name = QtWidgets.QLabel(text)
            if key in colours:
                name.setStyleSheet(f"color:{colours[key]}; font-weight:bold;")
            value = QtWidgets.QLabel("—")
            value.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
            value.setWordWrap(True)
            form.addRow(name, value)
            self.info[key] = value
        lay.addLayout(form)
        head = QtWidgets.QLabel("What the repair did")
        head.setStyleSheet("font-weight:bold; margin-top:6px;")
        lay.addWidget(head)
        self.lbl_summary = QtWidgets.QLabel("—")
        self.lbl_summary.setWordWrap(True)
        self.lbl_summary.setTextInteractionFlags(
            QtCore.Qt.TextSelectableByMouse)
        lay.addWidget(self.lbl_summary)
        head = QtWidgets.QLabel("Log")
        head.setStyleSheet("font-weight:bold; margin-top:6px;")
        lay.addWidget(head)
        self.log = QtWidgets.QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(500)
        lay.addWidget(self.log, 1)
        lay.addWidget(self._build_bodies())
        box.setMinimumWidth(300)
        return box

    def _build_bodies(self) -> QtWidgets.QWidget:
        """The section «Bodies to export»: a list of the bodies with the
        colour of the 3D view and a check box (on by default). Only the
        bodies with a check are in the 3D view and go to the export.
        Closed at the start."""
        box = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(box)
        lay.setContentsMargins(0, 6, 0, 0)
        row = QtWidgets.QHBoxLayout()
        self.btn_bodies = QtWidgets.QPushButton("Bodies to export")
        self.btn_bodies.setObjectName("bodies_toggle")
        self.btn_bodies.setCheckable(True)
        self.btn_bodies.setChecked(False)
        self.btn_bodies.setFlat(True)
        self.btn_bodies.setStyleSheet("text-align:left; font-weight:bold;")
        self.btn_bodies.toggled.connect(self._bodies_toggled)
        row.addWidget(self.btn_bodies, 1)
        self.lbl_bodies = QtWidgets.QLabel("")
        row.addWidget(self.lbl_bodies)
        lay.addLayout(row)
        self.bodies_panel = QtWidgets.QWidget()
        inner = QtWidgets.QVBoxLayout(self.bodies_panel)
        inner.setContentsMargins(0, 0, 0, 0)
        self.lst_bodies = QtWidgets.QListWidget()
        self.lst_bodies.setMaximumHeight(200)
        self.lst_bodies.itemChanged.connect(lambda _i: self._bodies_changed())
        # Select rows (Ctrl / Shift for more) to delete them.
        self.lst_bodies.setSelectionMode(
            QtWidgets.QAbstractItemView.ExtendedSelection)
        self.lst_bodies.itemSelectionChanged.connect(self._selection_changed)
        inner.addWidget(self.lst_bodies)
        self.btn_delete = QtWidgets.QPushButton("Delete Selected")
        self.btn_delete.setToolTip(
            "Delete the selected bodies from the model (key Delete). "
            "Select more rows with Ctrl or Shift. Undo brings them back.")
        self.btn_delete.clicked.connect(lambda _=False: self.delete_bodies())
        drow = QtWidgets.QHBoxLayout()
        drow.addWidget(self.btn_delete)
        drow.addStretch(1)
        inner.addLayout(drow)
        self.chk_each = QtWidgets.QCheckBox("A file for each body")
        self.chk_each.setToolTip(
            "Export each selected body to a file of its own: "
            "<name>_<body>.<extension> in the selected folder. Without a "
            "check: one file with all selected bodies.")
        inner.addWidget(self.chk_each)
        lay.addWidget(self.bodies_panel)
        self.bodies_panel.setVisible(False)
        self._unchecked: set = set()       # names of bodies without a check
        self._bodies_toggled(False)
        return box

    def _bodies_toggled(self, shown: bool):
        style = self.style()
        icon = (QtWidgets.QStyle.SP_ArrowDown if shown
                else QtWidgets.QStyle.SP_ArrowRight)
        self.btn_bodies.setIcon(style.standardIcon(icon))
        self.bodies_panel.setVisible(shown)

    def _fill_bodies(self):
        """The list of the bodies of the current mesh. A body keeps its
        check when the next mesh has a body with the same name."""
        lst = self.lst_bodies
        lst.blockSignals(True)
        lst.clear()
        names = (geo.body_names(self.state.mesh) if self.state is not None
                 else [])
        if self.state is not None and not names:
            names = [self.path.stem if self.path else tr("Model")]
        n = len(names)
        for i, name in enumerate(names):
            item = QtWidgets.QListWidgetItem()
            item.setText(name)
            pix = QtGui.QPixmap(14, 14)
            pix.fill(QtGui.QColor(body_color(i, n)))
            item.setIcon(QtGui.QIcon(pix))
            item.setFlags(item.flags() | QtCore.Qt.ItemIsUserCheckable)
            item.setCheckState(QtCore.Qt.Unchecked if name in self._unchecked
                               else QtCore.Qt.Checked)
            lst.addItem(item)
        lst.blockSignals(False)
        if hasattr(self, "view"):
            self.view.show_selected(None)
        self._bodies_changed(update_view=False)

    def _show_bodies(self, reset: bool = False):
        """Show the bodies with a check in the 3D view. A body without a
        check is not in the view and not in the export."""
        st = self.state
        if st is None:
            return
        v = self.view
        n = self.lst_bodies.count()
        v.n_bodies = n
        on = self.export_selection()
        disp = st.display
        if not on and n:
            v.show_body(None)
            v._drop("section")
            return
        if len(on) < n and geo.BODY in disp.cell_data:
            ids = np.asarray(disp.cell_data[geo.BODY])
            disp = disp.remove_cells(np.nonzero(~np.isin(ids, on))[0])
        v.show_body(self._clip(disp), reset=reset)
        self._show_cut(disp)

    def _bodies_changed(self, update_view: bool = True):
        lst = self.lst_bodies
        names = [lst.item(i).text() for i in range(lst.count())]
        on = self.export_selection()
        self._unchecked = {nm for i, nm in enumerate(names) if i not in on}
        self.lbl_bodies.setText(f"{len(on)} / {len(names)}" if names else "")
        self.chk_each.setEnabled(len(on) > 1)
        if update_view:
            self._show_bodies()
            if hasattr(self, "view"):
                self._selection_changed()      # a hidden body: no highlight
        self._sync()

    # ---------------------------------------------------------- section view
    def _build_section(self) -> QtWidgets.QWidget:
        """The bar of the section view (View > Section View): a plane
        across one axis cuts the model, the part on one side is not shown.
        Hidden while the section is off."""
        bar = QtWidgets.QWidget()
        bar.setObjectName("section_bar")
        row = QtWidgets.QHBoxLayout(bar)
        row.setContentsMargins(6, 3, 6, 3)
        row.addWidget(QtWidgets.QLabel("Section"))
        self.cmb_section = QtWidgets.QComboBox()
        for i, name in enumerate("XYZ"):
            self.cmb_section.addItem(name, i)
        self.cmb_section.setToolTip("The axis across the section plane")
        row.addWidget(self.cmb_section)
        self.sld_section = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.sld_section.setRange(0, 1000)
        self.sld_section.setValue(500)
        self.sld_section.setToolTip(
            "The place of the section plane, from the start to the end of "
            "the model along the axis")
        row.addWidget(self.sld_section, 1)
        self.lbl_section = QtWidgets.QLabel("")
        self.lbl_section.setMinimumWidth(110)
        row.addWidget(self.lbl_section)
        self.chk_section_flip = QtWidgets.QCheckBox("Other side")
        self.chk_section_flip.setToolTip(
            "Show the part on the other side of the plane")
        row.addWidget(self.chk_section_flip)
        close = QtWidgets.QToolButton()
        close.setText("×")
        close.setToolTip("Close the section view")
        close.clicked.connect(lambda: self.set_section(False))
        row.addWidget(close)
        bar.setVisible(False)
        self.section_bar = bar
        # A slider drag gives many values: draw after a short pause.
        self._section_timer = QtCore.QTimer(self)
        self._section_timer.setSingleShot(True)
        self._section_timer.setInterval(60)
        self._section_timer.timeout.connect(self._section_changed)
        self.cmb_section.currentIndexChanged.connect(
            lambda _i: self._section_timer.start())
        self.sld_section.valueChanged.connect(
            lambda _v: self._section_timer.start())
        self.chk_section_flip.toggled.connect(
            lambda _v: self._section_timer.start())
        return bar

    def set_section(self, on: bool) -> None:
        """Turn the section view on or off (View > Section View, Ctrl+K)."""
        on = bool(on)
        self.section_bar.setVisible(on)
        if hasattr(self, "act_section") and self.act_section.isChecked() != on:
            self.act_section.blockSignals(True)
            self.act_section.setChecked(on)
            self.act_section.blockSignals(False)
        self._section_changed()

    def section(self):
        """(axis, position, flip) of the active section, or None. The
        position is in the coordinates of the mesh."""
        if not self.section_bar.isVisible() or self.state is None:
            return None
        axis = int(self.cmb_section.currentData())
        lo, hi = self._section_range(axis)
        pos = lo + (hi - lo) * self.sld_section.value() / 1000.0
        return axis, pos, self.chk_section_flip.isChecked()

    def _section_range(self, axis: int):
        b = self.state.display.bounds
        return float(b[2 * axis]), float(b[2 * axis + 1])

    def _clip(self, mesh):
        """`mesh` on the shown side of the section; the mesh itself when
        the section is off. Triangles fully on the shown side stay as they
        are; only the few triangles across the plane are cut exactly (VTK
        clip), so a coarse mesh has no triangles that stick out past the
        plane, and a big mesh stays fast. Lines and points (the problem
        layers): by the cell centre."""
        sec = self.section()
        if sec is None or mesh is None or not mesh.n_cells:
            return mesh
        axis, pos, flip = sec
        if not (hasattr(mesh, "is_all_triangles") and mesh.n_faces_strict
                and mesh.is_all_triangles):
            c = np.asarray(mesh.cell_centers().points)[:, axis]
            hide = (c < pos) if flip else (c > pos)
            return mesh.remove_cells(np.nonzero(hide)[0]) if hide.any() else mesh
        tri = np.asarray(mesh.faces).reshape(-1, 4)[:, 1:]
        x = np.asarray(mesh.points)[:, axis][tri]
        lo, hi = x.min(axis=1), x.max(axis=1)
        if flip:
            full, gone = lo >= pos, hi <= pos
        else:
            full, gone = hi <= pos, lo >= pos
        across = ~(full | gone)
        if full.all():
            return mesh
        keep = mesh.remove_cells(np.nonzero(~full)[0]) if not full.all() else mesh
        if not across.any():
            return keep
        part = mesh.extract_cells(np.nonzero(across)[0]).extract_surface()
        normal = [0.0, 0.0, 0.0]
        normal[axis] = 1.0
        origin = [0.0, 0.0, 0.0]
        origin[axis] = pos
        cut = part.clip(normal=normal, origin=origin, invert=not flip)
        if cut.n_cells:
            cut = cut.triangulate()
            keep = keep.merge(cut, merge_points=False) if keep.n_cells else cut
        return keep

    def _section_changed(self):
        """Draw the model again with the section (or without it)."""
        sec = self.section()
        if sec is None:
            self.lbl_section.setText("")
        else:
            self.lbl_section.setText(
                f"{'XYZ'[sec[0]]} = {_real(sec[1] / self.factor)} "
                f"{self.units_text()}")
        self._pick_cache = None
        if self.state is not None:
            self._show_bodies()
            self._show_problems()
            self._selection_changed()

    def _show_cut(self, disp) -> None:
        """The line where the plane cuts the shown bodies."""
        v = self.view
        v._drop("section")
        sec = self.section()
        if sec is None or disp is None or not disp.n_cells:
            return
        axis, pos, _flip = sec
        normal = [0.0, 0.0, 0.0]
        normal[axis] = 1.0
        origin = list(disp.center)
        origin[axis] = pos
        try:
            cut = disp.slice(normal=normal, origin=origin)
        except Exception:                                   # noqa: BLE001
            return
        if cut is not None and cut.n_cells:
            v.actors["section"] = v.plotter.add_mesh(
                cut, color=COL_SECTION, line_width=3, name="section",
                reset_camera=False)
            v.plotter.render()

    # ------------------------------------------------------- pick in 3D view
    def eventFilter(self, obj, ev):                         # noqa: N802
        view = getattr(self, "view", None)
        if view is not None and obj is getattr(view.plotter, "interactor", None):
            t = ev.type()
            if (t == QtCore.QEvent.MouseButtonPress
                    and ev.button() == QtCore.Qt.LeftButton):
                self._press_at = ev.position()
            elif (t == QtCore.QEvent.MouseButtonRelease
                    and ev.button() == QtCore.Qt.LeftButton
                    and self._press_at is not None):
                d = ev.position() - self._press_at
                self._press_at = None
                if abs(d.x()) + abs(d.y()) <= 4:
                    add = bool(ev.modifiers() & QtCore.Qt.ControlModifier)
                    self.pick_at(ev.position().x(), ev.position().y(), add)
        return super().eventFilter(obj, ev)

    def _pick_data(self):
        """Triangles of the bodies in the view (v0, e1, e2, body ids),
        kept until the mesh or the shown bodies change."""
        st = self.state
        on = tuple(self.export_selection())
        key = (id(st.display), on, self.section())
        if self._pick_cache is not None and self._pick_cache[0] == key:
            return self._pick_cache[1]
        disp = st.display
        faces = np.asarray(disp.faces).reshape(-1, 4)[:, 1:]
        pts = np.asarray(disp.points, float)
        ids = (np.asarray(disp.cell_data[geo.BODY])
               if geo.BODY in disp.cell_data else np.zeros(len(faces), int))
        if self.lst_bodies.count() > 1:
            keep = np.isin(ids, on)
            faces, ids = faces[keep], ids[keep]
        sec = self.section()
        if sec is not None and len(faces):
            axis, pos, flip = sec
            c = pts[faces].mean(axis=1)[:, axis]
            keep = (c >= pos) if flip else (c <= pos)
            faces, ids = faces[keep], ids[keep]
        v0 = pts[faces[:, 0]]
        data = (v0, pts[faces[:, 1]] - v0, pts[faces[:, 2]] - v0, ids)
        self._pick_cache = (key, data)
        return data

    def body_at(self, x: float, y: float) -> int:
        """The body under the point (x, y) of the 3D view (widget pixels),
        -1 when the ray hits no body."""
        if self.state is None:
            return -1
        w = self.view.plotter.interactor
        origin, d = pick_ray(self.view.plotter.camera, w.width(), w.height(),
                             x, y)
        v0, e1, e2, ids = self._pick_data()
        i = first_hit(v0, e1, e2, origin, d)
        return int(ids[i]) if i >= 0 else -1

    def pick_at(self, x: float, y: float, add: bool = False) -> int:
        """A click in the 3D view: select the body under it in the list
        (add, with Ctrl: toggle it). A click beside the model clears the
        selection. Returns the body (-1: none)."""
        if self.state is None or self.busy_now:
            return -1
        body = self.body_at(x, y)
        lst = self.lst_bodies
        if body < 0 or body >= lst.count():
            if not add:
                lst.clearSelection()
            return -1
        item = lst.item(body)
        if add:
            item.setSelected(not item.isSelected())
        else:
            lst.clearSelection()
            item.setSelected(True)
        lst.scrollToItem(item)
        if not self.btn_bodies.isChecked():
            self.btn_bodies.setChecked(True)     # show the list and «Delete»
        self._say(tr("Selected: {name}", name=item.text()))
        return body

    def _selection_changed(self):
        """The rows of the list changed: highlight those bodies in 3D."""
        self._sync()
        st = self.state
        shown = set(self.export_selection())
        rows = [i for i in self.selected_bodies() if i in shown]
        if st is None or not rows or self.lst_bodies.count() < 2:
            self.view.show_selected(None)
            return
        disp = st.display
        ids = np.asarray(disp.cell_data[geo.BODY])
        self.view.show_selected(self._clip(
            disp.remove_cells(np.nonzero(~np.isin(ids, rows))[0])))

    def selected_bodies(self) -> list:
        """The indices of the selected rows of the body list (not the
        check boxes: those are for the export and the view)."""
        lst = self.lst_bodies
        return sorted(lst.row(it) for it in lst.selectedItems())

    def export_selection(self) -> list:
        """The indices of the bodies with a check."""
        lst = self.lst_bodies
        return [i for i in range(lst.count())
                if lst.item(i).checkState() == QtCore.Qt.Checked]

    def export_mesh(self):
        """The mesh that the export writes: the bodies with a check (the
        whole mesh when all have a check), or None when no body has one."""
        if self.state is None:
            return None
        mesh = self.state.mesh
        on = self.export_selection()
        bodies = geo.split_bodies(mesh)
        if len(on) == len(bodies) or self.lst_bodies.count() == 0:
            return mesh
        if not on:
            return None
        names = geo.body_names(mesh)
        out = geo.join_bodies([(names[i], bodies[i][1]) for i in on])
        if geo.UNIT in mesh.field_data:
            out.field_data[geo.UNIT] = np.asarray(mesh.field_data[geo.UNIT])
        return out

    def _build_menu(self):
        mb = self.menuBar()
        m = mb.addMenu("&File")
        self.act_open = m.addAction("Open…", self.open_dialog)
        self.act_open.setShortcut(QtGui.QKeySequence.Open)
        self.act_add = m.addAction("Add…", self.add_dialog)
        self.act_add.setShortcut(QtGui.QKeySequence("Ctrl+Shift+O"))
        self.act_export = m.addAction("Export…", self.export_dialog)
        self.act_export.setShortcut(QtGui.QKeySequence("Ctrl+E"))
        m.addSeparator()
        # The size of the triangles that the program makes for a STEP file.
        detail = m.addMenu("STEP Detail")
        detail.setEnabled(bool(geo.CAD_READERS))
        if not geo.CAD_READERS:
            detail.setToolTip("OpenCASCADE (the package cadquery-ocp-novtk) "
                              "is not installed")
        self.detail_group = QtGui.QActionGroup(self)
        self.act_detail = {}
        for key, d in cad.DETAILS.items():
            act = detail.addAction(d.label)
            act.setCheckable(True)
            act.setChecked(key == cad.detail)
            act.triggered.connect(lambda _=False, k=key: self.set_detail(k))
            self.detail_group.addAction(act)
            self.act_detail[key] = act
        m.addSeparator()
        m.addAction("Quit", self.close).setShortcut(QtGui.QKeySequence.Quit)

        m = mb.addMenu("&Edit")
        self.act_repair = m.addAction("Repair", lambda: self.repair())
        self.act_repair.setShortcut(QtGui.QKeySequence("Ctrl+R"))
        self.act_split = m.addAction("Split into Parts",
                                     lambda: self.split_parts())
        self.act_split.setShortcut(QtGui.QKeySequence("Ctrl+P"))
        self.act_delete = m.addAction("Delete Selected Bodies",
                                      lambda: self.delete_bodies())
        self.act_delete.setShortcut(QtGui.QKeySequence.Delete)
        self.act_undo = m.addAction("Undo", self.undo)
        self.act_undo.setShortcut(QtGui.QKeySequence.Undo)
        self.act_reset = m.addAction("Reset", self.reset)

        m = mb.addMenu("&View")
        m.addAction("Fit Model", self.view.fit_body).setShortcut(
            QtGui.QKeySequence("Ctrl+0"))
        for text, which in (("Iso", "iso"), ("X", "yz"), ("Y", "xz"),
                            ("Z", "xy")):
            m.addAction(text, lambda v=which: self.view.set_view(v))
        m.addSeparator()
        self.act_section = m.addAction("Section View")
        self.act_section.setCheckable(True)
        self.act_section.setShortcut(QtGui.QKeySequence("Ctrl+K"))
        self.act_section.setToolTip(
            "Cut the model with a plane and look inside")
        self.act_section.toggled.connect(self.set_section)
        m.addSeparator()
        lang = m.addMenu("Language")
        self.lang_group = QtGui.QActionGroup(self)
        self.act_lang = {}
        for code, name in fs_i18n.LANGUAGES.items():
            act = lang.addAction(name)
            act.setCheckable(True)
            act.setChecked(code == fs_i18n.language())
            act.triggered.connect(lambda _=False, c=code: self.set_language(c))
            self.lang_group.addAction(act)
            self.act_lang[code] = act

        m = mb.addMenu("&Help")
        m.addAction("About MeshFix Studio", self.about)

    def _fill_methods(self):
        """The method list of fs_repair; a method whose tool is missing is
        gray, and its tooltip tells why."""
        cmb = self.cmb_method
        cmb.blockSignals(True)
        want = cmb.currentData() or self.store.value("method",
                                                     fs_repair.DEFAULT)
        cmb.clear()
        model = cmb.model()
        for key, label, _tip in fs_repair.METHODS:
            cmb.addItem(label, key)
            row = cmb.count() - 1
            item = model.item(row)
            if fs_repair.available(key):
                item.setToolTip(fs_repair.tooltip(key))
            else:
                item.setEnabled(False)
                item.setToolTip(tr("Not available: {why}",
                                   why=fs_repair.why_not(key)))
        rows = [r for r in range(cmb.count()) if model.item(r).isEnabled()]
        pick = next((r for r in rows if cmb.itemData(r) == want),
                    rows[0] if rows else 0)
        cmb.setCurrentIndex(pick)
        cmb.blockSignals(False)
        self._method_changed(pick)

    def method(self) -> str:
        return self.cmb_method.currentData() or fs_repair.DEFAULT

    def _method_changed(self, row: int):
        item = self.cmb_method.model().item(row)
        if item is None:
            return
        self.cmb_method.setToolTip(item.toolTip())
        if item.isEnabled():
            self.store.setValue("method", item.data(QtCore.Qt.UserRole))
        self._sync()

    def _show_level(self):
        lv = getattr(self.view, "level", None)
        text = lv.text() if lv is not None else f"3D: {self.view.backend}"
        self.lbl_3d.setText(text)

    # ----------------------------------------------------------------- state
    @property
    def busy_now(self) -> bool:
        return self._thread is not None

    def _sync(self):
        """Enable the buttons for the current state."""
        if not hasattr(self, "btn_reset"):
            return
        idle = not self.busy_now
        has = self.state is not None
        item = self.cmb_method.model().item(self.cmb_method.currentIndex())
        can_fix = item is not None and item.isEnabled()
        for w in (self.btn_open, self.act_open if hasattr(self, "act_open")
                  else None):
            if w is not None:
                w.setEnabled(idle)
        self.cmb_units.setEnabled(idle and has)
        self.cmb_method.setEnabled(idle)
        self.btn_repair.setEnabled(idle and has and can_fix)
        self.btn_split.setEnabled(idle and has)
        self.btn_export.setEnabled(idle and has and (
            not hasattr(self, "lst_bodies") or self.lst_bodies.count() == 0
            or bool(self.export_selection())))
        self.btn_undo.setEnabled(idle and bool(self.history))
        if hasattr(self, "btn_delete"):
            sel = len(self.selected_bodies())
            self.btn_delete.setEnabled(
                idle and has and 0 < sel < self.lst_bodies.count())
        self.btn_reset.setEnabled(idle and has and self.state is not self.loaded)
        if hasattr(self, "act_repair"):
            self.act_repair.setEnabled(self.btn_repair.isEnabled())
            self.act_split.setEnabled(self.btn_split.isEnabled())
            self.act_delete.setEnabled(self.btn_delete.isEnabled())
            self.act_add.setEnabled(idle and has)
            self.act_export.setEnabled(self.btn_export.isEnabled())
            self.act_undo.setEnabled(self.btn_undo.isEnabled())
            self.act_reset.setEnabled(self.btn_reset.isEnabled())

    def _update_title(self):
        name = self.path.name if self.path else ""
        self.setWindowTitle(f"{name} — {APP_NAME}" if name else APP_NAME)

    def _say(self, text: str):
        self.lbl_step.setText(text)

    def _note(self, text: str):
        self.log.appendPlainText(f"{time.strftime('%H:%M:%S')}  {text}")

    # ------------------------------------------------------------ the worker
    def _start(self, name: str, job, text: str):
        """Run job(meshes, say) in a worker thread (meshfix.qt.RepairWorker).
        The window stays live; one job at a time."""
        if self.busy_now:
            return False
        self._job = name
        self._t0 = time.monotonic()
        self._busy_text = text
        self._say(text)
        self.busy.show()
        self.tick.start()
        self._worker = RepairWorker(job, [])
        self._thread = QtCore.QThread(self)
        self._thread.setObjectName(f"meshfix-{name}")
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.step.connect(self._on_step)
        self._worker.fraction.connect(self._on_fraction)
        self._worker.ready.connect(self._on_ready)
        self._worker.failed.connect(self._on_failed)
        self._thread.start()
        self._sync()
        return True

    def _end(self):
        self.tick.stop()
        self.busy.hide()
        self._on_fraction(-1.0)
        if self._thread is not None:
            self._thread.quit()
            self._thread.wait(5000)
            self._thread = None
        self._worker = None
        self._job = ""
        self._sync()

    def _tick(self):
        sec = int(time.monotonic() - self._t0)
        self._say(tr("{text} {sec} s", text=self._busy_text, sec=sec))

    @QtCore.Slot(str)
    def _on_step(self, text: str):
        if self._closing:
            return
        verdict = text.endswith(fs_meshfix.VERDICT)
        text = text.rstrip(fs_meshfix.VERDICT)
        self._busy_text = text
        self._tick()
        if verdict:
            self._note(text)

    @QtCore.Slot(float)
    def _on_fraction(self, value: float):
        """A percent bar for 0..1, the busy bar for a value below 0."""
        if value < 0:
            self.busy.setRange(0, 0)
            self.busy.setTextVisible(False)
        else:
            self.busy.setRange(0, 1000)
            self.busy.setValue(int(round(min(value, 1.0) * 1000)))
            self.busy.setFormat("%p %")
            self.busy.setTextVisible(True)

    def set_detail(self, key: str):
        """The detail of the triangles of the next STEP file. An open STEP
        file is read again with the new detail."""
        if key not in cad.DETAILS:
            return
        cad.detail = key
        self.store.setValue("step_detail", key)
        if key in self.act_detail:
            self.act_detail[key].setChecked(True)
        if (self.path is not None and cad.is_cad(self.path)
                and not self.busy_now and self.path.is_file()):
            self.open_file(self.path)

    @QtCore.Slot(str)
    def _on_failed(self, message: str):
        job = self._job
        self._end()
        if self._closing:
            return
        self._say("")
        self._note(tr("Failed: {message}", message=message))
        title = {"load": tr("Open failed"),
                 "split": tr("Split failed"),
                 "delete": tr("Delete failed")}.get(job, tr("Repair failed"))
        QtWidgets.QMessageBox.critical(self, title, message)

    @QtCore.Slot(object)
    def _on_ready(self, result):
        job = self._job
        self._end()
        if self._closing:
            return
        if job == "load":
            self._loaded(result)
        elif job == "repair":
            self._repaired(result)
        elif job == "split":
            self._split_done(result)
        elif job == "delete":
            self._delete_done(result)
        elif job == "units":
            self._units_done(result)
        elif job == "check":
            self._export_checked(result)

    # ------------------------------------------------------------------ open
    def _pick_files(self, title: str) -> list:
        start = self.store.value("folder", str(Path.home()))
        paths, _ = QtWidgets.QFileDialog.getOpenFileNames(
            self, title, start, geo.open_filter())
        return paths

    def open_dialog(self):
        """Open one or more mesh files. Several files become one model:
        each file is a body (or more, when the file has objects)."""
        if self.busy_now:
            return
        paths = self._pick_files(tr("Open a mesh"))
        if paths:
            self.open_files(paths)

    def add_dialog(self):
        """Add mesh files to the open model, as more bodies."""
        if self.busy_now or self.state is None:
            return
        paths = self._pick_files(tr("Add a mesh"))
        if paths:
            self.add_files(paths)

    def open_file(self, path) -> bool:
        """Read a mesh file in the worker thread."""
        return self.open_files([path])

    def open_files(self, paths) -> bool:
        """Read one or more mesh files in the worker thread. The first file
        sets the units (guessed from its size, or the unit of a 3MF or
        glTF file). The other files without a unit get the same units."""
        return self._read_files(paths, add=False)

    def add_files(self, paths) -> bool:
        """Read mesh files and add them to the model as more bodies (one
        step: Undo removes them). A file without a unit gets the units of
        the model."""
        if self.state is None:
            return False
        return self._read_files(paths, add=True)

    def _read_files(self, paths, add: bool) -> bool:
        paths = [Path(p) for p in paths]
        if self.busy_now or not paths or not all(p.is_file() for p in paths):
            return False
        self.store.setValue("folder", str(paths[0].parent))
        base = self.state.mesh if add else None
        base_factor = self.factor if add else None
        stem = self.path.stem if self.path else ""

        def job(_meshes, say):
            items, factor, note, given = [], base_factor, "", False
            for path in paths:
                say(tr("Reading {name}…", name=path.name))

                def progress(text, frac=None):
                    # -1: no percent (the busy bar), else 0..1.
                    say(text, -1.0 if frac is None else frac)
                raw = geo.load_surface(str(path), progress=progress)
                say(text=tr("Reading {name}…", name=path.name),
                    fraction=-1.0)
                f, why = geo.guess_scale(raw)
                has_unit = geo.UNIT in raw.field_data
                if factor is None:
                    factor, note, given = f, why, has_unit
                elif not has_unit:
                    f = factor
                items.append((path.stem, geo.apply_scale(raw, f)))
            if base is not None:
                items.insert(0, (stem, base))
            mesh = (items[0][1] if len(items) == 1
                    else geo.combine(items))
            say(tr("Checking {name}…", name=paths[-1].name))
            return paths, factor, (note, given), _state_of(mesh), add
        name = (paths[0].name if len(paths) == 1
                else tr("{n} files", n=len(paths)))
        return self._start("load", job, tr("Reading {name}…", name=name))

    def _loaded(self, result):
        paths, factor, (note, given), state, add = result
        names = ", ".join(p.name for p in paths)
        if add:
            self._push(self.state)
            self.state = state
            self.repaired = None
            self._show(reset_camera=True)
            text = tr("Added {names}: {n} bodies", names=names,
                      n=_num(geo.body_count(state.mesh)))
            self._note(text)
            self._say(text)
            self._sync()
            return
        self.path = paths[0]
        self._unchecked = set()
        self.factor = factor
        self.unit_note = note
        self.unit_given = given
        self.loaded = self.state = state
        self.history.clear()
        self.repaired = None
        self._select_units(factor)
        self._update_title()
        self._show(reset_camera=True)
        self._note(tr("Opened {name}: {n} triangles", name=names,
                      n=_num(state.diag.n_triangles)))
        if any(cad.is_cad(p) for p in paths):
            self._note(tr("STEP: detail «{level}» (File > STEP Detail)",
                          level=tr(cad.DETAILS[cad.detail].label)))
        if len(paths) > 1:
            self._note(tr("{n} files, {b} bodies", n=len(paths),
                          b=_num(geo.body_count(state.mesh))))
        self._say(tr("Opened {name}", name=names))
        self._sync()

    def _select_units(self, factor: float):
        for i, (_key, _text, f) in enumerate(UNITS):
            if abs(f - factor) <= 1e-12 * max(f, 1.0):
                self.cmb_units.setCurrentIndex(i)
                return

    def _units_chosen(self, row: int):
        new = UNITS[row][2]
        if self.state is None or abs(new - self.factor) < 1e-15:
            return
        k = new / self.factor
        states = [self.loaded, self.state] + self.history

        def job(_meshes, say):
            say(tr("Changing the units…"))
            done: dict[int, State] = {}
            for s in states:
                if s is not None and id(s) not in done:
                    done[id(s)] = _state_of(geo.apply_scale(s.mesh, k))
            return new, done
        if not self._start("units", job, tr("Changing the units…")):
            self._select_units(self.factor)

    def _units_done(self, result):
        new, done = result
        self.factor = new
        self.unit_note = ""
        self.loaded = done[id(self.loaded)]
        self.state = done[id(self.state)]
        self.history = [done[id(s)] for s in self.history]
        self.repaired = None
        self._show(reset_camera=True)
        self._note(tr("Units: {units}", units=self.units_text()))
        self._say("")

    def units_text(self) -> str:
        for _key, text, f in UNITS:
            if abs(f - self.factor) <= 1e-12 * max(f, 1.0):
                return text
        return f"× {self.factor:g} m"

    # ---------------------------------------------------------------- repair
    def repair(self, key: str | None = None) -> bool:
        """Repair the mesh with fs_repair (the same call as the «Repair»
        button of OpenFOAM Studio), in the worker thread."""
        if self.state is None or self.busy_now:
            return False
        key = key or self.method()
        if not fs_repair.available(key):
            QtWidgets.QMessageBox.information(self, "Repair",
                                              fs_repair.why_not(key))
            return False
        before = self.state
        label = fs_repair.label(key)

        def job(_meshes, say):
            t0 = time.perf_counter()
            # Each body alone, without the step stl_safe_output: the
            # export applies it to STL and glTF only.
            out = fs_repair.repair_bodies(key, before.mesh, say,
                                          stl_safe=False)
            sec = time.perf_counter() - t0
            say(tr("Checking the result…"))
            return key, sec, fs_repair.summary(key), _state_of(out)
        self._note(tr("Repair: {method}", method=label))
        return self._start("repair", job,
                           tr("Repairing ({method})…", method=label))

    def _repaired(self, result):
        key, sec, summary, state = result
        before = self.state
        self._push(before)
        self.state = state
        self.repaired = {"key": key, "seconds": sec, "summary": summary,
                         "steps": fs_repair.steps(key),
                         "before": before.diag}
        self._show(reset_camera=False)
        d0, d1 = before.diag, state.diag
        text = tr("Repaired with {method} in {sec} s: {result}",
                  method=fs_repair.label(key), sec=_seconds(sec),
                  result=(tr("closed and clean") if fs_repair.clean(d1)
                          else tr("problems are left")))
        self._say(text)
        self._note(text)
        if d0.n_triangles != d1.n_triangles:
            self._note(tr("Triangles: {a} → {b}", a=_num(d0.n_triangles),
                          b=_num(d1.n_triangles)))

    # ----------------------------------------------------------------- split
    def split_parts(self) -> bool:
        """Split each body into its separate parts (meshfix.formats
        .split_parts), in the worker thread. Undo goes back."""
        if self.state is None or self.busy_now:
            return False
        before = self.state
        stem = self.path.stem if self.path else ""

        def job(_meshes, say):
            mesh, info = geo.split_parts(before.mesh, stem)
            if mesh is before.mesh:
                return info, None
            say(tr("Checking the result…"))
            return info, _state_of(mesh)
        self._note(tr("Split into parts"))
        return self._start("split", job, tr("Splitting into parts…"))

    # ---------------------------------------------------------------- delete
    def delete_bodies(self, rows=None) -> bool:
        """Delete the selected bodies (meshfix.formats.remove_bodies), in
        the worker thread. One body at least stays. Undo goes back."""
        if self.state is None or self.busy_now:
            return False
        rows = self.selected_bodies() if rows is None else sorted(set(rows))
        n = max(self.lst_bodies.count(), 1)
        if not rows:
            return False
        if len(rows) >= n:
            text = tr("All bodies are selected: one body at least must "
                      "stay. To start again, open another file.")
            self._say(text)
            self._note(text)
            return False
        before = self.state
        names = [self.lst_bodies.item(i).text() for i in rows]

        def job(_meshes, say):
            mesh = geo.remove_bodies(before.mesh, rows)
            say(tr("Checking the result…"))
            return names, _state_of(mesh)
        self._note(tr("Delete: {names}", names=", ".join(names)))
        return self._start("delete", job, tr("Deleting bodies…"))

    def _delete_done(self, result):
        names, state = result
        self._push(self.state)
        self.state = state
        self.repaired = None
        self._show(reset_camera=False)
        text = tr("Deleted bodies: {n}", n=_num(len(names)))
        self._say(text)
        self._note(text)

    def _split_done(self, result):
        info, state = result
        if state is None:
            text = tr("Nothing to split: each body is one part")
            self._say(text)
            self._note(text)
            return
        self._push(self.state)
        self.state = state
        self.repaired = None
        self._show(reset_camera=False)
        text = tr("Split: {a} → {b} bodies", a=_num(info.bodies_before),
                  b=_num(info.bodies_after))
        self._say(text)
        self._note(text)
        if info.cavities:
            self._note(tr("Cavities kept in their bodies: {n}",
                          n=_num(info.cavities)))

    def _push(self, state: State):
        self.history.append(state)
        del self.history[:-HISTORY]

    def undo(self):
        if self.busy_now or not self.history:
            return
        self.state = self.history.pop()
        self.repaired = None
        self._show(reset_camera=False)
        self._say(tr("Undone"))
        self._note(tr("Undo"))
        self._sync()

    def reset(self):
        if self.busy_now or self.loaded is None or self.state is self.loaded:
            return
        self._push(self.state)
        self.state = self.loaded
        self.repaired = None
        self._show(reset_camera=False)
        self._say(tr("Back to the loaded mesh"))
        self._note(tr("Reset to the loaded mesh"))
        self._sync()

    # ---------------------------------------------------------------- export
    def export_dialog(self):
        if self.state is None or self.busy_now:
            return
        folder = self.store.value("export_folder",
                                  str(self.path.parent if self.path
                                      else Path.home()))
        stem = self.path.stem if self.path else "mesh"
        if self.repaired is not None or self.state is not self.loaded:
            stem += "_repaired"
        key = str(self.store.value("export_format", "stl") or "stl")
        if key not in geo.FORMATS:
            key = "stl"
        mesh = self.export_mesh()
        if mesh is None:
            self._say(tr("No body to export: check a body in «Bodies to "
                         "export»"))
            return
        n = geo.body_count(mesh)
        each = n > 1 and self.chk_each.isChecked()
        filters = geo.export_filters(1 if each else n)
        texts = [text for _k, text in filters]
        chosen = dict(filters)[key]
        path, picked = QtWidgets.QFileDialog.getSaveFileName(
            self, tr("Export"),
            str(Path(folder) / (stem + geo.FORMATS[key].suffix)),
            ";;".join(texts), chosen)
        if path:
            keys = [k for k, text in filters if text == picked]
            fmt = keys[0] if keys else None
            if each:
                self.export_bodies(path, fmt)
            else:
                self.export_file(path, fmt)

    def export_bodies(self, path, fmt: str | None = None) -> list:
        """Write each body to a file of its own: <name>_<body><suffix> in
        the folder of `path` (meshfix.check.save_bodies). Files that are
        there already: one question. Returns the paths ([] on an error or
        a cancel)."""
        mesh = self.export_mesh()
        if mesh is None:
            return []
        path = Path(path)
        if path.suffix.lower() not in geo.WRITERS:
            path = Path(str(path) + geo.FORMATS[fmt or "stl"].suffix)
        source = self.path.stem if self.path else ""
        files = geo.body_file_names(mesh, path, source)
        there = [f for f in files if f.exists()]
        if there:
            answer = QtWidgets.QMessageBox.question(
                self, tr("Export"),
                tr("{n} of the files are there already ({first}, ...). "
                   "Replace them?", n=len(there), first=there[0].name))
            if answer != QtWidgets.QMessageBox.Yes:
                return []
        try:
            form = geo.format_for(path, fmt)
            done = geo.save_bodies(mesh, path, form,
                                   unit_m=self.factor, source_stem=source)
        except Exception as exc:                          # noqa: BLE001
            QtWidgets.QMessageBox.critical(self, tr("Export failed"), str(exc))
            return []
        self.store.setValue("export_folder", str(path.parent))
        self.store.setValue("export_format", form.key)
        self.export_info = done[-1][1] if done else None
        text = tr("Exported {n} files ({format}, {units}) to {folder}",
                  n=len(done), format=geo.format_label(form),
                  units=done[0][1].unit if done else "",
                  folder=str(path.parent))
        self._say(text)
        self._note(text)
        for file, _info, body in done:
            self._note(tr("  {name}: {n} triangles", name=file.name,
                          n=_num(body.n_cells)))
        self._check_exports([(file, body) for file, _i, body in done])
        return [file for file, _i, _b in done]

    def _check_exports(self, items):
        """Read each written body file again and check it against its body
        (worker thread). The result: the same as _check_export."""
        self.export_check = None

        def job(_meshes, say):
            out = []
            for file, body in items:
                say(tr("Checking {name}…", name=file.name))
                out.append((file, geo.diagnose(body),
                            geo.diagnose(geo.load_surface(str(file)))))
            return out
        self._start("check", job, tr("Checking {name}…",
                                     name=tr("{n} files", n=len(items))))

    def export_file(self, path, fmt: str | None = None) -> Path | None:
        """Write the current mesh to `path`. The format: `fmt` (a key of
        meshfix.check.FORMATS, the filter of the dialog) when it has the
        extension of the name, else the format of the extension. A name
        without a known extension gets the extension of `fmt` (default
        binary STL). A format without a unit is written in the units of
        the input file. Returns the path, or None on an error (a message
        box)."""
        mesh = self.export_mesh()
        if mesh is None:
            return None
        path = Path(path)
        if path.suffix.lower() not in geo.WRITERS:
            path = Path(str(path) + geo.FORMATS[fmt or "stl"].suffix)
        try:
            form = geo.format_for(path, fmt)
            info = geo.save_mesh(mesh, path, form, unit_m=self.factor)
        except Exception as exc:                          # noqa: BLE001
            QtWidgets.QMessageBox.critical(self, tr("Export failed"), str(exc))
            return None
        self.store.setValue("export_folder", str(path.parent))
        self.store.setValue("export_format", form.key)
        self.export_info = info
        text = tr("Exported {name} ({format}, {n} triangles, {units})",
                  name=path.name, format=geo.format_label(form),
                  n=_num(mesh.n_cells), units=info.unit)
        self._say(text)
        self._note(text)
        self._note(geo.save_note(info))
        moved = sum((info.stl_safe or {}).get(k, 0)
                    for k in ("moved", "collapsed", "flipped"))
        if moved:
            self._note(tr("STL-safe output: {n} changes (points moved by "
                          "up to {d} {units})", n=_num(moved),
                          d=f"{info.stl_safe.get('max_move', 0):.2g}",
                          units=info.unit))
        self._check_export(path, None if mesh is self.state.mesh else mesh)
        return path

    def _check_export(self, path: Path, part=None):
        """Read the written file again and check it (worker thread).

        STL keeps float32 coordinates and no topology: a reader joins equal
        points. Vertices that the repair keeps apart (the two copies of a
        pinched edge, points nearer than the float32 step) are then one
        point again, and the file can show problems that the mesh in memory
        does not have. The export applies the step «STL-safe output» for
        this; when a problem stays, the person must know it.
        """
        want = self.state.diag
        self.export_check = None

        def job(_meshes, say):
            say(tr("Checking {name}…", name=path.name))
            ref = want if part is None else geo.diagnose(part)
            return [(path, ref, geo.diagnose(geo.load_surface(str(path))))]
        self._start("check", job, tr("Checking {name}…", name=path.name))

    def _export_checked(self, results):
        """The check of the written files. One warning box for all files
        with a problem (each problem is also in the log)."""
        self.export_checks = [got for _p, _w, got in results]
        bad = [text for text in map(self._export_checked_one, results)
               if text]
        if bad:
            more = (tr("\n\n{n} more files have problems (see the log).",
                       n=len(bad) - 1) if len(bad) > 1 else "")
            QtWidgets.QMessageBox.warning(self, "Export check", bad[0] + more)

    def _export_checked_one(self, result) -> str:
        """Log the check of one file. Returns the warning text, or ""."""
        path, want, got = result
        self.export_check = got
        lost = [(label, fs_repair.counts(want)[attr], fs_repair.counts(got)[attr])
                for attr, label in fs_repair.COUNTS
                if fs_repair.counts(got)[attr] != fs_repair.counts(want)[attr]]
        if got.n_triangles != want.n_triangles:
            lost.append(("Triangles", want.n_triangles, got.n_triangles))
        if not lost:
            text = tr("Check of {name}: the same as the mesh", name=path.name)
            self._say(text)
            self._note(text)
            return ""
        parts = ", ".join(f"{tr(label)} {_num(a)} → {_num(b)}"
                          for label, a, b in lost)
        if path.suffix.lower() == ".stl":
            text = tr("Check of {name}: the STL file is not the same as the "
                      "mesh ({parts}). STL keeps float32 coordinates, and a "
                      "reader joins points at the same place: vertices that "
                      "the repair keeps apart become one point again.",
                      name=path.name, parts=parts)
        else:
            text = tr("Check of {name}: the file is not the same as the mesh "
                      "({parts}).", name=path.name, parts=parts)
        self._say(tr("Check of {name}: the file has problems",
                     name=path.name))
        self._note(text)
        return text

    # ------------------------------------------------------------ the 3D view
    def _show(self, reset_camera: bool):
        st = self.state
        v = self.view
        v.clear_problems()
        self._spots, self._spot_at = [], -1
        self._fill_bodies()
        if st is None:
            v.show_body(None)
            self._refresh_info()
            return
        self._show_bodies(reset=reset_camera)
        d = st.diag
        self._show_problems()
        v.btn_spot.setEnabled(bool(d.open_edges or d.flipped_faces
                                   or d.degenerate))
        self._refresh_info()
        self._sync()

    def _show_problems(self):
        """The problem layers (holes, flipped, ...), cut by the section."""
        st = self.state
        if st is None:
            return
        d = st.diag
        counts = {"holes": d.open_edges, "flip": d.flipped_faces,
                  "nm": d.non_manifold_edges, "degen": d.degenerate}
        for key, data in st.layers.items():
            self.view.show_problem(key, self._clip(data), counts[key])

    def next_problem(self):
        """Fly the camera to the next hole, flipped part or degenerate
        face, the largest first (as in OpenFOAM Studio)."""
        st = self.state
        if st is None:
            return
        if not self._spots:
            self._spots = geo.problem_spots(st.mesh, st.diag)
            self._spot_at = -1
        if not self._spots:
            self._say(tr("No problem spots found"))
            return
        self._spot_at = (self._spot_at + 1) % len(self._spots)
        spot = self._spots[self._spot_at]
        radius = spot["size"] if spot["size"] > 0 else st.diag.diagonal * 0.01
        centre = np.asarray(spot["centre"], dtype=float)
        self.view.look_at(spot["centre"], radius,
                          outward=centre - np.asarray(st.mesh.center))
        self.view.mark_spot(spot["centre"], radius)
        self._say(tr("{what} {i} of {n}", what=tr(spot["what"]).capitalize(),
                     i=self._spot_at + 1, n=len(self._spots)))

    # ------------------------------------------------------------- info panel
    def _refresh_info(self):
        st = self.state
        info = self.info
        if st is None:
            for lab in info.values():
                lab.setText("—")
            self.lbl_summary.setText("—")
            self.lbl_summary.setToolTip("")
            return
        d = st.diag
        rep = self.repaired
        d0 = rep["before"] if rep else None
        unit = self.units_text()
        f = self.factor

        def pair(fmt, a, b=None):
            if b is None or fmt(a) == fmt(b):
                return fmt(b if b is not None else a)
            return f"{fmt(a)} → {fmt(b)}"

        info["file"].setText(self.path.name if self.path else "—")
        info["file"].setToolTip(str(self.path) if self.path else "")
        if not self.unit_note:
            info["units"].setText(unit)
        elif self.unit_given:
            info["units"].setText(unit + "  (" + self.unit_note + ")")
        else:
            info["units"].setText(unit + tr("  (guessed: {note})",
                                            note=self.unit_note))
        sx, sy, sz = (s / f for s in d.size)
        info["size"].setText(f"{_real(sx)} × {_real(sy)} × {_real(sz)} {unit}")
        info["triangles"].setText(pair(_num, d0.n_triangles if d0 else d.n_triangles,
                                       d.n_triangles if d0 else None))
        names = geo.body_names(st.mesh)
        info["bodies"].setText(_num(max(1, len(names))))
        info["bodies"].setToolTip(fs_i18n.join("\n", names[:50]))
        info["parts"].setText(pair(_num, d0.parts if d0 else d.parts,
                                   d.parts if d0 else None))
        yes_no = (lambda c: tr("yes") if c else tr("no"))
        info["closed"].setText(pair(yes_no, d0.closed if d0 else d.closed,
                                    d.closed if d0 else None))
        for attr, _label in fs_repair.COUNTS:
            a = getattr(d0 if d0 else d, attr)
            b = getattr(d, attr) if d0 else None
            info[attr].setText(pair(_num, a, b))
        vol = (lambda v: f"{_real(v / f ** 3)} {unit}³")
        info["volume"].setText(pair(vol, d0.volume if d0 else d.volume,
                                    d.volume if d0 else None))
        if rep:
            info["method"].setText(fs_repair.label(rep["key"]))
            info["time"].setText(tr("{sec} s", sec=_seconds(rep["seconds"])))
            self.lbl_summary.setText(rep["summary"] or "—")
            self.lbl_summary.setToolTip(rep.get("steps") or "")
        else:
            info["method"].setText("—")
            info["time"].setText("—")
            self.lbl_summary.setText("—")

    # ---------------------------------------------------------------- language
    def set_language(self, code: str):
        self.store.setValue("language", code)
        fs_i18n.set_language(code)
        for c, act in self.act_lang.items():
            act.setChecked(c == fs_i18n.language())

    def _language_changed(self, _lang: str):
        self._fill_methods()
        self._show_level()
        self._refresh_info()

    def about(self):
        QtWidgets.QMessageBox.about(
            self, "About MeshFix Studio",
            tr("MeshFix Studio {version} repairs a triangle mesh (STL, 3MF, "
               "OBJ, PLY, OFF, glTF, VTK) with meshfix (Rust), alpha wrap, "
               "the Windows repair service (on Windows only) and the volume "
               "rebuild.\n\n"
               "Problems in the 3D view: red — holes (open edges), magenta "
               "— flipped faces, yellow — non-manifold edges, green — "
               "degenerate faces.\n\n3D: {level}\nCore: meshfix "
               "{core}\n\nLicense: GNU GPL version 3 or later. Source code: "
               "{url}", version=__version__, core=CORE_VERSION,
               level=self.lbl_3d.text(), url=SOURCE_URL))

    # ------------------------------------------------------- drag and drop
    @staticmethod
    def _dropped_file(event) -> str | None:
        files = MeshFixWindow._dropped_files(event)
        return files[0] if files else None

    @staticmethod
    def _dropped_files(event) -> list:
        md = event.mimeData()
        if not md.hasUrls():
            return []
        return [p for p in (url.toLocalFile() for url in md.urls())
                if p and Path(p).suffix.lower() in SUFFIXES]

    def dragEnterEvent(self, event):                      # noqa: N802
        if not self.busy_now and self._dropped_file(event):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):                       # noqa: N802
        self.dragEnterEvent(event)

    def dropEvent(self, event):                           # noqa: N802
        paths = self._dropped_files(event)
        if paths and self.open_files(paths):
            event.acceptProposedAction()

    # ------------------------------------------------------------------ close
    def closeEvent(self, event):                          # noqa: N802
        """Close at once, also during a repair.

        A repair in Rust cannot stop in the middle. The window does not wait
        for it and does not destroy the running thread (that is a qFatal,
        T26): the result is ignored (_closing), and run() ends the process
        with meshfix.qt.end_process after a short wait.
        """
        self._closing = True
        self.tick.stop()
        try:
            self.store.setValue("geometry", self.saveGeometry())
            self.store.sync()
        except Exception:                                 # noqa: BLE001
            pass
        if self._thread is not None and not self._thread.isRunning():
            self._end()
        try:
            self.view.plotter.close()
        except Exception:                                 # noqa: BLE001
            pass
        super().closeEvent(event)


def start_language(store: QtCore.QSettings | None = None) -> str:
    """FS_LANG, else the setting of this program, else English."""
    store = store or open_settings()
    fs_i18n.add_catalogue_dir(I18N_DIR)
    lang = fs_i18n.env_language() or str(store.value("language", "") or "")
    lang = lang if lang in fs_i18n.LANGUAGES else DEFAULT_LANGUAGE
    fs_i18n.set_language(lang)
    return lang


def run(app, win, grace_ms: int = CLOSE_GRACE_MS) -> None:
    """The event loop, then the end of the process without a qFatal: a
    repair that still runs is not waited for longer than grace_ms."""
    rc = app.exec()
    end_process(win, rc, grace_ms=grace_ms, settings=win.store)


def _stdout_for_child() -> None:
    """A frozen GUI program (console=False) starts with sys.stdout None.
    A probe child must write its result line to the pipe of the parent:
    open the standard output handle that the parent gave."""
    if sys.stdout is not None:
        return
    try:
        sys.stdout = open(1, "w", encoding="utf-8", closefd=False)
        return
    except OSError:
        pass
    if os.name == "nt":
        try:
            import ctypes
            import msvcrt
            handle = ctypes.windll.kernel32.GetStdHandle(-11)
            fd = msvcrt.open_osfhandle(handle, os.O_WRONLY)
            sys.stdout = open(fd, "w", encoding="utf-8", closefd=False)
        except OSError:
            pass


def smoke_test(win, app, src: str, out: str) -> int:
    """«--smoke-test IN OUT»: open IN, repair it with meshfix, export OUT,
    read OUT again, and write the result to OUT + ".json". Exit code 0
    when the repaired mesh is clean and the file has the same counts.
    The installers run this check on each operating system (CI)."""
    import json

    def wait(limit_s: float = 600.0) -> bool:
        end = time.monotonic() + limit_s
        while win.busy_now and time.monotonic() < end:
            app.processEvents(QtCore.QEventLoop.AllEvents, 50)
            time.sleep(0.01)
        return not win.busy_now

    res: dict = {"level": win.lbl_3d.text(), "ok": False}
    try:
        win.open_file(src)
        res["loaded"] = wait() and win.state is not None
        if res["loaded"]:
            res["before"] = fs_repair.counts(win.state.diag)
            res["repair_started"] = win.repair(fs_repair.DEFAULT)
            res["repaired"] = wait()
            res["after"] = fs_repair.counts(win.state.diag)
            res["closed"] = bool(win.state.diag.closed)
            path = win.export_file(out)
            wait()
            check = win.export_check
            res["exported"] = path is not None
            res["file"] = fs_repair.counts(check) if check else None
            res["ok"] = bool(res["repaired"] and res["closed"]
                             and fs_repair.clean(win.state.diag)
                             and res["file"] == res["after"])
    except Exception as exc:                              # noqa: BLE001
        res["error"] = f"{type(exc).__name__}: {exc}"
    with open(out + ".json", "w", encoding="utf-8") as fh:
        json.dump(res, fh, ensure_ascii=False, indent=1)
    return 0 if res["ok"] else 1


def main(argv=None):
    argv = list(sys.argv if argv is None else argv)
    from foamview import level
    if argv[1:2] == ["--foamview-probe"]:
        # A child process of foamview.level: probe one renderer and exit.
        # In the frozen program, sys.executable is this program.
        _stdout_for_child()
        sys.exit(level.probe_main(argv[2:]))
    level.configure(app_name=APP_NAME)
    own_taskbar_button()
    QtCore.QCoreApplication.setAttribute(QtCore.Qt.AA_ShareOpenGLContexts)
    app = QtWidgets.QApplication(argv)
    app.setStyle("Fusion")
    app.setApplicationName(APP_NAME)
    app.setWindowIcon(app_icon())
    start_language()
    win = MeshFixWindow()
    win.show()
    if argv[1:2] == ["--smoke-test"] and len(argv) >= 4:
        rc = smoke_test(win, app, argv[2], argv[3])
        win.close()
        end_process(win, rc, grace_ms=CLOSE_GRACE_MS, settings=win.store)
        return
    if len(argv) > 1 and os.path.isfile(argv[1]):
        win.open_file(argv[1])
    run(app, win)


if __name__ == "__main__":
    main()

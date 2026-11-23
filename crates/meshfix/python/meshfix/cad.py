"""Read a CAD file (STEP) and make a triangle mesh of it.

A STEP file (.step, .stp) has exact surfaces, not triangles. OpenCASCADE
(the Python package OCP, `pip install cadquery-ocp-novtk`) reads the file
and makes triangles on each face (BRepMesh, the method of the CAD
programs). The program then shows the mesh, repairs it and writes it in
each mesh format (STL, 3MF, OBJ...).

OCP is optional. Without it, available() is False and read_step() gives a
clear error. OCP needs about 2 s to import, thus this module imports it
only in read_step().

BODIES. Each solid of the file is a body. Its name is the name of the
part in the assembly tree of the file (an instance name, else the name of
the part). Two solids with the same name get "name 1", "name 2". A file
without solids (only surfaces) gives one body for each free shape.

UNITS. OpenCASCADE gives the coordinates in millimetres (it converts the
unit of the file). The reader gives unit_m = 0.001.

DETAIL. The size of the triangles comes from two limits of BRepMesh: the
largest distance between a triangle and the exact surface (linear
deflection, a fraction of the model size) and the largest angle between
the normals of two adjacent triangles (angular deflection). DETAIL has
the levels; the default is "normal".

PROGRESS. The read of the file and the transfer give no percent (the OCP
package cannot report the progress of OpenCASCADE to Python): the caller
shows a busy bar with the name of the step. The mesh of the bodies gives
a percent: progress(text, fraction).
"""

from __future__ import annotations

import importlib.util
import os
from dataclasses import dataclass

import numpy as np

from .i18n import tr

SUFFIXES = (".step", ".stp")


@dataclass(frozen=True)
class Detail:
    """One level of detail. linear: the largest distance between the mesh
    and the exact surface, as a fraction of the diagonal of the model.
    angular: the largest angle between adjacent triangles, in degrees."""
    key: str
    label: str
    linear: float
    angular: float


DETAILS = {d.key: d for d in (
    Detail("coarse", "Coarse", 1e-3, 30.0),
    Detail("normal", "Normal", 2e-4, 15.0),
    Detail("fine", "Fine", 5e-5, 8.0),
    Detail("very_fine", "Very fine", 1.5e-5, 4.0),
)}
DEFAULT_DETAIL = "normal"

# The level of detail of the next read. The programs set it (a setting).
detail = DEFAULT_DETAIL


def available() -> bool:
    """True when the OCP package (OpenCASCADE) is installed."""
    try:
        return importlib.util.find_spec("OCP") is not None
    except (ImportError, ValueError):
        return False


def is_cad(path) -> bool:
    """True for a file name with a STEP suffix."""
    return os.path.splitext(str(path))[1].lower() in SUFFIXES


def deflection(diagonal: float, key: str | None = None) -> tuple:
    """(linear in mm, angular in radians) for a model with this diagonal
    (mm) and a level of DETAILS."""
    d = DETAILS.get(key or detail, DETAILS[DEFAULT_DETAIL])
    lin = max(diagonal, 1e-6) * d.linear
    return lin, np.radians(d.angular)


def _label_name(label) -> str:
    from OCP.TDataStd import TDataStd_Name
    attr = TDataStd_Name()
    if label.FindAttribute(TDataStd_Name.GetID_s(), attr):
        return attr.Get().ToExtString().strip()
    return ""


def _quiet() -> None:
    """No messages of OpenCASCADE on the console (the statistics of the
    STEP transfer, the syntax notes of the parser)."""
    try:
        from OCP.Message import Message, Message_PrinterOStream
        Message.DefaultMessenger_s().RemovePrinters(
            Message_PrinterOStream.get_type_descriptor_s())
    except Exception:                                     # noqa: BLE001
        pass


def _label_sequence():
    """An empty sequence of labels (OCP 8: OCP.OCP.collections, OCP 7:
    OCP.TDF.TDF_LabelSequence)."""
    try:
        from OCP.OCP.collections import Sequence_TDF_Label
        return Sequence_TDF_Label()
    except ImportError:
        from OCP.TDF import TDF_LabelSequence
        return TDF_LabelSequence()


def _collect(doc) -> list:
    """[(name, TopoDS_Shape)] with one item for each solid of the
    document, in the place of the assembly (the location applied)."""
    from OCP.TopAbs import TopAbs_SOLID
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopLoc import TopLoc_Location
    from OCP.XCAFDoc import XCAFDoc_DocumentTool, XCAFDoc_ShapeTool

    tool = XCAFDoc_DocumentTool.ShapeTool_s(doc.Main())
    out = []

    def solids(shape, name: str):
        found = []
        exp = TopExp_Explorer(shape, TopAbs_SOLID)
        while exp.More():
            found.append(exp.Current())
            exp.Next()
        # No solid (surfaces only, or a mesh saved as STEP): the shape is
        # one body.
        for s in found or [shape]:
            out.append((name, s))

    def walk(label, loc, name: str):
        own = _label_name(label)
        if XCAFDoc_ShapeTool.IsAssembly_s(label):
            comps = _label_sequence()
            XCAFDoc_ShapeTool.GetComponents_s(label, comps, False)
            for i in range(1, comps.Length() + 1):
                comp = comps.Value(i)
                ref = comp.__class__()
                if not XCAFDoc_ShapeTool.GetReferredShape_s(comp, ref):
                    continue
                cloc = loc.Multiplied(XCAFDoc_ShapeTool.GetLocation_s(comp))
                walk(ref, cloc, _label_name(comp) or _label_name(ref)
                     or own or name)
        else:
            shape = XCAFDoc_ShapeTool.GetShape_s(label)
            if shape.IsNull():
                return
            solids(shape.Moved(loc), own or name)

    free = _label_sequence()
    tool.GetFreeShapes(free)
    for i in range(1, free.Length() + 1):
        walk(free.Value(i), TopLoc_Location(), "")
    return out


def _bbox_diagonal(shapes) -> float:
    from OCP.Bnd import Bnd_Box
    from OCP.BRepBndLib import BRepBndLib
    box = Bnd_Box()
    for _name, s in shapes:
        BRepBndLib.Add_s(s, box)
    if box.IsVoid():
        return 0.0
    a, b = box.CornerMin(), box.CornerMax()
    return float(a.Distance(b))


def _matrix(loc) -> np.ndarray:
    t = loc.Transformation()
    return np.array([[t.Value(r, c) for c in range(1, 5)]
                     for r in range(1, 4)], np.float64)


def _triangles(shape) -> tuple:
    """(points (N, 3), triangles (M, 3)) of a shape after BRepMesh. The
    faces have their own points: the points on a shared edge are at the
    same place, and _merge() joins them."""
    from OCP.BRep import BRep_Tool
    from OCP.TopAbs import TopAbs_FACE, TopAbs_REVERSED
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopLoc import TopLoc_Location
    from OCP.TopoDS import TopoDS

    # OCP 8: TopoDS.Face, OCP 7: TopoDS.Face_s.
    to_face = getattr(TopoDS, "Face_s", None) or TopoDS.Face
    pts, tris, base = [], [], 0
    exp = TopExp_Explorer(shape, TopAbs_FACE)
    while exp.More():
        face = to_face(exp.Current())
        exp.Next()
        loc = TopLoc_Location()
        tri = BRep_Tool.Triangulation_s(face, loc)
        if tri is None:
            continue
        n, m = tri.NbNodes(), tri.NbTriangles()
        if n == 0 or m == 0:
            continue
        p = np.array([tri.Node(i).Coord() for i in range(1, n + 1)],
                     np.float64)
        if not loc.IsIdentity():
            mat = _matrix(loc)
            p = p @ mat[:, :3].T + mat[:, 3]
        t = np.array([tri.Triangle(i).Get() for i in range(1, m + 1)],
                     np.int64)
        t -= 1
        if face.Orientation() == TopAbs_REVERSED:
            t = t[:, ::-1]
        pts.append(p)
        tris.append(t + base)
        base += n
    if not pts:
        return np.zeros((0, 3)), np.zeros((0, 3), np.int64)
    return np.vstack(pts), np.vstack(tris)


def _merge(points: np.ndarray, tris: np.ndarray, tol: float) -> tuple:
    """Join the points nearer than `tol` (on a grid of size tol) and remove
    the triangles that then have two equal corners."""
    if not len(points):
        return points, tris
    key = np.round(points / tol).astype(np.int64)
    _u, first, inv = np.unique(key, axis=0, return_index=True,
                               return_inverse=True)
    inv = inv.reshape(-1)
    t = inv[tris]
    ok = (t[:, 0] != t[:, 1]) & (t[:, 1] != t[:, 2]) & (t[:, 0] != t[:, 2])
    return points[first], t[ok]


# The part of the percent bar for BRepMesh (the rest: the triangles to
# numpy). Measured on an assembly with 725 solids: 5 s and 7 s.
MESH_SHARE = 0.45
# BRepMesh runs on a compound of bodies with about this number of faces:
# the faces of one compound go in parallel, and the percent goes up after
# each compound.
CHUNK_FACES = 2000


def _mesh(shapes, lin: float, ang: float, on_fraction) -> None:
    """BRepMesh on all shapes (the triangles stay in the faces)."""
    from OCP.BRep import BRep_Builder
    from OCP.BRepMesh import BRepMesh_IncrementalMesh
    from OCP.TopAbs import TopAbs_FACE
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopoDS import TopoDS_Compound

    def faces(shape) -> int:
        n, exp = 0, TopExp_Explorer(shape, TopAbs_FACE)
        while exp.More():
            n += 1
            exp.Next()
        return n

    counts = [faces(s) for _n, s in shapes]
    total = max(1, sum(counts))
    done, i = 0, 0
    on_fraction(0.0)
    while i < len(shapes):
        builder, comp, n = BRep_Builder(), TopoDS_Compound(), 0
        builder.MakeCompound(comp)
        while i < len(shapes) and (n == 0 or n + counts[i] <= CHUNK_FACES):
            builder.Add(comp, shapes[i][1])
            n += counts[i]
            i += 1
        BRepMesh_IncrementalMesh(comp, lin, False, ang, True)
        done += n
        on_fraction(done / total)


def read_step(path, progress=None, level: str | None = None):
    """Read a STEP file. Gives meshfix.formats.Data (one Part for each
    solid, unit_m = 0.001). progress(text, fraction or None) reports the
    steps. RuntimeError when OCP is missing or the file cannot be read."""
    from .formats import Data, Part

    def say(text, frac=None):
        if progress is not None:
            progress(text, frac)

    if not available():
        raise RuntimeError(tr(
            "To open a STEP file, the program needs OpenCASCADE (the "
            "Python package cadquery-ocp-novtk). It is not installed."))
    name = os.path.basename(str(path))
    say(tr("Reading the STEP file {name}…", name=name))
    from OCP.IFSelect import IFSelect_RetDone
    from OCP.STEPCAFControl import STEPCAFControl_Reader
    from OCP.TCollection import TCollection_ExtendedString
    from OCP.TDocStd import TDocStd_Document
    from OCP.XCAFApp import XCAFApp_Application
    from OCP.XCAFDoc import XCAFDoc_DocumentTool

    _quiet()
    app = XCAFApp_Application.GetApplication_s()
    doc = TDocStd_Document(TCollection_ExtendedString("MDTV-XCAF"))
    app.InitDocument(doc)
    # Millimetres in the document: the reader converts the file to them.
    XCAFDoc_DocumentTool.SetLengthUnit_s(doc, 0.001)
    reader = STEPCAFControl_Reader()
    reader.SetNameMode(True)
    reader.SetColorMode(False)
    reader.SetLayerMode(False)
    if reader.ReadFile(str(path)) != IFSelect_RetDone:
        raise RuntimeError(tr("The file {name} is not a STEP file, or it "
                              "is damaged.", name=name))
    say(tr("Making the solids of {name}…", name=name))
    if not reader.Transfer(doc):
        raise RuntimeError(tr("The file {name} has no shape that the "
                              "program can read.", name=name))
    shapes = _collect(doc)
    if not shapes:
        raise RuntimeError(tr("The file {name} has no solid and no "
                              "surface.", name=name))

    diag = _bbox_diagonal(shapes)
    lin, ang = deflection(diag, level)
    _mesh(shapes, lin, ang, lambda f: say(
        tr("Making triangles: {pct} %", pct=int(f * 100)), MESH_SHARE * f))
    tol = max(diag * 1e-9, 1e-9)
    parts, seen, total = [], {}, len(shapes)
    for i, (pname, shape) in enumerate(shapes):
        say(tr("Collecting the triangles: body {i} of {n}", i=i + 1,
               n=total), MESH_SHARE + (1 - MESH_SHARE) * i / total)
        p, t = _merge(*_triangles(shape), tol)
        if not len(t):
            continue
        pname = pname or os.path.splitext(name)[0]
        seen[pname] = seen.get(pname, 0) + 1
        parts.append(Part(pname, p, t))
    say(tr("Collecting the triangles: body {i} of {n}", i=total, n=total),
        1.0)
    if not parts:
        raise RuntimeError(tr("OpenCASCADE made no triangles for the file "
                              "{name}.", name=name))
    # The same name two or more times: "name 1", "name 2"…
    count = {}
    for part in parts:
        if seen[part.name] > 1:
            count[part.name] = count.get(part.name, 0) + 1
            part.name = f"{part.name} {count[part.name]}"
    return Data(parts, unit_m=0.001)

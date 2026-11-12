"""The file formats of a triangle mesh: read and write.

meshfix.check has the tables READERS and WRITERS (suffix -> function) and
the calls load_surface() and save_mesh(). This module has the formats.

FORMATS (read and write):

| key        | file            | unit in the file | bodies          | coordinates |
|------------|-----------------|------------------|-----------------|-------------|
| stl        | binary STL      | none             | one             | float32     |
| stl_ascii  | ASCII STL       | none             | `solid` blocks  | float32     |
| 3mf        | 3MF             | yes (we write mm)| objects         | text        |
| obj        | Wavefront OBJ   | none             | `o` objects     | text        |
| ply        | binary PLY      | none             | one             | float64     |
| ply_ascii  | ASCII PLY       | none             | one             | text        |
| off        | OFF             | none             | one             | text        |
| glb, gltf  | glTF 2.0        | metres (spec)    | nodes           | float32     |
| vtp, vtk   | VTK XML, legacy | none             | cell array      | float64     |

BODIES. A body is a named object of the file: a 3MF object (a build item),
an OBJ object, a `solid` block of an ASCII STL, a glTF node with a mesh.
A mesh with bodies has the cell array BODY (the body index of each
triangle) and the field array BODY_NAMES (the names). split_bodies() and
join_bodies() go between one mesh and a list of bodies. A format without
bodies gets one merged body (Format.bodies is False).

UNITS. Both programs keep a mesh in metres. A format with a unit (3MF,
glTF) gives its unit to the reader: the field array UNIT (metres per unit
of the file), and meshfix.check.guess_scale() uses it. The writers of 3MF
write millimetres (the unit of the slicers), glTF writes metres. The other
formats keep no unit: save_mesh() writes them in the unit that the
program gives (unit_m, metres per unit of the file).

STL-SAFE OUTPUT. STL keeps float32 coordinates and no topology: a reader
joins the points at the same place. save_mesh() applies the step
stl_safe_output of the repair (meshfix._native.stl_safe) to the file
coordinates before it writes an STL (Format.stl_safe). glTF keeps an index
for each point (no point is joined), but its coordinates are float32 too:
the rounding made 3 faces of a large aircraft model degenerate (measured
2026-11-12). Thus glTF gets the step too. The other formats keep the
index of each point and float64 or text coordinates: their points are
written as they are.

glTF is "Y up". The models of CAD programs and slicers are "Z up". The
glTF writer turns the model (x, y, z) -> (x, z, -y) and the reader turns it
back, as other programs do (Blender, for example).

Only numpy, pyvista (VTK) and the standard library: the readers and
writers of 3MF, OBJ, PLY, OFF and glTF are in this module, the binary STL
reader and the VTK formats are VTK. Each format works on each operating
system and in the frozen program.
"""

from __future__ import annotations

import base64
import json
import os
import re
import struct
import zipfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from xml.sax.saxutils import escape, quoteattr

import numpy as np
import pyvista as pv

from .i18n import tr

BODY = "meshfix_body"              # cell data: the body index (int32)
BODY_NAMES = "meshfix_body_names"  # field data: the names of the bodies
UNIT = "meshfix_unit_m"            # field data: metres per unit of the file

APP = "MeshFix Studio"
NUM = "%.15g"                      # coordinates of the text formats


# ------------------------------------------------------------- the bodies
@dataclass
class Part:
    """One body: a name, points (N, 3) float64 and triangles (M, 3) int64."""
    name: str
    points: np.ndarray
    tris: np.ndarray


@dataclass
class Data:
    """What a reader gives: the bodies and, if the file has one, its unit
    (metres per unit of the file)."""
    parts: list = field(default_factory=list)
    unit_m: float | None = None


def _tris_of(mesh: pv.PolyData) -> np.ndarray:
    faces = np.asarray(mesh.faces)
    if faces.size and (faces.size % 4 or not np.all(faces[::4] == 3)):
        mesh = mesh.triangulate()
        faces = np.asarray(mesh.faces)
    return faces.reshape(-1, 4)[:, 1:].astype(np.int64)


def _poly(points, tris) -> pv.PolyData:
    tris = np.asarray(tris, np.int64).reshape(-1, 3)
    cells = np.hstack([np.full((len(tris), 1), 3, np.int64), tris]).ravel()
    return pv.PolyData(np.asarray(points, np.float64), cells)


def body_names(mesh) -> list:
    """The names of the bodies of `mesh` ([] when it has no body array)."""
    if mesh is None or BODY not in mesh.cell_data:
        return []
    ids = np.asarray(mesh.cell_data[BODY])
    n = int(ids.max()) + 1 if ids.size else 0
    names = []
    if BODY_NAMES in mesh.field_data:
        names = [str(s) for s in np.asarray(mesh.field_data[BODY_NAMES])]
    return [names[i] if i < len(names) and names[i] else
            tr("body {i}", i=i + 1) for i in range(n)]


def body_count(mesh) -> int:
    """The number of bodies (1 for a mesh without the body array)."""
    return max(1, len(body_names(mesh)))


def split_bodies(mesh: pv.PolyData) -> list:
    """[(name, PolyData)] with one item for each body of `mesh`. A mesh
    without the body array is one body with the name ''. The meshes have
    only the points and the triangles (no arrays)."""
    names = body_names(mesh)
    if len(names) <= 1:
        return [(names[0] if names else "", mesh)]
    ids = np.asarray(mesh.cell_data[BODY])
    tris = _tris_of(mesh)
    pts = np.asarray(mesh.points, np.float64)
    out = []
    for i, name in enumerate(names):
        t = tris[ids == i]
        if not len(t):
            continue
        used, local = np.unique(t.ravel(), return_inverse=True)
        out.append((name, _poly(pts[used], local.reshape(-1, 3))))
    return out


def join_bodies(parts) -> pv.PolyData:
    """One mesh from [(name, PolyData)], with the body array and the names.
    The points of the bodies stay apart (no merge)."""
    parts = [(n, m) for n, m in parts if m is not None and m.n_cells]
    if not parts:
        return pv.PolyData()
    pts, tris, ids, off = [], [], [], 0
    for i, (_name, m) in enumerate(parts):
        t = _tris_of(m)
        pts.append(np.asarray(m.points, np.float64))
        tris.append(t + off)
        ids.append(np.full(len(t), i, np.int32))
        off += m.n_points
    out = _poly(np.vstack(pts), np.vstack(tris))
    out.cell_data[BODY] = np.concatenate(ids)
    out.field_data[BODY_NAMES] = np.array([str(n) for n, _m in parts])
    return out


def to_polydata(data: Data) -> pv.PolyData:
    """The mesh of a reader result: the bodies, their names, the unit."""
    parts = [p for p in data.parts if len(p.tris)]
    if not parts:
        mesh = pv.PolyData(np.zeros((0, 3)))
    else:
        mesh = join_bodies([(p.name, _poly(p.points, p.tris)) for p in parts])
    if data.unit_m:
        mesh.field_data[UNIT] = np.array([float(data.unit_m)])
    return mesh


def _parts_of(mesh, stem: str) -> list:
    """[Part] of a mesh: the bodies, with a name for each."""
    out = []
    bodies = split_bodies(mesh)
    for i, (name, m) in enumerate(bodies, 1):
        if not name:
            name = stem if len(bodies) == 1 else f"{stem}_{i}"
        out.append(Part(name, np.asarray(m.points, np.float64), _tris_of(m)))
    return out


def _merged(parts: list, name: str) -> Part:
    if len(parts) == 1:
        return parts[0]
    pts, tris, off = [], [], 0
    for p in parts:
        pts.append(p.points)
        tris.append(p.tris + off)
        off += len(p.points)
    return Part(name, np.vstack(pts), np.vstack(tris))


def _fan(poly: list) -> list:
    """Triangles of a polygon (a fan from the first vertex)."""
    return [(poly[0], poly[k], poly[k + 1]) for k in range(1, len(poly) - 1)]


def _text(path) -> str:
    with open(path, "rb") as f:
        return f.read().decode("utf-8", errors="replace")


# -------------------------------------------------------------------- STL
def is_binary_stl(path) -> bool:
    """True when the size of the file is the size of a binary STL with the
    triangle count of its header. An ASCII STL starts with "solid", but
    some programs write "solid" into the header of a binary STL too."""
    size = os.path.getsize(path)
    if size < 84:
        return False
    with open(path, "rb") as f:
        f.seek(80)
        n = struct.unpack("<I", f.read(4))[0]
    return size == 84 + 50 * n


def read_stl(path):
    """Binary STL: the VTK reader (equal points are joined). ASCII STL:
    each `solid` block is a body with its name; equal points are joined,
    as VTK does."""
    if is_binary_stl(path):
        return pv.read(str(path))
    text = _text(path)
    starts = [(m.start(), m.group(1).strip())
              for m in re.finditer(r"^[ \t]*solid\b[ \t]*([^\r\n]*)", text,
                                   re.MULTILINE)]
    if not starts:
        return pv.read(str(path))
    vert = re.compile(r"vertex\s+(\S+)\s+(\S+)\s+(\S+)")
    raw = []
    for k, (pos, name) in enumerate(starts):
        end = starts[k + 1][0] if k + 1 < len(starts) else len(text)
        v = np.array(vert.findall(text, pos, end), dtype=np.float64)
        v = v[: len(v) // 3 * 3]
        if len(v):
            raw.append((name, v))
    if not raw:
        return pv.read(str(path))
    allv = np.vstack([v for _n, v in raw])
    pts, inv = np.unique(allv, axis=0, return_inverse=True)
    inv = inv.reshape(-1)
    parts, off = [], 0
    for i, (name, v) in enumerate(raw, 1):
        t = inv[off: off + len(v)].reshape(-1, 3)
        off += len(v)
        parts.append(Part(name or tr("body {i}", i=i), pts, t))
    # One point list for all bodies (the reader joins points of different
    # solids, as VTK does).
    return _shared_points(parts)


def _shared_points(parts: list) -> pv.PolyData:
    """A mesh of bodies that share one point list (Part.points is the same
    array for each part)."""
    pts = parts[0].points
    tris = np.vstack([p.tris for p in parts])
    mesh = _poly(pts, tris)
    mesh.cell_data[BODY] = np.concatenate(
        [np.full(len(p.tris), i, np.int32) for i, p in enumerate(parts)])
    mesh.field_data[BODY_NAMES] = np.array([p.name for p in parts])
    return mesh


def _normals(p: np.ndarray, t: np.ndarray) -> np.ndarray:
    a, b, c = p[t[:, 0]], p[t[:, 1]], p[t[:, 2]]
    n = np.cross(b - a, c - a)
    length = np.linalg.norm(n, axis=1, keepdims=True)
    return np.divide(n, length, out=np.zeros_like(n), where=length > 0)


def write_stl_binary(path, parts: list, unit: str) -> None:
    part = _merged(parts, parts[0].name)
    p32 = part.points.astype(np.float32)
    t = part.tris
    rec = np.zeros(len(t), dtype=[("n", "<f4", 3), ("v", "<f4", (3, 3)),
                                  ("a", "<u2")])
    rec["n"] = _normals(p32.astype(np.float64), t)
    rec["v"] = p32[t]
    head = f"{APP} binary STL, unit {unit or '?'}".encode("ascii", "replace")
    with open(path, "wb") as f:
        f.write(head[:80].ljust(80, b" "))
        f.write(struct.pack("<I", len(t)))
        f.write(rec.tobytes())


def _stl_name(name: str) -> str:
    return re.sub(r"\s+", "_", name.strip()) or "body"


def write_stl_ascii(path, parts: list, unit: str) -> None:
    """One `solid` block for each body. The coordinates are float32 values
    with 9 digits: each reader gets the same float32 numbers."""
    fmt = ("  facet normal %.9g %.9g %.9g\n    outer loop\n"
           "      vertex %.9g %.9g %.9g\n      vertex %.9g %.9g %.9g\n"
           "      vertex %.9g %.9g %.9g\n    endloop\n  endfacet\n")
    with open(path, "w", encoding="ascii", newline="\n") as f:
        for part in parts:
            name = _stl_name(part.name)
            p32 = part.points.astype(np.float32).astype(np.float64)
            t = part.tris
            n = _normals(p32, t).astype(np.float32).astype(np.float64)
            rows = np.hstack([n, p32[t].reshape(-1, 9)]).tolist()
            f.write(f"solid {name}\n")
            f.write("".join([fmt % tuple(r) for r in rows]))
            f.write(f"endsolid {name}\n")


# -------------------------------------------------------------------- OBJ
def read_obj(path):
    """Wavefront OBJ: `v` and `f` (polygons become triangle fans, negative
    indices count from the end). Each `o` is a body; a file without `o`
    takes its `g` groups as the bodies. The bodies with the same name are
    one body."""
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        lines = f.read().splitlines()
    split = "o" if any(s.startswith("o ") or s == "o" for s in lines) else "g"
    verts: list = []
    bodies: dict = {}                     # name -> [triangles]
    cur = None
    for line in lines:
        if not line or line[0] not in "vfog":
            continue
        words = line.split()
        head = words[0] if words else ""
        if head == "v":
            verts.append((float(words[1]), float(words[2]), float(words[3])))
        elif head == "f":
            n = len(verts)
            idx = []
            for tok in words[1:]:
                i = int(tok.split("/", 1)[0])
                idx.append(i - 1 if i > 0 else n + i)
            if cur is None:
                cur = bodies.setdefault("", [])
            if len(idx) == 3:
                cur.append(idx)
            else:
                cur.extend(_fan(idx))
        elif head == split:
            cur = bodies.setdefault(" ".join(words[1:]), [])
    pts = np.asarray(verts, np.float64).reshape(-1, 3)
    parts = [Part(name or tr("body {i}", i=k), pts,
                  np.asarray(tris, np.int64).reshape(-1, 3))
             for k, (name, tris) in enumerate(
                 [(n, t) for n, t in bodies.items() if t], 1)]
    if not parts:
        return pv.PolyData(pts)
    return _shared_points(parts)

def _rows(fmt: str, arr: np.ndarray) -> str:
    return "".join([fmt % tuple(r) for r in arr.tolist()])


def write_obj(path, parts: list, unit: str) -> None:
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(f"# {APP}\n# unit: {unit or '?'} (OBJ keeps no unit)\n")
        off = 1
        for part in parts:
            f.write(f"o {part.name.strip() or 'body'}\n")
            f.write(_rows(f"v {NUM} {NUM} {NUM}\n", part.points))
            f.write(_rows("f %d %d %d\n", part.tris + off))
            off += len(part.points)


# -------------------------------------------------------------------- PLY
_PLY_TYPES = {"char": "i1", "int8": "i1", "uchar": "u1", "uint8": "u1",
              "short": "i2", "int16": "i2", "ushort": "u2", "uint16": "u2",
              "int": "i4", "int32": "i4", "uint": "u4", "uint32": "u4",
              "float": "f4", "float32": "f4", "double": "f8",
              "float64": "f8"}


def _ply_header(f):
    """(format, [(element, count, [(name, type, list count type)])],
    header size)."""
    if f.readline().strip() != b"ply":
        raise ValueError("no ply")
    fmt, elements = None, []
    while True:
        line = f.readline()
        if not line:
            raise ValueError("no end_header")
        words = line.decode("ascii", "replace").split()
        if not words or words[0] in ("comment", "obj_info"):
            continue
        if words[0] == "format":
            fmt = words[1]
        elif words[0] == "element":
            elements.append((words[1], int(words[2]), []))
        elif words[0] == "property":
            if words[1] == "list":
                elements[-1][2].append((words[4], words[3], words[2]))
            else:
                elements[-1][2].append((words[2], words[1], None))
        elif words[0] == "end_header":
            return fmt, elements, f.tell()


def read_ply(path):
    """PLY: ASCII and binary, with float64 coordinates (the VTK reader gives
    float32). An unusual file goes to the VTK reader."""
    try:
        return _read_ply(path)
    except (ValueError, KeyError, IndexError, struct.error):
        return pv.read(str(path))


def _read_ply(path):
    with open(path, "rb") as f:
        fmt, elements, start = _ply_header(f)
        data = f.read()
    pts = tris = None
    if fmt == "ascii":
        tokens = data.decode("ascii", "replace").split()
        at = 0
        for name, count, props in elements:
            if name == "vertex":
                if any(p[2] for p in props):
                    raise ValueError("list in vertex")
                k = len(props)
                arr = np.array(tokens[at: at + count * k], dtype=np.float64)
                arr = arr.reshape(count, k)
                at += count * k
                cols = [p[0] for p in props]
                pts = arr[:, [cols.index("x"), cols.index("y"),
                              cols.index("z")]]
            elif name == "face":
                out = []
                for _ in range(count):
                    for pname, _t, lst in props:
                        if lst:
                            n = int(tokens[at])
                            idx = [int(x) for x in tokens[at + 1: at + 1 + n]]
                            at += 1 + n
                            if pname in ("vertex_indices", "vertex_index"):
                                out.extend(_fan(idx))
                        else:
                            at += 1
                tris = np.asarray(out, np.int64).reshape(-1, 3)
            else:
                if any(p[2] for p in props):
                    raise ValueError("list in other element")
                at += count * len(props)
    elif fmt in ("binary_little_endian", "binary_big_endian"):
        end = "<" if fmt == "binary_little_endian" else ">"
        at = 0
        for name, count, props in elements:
            lists = [p for p in props if p[2]]
            if not lists:
                dt = np.dtype([(p[0], end + _PLY_TYPES[p[1]]) for p in props])
                arr = np.frombuffer(data, dt, count, at)
                at += count * dt.itemsize
                if name == "vertex":
                    pts = np.stack([arr["x"], arr["y"], arr["z"]], 1
                                   ).astype(np.float64)
                continue
            if name != "face" or len(props) != 1:
                raise ValueError("unusual list element")
            pname, itype, ctype = props[0]
            cdt = np.dtype(end + _PLY_TYPES[ctype])
            idt = np.dtype(end + _PLY_TYPES[itype])
            # The usual case: all faces are triangles.
            row = np.dtype([("n", cdt), ("i", idt, 3)])
            if count == 0:
                tris = np.zeros((0, 3), np.int64)
                continue
            if at + count * row.itemsize <= len(data):
                arr = np.frombuffer(data, row, count, at)
                if np.all(arr["n"] == 3):
                    tris = arr["i"].astype(np.int64)
                    at += count * row.itemsize
                    continue
            out = []
            for _ in range(count):
                n = int(np.frombuffer(data, cdt, 1, at)[0])
                at += cdt.itemsize
                idx = np.frombuffer(data, idt, n, at).astype(np.int64)
                at += n * idt.itemsize
                out.extend(_fan(list(idx)))
            tris = np.asarray(out, np.int64).reshape(-1, 3)
    else:
        raise ValueError(f"PLY format {fmt}")
    if pts is None:
        raise ValueError("no vertices")
    if tris is None:
        return pv.PolyData(pts)
    return _poly(pts, tris)


def _ply_head(fmt: str, part: Part, unit: str) -> str:
    return (f"ply\nformat {fmt} 1.0\ncomment {APP}\n"
            f"comment unit: {unit or '?'} (PLY keeps no unit)\n"
            f"element vertex {len(part.points)}\n"
            "property double x\nproperty double y\nproperty double z\n"
            f"element face {len(part.tris)}\n"
            "property list uchar int vertex_indices\nend_header\n")


def write_ply_binary(path, parts: list, unit: str) -> None:
    part = _merged(parts, parts[0].name)
    rows = np.zeros(len(part.tris), dtype=[("n", "u1"), ("i", "<i4", 3)])
    rows["n"] = 3
    rows["i"] = part.tris
    with open(path, "wb") as f:
        f.write(_ply_head("binary_little_endian", part, unit).encode("ascii"))
        f.write(np.ascontiguousarray(part.points, "<f8").tobytes())
        f.write(rows.tobytes())


def write_ply_ascii(path, parts: list, unit: str) -> None:
    part = _merged(parts, parts[0].name)
    with open(path, "w", encoding="ascii", newline="\n") as f:
        f.write(_ply_head("ascii", part, unit))
        f.write(_rows(f"{NUM} {NUM} {NUM}\n", part.points))
        f.write(_rows("3 %d %d %d\n", part.tris))


# -------------------------------------------------------------------- OFF
def read_off(path):
    """OFF (also COFF, NOFF...): the vertices and the faces; polygons become
    triangle fans, the colours of a face are skipped. Comments start
    with #."""
    lines = [s.split("#", 1)[0].split() for s in _text(path).splitlines()]
    lines = [w for w in lines if w]
    if not lines or not lines[0][0].endswith("OFF"):
        raise ValueError(tr("{name} is not an OFF file.",
                            name=os.path.basename(str(path))))
    counts = lines[0][1:] if len(lines[0]) > 1 else lines[1]
    at = 1 if len(lines[0]) > 1 else 2
    nv, nf = int(counts[0]), int(counts[1])
    v = np.array([w[:3] for w in lines[at: at + nv]], dtype=np.float64)
    tris = []
    for w in lines[at + nv: at + nv + nf]:
        n = int(w[0])
        tris.extend(_fan([int(x) for x in w[1: 1 + n]]))
    return _poly(v.reshape(-1, 3), np.asarray(tris, np.int64))

def write_off(path, parts: list, unit: str) -> None:
    part = _merged(parts, parts[0].name)
    with open(path, "w", encoding="ascii", newline="\n") as f:
        f.write(f"OFF\n# {APP}\n# unit: {unit or '?'} (OFF keeps no unit)\n")
        f.write(f"{len(part.points)} {len(part.tris)} 0\n")
        f.write(_rows(f"{NUM} {NUM} {NUM}\n", part.points))
        f.write(_rows("3 %d %d %d\n", part.tris))


# -------------------------------------------------------------------- 3MF
NS_3MF = "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"
NS_PROD = "http://schemas.microsoft.com/3dmanufacturing/production/2015/06"
UNITS_3MF = {"micron": 1e-6, "millimeter": 1e-3, "centimeter": 1e-2,
             "inch": 0.0254, "foot": 0.3048, "meter": 1.0}


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _attr(el, name: str):
    """An attribute without its namespace (p:path, path)."""
    for key, value in el.attrib.items():
        if _local(key) == name:
            return value
    return None


def _matrix(text) -> np.ndarray:
    """A 3MF transform "m00 m01 m02 m10 ... m32" as a 4x4 matrix for
    column vectors."""
    m = np.eye(4)
    if text:
        v = [float(x) for x in text.split()]
        if len(v) == 12:
            m[:3, :3] = np.array(v[:9]).reshape(3, 3).T
            m[:3, 3] = v[9:12]
    return m


def _apply(m: np.ndarray, pts: np.ndarray) -> np.ndarray:
    return pts @ m[:3, :3].T + m[:3, 3]


def read_3mf(path):
    """3MF: each build item is a body (the name of its object). Components
    (also in other model files of the package, as Bambu Studio and
    OrcaSlicer write them) and the transforms are applied. The unit of the
    model goes to the field array UNIT."""
    with zipfile.ZipFile(path) as z:
        names = {n.lower().lstrip("/"): n for n in z.namelist()}
        root = _start_part(z, names)
        models: dict = {}

        def model(part: str):
            key = part.lower().lstrip("/")
            if key not in models:
                if key not in names:
                    raise ValueError(tr("3MF: the part {part} is missing.",
                                        part=part))
                models[key] = ET.fromstring(z.read(names[key]))
            return models[key]

        top = model(root)
        unit_m = UNITS_3MF.get(top.get("unit", "millimeter"), 1e-3)
        settings = _bambu_names(z, names)
        cache: dict = {}

        def objects_of(part: str) -> dict:
            key = part.lower().lstrip("/")
            if key not in cache:
                cache[key] = {o.get("id"): o for o in model(part).iter()
                              if _local(o.tag) == "object"}
            return cache[key]

        def geometry(part: str, oid: str, m: np.ndarray, depth=0):
            """[(points, tris)] of an object, in the frame of the item."""
            obj = objects_of(part).get(oid)
            if obj is None or depth > 16:
                return []
            out = []
            for child in obj:
                tag = _local(child.tag)
                if tag == "mesh":
                    p, t = _mesh_3mf(child)
                    if len(t):
                        out.append((_apply(m, p), t))
                elif tag == "components":
                    for c in child:
                        if _local(c.tag) != "component":
                            continue
                        sub = _attr(c, "path") or part
                        out.extend(geometry(sub, c.get("objectid"),
                                            m @ _matrix(c.get("transform")),
                                            depth + 1))
            return out

        parts = []
        objs = objects_of(root)
        items = [el for el in top.iter() if _local(el.tag) == "item"]
        if not items:                    # no build: each mesh object
            items = [ET.Element("item", objectid=k) for k in objs]
        for k, item in enumerate(items, 1):
            oid = item.get("objectid")
            sub = _attr(item, "path") or root
            pieces = geometry(sub, oid, _matrix(item.get("transform")))
            if not pieces:
                continue
            obj = objects_of(sub).get(oid)
            name = ((obj.get("name") if obj is not None else None)
                    or settings.get(oid) or tr("object {i}", i=k))
            pts, tris, off = [], [], 0
            for p, t in pieces:
                pts.append(p)
                tris.append(t + off)
                off += len(p)
            parts.append(Part(name, np.vstack(pts), np.vstack(tris)))
    return to_polydata(Data(parts, unit_m))


def _start_part(z, names) -> str:
    """The path of the main model: the start part of _rels/.rels."""
    rels = names.get("_rels/.rels")
    if rels:
        for el in ET.fromstring(z.read(rels)).iter():
            if (_local(el.tag) == "Relationship"
                    and el.get("Type", "").endswith("/3dmodel")):
                return el.get("Target", "/3D/3dmodel.model")
    for key, real in names.items():
        if key.endswith(".model"):
            return real
    raise ValueError(tr("3MF: the package has no model."))


def _bambu_names(z, names) -> dict:
    """Object names of Bambu Studio and OrcaSlicer (Metadata/
    model_settings.config): object id -> name."""
    real = names.get("metadata/model_settings.config")
    out = {}
    if not real:
        return out
    try:
        root = ET.fromstring(z.read(real))
    except ET.ParseError:
        return out
    for obj in root.iter("object"):
        for md in obj.findall("metadata"):
            if md.get("key") == "name" and obj.get("id"):
                out[obj.get("id")] = md.get("value", "")
    return out


def _mesh_3mf(mesh_el):
    pts, tris = [], []
    for el in mesh_el:
        tag = _local(el.tag)
        if tag == "vertices":
            pts = [(float(v.get("x")), float(v.get("y")), float(v.get("z")))
                   for v in el]
        elif tag == "triangles":
            tris = [(int(t.get("v1")), int(t.get("v2")), int(t.get("v3")))
                    for t in el]
    return (np.asarray(pts, np.float64).reshape(-1, 3),
            np.asarray(tris, np.int64).reshape(-1, 3))


def write_3mf(path, parts: list, unit: str) -> None:
    """3MF in millimetres: one object and one build item for each body,
    with its name. The points are already in mm (save_mesh)."""
    out = [f'<?xml version="1.0" encoding="UTF-8"?>\n'
           f'<model unit="millimeter" xml:lang="en-US" xmlns="{NS_3MF}">\n'
           f' <metadata name="Application">{escape(APP)}</metadata>\n'
           ' <resources>\n']
    for i, part in enumerate(parts, 1):
        out.append(f'  <object id="{i}" type="model" name='
                   f'{quoteattr(part.name)}>\n   <mesh>\n    <vertices>\n')
        out.append(_rows(f'     <vertex x="{NUM}" y="{NUM}" z="{NUM}"/>\n',
                         part.points))
        out.append('    </vertices>\n    <triangles>\n')
        out.append(_rows('     <triangle v1="%d" v2="%d" v3="%d"/>\n',
                         part.tris))
        out.append('    </triangles>\n   </mesh>\n  </object>\n')
    out.append(' </resources>\n <build>\n')
    out.extend(f'  <item objectid="{i}"/>\n' for i in range(1, len(parts) + 1))
    out.append(' </build>\n</model>\n')
    types = ('<?xml version="1.0" encoding="UTF-8"?>\n<Types xmlns="http://'
             'schemas.openxmlformats.org/package/2006/content-types">\n'
             ' <Default Extension="rels" ContentType="application/vnd.'
             'openxmlformats-package.relationships+xml"/>\n'
             ' <Default Extension="model" ContentType="application/vnd.'
             'ms-package.3dmanufacturing-3dmodel+xml"/>\n</Types>\n')
    rels = ('<?xml version="1.0" encoding="UTF-8"?>\n<Relationships xmlns='
            '"http://schemas.openxmlformats.org/package/2006/relationships">'
            '\n <Relationship Target="/3D/3dmodel.model" Id="rel0" Type='
            '"http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/>'
            '\n</Relationships>\n')
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", types)
        z.writestr("_rels/.rels", rels)
        z.writestr("3D/3dmodel.model", "".join(out))


# ------------------------------------------------------------------- glTF
_GL_COMP = {5120: "i1", 5121: "u1", 5122: "i2", 5123: "u2", 5125: "u4",
            5126: "f4"}
_GL_SIZE = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}
# glTF is Y up, the models are Z up: (x, y, z) -> (x, z, -y) and back.
_Z_TO_Y = np.array([[1.0, 0, 0], [0, 0, 1.0], [0, -1.0, 0]])


def read_gltf(path):
    """glTF 2.0 (.gltf with embedded or separate buffers, .glb): each node
    with a mesh is a body; the node transforms are applied. The triangles
    of each primitive (mode 4). Compressed meshes (Draco, meshopt) are not
    read."""
    raw = open(path, "rb").read()
    bin_chunk = None
    if raw[:4] == b"glTF":
        length = struct.unpack_from("<I", raw, 8)[0]
        at, doc = 12, None
        while at + 8 <= min(length, len(raw)):
            size, kind = struct.unpack_from("<II", raw, at)
            chunk = raw[at + 8: at + 8 + size]
            if kind == 0x4E4F534A:
                doc = json.loads(chunk.decode("utf-8"))
            elif kind == 0x004E4942:
                bin_chunk = chunk
            at += 8 + size
        if doc is None:
            raise ValueError(tr("glTF: the file has no JSON part."))
    else:
        doc = json.loads(raw.decode("utf-8"))
    for ext in doc.get("extensionsRequired", ()):
        raise ValueError(tr("glTF: the extension {ext} is not supported.",
                            ext=ext))
    folder = os.path.dirname(os.path.abspath(str(path)))
    buffers = []
    for b in doc.get("buffers", ()):
        uri = b.get("uri")
        if uri is None:
            buffers.append(bin_chunk or b"")
        elif uri.startswith("data:"):
            buffers.append(base64.b64decode(uri.split(",", 1)[1]))
        else:
            from urllib.parse import unquote
            with open(os.path.join(folder, unquote(uri)), "rb") as f:
                buffers.append(f.read())

    def accessor(i: int) -> np.ndarray:
        acc = doc["accessors"][i]
        if "sparse" in acc:
            raise ValueError(tr("glTF: sparse accessors are not supported."))
        comp = np.dtype("<" + _GL_COMP[acc["componentType"]])
        k = _GL_SIZE[acc["type"]]
        count = acc["count"]
        view = doc["bufferViews"][acc["bufferView"]]
        buf = buffers[view["buffer"]]
        start = view.get("byteOffset", 0) + acc.get("byteOffset", 0)
        stride = view.get("byteStride") or comp.itemsize * k
        if stride == comp.itemsize * k:
            arr = np.frombuffer(buf, comp, count * k, start)
        else:
            rows = np.frombuffer(buf, np.uint8, (count - 1) * stride
                                 + comp.itemsize * k, start)
            idx = (np.arange(count)[:, None] * stride
                   + np.arange(comp.itemsize * k)[None, :])
            arr = rows[idx].copy().view(comp)
        return arr.reshape(count, k) if k > 1 else arr

    def local(node) -> np.ndarray:
        if "matrix" in node:
            return np.array(node["matrix"], float).reshape(4, 4).T
        m = np.eye(4)
        x, y, z, w = node.get("rotation", (0, 0, 0, 1))
        r = np.array([
            [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
            [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
            [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])
        m[:3, :3] = r * np.asarray(node.get("scale", (1, 1, 1)), float)
        m[:3, 3] = node.get("translation", (0, 0, 0))
        return m

    nodes = doc.get("nodes", [])
    scenes = doc.get("scenes", [])
    if scenes:
        roots = scenes[doc.get("scene", 0)].get("nodes", [])
    else:
        children = {c for n in nodes for c in n.get("children", ())}
        roots = [i for i in range(len(nodes)) if i not in children]
    parts = []

    def walk(i: int, parent: np.ndarray, depth=0):
        node = nodes[i]
        m = parent @ local(node)
        if "mesh" in node:
            mesh = doc["meshes"][node["mesh"]]
            pts, tris, off = [], [], 0
            for prim in mesh.get("primitives", ()):
                if prim.get("mode", 4) != 4 or "POSITION" not in \
                        prim.get("attributes", {}):
                    continue
                p = accessor(prim["attributes"]["POSITION"]).astype(np.float64)
                if "indices" in prim:
                    t = accessor(prim["indices"]).astype(np.int64)
                else:
                    t = np.arange(len(p), dtype=np.int64)
                t = t[: len(t) // 3 * 3].reshape(-1, 3)
                if np.linalg.det(m[:3, :3]) < 0:
                    t = t[:, ::-1]
                pts.append(_apply(m, p) @ _Z_TO_Y)
                tris.append(t + off)
                off += len(p)
            if pts:
                name = (node.get("name") or mesh.get("name")
                        or tr("body {i}", i=len(parts) + 1))
                parts.append(Part(name, np.vstack(pts), np.vstack(tris)))
        if depth < 64:
            for c in node.get("children", ()):
                walk(c, m, depth + 1)

    for r in roots:
        walk(r, np.eye(4))
    return to_polydata(Data(parts, 1.0))


def _gltf(parts: list) -> tuple:
    """(the JSON document, the binary buffer) of the bodies (in metres)."""
    blob = bytearray()
    views, accessors, meshes, nodes = [], [], [], []
    for part in parts:
        p = (part.points @ _Z_TO_Y.T).astype("<f4")
        t = np.ascontiguousarray(part.tris, "<u4")
        for data, target in ((p, 34962), (t, 34963)):
            views.append({"buffer": 0, "byteOffset": len(blob),
                          "byteLength": data.nbytes, "target": target})
            blob += data.tobytes()
            blob += b"\0" * (-len(blob) % 4)
        accessors.append({"bufferView": len(views) - 2, "componentType": 5126,
                          "count": len(p), "type": "VEC3",
                          "min": p.min(0).tolist(), "max": p.max(0).tolist()})
        accessors.append({"bufferView": len(views) - 1, "componentType": 5125,
                          "count": t.size, "type": "SCALAR"})
        meshes.append({"name": part.name, "primitives": [{
            "attributes": {"POSITION": len(accessors) - 2},
            "indices": len(accessors) - 1, "mode": 4}]})
        nodes.append({"name": part.name, "mesh": len(meshes) - 1})
    doc = {"asset": {"version": "2.0", "generator": APP},
           "scene": 0, "scenes": [{"nodes": list(range(len(nodes)))}],
           "nodes": nodes, "meshes": meshes, "accessors": accessors,
           "bufferViews": views, "buffers": [{"byteLength": len(blob)}]}
    return doc, bytes(blob)


def write_glb(path, parts: list, unit: str) -> None:
    doc, blob = _gltf(parts)
    js = json.dumps(doc, separators=(",", ":")).encode("utf-8")
    js += b" " * (-len(js) % 4)
    total = 12 + 8 + len(js) + 8 + len(blob)
    with open(path, "wb") as f:
        f.write(struct.pack("<III", 0x46546C67, 2, total))
        f.write(struct.pack("<II", len(js), 0x4E4F534A) + js)
        f.write(struct.pack("<II", len(blob), 0x004E4942) + blob)


def write_gltf(path, parts: list, unit: str) -> None:
    doc, blob = _gltf(parts)
    doc["buffers"][0]["uri"] = ("data:application/octet-stream;base64,"
                                + base64.b64encode(blob).decode("ascii"))
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(doc, f, separators=(",", ":"))


# -------------------------------------------------------------------- VTK
def read_vtk(path):
    return pv.read(str(path))


def _write_vtk(path, parts: list, binary: bool) -> None:
    mesh = join_bodies([(p.name, _poly(p.points, p.tris)) for p in parts])
    mesh.save(str(path), binary=binary)


def write_vtp(path, parts: list, unit: str) -> None:
    _write_vtk(path, parts, True)


def write_vtk_legacy(path, parts: list, unit: str) -> None:
    _write_vtk(path, parts, True)


# ---------------------------------------------------------------- the table
@dataclass(frozen=True)
class Format:
    """One file format. label: English text (tr() at the place of use).
    unit: None = the file keeps no unit; "mm" / "m" = the writer always
    writes this unit. bodies: the file keeps several bodies. stl_safe: the
    file has float32 coordinates, the writer needs the step
    stl_safe_output first."""
    key: str
    label: str
    suffix: str
    read: object
    write: object
    unit: str | None = None
    bodies: bool = False
    stl_safe: bool = False


FORMATS = {f.key: f for f in (
    Format("stl", "STL binary", ".stl", read_stl, write_stl_binary,
           stl_safe=True),
    Format("stl_ascii", "STL ASCII", ".stl", read_stl, write_stl_ascii,
           bodies=True, stl_safe=True),
    Format("3mf", "3MF", ".3mf", read_3mf, write_3mf, unit="mm",
           bodies=True),
    Format("obj", "OBJ", ".obj", read_obj, write_obj, bodies=True),
    Format("ply", "PLY binary", ".ply", read_ply, write_ply_binary),
    Format("ply_ascii", "PLY ASCII", ".ply", read_ply, write_ply_ascii),
    Format("off", "OFF", ".off", read_off, write_off),
    Format("glb", "glTF binary", ".glb", read_gltf, write_glb, unit="m",
           bodies=True, stl_safe=True),
    Format("gltf", "glTF", ".gltf", read_gltf, write_gltf, unit="m",
           bodies=True, stl_safe=True),
    Format("vtp", "VTK PolyData", ".vtp", read_vtk, write_vtp, bodies=True),
    Format("vtk", "VTK legacy", ".vtk", read_vtk, write_vtk_legacy,
           bodies=True),
)}

# The first format of each suffix is the default of that suffix.
DEFAULT_FOR_SUFFIX: dict = {}
for _f in FORMATS.values():
    DEFAULT_FOR_SUFFIX.setdefault(_f.suffix, _f.key)
del _f

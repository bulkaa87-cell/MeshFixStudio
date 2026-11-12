"""The core package meshfix, without a window.

1. The native module: it is there, and it has the repair and the check.
2. The check: the Rust path and the VTK/numpy path give the same counts.
3. The repair (meshfix) of the test meshes of tests/meshfix_cases.py:
   watertight and oriented, no crossing faces, the known thresholds, and
   the STL round trip of each result (binary STL in mm and in m).
4. The method list: the Windows method only on Windows.
5. The languages: English keys, the Ukrainian catalogue of the core.
6. The step ids (and the old ids of a saved report), the file formats.
7. Each file format: the repaired test meshes written and read again
   (the same counts, triangles and size, in mm and in m), two bodies, the
   units of 3MF and glTF.
8. Files of other programs: OBJ groups, PLY and OFF variants, ASCII STL
   names, a 3MF with components in other model files, a glTF node tree.
9. With --big FOLDER: each *.stl of FOLDER (use copies), repaired, in each
   format.

    python tests/test_core.py [--big FOLDER]
"""

import _isolate  # noqa: F401  — first: temp settings, sys.path
import os
import sys

import numpy as np
import pyvista as pv

from _isolate import check, problems
import meshfix
from meshfix import check as geo
from meshfix import i18n
from meshfix import methods
from meshfix import repair as mf
import meshfix_cases as mc

os.environ["FS_LANG"] = "en"
i18n.set_language(None)


def poly(p_mm, t):
    t = np.asarray(t, np.int64)
    return pv.PolyData(np.asarray(p_mm, float) / 1000.0,
                       np.hstack([np.full((len(t), 1), 3), t]).ravel())


def back(mesh):
    return (np.asarray(mesh.points) * 1000.0,
            np.asarray(mesh.faces).reshape(-1, 4)[:, 1:])


EMPTY = {"plate"}          # the repair gives no triangles (as Windows)


def part_native():
    print("1. the native module")
    check("meshfix._native is there", meshfix.native_version() is not None,
          mf.why_not())
    rs = mf._rs
    for name in ("repair", "crossings", "mesh_check", "shell_projections"):
        check(f"native has {name}", rs is not None and hasattr(rs, name))


def part_check():
    print("2. the check: Rust and VTK give the same counts")
    keys = ("open_edges", "non_manifold_edges", "degenerate", "parts",
            "flipped_faces", "inverted_parts", "bad_winding")
    real = geo._rust_mesh
    for name, (p, t) in mc.cases().items():
        mesh = poly(p, t)
        d_rs = geo.diagnose(mesh)
        geo._rust_mesh = lambda: None
        try:
            d_vtk = geo.diagnose(mesh)
        finally:
            geo._rust_mesh = real
        a = {k: getattr(d_rs, k) for k in keys}
        b = {k: getattr(d_vtk, k) for k in keys}
        check(f"{name}: same counts", a == b, f"rust {a} vtk {b}")
    p, t = mc.cube()
    d = geo.diagnose(poly(p, t), projected=True)
    check("projected areas of a 10 mm cube (about 1e-4 m2)",
          all(abs(a - 1e-4) < 0.05e-4 for a in d.projected), d.projected)
    layers = geo.problem_layers(poly(p, np.delete(t, 2, 0)),
                                geo.diagnose(poly(p, np.delete(t, 2, 0))))
    check("problem layers: holes only", layers["holes"] is not None
          and layers["holes"].n_cells == 3 and layers["flip"] is None, layers)


def part_repair():
    print("3. the repair of the test meshes")
    if not mf.available():
        check("repair available", False, mf.why_not())
        return
    out = {}
    for name, (p, t) in mc.cases().items():
        try:
            q, f = back(mf.repair(poly(p, t)))
            s = mc.stats(q, f)
        except RuntimeError as exc:
            s = {"error": str(exc)}
        out[name] = s
        if name in EMPTY:
            check(f"{name}: no triangles left", "error" in s, str(s))
        else:
            check(f"{name}: watertight, oriented", "error" not in s
                  and s["open"] == 0 and s["nm"] == 0 and s["flip"] == 0
                  and s["vol"] > 0, str(s))
    for name, (p, t) in mc.cases().items():
        if name in EMPTY:
            continue
        q, f, _rep = mf.repair_arrays(np.asarray(p, float), t)
        f = np.asarray(f)
        res = pv.PolyData(np.asarray(q) / 1000.0,
                          np.hstack([np.full((len(f), 1), 3), f]).ravel())
        worse = mf.worse_than(poly(p, t), res)
        check(f"{name}: Rust result not worse", not worse, str(worse))
        if len(f):
            cr = mf._rs.crossings(np.ascontiguousarray(q, np.float64),
                                  np.ascontiguousarray(f, np.int64))
            check(f"{name}: no crossing faces", len(cr) == 0, f"{len(cr)} faces")
    # The STL round trip (StlSafe step, from T31 of OpenFOAM Studio): the
    # result written as a binary STL (float32) in mm and in m, read with
    # the loader (equal points join), keeps the counts and stays closed.
    import tempfile
    tmp = tempfile.mkdtemp(prefix="meshfix_stl_")

    def rt_counts(d):
        return (d.open_edges, d.flipped_faces, d.non_manifold_edges,
                d.degenerate, d.n_triangles)
    for name, (p, t) in mc.cases().items():
        if name in EMPTY:
            continue
        res = mf.repair(poly(p, t))
        want = rt_counts(geo.diagnose(res))
        for unit, factor in (("mm", 1000.0), ("m", 1.0)):
            path = os.path.join(tmp, f"{name}_{unit}.stl")
            geo.write_stl(geo.apply_scale(res, factor), path, binary=True)
            got_mesh = geo.apply_scale(geo.load_surface(path), 1.0 / factor)
            got = rt_counts(geo.diagnose(got_mesh))
            s = mc.stats(*back(got_mesh))
            check(f"{name}: STL in {unit} read again: same counts, closed",
                  got == want and s["open"] == 0 and s["nm"] == 0
                  and s["flip"] == 0, f"{want} -> {got}, {s}")
    check("report has stl_safe", mf.last_report is not None
          and "stl_safe" in mf.last_report, str(list(mf.last_report or {})))
    v = {n: out[n]["V"] for n in out if n.startswith("seam") and "V" in out[n]}
    check("seam stitched below 0.01 normalized, filled above",
          v.get("seam_0.009") == 8 and v.get("seam_0.011") == 10
          and v.get("seam1000_0.02") == 8 and v.get("seam1000_0.03") == 10
          and v.get("seam1_0.0015") == 8 and v.get("seam1_0.003") == 10, str(v))
    sh = {n: out[n]["shells"] for n in out if n.startswith("tiny")}
    check("tiny shell removed below 0.001 normalized volume",
          sh == {"tiny_0.05": 1, "tiny_0.08": 1, "tiny_0.12": 2, "tiny_0.3": 2},
          str(sh))
    # The guard: a result with more holes gives the input back.
    saved = mf.repair_arrays
    try:
        p, t = mc.cube()
        mf.repair_arrays = lambda pts, tri, wrap=True, method="meshfix": (
            pts, np.asarray(tri)[1:], {"stages": [], "union": {}})
        src = poly(p, t)
        res = mf.repair(src)
        check("guard: a worse result gives the input back",
              res.n_cells == src.n_cells
              and "worse" in mf.summary(mf.last_report),
              mf.summary(mf.last_report))
    finally:
        mf.repair_arrays = saved
    # repair_meshes: the one call of both programs.
    p, t = mc.cube()
    meshes = [poly(p, np.delete(t, 2, 0)), poly(p + 20.0, t)]
    res = methods.repair_meshes("meshfix", meshes)
    check("repair_meshes parts: one result for each mesh",
          len(res) == 2 and all(methods.clean(geo.diagnose(m)) for m in res))
    res = methods.repair_meshes("alphawrap", meshes)
    check("repair_meshes wrap: one closed result", len(res) == 1
          and geo.diagnose(res[0]).closed)


def part_methods():
    print("4. the method list")
    check("keys", methods.KEYS == ("meshfix", "alphawrap", "winfix", "volume"),
          methods.KEYS)
    if sys.platform != "win32":
        check("Windows method not available here",
              not methods.available("winfix") and methods.why_not("winfix"))
    check("meshfix available", methods.available("meshfix"),
          methods.why_not("meshfix"))


def part_language():
    print("5. the languages")
    i18n.set_language("uk")
    check("uk: a method label", methods.label("volume") != "volume rebuild",
          methods.label("volume"))
    check("uk: a count label", i18n.tr("Holes (open edges)")
          != "Holes (open edges)", i18n.tr("Holes (open edges)"))
    i18n.set_language("en")
    check("en: the key", methods.label("volume") == "volume rebuild",
          methods.label("volume"))


def part_steps():
    print("6. the step ids, the old ids, the file formats")
    want = ("stitch_seams", "fill_tiny_holes", "remove_duplicates",
            "fix_orientation", "fill_tiny_holes_again", "stitch_seams_again",
            "fix_orientation_again", "fill_holes", "merge_bodies",
            "fix_degenerate_faces", "remove_tiny_shells", "split_t_junctions",
            "alpha_wrap", "volume_rebuild", "stl_safe_output")
    check("the step ids", tuple(mf.STEPS) == want, list(mf.STEPS))
    check("each old id maps to a step id",
          all(v in mf.STEPS for v in mf.LEGACY_STEP_IDS.values())
          and not set(mf.LEGACY_STEP_IDS) & set(mf.STEPS)
          and len(set(mf.LEGACY_STEP_IDS.values())) == len(mf.STEPS))
    check("step_id: old id", mf.step_id("Stitch1") == "stitch_seams"
          and mf.step_id("Wrap") == "merge_bodies"
          and mf.step_id("fill_holes") == "fill_holes")
    if mf.available():
        p, t = mc.cube()
        _q, _f, rep = mf.repair_arrays(np.asarray(p, float), np.delete(t, 2, 0))
        names = [n for n, _c, _s in rep["stages"]]
        check("the native report uses the step ids",
              names[:12] == list(want[:12]) and all(n in mf.STEPS for n in names),
              names)
        for stop in ("fill_holes", "CloseAllHoles"):
            try:
                _rs = mf._rs.repair(np.asarray(p, float), np.asarray(t, np.int64),
                                    True, True, stop_after=stop)
                ok = [n for n, _c, _s in _rs[2]["stages"]][-1] == "fill_holes"
            except ValueError as exc:
                ok = False
                stop = f"{stop}: {exc}"
            check(f"stop_after {stop}", ok)
        mf.repair(poly(p, np.delete(t, 2, 0)))
        text = methods.steps("meshfix")
        check("steps text: one line for each step",
              len(text.splitlines()) == len(mf.last_report["stages"])
              and "Stitch seams" in text, text)
    # The status line of a fallback that replaced the result, with the ids
    # of now and with the old ids (a saved report).
    for wrap, alpha in (("merge_bodies", "alpha_wrap"), ("Wrap", "AlphaWrap")):
        rep = {"stages": [(wrap, 3, 0.1), (alpha, 500, 1.0)], "union": {},
               "fallback": alpha, "after": {}}
        check(f"fallback named in the status line ({alpha})",
              "alpha wrap" in mf.summary(rep), mf.summary(rep))
        rep = {"stages": [(wrap, 3, 0.1), (alpha, 500, 1.0)], "union": {},
               "fallback": None, "after": {}}
        check(f"unused fallback not in the status line ({alpha})",
              "alpha" not in mf.summary(rep)
              and "inner shells removed 3" in mf.summary(rep),
              mf.summary(rep))
    i18n.set_language("uk")
    label = mf.step_label("Stitch1")
    check("uk: a step name", label not in ("Stitch seams", "Stitch1"), label)
    text = mf.steps_text({"stages": [("fill_holes", 2, 0.5)]})
    check("uk: the steps text", "2" in text and "Fill holes" not in text, text)
    i18n.set_language("en")
    check("en: the step name", mf.step_label("fill_holes") == "Fill holes")
    check("en: the steps text", "Fill holes" in mf.steps_text(
        {"stages": [("fill_holes", 2, 0.5)]}))
    # The file format tables: the readers and the writers.
    check("readers", set(geo.READERS) >= {".stl", ".obj", ".ply"},
          sorted(geo.READERS))
    check("writers: one for each reader", set(geo.WRITERS) == set(geo.READERS),
          sorted(geo.WRITERS))
    import tempfile
    p, t = mc.cube()
    path = os.path.join(tempfile.mkdtemp(prefix="meshfix_io_"), "cube.stl")
    geo.write_mesh(poly(p, t), path)
    back_mesh = geo.load_surface(path)
    check("write_mesh + load_surface: the cube", back_mesh.n_cells == 12,
          back_mesh.n_cells)
    try:
        geo.write_mesh(poly(p, t), path[:-4] + ".xyz")
        check("no writer: an error", False)
    except ValueError as exc:
        check("no writer: an error", ".xyz" in str(exc), str(exc))


def mm_poly(p_mm, t, shift=0.0):
    """A test mesh in m from points in mm."""
    return poly(np.asarray(p_mm, float) + shift, t)


def rt(d):
    """The counts of a round trip: the four counts and the triangles."""
    return (d.open_edges, d.flipped_faces, d.non_manifold_edges,
            d.degenerate, d.n_triangles)


def read_back(path, fmt, unit_m):
    """The mesh of a written file, in m."""
    raw = geo.load_surface(path)
    factor = geo.guess_scale(raw)[0] if fmt.unit else unit_m
    return raw, geo.apply_scale(raw, factor)


def part_formats():
    print("7. the file formats: write, read again, units, bodies")
    import tempfile
    tmp = tempfile.mkdtemp(prefix="meshfix_fmt_")
    want_keys = ("stl", "stl_ascii", "3mf", "obj", "ply", "ply_ascii", "off",
                 "glb", "gltf", "vtp", "vtk")
    check("the export formats", geo.EXPORT_FORMATS == want_keys,
          geo.EXPORT_FORMATS)
    check("the readers", set(geo.READERS) == {".stl", ".3mf", ".obj", ".ply",
                                              ".off", ".glb", ".gltf",
                                              ".vtp", ".vtk"},
          sorted(geo.READERS))
    check("format_for: suffix, filter, other suffix",
          geo.format_for("a.STL").key == "stl"
          and geo.format_for("a.stl", "stl_ascii").key == "stl_ascii"
          and geo.format_for("a.ply", "stl").key == "ply"
          and geo.format_for("a.3mf").unit == "mm")
    # 1. Each repaired test mesh in each format, in mm and in m: the same
    # counts and triangles after the read, the same size. The repair runs
    # without its stl_safe_output step: save_mesh applies it (STL, glTF).
    meshes = {}
    for name, (p, t) in mc.cases().items():
        if name in EMPTY:
            continue
        meshes[name] = methods.repair_meshes("meshfix", [mm_poly(p, t)],
                                             stl_safe=False)[0]
    check("repair without stl_safe_output: no such step",
          all(n != "stl_safe_output" for n, _c, _s in
              mf.last_report["stages"]) and "stl_safe" not in mf.last_report,
          [n for n, _c, _s in mf.last_report["stages"]])
    for key in want_keys:
        fmt = geo.FORMATS[key]
        bad = []
        for name, res in meshes.items():
            want = rt(geo.diagnose(res))
            for unit_m in ((0.001, 1.0) if fmt.unit is None else (0.001,)):
                path = os.path.join(tmp, f"{name}_{unit_m:g}{fmt.suffix}")
                info = geo.save_mesh(res, path, key, unit_m=unit_m)
                _raw, got = read_back(path, fmt, unit_m)
                size = np.ptp(np.asarray(got.points), 0)
                ref = np.ptp(np.asarray(res.points), 0)
                if (rt(geo.diagnose(got)) != want
                        or not np.allclose(size, ref, rtol=1e-6, atol=1e-9)
                        or (info.stl_safe is not None) != fmt.stl_safe):
                    bad.append(f"{name} {unit_m:g}: {want} -> "
                               f"{rt(geo.diagnose(got))}")
        check(f"{key}: {len(meshes)} repaired meshes, read again: the same "
              f"counts and size", not bad, "; ".join(bad[:4]))
    # 2. Two bodies.
    p, t = mc.cube()
    two = geo.join_bodies([("Left side", mm_poly(p, t)),
                           ("Right", mm_poly(p, t, 30.0))])
    check("join_bodies: names", geo.body_names(two) == ["Left side", "Right"])
    split = geo.split_bodies(two)
    check("split_bodies: 2 bodies of 12 triangles",
          [(n, m.n_cells, m.n_points) for n, m in split]
          == [("Left side", 12, 8), ("Right", 12, 8)], split)
    for key in want_keys:
        fmt = geo.FORMATS[key]
        path = os.path.join(tmp, f"two{fmt.suffix}")
        info = geo.save_mesh(two, path, key, unit_m=0.001)
        raw, got = read_back(path, fmt, 0.001)
        names = geo.body_names(raw)
        if fmt.bodies:
            want = (["Left_side", "Right"] if key == "stl_ascii"
                    else ["Left side", "Right"])
            ok = names == want and not info.merged and info.written == 2
        else:
            ok = len(names) <= 1 and info.merged and info.written == 1
        check(f"{key}: two bodies {'kept' if fmt.bodies else 'merged'}",
              ok and got.n_cells == 24
              and np.isclose(np.ptp(got.points[:, 0]), 0.04), (names, info))
    # 3. Units: 3MF always in mm, glTF in m, the others in unit_m.
    cube = mm_poly(p, t)
    for key, unit_m, span, unit in (("3mf", 1.0, 10.0, "mm"),
                                    ("glb", 0.001, 0.01, "m"),
                                    ("obj", 0.001, 10.0, "mm"),
                                    ("obj", 0.0254, 10.0 / 25.4, "in")):
        path = os.path.join(tmp, f"unit_{key}_{unit}{geo.FORMATS[key].suffix}")
        info = geo.save_mesh(cube, path, key, unit_m=unit_m)
        raw = geo.load_surface(path)
        factor, note = geo.guess_scale(raw)
        check(f"{key}: written in {unit}", info.unit == unit
              and np.isclose(np.ptp(raw.points[:, 0]), span), (info.unit,
                                                               raw.bounds))
        if geo.FORMATS[key].unit:
            check(f"{key}: the reader gives the unit",
                  np.isclose(factor * span, 0.01) and unit in note, note)
    check("save_note: no unit", "keeps no unit" in geo.save_note(
        geo.save_mesh(cube, os.path.join(tmp, "n.ply"), unit_m=0.001)))
    check("save_note: merged bodies", "2 bodies are one body" in geo.save_note(
        geo.save_mesh(two, os.path.join(tmp, "n.off"), unit_m=0.001)))
    # write_mesh (the call of 0.2.0): the coordinates as they are.
    path = os.path.join(tmp, "plain.stl")
    geo.write_mesh(poly(np.asarray(p, float) * 1000.0, t), path)
    check("write_mesh: binary STL, coordinates as they are",
          np.isclose(np.ptp(geo.load_surface(path).points[:, 0]), 10.0))
    part_foreign(tmp)


def _write(path, text, mode="w"):
    with open(path, mode, **({} if "b" in mode else {"newline": "\n"})) as f:
        f.write(text)
    return path


def part_foreign(tmp):
    print("8. files of other programs")
    import json
    import struct
    import zipfile
    p, t = mc.cube()
    cube = poly(p, t)
    # OBJ: g groups (no o), a quad, negative indices, v/vt/vn.
    path = _write(os.path.join(tmp, "groups.obj"), "\n".join([
        "# test", "v 0 0 0", "v 1 0 0", "v 1 1 0", "v 0 1 0", "vt 0 0",
        "vn 0 0 1", "g first", "f 1/1/1 2/1/1 3/1/1 4/1/1", "g second",
        "v 0 0 1", "v 1 0 1", "v 0 1 1", "f -3 -2 -1", ""]))
    m = geo.load_surface(path)
    check("OBJ: g groups, quad, negative indices",
          m.n_cells == 3 and geo.body_names(m) == ["first", "second"],
          (m.n_cells, geo.body_names(m)))
    path = _write(os.path.join(tmp, "objects.obj"), "\n".join([
        "o Part A", "v 0 0 0", "v 1 0 0", "v 0 1 0", "g mat", "f 1 2 3",
        "o Part B", "v 0 0 1", "v 1 0 1", "v 0 1 1", "g mat", "f 4 5 6", ""]))
    m = geo.load_surface(path)
    check("OBJ: o objects win over g", geo.body_names(m) == ["Part A", "Part B"],
          geo.body_names(m))
    # PLY of VTK (float32, binary and ASCII), a PLY with a quad and other
    # elements.
    for binary in (True, False):
        path = os.path.join(tmp, f"vtk_{binary}.ply")
        cube.save(path, binary=binary)
        m = geo.load_surface(path)
        check(f"PLY of VTK (binary {binary})", m.n_cells == 12
              and geo.diagnose(m).closed, m.n_cells)
    path = _write(os.path.join(tmp, "quad.ply"), "\n".join([
        "ply", "format ascii 1.0", "comment test", "element vertex 4",
        "property float x", "property float y", "property float z",
        "property uchar red", "element face 1",
        "property list uchar int vertex_indices", "element edge 1",
        "property int vertex1", "property int vertex2", "end_header",
        "0 0 0 255", "1 0 0 255", "1 1 0 255", "0 1 0 255", "4 0 1 2 3",
        "0 1", ""]))
    m = geo.load_surface(path)
    check("PLY ASCII: a quad, colour, an edge element", m.n_cells == 2,
          m.n_cells)
    # OFF: the counts on the first line, comments, face colours.
    path = _write(os.path.join(tmp, "c.off"), "\n".join(
        ["OFF 4 2 0", "# comment", "0 0 0", "1 0 0", "1 1 0", "0 1 0",
         "3 0 1 2 255 0 0", "3 0 2 3", ""]))
    m = geo.load_surface(path)
    check("OFF: counts on line 1, comments, colours", m.n_cells == 2
          and m.n_points == 4, (m.n_cells, m.n_points))
    # ASCII STL with names, and a binary STL whose header starts with
    # "solid".
    geo.save_mesh(geo.join_bodies([("wing", cube), ("fin", poly(p + 20, t))]),
                  os.path.join(tmp, "named.stl"), "stl_ascii")
    m = geo.load_surface(os.path.join(tmp, "named.stl"))
    check("ASCII STL: solid names", geo.body_names(m) == ["wing", "fin"]
          and m.n_cells == 24, geo.body_names(m))
    path = os.path.join(tmp, "solid_head.stl")
    geo.save_mesh(cube, path, "stl")
    with open(path, "r+b") as f:
        f.write(b"solid head of a binary file")
    m = geo.load_surface(path)
    check("binary STL with 'solid' in the header", m.n_cells == 12
          and m.n_points == 8, (m.n_cells, m.n_points))
    # 3MF as Bambu Studio / OrcaSlicer write it: the mesh in another model
    # file (p:path), a component and a build transform, the name in
    # Metadata/model_settings.config, unit inch.
    ns = 'xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02"'
    pns = 'xmlns:p="http://schemas.microsoft.com/3dmanufacturing/production/2015/06"'
    verts = "".join(f'<vertex x="{a}" y="{b}" z="{c}"/>' for a, b, c in p)
    tris = "".join(f'<triangle v1="{a}" v2="{b}" v3="{c}"/>' for a, b, c in t)
    sub = (f'<model unit="inch" {ns}><resources><object id="1" type="model">'
           f'<mesh><vertices>{verts}</vertices><triangles>{tris}</triangles>'
           '</mesh></object></resources><build/></model>')
    top = (f'<model unit="inch" {ns} {pns}><resources><object id="2" '
           'type="model"><components><component p:path="/3D/Objects/'
           'object_1.model" objectid="1" transform="1 0 0 0 1 0 0 0 1 5 0 0"'
           '/></components></object></resources><build><item objectid="2" '
           'transform="1 0 0 0 1 0 0 0 1 0 0 2"/></build></model>')
    cfg = ('<?xml version="1.0"?><config><object id="2"><metadata key="name"'
           ' value="Bambu part"/></object></config>')
    rels = ('<Relationships xmlns="http://schemas.openxmlformats.org/package/'
            '2006/relationships"><Relationship Target="/3D/3dmodel.model" '
            'Id="rel-1" Type="http://schemas.microsoft.com/3dmanufacturing/'
            '2013/01/3dmodel"/></Relationships>')
    path = os.path.join(tmp, "bambu.3mf")
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("_rels/.rels", rels)
        z.writestr("3D/3dmodel.model", top)
        z.writestr("3D/Objects/object_1.model", sub)
        z.writestr("Metadata/model_settings.config", cfg)
    m = geo.load_surface(path)
    factor, _note = geo.guess_scale(m)
    b = m.bounds
    check("3MF: p:path, transforms, Bambu name, inch",
          m.n_cells == 12 and geo.body_names(m) == ["Bambu part"]
          and np.isclose(factor, 0.0254) and np.isclose(b[0], 5.0)
          and np.isclose(b[4], 2.0), (geo.body_names(m), factor, b))
    # glTF with a separate .bin, an interleaved buffer (byteStride), a node
    # tree with translation, rotation and scale.
    pts = np.asarray(p, np.float32)
    inter = np.zeros((len(pts), 4), np.float32)
    inter[:, :3] = pts
    idx = np.asarray(t, np.uint16).ravel()
    blob = inter.tobytes() + idx.tobytes()
    _write(os.path.join(tmp, "tree.bin"), blob, "wb")
    q = [0.0, 0.0, np.sin(np.pi / 4), np.cos(np.pi / 4)]  # 90 deg about Z
    doc = {"asset": {"version": "2.0"}, "scene": 0,
           "scenes": [{"nodes": [0]}],
           "nodes": [{"name": "root", "translation": [1, 0, 0],
                      "children": [1]},
                     {"name": "child", "mesh": 0, "rotation": q,
                      "scale": [2, 2, 2]}],
           "meshes": [{"name": "m", "primitives": [
               {"attributes": {"POSITION": 0}, "indices": 1}]}],
           "accessors": [{"bufferView": 0, "componentType": 5126,
                          "count": len(pts), "type": "VEC3"},
                         {"bufferView": 1, "componentType": 5123,
                          "count": idx.size, "type": "SCALAR"}],
           "bufferViews": [{"buffer": 0, "byteOffset": 0,
                            "byteLength": inter.nbytes, "byteStride": 16},
                           {"buffer": 0, "byteOffset": inter.nbytes,
                            "byteLength": idx.nbytes}],
           "buffers": [{"uri": "tree.bin", "byteLength": len(blob)}]}
    path = _write(os.path.join(tmp, "tree.gltf"), json.dumps(doc))
    m = geo.load_surface(path)
    b = np.round(m.bounds, 6)
    # glTF (Y up) -> model (Z up): (x, y, z) -> (x, -z, y). The cube 0..10
    # turned 90 deg about the glTF Y... about Z, scaled 2, moved 1 in x.
    check("glTF: .bin, byteStride, node tree, TRS",
          m.n_cells == 12 and geo.body_names(m) == ["child"]
          and geo.diagnose(m).closed and np.allclose(
              b, [-19, 1, -20, 0, 0, 20]), (geo.body_names(m), b.tolist()))
    doc["extensionsRequired"] = ["KHR_draco_mesh_compression"]
    path = _write(os.path.join(tmp, "draco.gltf"), json.dumps(doc))
    try:
        geo.load_surface(path)
        check("glTF: a required extension gives an error", False)
    except ValueError as exc:
        check("glTF: a required extension gives an error",
              "KHR_draco" in str(exc), str(exc))
    # GLB header.
    path = os.path.join(tmp, "c.glb")
    geo.save_mesh(cube, path)
    with open(path, "rb") as f:
        magic, version, length = struct.unpack("<III", f.read(12))
    check("GLB: header", magic == 0x46546C67 and version == 2
          and length == os.path.getsize(path))


def part_big(folder):
    """The large models (copies) in `folder`: repair, then each format."""
    print("9. large models: repair, each format, read again")
    import glob
    import tempfile
    import time
    tmp = tempfile.mkdtemp(prefix="meshfix_big_")
    for src in sorted(glob.glob(os.path.join(folder, "*.stl"))):
        raw = geo.load_surface(src)
        factor, _note = geo.guess_scale(raw)
        t0 = time.perf_counter()
        res = methods.repair_meshes("meshfix", [geo.apply_scale(raw, factor)],
                                    stl_safe=False)[0]
        want = rt(geo.diagnose(res))
        name = os.path.basename(src)
        check(f"{name}: repaired 0/0/0/0 ({time.perf_counter() - t0:.0f} s)",
              want[:4] == (0, 0, 0, 0), want)
        for key in geo.EXPORT_FORMATS:
            fmt = geo.FORMATS[key]
            for unit_m in ((0.001, 1.0) if fmt.unit is None else (0.001,)):
                path = os.path.join(tmp, f"big_{unit_m:g}{fmt.suffix}")
                geo.save_mesh(res, path, key, unit_m=unit_m)
                _r, got = read_back(path, fmt, unit_m)
                check(f"{name}: {key} in {geo.unit_name(unit_m)}",
                      rt(geo.diagnose(got)) == want, rt(geo.diagnose(got)))
                os.remove(path)


def main():
    try:
        part_native()
        part_check()
        part_repair()
        part_methods()
        part_language()
        part_steps()
        part_formats()
        if "--big" in sys.argv:
            part_big(sys.argv[sys.argv.index("--big") + 1])
    except Exception:                                     # noqa: BLE001
        import traceback
        traceback.print_exc()
        problems.append("exception")
    print(f"\n{len(problems)} problems"
          + ("" if not problems else ": " + ", ".join(problems)))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())

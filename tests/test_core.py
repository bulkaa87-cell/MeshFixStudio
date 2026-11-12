"""The core package meshfix, without a window.

1. The native module: it is there, and it has the repair and the check.
2. The check: the Rust path and the VTK/numpy path give the same counts.
3. The repair (meshfix) of the test meshes of tests/meshfix_cases.py:
   watertight and oriented, no crossing faces, the known thresholds, and
   the STL round trip of each result (binary STL in mm and in m).
4. The method list: the Windows method only on Windows.
5. The languages: English keys, the Ukrainian catalogue of the core.

    python tests/test_core.py
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


def main():
    try:
        part_native()
        part_check()
        part_repair()
        part_methods()
        part_language()
    except Exception:                                     # noqa: BLE001
        import traceback
        traceback.print_exc()
        problems.append("exception")
    print(f"\n{len(problems)} problems"
          + ("" if not problems else ": " + ", ".join(problems)))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())

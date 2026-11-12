"""meshfix repair: the mesh repair in Rust.

SHARED CODE: this module was fs_meshfix.py of OpenFOAM Studio. MeshFix
Studio and OpenFOAM Studio both use it (see PLAN.md).

WHAT IT IS. The method «Windows» of the «Repair» menu (meshfix.winfix)
calls the 3D-model repair service of Windows. meshfix (crates/meshfix,
module meshfix._native) repairs the mesh itself in 12 steps (STEPS below):
stitch seams, fill tiny holes, remove duplicates, fix the orientation,
fill all holes, merge the bodies, fix degenerate faces, remove tiny
shells, split T-junctions. The result is close to the Windows 3D-model
repair; this is checked by measurements on test meshes. The comments of
crates/meshfix/src/stages.rs describe the steps.

WHAT THE REPAIR DOES AND DOES NOT DO (measured on tests/meshfix_cases.py):
- it works without WinRT and on each operating system;
- it does NOT refine the mesh: a 10 mm cube keeps its 12 triangles;
- it does NOT move vertices of a clean mesh;
- bodies that intersect become one body (a union). Faces that touch
  almost coplanar (less than 0.5 deg) are a contact, not a cut. A cut
  group that would give open edges is left uncut;
- an edge or a vertex that two bodies share gets one copy for each body;
- the step merge_bodies cuts all faces against each other and keeps the
  faces between inside and outside by the winding number of the whole
  input (also of open parts). Steps after it do not make faces cross;
- the last step stl_safe_output (crates/meshfix/src/stlsafe.rs) makes the
  result keep its counts after a write to STL (float32) and a read that
  joins equal points: the copies of a pinched edge or vertex move apart by
  some float32 steps (about 1e-3 mm on a model of 3 m), and faces that the
  rounding makes degenerate get a flip or a small vertex move. Report key
  "stl_safe".
- fallbacks, when the 12 steps do not give a closed mesh: first an alpha
  wrap of the input (shrunk onto the input), then a volume rebuild.
  Each result is used only when it is closed and no count of the
  program's check is larger than in the input. Report key "fallback".

STEP IDS. The report gives each step by its id (ASCII, snake_case, the
same as Stage::name in crates/meshfix). The versions before 0.2.0 used
other ids: LEGACY_STEP_IDS maps them, and step_id() reads both.

FORCED METHODS. repair(..., method=...) with "alphawrap" or "volume" runs
only that fallback, also on a mesh that the 12 steps would make clean. The
«Repair» menu of the window gives these methods (METHODS below).

UNITS. The step tolerances are in mm. Thus the mesh goes from m to mm for
the repair and back, as in meshfix.winfix.
"""

from __future__ import annotations

import numpy as np
import pyvista as pv
from . import i18n as fs_i18n
from .i18n import tr

try:                                       # pragma: no cover - depends on the build
    from . import _native as _rs
except ImportError:                        # pragma: no cover
    _rs = None

M_TO_MM = 1000.0

# The steps: id (Stage::name in crates/meshfix) -> (the name of the step,
# the text of its count in the summary). The order is the order of the
# repair: the 12 steps, the two fallbacks, the last step.
STEPS = {
    "stitch_seams": ("Stitch seams", "stitched"),
    "fill_tiny_holes": ("Fill tiny holes", "3-edge holes"),
    "remove_duplicates": ("Remove duplicates", "duplicates removed"),
    "fix_orientation": ("Fix orientation", "triangles flipped"),
    "fill_tiny_holes_again": ("Fill tiny holes (2)", "3-edge holes (2)"),
    "stitch_seams_again": ("Stitch seams (2)", "stitched (2)"),
    "fix_orientation_again": ("Fix orientation (2)", "flipped (2)"),
    "fill_holes": ("Fill holes", "holes closed"),
    "merge_bodies": ("Merge bodies", "inner shells removed"),
    "fix_degenerate_faces": ("Fix degenerate faces", "degenerate faces fixed"),
    "remove_tiny_shells": ("Remove tiny shells", "tiny shells removed"),
    "split_t_junctions": ("Split T-junctions", "T-junctions cut"),
    "alpha_wrap": ("Alpha wrap", "alpha wrap, triangles"),
    "volume_rebuild": ("Volume rebuild", "volume rebuild, triangles"),
    "stl_safe_output": ("STL-safe output", "points moved for STL"),
}

# The step ids of the versions before 0.2.0 (a saved report, a script, a
# setting) -> the id of now. step_id() reads both.
LEGACY_STEP_IDS = {
    "Stitch1": "stitch_seams",
    "CloseTrivialHoles1": "fill_tiny_holes",
    "RemoveDoubleTriangles": "remove_duplicates",
    "FixFlipped1": "fix_orientation",
    "CloseTrivialHoles2": "fill_tiny_holes_again",
    "Stitch2": "stitch_seams_again",
    "FixFlipped2": "fix_orientation_again",
    "CloseAllHoles": "fill_holes",
    "Wrap": "merge_bodies",
    "RemoveDegeneratedFaces": "fix_degenerate_faces",
    "RemoveTinyShells": "remove_tiny_shells",
    "PrepareForExport": "split_t_junctions",
    "AlphaWrap": "alpha_wrap",
    "VolumeRemesh": "volume_rebuild",
    "StlSafe": "stl_safe_output",
}

# The text of the count of each step (the summary).
STEP_NAMES = {key: count for key, (_label, count) in STEPS.items()}


def step_id(name) -> str | None:
    """The id of a step; an old id (LEGACY_STEP_IDS) gives the id of now."""
    if name is None:
        return None
    return LEGACY_STEP_IDS.get(name, name)


def step_label(name) -> str:
    """The name of a step in the language of the interface."""
    key = step_id(name)
    return tr(STEPS[key][0]) if key in STEPS else str(name)


# Text for the status line when a fallback replaced the result.
FALLBACK_TEXT = {
    "alpha_wrap": "12 steps did not give a closed mesh — result: model "
                 "wrap (alpha wrap), shrunk onto the surface",
    "volume_rebuild": "12 steps did not give a closed mesh — result: "
                    "volume rebuild (parts thinner than ~0.7 mm can "
                    "disappear)",
}

# Methods of this module: key → (name in the status text, report key of
# the step that gives the result; None = the 12 steps).
METHODS = {
    "meshfix": ("meshfix", None),
    "alphawrap": ("alpha wrap", "alpha_wrap"),
    "volume": ("volume rebuild", "volume_rebuild"),
}

# Status text of a forced method.
FORCED_TEXT = {
    "alpha_wrap": "model wrap (alpha wrap), shrunk onto the surface",
    "volume_rebuild": "volume rebuild (parts thinner than ~0.7 mm may have "
                    "disappeared)",
}

# Report of the last repair. The window uses it for the status line.
last_report: dict | None = None


def available() -> bool:
    return _rs is not None and hasattr(_rs, "repair")


def why_not() -> str:
    if available():
        return ""
    return tr("The native module meshfix._native is missing. Install the "
              "package meshfix-core again, or build it: maturin develop "
              "-m crates/meshfix/Cargo.toml")


def _triangles(mesh: pv.PolyData) -> np.ndarray:
    faces = np.asarray(mesh.faces)
    if faces.size == 0 or faces.size % 4 or not np.all(faces[::4] == 3):
        mesh = mesh.triangulate()
        faces = np.asarray(mesh.faces)
    return faces.reshape(-1, 4)[:, 1:]


def repair_arrays(points_mm, tris, *, wrap: bool = True,
                  method: str = "meshfix", stl_safe: bool = True):
    """(points mm, triangles) → (points mm, triangles, report). No pyvista.

    stl_safe=False: no last step stl_safe_output. Use it when the program
    applies that step at the export to STL (meshfix.check.save_mesh).
    """
    if not available():
        raise RuntimeError(why_not())
    if method not in METHODS:
        raise ValueError(f"no meshfix method {method!r}")
    args = (np.ascontiguousarray(points_mm, dtype=np.float64),
            np.ascontiguousarray(tris, dtype=np.int64), True, bool(wrap))
    kw = {} if method == "meshfix" else {"method": method}
    if not stl_safe:
        kw["stl_safe"] = False
    return _rs.repair(*args, **kw)


# The end of a repair step text that is a verdict (what the repair did):
# the window keeps such a line in the log. A character, not a word of the
# text: the text is translated (T24). Invisible (U+2063).
VERDICT = "\u2063"


def summary(report: dict) -> str:
    """One line "what was done" from the steps with a count above zero."""
    parts = []
    fallback = step_id(report.get("fallback"))
    for name, count, _sec in report.get("stages", ()):
        name = step_id(name)
        if name in FALLBACK_TEXT and name != fallback:
            continue                       # ran, but its result was not used
        if count:
            parts.append(tr(STEP_NAMES.get(name, name)) + f" {count}")
    u = report.get("union") or {}
    if u.get("pairs"):
        parts.append(tr("body intersections cut {u}", u=u['pairs']))
    if u.get("skipped_clusters"):
        parts.append(tr("intersection spots left as they are {u}", u=u['skipped_clusters']))
    if u.get("rolled_back") or u.get("panicked"):
        parts.append(tr("merging the bodies failed — the bodies stay separate"))
    if report.get("guard"):
        return guard_text(report["guard"])
    if report.get("method", "meshfix") != "meshfix" and fallback in FORCED_TEXT:
        return tr(FORCED_TEXT[fallback])
    if fallback in FALLBACK_TEXT:
        return tr(FALLBACK_TEXT[fallback])
    after = report.get("after") or {}
    if after.get("boundary_edges") or after.get("non_manifold_edges"):
        # meshfix only cuts and joins closed bodies. An assembly with open
        # and non-manifold parts needs the full wrap of the Windows service.
        parts.append(tr("open edges left {get}, non-manifold {get2} — "
                        "for such an assembly, use “Windows” or “volume "
                        "rebuild” in the “Repair” menu", get=after.get('boundary_edges', 0), get2=after.get('non_manifold_edges', 0)))
    return (fs_i18n.join(", ", parts) if parts
            else tr("the steps changed nothing"))


def steps_text(report: dict) -> str:
    """Each step of the report on its own line: name, count, time."""
    out = []
    for name, count, sec in (report or {}).get("stages", ()):
        out.append(tr("{step}: {count} ({sec:.2f} s)", step=step_label(name),
                      count=count, sec=sec))
    return fs_i18n.join("\n", out)


def repair(mesh: pv.PolyData, say=None,
           method: str = "meshfix", stl_safe: bool = True) -> pv.PolyData:
    """A repaired copy of `mesh`. The input and the output are in m.

    The same contract as fs_winfix.repair: call it from a thread
    (RepairWorker). Rust releases the GIL, thus the window stays live.
    method: a key of METHODS. A forced method that gives no result raises
    RuntimeError (the window then puts the model back).
    stl_safe: the last step stl_safe_output (see repair_arrays).
    """
    global last_report
    say = say or (lambda _text: None)
    if mesh is None or mesh.n_cells == 0:
        raise ValueError(tr("Nothing to repair: the model has no triangles."))
    if not available():
        raise RuntimeError(why_not())
    tri = _triangles(mesh)
    pts = np.asarray(mesh.points, dtype=np.float64) * M_TO_MM
    label, stage = METHODS[method]
    say(tr("{label}: {n_tri} triangles{v}", label=label, n_tri=len(tri), v=", 12 steps" if stage is None else ""))
    try:
        kw = {} if stl_safe else {"stl_safe": False}
        out_p, out_t, report = repair_arrays(pts, tri, method=method, **kw)
    except ValueError as exc:
        raise RuntimeError(tr("{label} failed: {exc}.", label=label, exc=exc)) from exc
    last_report = report
    if stage is not None and step_id(report.get("fallback")) != stage:
        raise RuntimeError(forced_failure(method, report))
    say(tr(label) + ": " + summary(report) + VERDICT)
    if len(out_t) == 0:
        raise RuntimeError(tr("No triangles are left after the repair: the "
                           "model was flat or made only of tiny shells."))
    out_t = np.asarray(out_t, dtype=np.int64)
    out = pv.PolyData(
        np.asarray(out_p) / M_TO_MM,
        np.hstack([np.full((len(out_t), 1), 3, np.int64), out_t]).ravel())
    # Guard for the whole repair, with the counts of the program's own
    # check (the same numbers as «Дірки / Вивернуті / Non-manifold»). When
    # one of them is larger after the repair, the input comes back.
    worse = worse_than(mesh, out)
    report["guard"] = worse
    if worse:
        say(tr(label) + ": " + guard_text(worse) + VERDICT)
        return mesh.copy()
    return out


def forced_failure(method: str, report: dict) -> str:
    """Text for the dialog when a forced method gave no result."""
    if method == "volume":
        v = report.get("volume") or {}
        if v and 0 < v.get("volume_ratio", 1.0) <= 0.3:
            return (tr("The volume rebuild lost the body: {v:.0f}% of "
                       "the volume is left. Most often this is a large "
                       "hole through which the “outside” leaked inside. "
                       "Try meshfix or alpha wrap.", v=v['volume_ratio'] * 100))
        return (tr("The volume rebuild gave no surface: the model probably "
                "consists of parts thinner than ~0.7 mm."))
    return (tr("Alpha wrap did not give a closed shell. Try meshfix or the "
            "volume rebuild."))


# Program counts that the guard compares: (key, label for the status line).
GUARD_COUNTS = (("open_edges", "holes"), ("flipped_faces", "flipped"),
                ("non_manifold_edges", "non-manifold"))


def worse_than(before: pv.PolyData, after: pv.PolyData) -> list:
    """[(label, before, after)] for each program count that got larger."""
    from . import check as geo
    d0, d1 = geo.diagnose(before), geo.diagnose(after)
    return [(label, getattr(d0, key), getattr(d1, key))
            for key, label in GUARD_COUNTS
            if getattr(d1, key) > getattr(d0, key)]


def guard_text(worse: list) -> str:
    return (tr("the result is worse than the input model ({join}) — the "
               "model stays unchanged", join=", ".join(f"{label} {a} → {b}" for label, a, b in worse)))

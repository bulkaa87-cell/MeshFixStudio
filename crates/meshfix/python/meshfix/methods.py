"""The repair methods and the repair call: ONE place for all programs.

SHARED CODE: this module was fs_repair.py of OpenFOAM Studio. MeshFix
Studio and OpenFOAM Studio («Repair» in the geometry panel) repair a mesh
with the same code. Both use this module. Do not repair a mesh in a window
module: put a change here, in meshfix.repair or in crates/meshfix, and run
the tests (tests/test_core.py, tests/test_app.py, and the tests of
OpenFOAM Studio after it moves its pin).

What is here:
- METHODS: the method list (key, label, tooltip) in the order of the menu.
  DEFAULT is the first method.
- available(key), why_not(key): is the tool of the method on this computer.
- mode(key): "parts" (each model is repaired alone) or "wrap" (one shell
  from all models together).
- repair_meshes(key, meshes, say): the repair. Call it from a worker thread,
  never from the thread of the window.
- repair_bodies(key, mesh, say): the repair of each body of one mesh (the
  bodies of a 3MF, OBJ, ASCII STL or glTF file, meshfix.formats), with the
  names of the bodies.
- counts(diagnosis), COUNTS: the four counts of the program check that a
  repair must make zero.
- summary(key): the text "what the last repair did" (meshfix methods).
- steps(key): each step of the last repair on its own line (meshfix
  methods), with the step names of meshfix.repair.STEPS.

The meshes are in metres, as in meshfix.repair and meshfix.winfix: the tolerances of
the repair are in mm, and these modules change the units for the repair.
"""

from __future__ import annotations

from . import repair as fs_meshfix
from . import winfix as fs_winfix
from .i18n import tr

# (key, label, tooltip). The keys are the data of the menu items: the code
# reads the key, never the label.
METHODS = (
    ("meshfix", "meshfix",
     "Our own repair in Rust (crates/meshfix), without the Windows service: "
     "stitch gaps up to 0.01 mm, remove duplicates, make normals consistent, "
     "close all holes, merge bodies that cut into each other, remove nested "
     "and tiny shells. The surface stays in place. If the mesh still did not "
     "close, it uses alpha wrap by itself, and then the volume rebuild."),
    ("alphawrap", "alpha wrap",
     "Wrap the whole assembly in one shell (alpha wrap in Rust, in the "
     "program itself) and shrink it onto the surface. The shell is closed, "
     "edges stay edges. Cost: narrow cavities (the gap between a nacelle and "
     "the skin) are filled, all models become one body"),
    ("winfix", "Windows",
     "Repair service built into Windows (Netfabb) — the same as “Fix model” "
     "in Bambu Studio, Orca and PrusaSlicer. Refines the mesh and moves "
     "vertices slightly. It takes long: about a minute per 250k triangles"),
    ("volume", "volume rebuild",
     "For very dirty models: the model is rebuilt from zero on a cell grid, "
     "the face orientation does not matter. The result is always closed, but "
     "details thinner than ~0.7 mm disappear. All models become one body"),
)

DEFAULT = METHODS[0][0]
KEYS = tuple(key for key, _label, _tip in METHODS)

# Methods that make one shell from all models (mode "wrap").
WHOLE = ("alphawrap", "volume")

# The counts of the program check (fs_geometry.Diagnosis) that a repair
# must make zero: (attribute, label). The same four layers as the «3D» tab.
COUNTS = (("open_edges", "Holes (open edges)"),
          ("flipped_faces", "Flipped faces"),
          ("non_manifold_edges", "Non-manifold edges"),
          ("degenerate", "Degenerate faces"))


def label(key: str) -> str:
    for k, text, _tip in METHODS:
        if k == key:
            return tr(text)
    return key


def tooltip(key: str) -> str:
    for k, _text, tip in METHODS:
        if k == key:
            return tr(tip)
    return ""


def _tool(key: str):
    if key not in KEYS:
        raise ValueError(f"no repair method {key!r}")
    return fs_winfix if key == "winfix" else fs_meshfix


def available(key: str) -> bool:
    """Is the tool of this method on this computer?"""
    return _tool(key).available()


def why_not(key: str) -> str:
    """Why the method is not available ("" if it is)."""
    return _tool(key).why_not()


def mode(key: str) -> str:
    """"wrap": one shell from all models; "parts": each model alone."""
    _tool(key)
    return "wrap" if key in WHOLE else "parts"


def _merge(meshes):
    if len(meshes) == 1:
        return meshes[0]
    return meshes[0].merge(list(meshes[1:]), merge_points=False)


def repair_meshes(key: str, meshes, say=None, merged=None,
                  stl_safe: bool = True) -> list:
    """Repaired copies of `meshes` (pyvista PolyData in m).

    mode(key) == "parts": one result for each input mesh, in the same order.
    mode(key) == "wrap": one result, made from `merged` (the scene of the
    window) or from all `meshes` together.

    `say(text)` receives the progress texts. A text that ends with
    fs_meshfix.VERDICT tells what the repair did (a window keeps it).
    stl_safe=False: the meshfix methods do not run their last step
    stl_safe_output. A program that writes the result with
    meshfix.check.save_mesh gives False: save_mesh applies the step only
    at an export to STL (the other formats keep the points as they are).
    Raises RuntimeError when the method failed or is not available.
    Call it from a worker thread: a repair can take minutes.
    """
    say = say or (lambda _text: None)
    if not available(key):
        raise RuntimeError(why_not(key))
    meshes = list(meshes)
    if mode(key) == "wrap":
        whole = merged if merged is not None else _merge(meshes)
        return [fs_meshfix.repair(whole, say, method=key, stl_safe=stl_safe)]
    out = []
    for i, mesh in enumerate(meshes, 1):
        head = (tr("model {i} of {n_meshes}: ", i=i, n_meshes=len(meshes))
                if len(meshes) > 1 else "")

        def tell(text, h=head):
            say(h + text)
        if key == "winfix":
            out.append(fs_winfix.repair(mesh, tell))
        else:
            out.append(fs_meshfix.repair(mesh, tell, method=key,
                                          stl_safe=stl_safe))
    return out


def repair_bodies(key: str, mesh, say=None, stl_safe: bool = True):
    """Repair each body of `mesh` alone (repair_meshes) and keep the body
    names (meshfix.formats.BODY). A method of mode "wrap" makes one shell
    of all bodies: then the result is one body. A mesh without bodies gives
    the result of repair_meshes as it is. Call it from a worker thread."""
    from . import formats
    bodies = formats.split_bodies(mesh)
    kw = {} if stl_safe else {"stl_safe": False}      # an old spy has no kw
    outs = repair_meshes(key, [m for _n, m in bodies], say, **kw)
    if len(outs) != len(bodies):
        return outs[0]
    if len(bodies) == 1 and not bodies[0][0]:
        return outs[0]
    return formats.join_bodies([(name, out) for (name, _m), out
                                in zip(bodies, outs)])


def counts(diagnosis) -> dict:
    """{attribute: count} of COUNTS for a fs_geometry.Diagnosis."""
    return {attr: int(getattr(diagnosis, attr)) for attr, _label in COUNTS}


def clean(diagnosis) -> bool:
    """True when all four counts are zero (a closed, clean surface)."""
    return not any(counts(diagnosis).values())


def summary(key: str) -> str:
    """What the last meshfix repair did ("" for other methods)."""
    if key in fs_meshfix.METHODS and fs_meshfix.last_report:
        return fs_meshfix.summary(fs_meshfix.last_report)
    return ""


def steps(key: str) -> str:
    """Each step of the last repair with its count and time, one per line
    (meshfix methods; empty for the other methods)."""
    if key in fs_meshfix.METHODS and fs_meshfix.last_report:
        return fs_meshfix.steps_text(fs_meshfix.last_report)
    return ""

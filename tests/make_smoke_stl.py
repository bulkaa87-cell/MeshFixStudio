"""Write the input of the smoke test of a built program: a sphere (r 20 mm)
with a cut cap and a flipped part, as a binary STL.

    python tests/make_smoke_stl.py OUT.stl
    "MeshFix Studio" --smoke-test OUT.stl REPAIRED.stl   (exit code 0 = ok)
"""

import os
import sys

import numpy as np
import pyvista as pv

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import meshfix_cases as mc  # noqa: E402


def main(path: str) -> None:
    p, t = mc.icosphere(r=20.0, level=3)
    centre = p[t].mean(1)
    t = t[centre[:, 2] < 17.0]                      # a hole at the top
    q, u = mc.cube(8.0, (40.0, 0.0, 0.0))
    u = u[:, ::-1]                                  # a cube inside out
    pts = np.vstack([p, q])
    tris = np.vstack([t, u + len(p)])
    mesh = pv.PolyData(pts, np.hstack([np.full((len(tris), 1), 3), tris]).ravel())
    mesh.save(path, binary=True)
    print(f"{path}: {mesh.n_cells} triangles")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "smoke.stl")

"""Small test meshes for the mesh repair (meshfix and the Windows repair).

Each case is a pair (points in mm, triangles). The units are mm because the
two repairs measure their tolerances in mm. The cases are the same in
crates/meshfix/src/tests.rs, so the Python comparison and the cargo tests use
one set of defects.

stats() gives the numbers that the comparison table shows.
"""

from __future__ import annotations

import numpy as np

CUBE_T = np.array([[0, 2, 1], [0, 3, 2], [4, 5, 6], [4, 6, 7], [0, 1, 5],
                   [0, 5, 4], [3, 7, 6], [3, 6, 2], [0, 4, 7], [0, 7, 3],
                   [1, 2, 6], [1, 6, 5]], np.int64)


def cube(size=10.0, origin=(0.0, 0.0, 0.0)):
    v = np.array([[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0],
                  [0, 0, 1], [1, 0, 1], [1, 1, 1], [0, 1, 1]], float)
    return v * size + np.asarray(origin, float), CUBE_T.copy()


def join(*parts):
    pts, tri, off = [], [], 0
    for p, t in parts:
        pts.append(p)
        tri.append(t + off)
        off += len(p)
    return np.vstack(pts), np.vstack(tri)


def soup(p, t):
    """Each triangle gets its own three vertices (an unwelded STL)."""
    return p[t.reshape(-1)].copy(), np.arange(t.size).reshape(-1, 3)


def cylinder(r=5.0, h=10.0, n=24):
    a = np.linspace(0, 2 * np.pi, n, endpoint=False)
    ring = np.c_[r * np.cos(a), r * np.sin(a), np.zeros(n)]
    p = np.vstack([ring, ring + [0, 0, h]])
    t = []
    for i in range(n):
        j = (i + 1) % n
        t += [[i, j, n + j], [i, n + j, n + i]]
    return p, np.array(t, np.int64)


def icosphere(r=5.0, level=2):
    g = (1 + 5 ** 0.5) / 2
    v = [[-1, g, 0], [1, g, 0], [-1, -g, 0], [1, -g, 0], [0, -1, g],
         [0, 1, g], [0, -1, -g], [0, 1, -g], [g, 0, -1], [g, 0, 1],
         [-g, 0, -1], [-g, 0, 1]]
    f = [[0, 11, 5], [0, 5, 1], [0, 1, 7], [0, 7, 10], [0, 10, 11],
         [1, 5, 9], [5, 11, 4], [11, 10, 2], [10, 7, 6], [7, 1, 8],
         [3, 9, 4], [3, 4, 2], [3, 2, 6], [3, 6, 8], [3, 8, 9],
         [4, 9, 5], [2, 4, 11], [6, 2, 10], [8, 6, 7], [9, 8, 1]]
    v = [np.array(x, float) / np.linalg.norm(x) for x in v]
    for _ in range(level):
        mid, nf = {}, []

        def m(a, b):
            k = (min(a, b), max(a, b))
            if k not in mid:
                c = v[a] + v[b]
                v.append(c / np.linalg.norm(c))
                mid[k] = len(v) - 1
            return mid[k]
        for a, b, c in f:
            ab, bc, ca = m(a, b), m(b, c), m(c, a)
            nf += [[a, ab, ca], [b, bc, ab], [c, ca, bc], [ab, bc, ca]]
        f = nf
    return np.array(v) * r, np.array(f, np.int64)


def seam(gap, size=10.0):
    """A cube with the top edge 4-5 split: the top face uses its own copies
    of vertices 4 and 5, moved up by `gap`. This gives one thin hole of
    width `gap` around the front-top edge. A stitch gives 8 vertices, a hole
    fill gives 10."""
    p, t = cube(size)
    p = np.vstack([p, p[4] + [0, 0, gap], p[5] + [0, 0, gap]])
    t[2] = [8, 9, 6]
    t[3] = [8, 6, 7]
    return p, t


def degenerate():
    """A closed cube with one zero-area triangle on the edge 4-5."""
    p, t = cube()
    p = np.vstack([p, (p[4] + p[5]) / 2])        # vertex 8 = midpoint
    t = t.tolist()
    t[2] = [4, 8, 6]
    t.append([8, 5, 6])
    t.append([8, 4, 5])
    return p, np.array(t, np.int64)


def flip(p, t, rows):
    t = t.copy()
    t[rows] = t[rows][:, ::-1]
    return p, t


def cases():
    """Name → (points mm, triangles)."""
    c = {}
    c["cube"] = cube()
    c["soup"] = soup(*cube())
    p, t = cube()
    c["hole_tri"] = (p, np.delete(t, 2, 0))
    c["hole_quad"] = (p, np.delete(t, [2, 3], 0))
    c["open_cyl"] = cylinder()
    p, t = icosphere()
    cen = p[t].mean(1)
    c["sphere_hole"] = (p, t[cen[:, 2] < 4.0])      # cap of ~10 faces cut off
    c["flip_one"] = flip(*cube(), [6])
    c["inverted"] = flip(*cube(), slice(None))
    p, t = cube()
    c["dup_tri"] = (p, np.vstack([t, t[:1]]))
    c["degenerate"] = degenerate()
    for g in (0.005, 0.009, 0.011, 0.02, 0.05):
        c[f"seam_{g:g}"] = seam(g)
    for g in (0.02, 0.03):                       # 1000 mm → scale 0.4
        c[f"seam1000_{g:g}"] = seam(g, 1000.0)
    for g in (0.0015, 0.003):
        c[f"seam1_{g:g}"] = seam(g, 1.0)
    for s in (0.05, 0.08, 0.12, 0.3):
        c[f"tiny_{s:g}"] = join(cube(), cube(s, (20, 0, 0)))
    c["nonmanifold"] = _shared_edge()
    c["overlap"] = join(cube(), cube(10, (5, 5, 5)))
    c["nested"] = join(cube(), cube(4, (3, 3, 3)))
    c["plate"] = (np.array([[0, 0, 0], [10, 0, 0], [10, 10, 0], [0, 10, 0]],
                           float), np.array([[0, 1, 2], [0, 2, 3]], np.int64))
    c["overlap_rot"] = join(cube(), turned(cube(10), (6, 4, 3)))
    c["overlap3"] = join(cube(), cube(10, (5, 5, 5)),
                         turned(cube(8), (2, -4, 4), 25, 35))
    c["touch_corner"] = _shared_corner()
    c["c_hole"] = c_prism()
    # Regressions from a real aircraft model (interceptor, 251k faces):
    # bodies that touch with their own vertex copies, and a flap face on a
    # cube edge (3 faces on one edge).
    c["touch_copies"] = join(cube(), cube(10, (10, 10, 0)))
    p, t = cube()
    c["fin"] = (np.vstack([p, [[10, -5, 5]]]),
                np.vstack([t, [[5, 1, 8]]]))
    return c


def turned(mesh, shift, az=30.0, ax=20.0):
    """The mesh turned by `az` deg about z and `ax` deg about x (about its
    centre), then moved by `shift`. A general position: no edge of it lies
    on an edge or a face of an axis-aligned cube."""
    p, t = mesh
    a, b = np.radians(az), np.radians(ax)
    rz = np.array([[np.cos(a), -np.sin(a), 0], [np.sin(a), np.cos(a), 0],
                   [0, 0, 1]])
    rx = np.array([[1, 0, 0], [0, np.cos(b), -np.sin(b)],
                   [0, np.sin(b), np.cos(b)]])
    c = p.mean(0)
    return (p - c) @ (rx @ rz).T + c + np.asarray(shift, float), t


def c_prism(n=160, r_out=5.0, r_in=3.0, h=10.0, gap_deg=60.0):
    """A C-shaped prism, open at both ends: two concave holes of 2n
    vertices. The centroid of the C is outside the C, so a fan from the
    centroid overlaps itself."""
    a = np.radians(np.linspace(gap_deg / 2, 360 - gap_deg / 2, n))
    outer = np.c_[r_out * np.cos(a), r_out * np.sin(a)]
    inner = np.c_[r_in * np.cos(a[::-1]), r_in * np.sin(a[::-1])]
    ring = np.vstack([outer, inner])                 # counter-clockwise
    m = len(ring)
    p = np.vstack([np.c_[ring, np.zeros(m)], np.c_[ring, np.full(m, h)]])
    t = []
    for i in range(m):
        j = (i + 1) % m
        t += [[i, j, m + j], [i, m + j, m + i]]
    return p, np.array(t, np.int64)


def _shared_corner():
    """Two cubes that touch at one corner (10, 10, 10), welded."""
    p, t = join(cube(), cube(10, (10, 10, 10)))
    t[t == 8] = 6                      # vertex 0 of cube B = vertex 6 of A
    return p, t


def _shared_edge():
    """Two cubes that touch along one edge (x = y = 10), welded."""
    p, t = join(cube(), cube(10, (10, 10, 0)))
    # vertices 2 (10,10,0) and 6 (10,10,10) of cube A = 8 and 12 of cube B
    t[t == 8] = 2
    t[t == 12] = 6
    return p, t


# --------------------------------------------------------------------------

def stats(p, t):
    """Counts for the comparison table, from the indexed mesh as given."""
    p = np.asarray(p, float)
    t = np.asarray(t, np.int64).reshape(-1, 3)
    e = np.sort(np.vstack([t[:, [0, 1]], t[:, [1, 2]], t[:, [2, 0]]]), 1)
    _, inv, cnt = np.unique(e, axis=0, return_inverse=True,
                            return_counts=True)
    inv = inv.reshape(-1)
    boundary = int((cnt == 1).sum())
    nonman = int((cnt > 2).sum())
    # directed edges: a manifold edge is consistent when the two faces use it
    # in opposite directions
    d = np.vstack([t[:, [0, 1]], t[:, [1, 2]], t[:, [2, 0]]])
    fwd = d[:, 0] < d[:, 1]
    order = np.argsort(inv, kind="stable")
    sk = inv[order]
    start = np.r_[0, np.nonzero(np.diff(sk))[0] + 1]
    two = start[cnt[sk[start]] == 2]
    flipped = int((fwd[order[two]] == fwd[order[two + 1]]).sum())
    # shells = edge-connected face groups (union-find with numpy)
    nf = len(t)
    face = np.tile(np.arange(nf), 3)[order]
    same = np.nonzero(np.diff(sk) == 0)[0]
    fa, fb = face[same], face[same + 1]
    lab = np.arange(nf)
    while len(fa):
        ra, rb = lab[fa], lab[fb]
        if np.array_equal(ra, rb):
            break
        lo = np.minimum(ra, rb)
        np.minimum.at(lab, ra, lo)
        np.minimum.at(lab, rb, lo)
        while True:
            nxt = lab[lab]
            if np.array_equal(nxt, lab):
                break
            lab = nxt
    shells = len(np.unique(lab)) if nf else 0
    a, b, c = p[t[:, 0]], p[t[:, 1]], p[t[:, 2]]
    vol = float(np.einsum("ij,ij->i", a, np.cross(b, c)).sum() / 6.0)
    used = np.unique(t)
    return {"V": len(used), "F": nf, "open": boundary, "nm": nonman,
            "flip": flipped, "shells": shells, "vol": vol}

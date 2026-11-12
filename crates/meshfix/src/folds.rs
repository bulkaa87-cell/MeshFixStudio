//! Inner folds (T12b, option MESHFIX_FOLD_CLOSE, default off).
//!
//! After the winding union, a thin crack can stay in the body: two kept
//! faces that share an edge fold onto each other (normals more than about
//! 170 degrees apart), both normals point into the thin wedge between
//! them, and the input is inside in that wedge. The label of a patch is
//! the label of most of its area, thus the walls of such a crack stay.
//!
//! `close_inner_folds` removes groups of such faces and closes each hole
//! with the minimum-area triangulation of its rim. Across a thin crack this
//! gives a narrow cap that is almost normal to the walls, so the walls that
//! stay do not fold. A group is kept only when:
//!
//! - its hole has one simple rim of at most `MAX_RIM` vertices;
//! - each point of the fill is nearer than `tol` to the removed faces;
//! - no face of the fill folds onto a neighbor;
//! - no face of the fill crosses another face (checked for all groups
//!   together, the groups with a crossing go back, two passes);
//! - the mesh stays closed and manifold.

use crate::aabb::closest_on_tri;
use crate::math::*;
use crate::mesh::*;
use crate::union::Fwn;
use rayon::prelude::*;
use std::collections::{HashMap, HashSet};

/// Largest rim of a hole that gets a fill.
const MAX_RIM: usize = 160;
/// Largest group of faces that is removed in one piece.
const MAX_GROUP: usize = 48;
/// Dot product of two unit normals below which two faces fold.
const FOLD_DOT: f64 = -0.985;

/// Report of `close_inner_folds`.
#[derive(Debug, Default, Clone)]
pub struct FoldReport {
    /// Fold edges with the input inside in the wedge.
    pub inner_edges: usize,
    /// Groups of faces tried.
    pub groups: usize,
    /// Groups removed and closed.
    pub closed: usize,
    /// Groups not used, by the reason.
    pub bad_rim: usize,
    pub far: usize,
    pub new_fold: usize,
    pub crossing: usize,
    pub not_manifold: usize,
    /// Faces removed and faces added.
    pub removed_faces: usize,
    pub added_faces: usize,
}

fn unit_normal(m: &Mesh, f: usize) -> Vec3 {
    let [a, b, c] = m.tri_pos(f);
    let n = cross(sub(b, a), sub(c, a));
    let l = norm(n);
    if l > 0.0 {
        scale(n, 1.0 / l)
    } else {
        [0.0; 3]
    }
}

fn centroid(m: &Mesh, f: usize) -> Vec3 {
    let [a, b, c] = m.tri_pos(f);
    scale(add(add(a, b), c), 1.0 / 3.0)
}

/// The faces of the fold edges of `mesh` whose wedge holds the input
/// (winding number of `input` above `w_min` at the middle of the two
/// centroids), with both normals into the wedge.
fn inner_fold_faces(mesh: &Mesh, ef: &EdgeFaces, fwn: &Fwn, w_min: f64) -> (Vec<u32>, usize) {
    let nrm: Vec<Vec3> = (0..mesh.triangles.len()).map(|f| unit_normal(mesh, f)).collect();
    let cands: Vec<(u32, u32)> = ef
        .values()
        .filter(|fs| fs.len() == 2)
        .filter_map(|fs| {
            let (f, g) = (fs[0] as usize, fs[1] as usize);
            if dot(nrm[f], nrm[g]) >= FOLD_DOT {
                return None;
            }
            let (cf, cg) = (centroid(mesh, f), centroid(mesh, g));
            let mid = scale(add(cf, cg), 0.5);
            let into = dot(nrm[f], sub(mid, cf)) > 0.0 && dot(nrm[g], sub(mid, cg)) > 0.0;
            into.then_some((fs[0], fs[1]))
        })
        .collect();
    let inner: Vec<bool> = cands
        .par_iter()
        .map(|&(f, g)| {
            let mid = scale(add(centroid(mesh, f as usize), centroid(mesh, g as usize)), 0.5);
            fwn.eval(mid, None) > w_min
        })
        .collect();
    let mut out: Vec<u32> = Vec::new();
    let mut n = 0;
    for (&(f, g), &ok) in cands.iter().zip(&inner) {
        if ok {
            out.push(f);
            out.push(g);
            n += 1;
        }
    }
    out.sort_unstable();
    out.dedup();
    (out, n)
}

/// Groups of the marked faces joined through shared edges, at most
/// MAX_GROUP faces each (breadth first from the lowest face id).
fn groups(mesh: &Mesh, ef: &EdgeFaces, marked: &[u32]) -> Vec<Vec<u32>> {
    let set: HashSet<u32> = marked.iter().copied().collect();
    let mut seen: HashSet<u32> = HashSet::new();
    let mut out = Vec::new();
    for &s in marked {
        if seen.contains(&s) {
            continue;
        }
        let mut g = vec![s];
        seen.insert(s);
        let mut i = 0;
        while i < g.len() && g.len() < MAX_GROUP {
            let t = mesh.triangles[g[i] as usize];
            for k in 0..3 {
                if let Some(fs) = ef.get(&ekey(t[k], t[(k + 1) % 3])) {
                    for &h in fs {
                        if g.len() < MAX_GROUP && set.contains(&h) && seen.insert(h) {
                            g.push(h);
                        }
                    }
                }
            }
            i += 1;
        }
        out.push(g);
    }
    out
}

/// The rim of a group: the directed edges of its faces that no other face
/// of the group has, as one simple loop. None when there are more loops or
/// a vertex is on the rim two times.
fn rim(mesh: &Mesh, group: &[u32]) -> Option<Vec<u32>> {
    let mut cnt: HashMap<EdgeKey, i32> = HashMap::new();
    for &f in group {
        let t = mesh.triangles[f as usize];
        for k in 0..3 {
            *cnt.entry(ekey(t[k], t[(k + 1) % 3])).or_default() += 1;
        }
    }
    let mut next: HashMap<u32, u32> = HashMap::new();
    for &f in group {
        let t = mesh.triangles[f as usize];
        for k in 0..3 {
            let (a, b) = (t[k], t[(k + 1) % 3]);
            if cnt[&ekey(a, b)] == 1 && next.insert(a, b).is_some() {
                return None;
            }
        }
    }
    let &start = next.keys().min()?;
    let mut lp = vec![start];
    let mut x = next[&start];
    while x != start {
        if lp.len() > next.len() {
            return None;
        }
        lp.push(x);
        x = *next.get(&x)?;
    }
    (lp.len() == next.len() && lp.len() >= 3).then_some(lp)
}

/// Minimum-area triangulation of `poly` (same order as the removed faces).
fn fill(v: &[Vec3], poly: &[u32], ef: &EdgeFaces) -> Vec<[u32; 3]> {
    let n = poly.len();
    let used = |i: usize, j: usize| ef.contains_key(&ekey(poly[i], poly[j]));
    let p = |i: usize| v[poly[i] as usize];
    let mut w = vec![f64::INFINITY; n * n];
    let mut o = vec![0usize; n * n];
    for i in 0..n - 1 {
        w[i * n + i + 1] = 0.0;
    }
    for len in 2..n {
        for i in 0..n - len {
            let j = i + len;
            if !(i == 0 && j == n - 1) && used(i, j) {
                continue;
            }
            for m in i + 1..j {
                let c = w[i * n + m] + w[m * n + j] + tri_area(p(i), p(m), p(j));
                if c < w[i * n + j] {
                    w[i * n + j] = c;
                    o[i * n + j] = m;
                }
            }
        }
    }
    if !w[n - 1].is_finite() {
        return Vec::new();
    }
    let mut out = Vec::new();
    let mut st = vec![(0usize, n - 1)];
    while let Some((i, j)) = st.pop() {
        if j < i + 2 {
            continue;
        }
        let m = o[i * n + j];
        out.push([poly[i], poly[m], poly[j]]);
        st.push((i, m));
        st.push((m, j));
    }
    out
}

fn tri_unit(v: &[Vec3], t: [u32; 3]) -> Vec3 {
    let (a, b, c) = (v[t[0] as usize], v[t[1] as usize], v[t[2] as usize]);
    let n = cross(sub(b, a), sub(c, a));
    let l = norm(n);
    if l > 0.0 {
        scale(n, 1.0 / l)
    } else {
        [0.0; 3]
    }
}

/// One plan: the faces of a group and the fill of its hole.
struct Plan {
    remove: Vec<u32>,
    add: Vec<[u32; 3]>,
}

/// Plan for one group, or the reason why not (1 rim, 2 far, 3 fold).
fn plan_group(mesh: &Mesh, ef: &EdgeFaces, group: &[u32], tol: f64) -> Result<Plan, u8> {
    let lp = rim(mesh, group).ok_or(1u8)?;
    if lp.len() > MAX_RIM {
        return Err(1);
    }
    let tris = fill(&mesh.vertices, &lp, ef);
    if tris.len() != lp.len() - 2 {
        return Err(1);
    }
    let v = &mesh.vertices;
    // Each point of the fill near the removed faces: the centroid and the
    // edge midpoints of each fill face.
    let removed: Vec<[Vec3; 3]> = group.iter().map(|&f| mesh.tri_pos(f as usize)).collect();
    let near = |p: Vec3| removed.iter().any(|r| dist(p, closest_on_tri(p, r[0], r[1], r[2])) <= tol);
    for t in &tris {
        let (a, b, c) = (v[t[0] as usize], v[t[1] as usize], v[t[2] as usize]);
        let pts = [scale(add(add(a, b), c), 1.0 / 3.0), scale(add(a, b), 0.5), scale(add(b, c), 0.5), scale(add(c, a), 0.5)];
        if !pts.iter().all(|&p| near(p)) {
            return Err(2);
        }
    }
    // No new fold: between two fill faces, and between a fill face and the
    // face that stays on the other side of a rim edge.
    let gset: HashSet<u32> = group.iter().copied().collect();
    let mut fill_edge: HashMap<EdgeKey, Vec<Vec3>> = HashMap::new();
    for t in &tris {
        let n = tri_unit(v, *t);
        for k in 0..3 {
            fill_edge.entry(ekey(t[k], t[(k + 1) % 3])).or_default().push(n);
        }
    }
    for (e, ns) in &fill_edge {
        let mut all: Vec<Vec3> = ns.clone();
        if let Some(fs) = ef.get(e) {
            for &h in fs {
                if !gset.contains(&h) {
                    all.push(unit_normal(mesh, h as usize));
                }
            }
        }
        if all.len() != 2 {
            return Err(1);
        }
        if dot(all[0], all[1]) < FOLD_DOT {
            return Err(3);
        }
    }
    Ok(Plan { remove: group.to_vec(), add: tris })
}

/// Remove the walls of thin inner cracks and close them (see the module).
/// `input` is the mesh of the input of the union (for the winding number);
/// `tol` is the largest distance of the fill from the removed faces.
pub fn close_inner_folds(mesh: &mut Mesh, input: &Mesh, tol: f64, w_min: f64) -> FoldReport {
    let mut rep = FoldReport::default();
    if mesh.defect_edges() > 0 {
        return rep;
    }
    let all: Vec<u32> = (0..input.triangles.len() as u32).collect();
    let fwn = Fwn::with_beta(input, &all, 2.0);
    let ef = mesh.edge_faces();
    let (marked, n_inner) = inner_fold_faces(mesh, &ef, &fwn, w_min);
    rep.inner_edges = n_inner;
    let gs = groups(mesh, &ef, &marked);
    rep.groups = gs.len();
    let results: Vec<Result<Plan, u8>> = gs.par_iter().map(|g| plan_group(mesh, &ef, g, tol)).collect();
    let mut plans: Vec<Plan> = Vec::new();
    for r in results {
        match r {
            Ok(p) => plans.push(p),
            Err(1) => rep.bad_rim += 1,
            Err(2) => rep.far += 1,
            _ => rep.new_fold += 1,
        }
    }
    // Two plans must not add the same edge (an edge with four faces).
    {
        let mut owner: HashMap<EdgeKey, usize> = HashMap::new();
        let mut drop = vec![false; plans.len()];
        for (i, p) in plans.iter().enumerate() {
            for t in &p.add {
                for k in 0..3 {
                    let e = ekey(t[k], t[(k + 1) % 3]);
                    if let Some(&j) = owner.get(&e) {
                        if j != i && !ef.contains_key(&e) {
                            drop[i] = true;
                            drop[j] = true;
                        }
                    } else {
                        owner.insert(e, i);
                    }
                }
            }
        }
        let n0 = plans.len();
        let mut i = 0;
        plans.retain(|_| {
            i += 1;
            !drop[i - 1]
        });
        rep.not_manifold += n0 - plans.len();
    }
    let base = mesh.clone();
    let mut clean = false;
    for _pass in 0..4 {
        *mesh = base.clone();
        let mut gone = vec![false; mesh.triangles.len()];
        for p in &plans {
            for &f in &p.remove {
                gone[f as usize] = true;
            }
        }
        // Not retain_faces: it renumbers the vertices, and the plans use
        // the vertex ids of `base`.
        let mut i = 0;
        mesh.triangles.retain(|_| {
            i += 1;
            !gone[i - 1]
        });
        let n_base = mesh.triangles.len();
        let mut owner: Vec<usize> = Vec::new();
        for (i, p) in plans.iter().enumerate() {
            for t in &p.add {
                mesh.triangles.push(*t);
                owner.push(i);
            }
        }
        let active: Vec<bool> = (0..mesh.triangles.len()).map(|f| f >= n_base).collect();
        let pairs = crate::alphawrap::crossing_pairs_opt(mesh, Some(&active), false);
        let mut bad = vec![false; plans.len()];
        for (f, g) in pairs {
            for h in [f as usize, g as usize] {
                if h >= n_base {
                    bad[owner[h - n_base]] = true;
                }
            }
        }
        if !bad.iter().any(|&b| b) {
            clean = true;
            break;
        }
        let n0 = plans.len();
        let mut i = 0;
        plans.retain(|_| {
            i += 1;
            !bad[i - 1]
        });
        rep.crossing += n0 - plans.len();
        if plans.is_empty() {
            *mesh = base.clone();
            break;
        }
    }
    if !clean || mesh.defect_edges() > 0 {
        *mesh = base;
        if clean {
            rep.not_manifold += plans.len();
        }
        return rep;
    }
    mesh.compact();
    rep.closed = plans.len();
    rep.removed_faces = plans.iter().map(|p| p.remove.len()).sum();
    rep.added_faces = plans.iter().map(|p| p.add.len()).sum();
    rep
}

// ---- vertices on straight fold lines -------------------------------------

/// T12b approach B (option MESHFIX_FOLD_VERTS, default off): remove the
/// vertices inside straight fold lines when the shape stays the same.
///
/// A fold line is a chain of edges whose two faces fold onto each other
/// (normals more than about 170 degrees apart). The cut curves of the
/// union put many vertices on such a line. A vertex `v` goes (its edge to
/// the next vertex `u` on the line collapses into `u`) when:
///
/// - `v` has exactly two fold edges, and they are on one straight line
///   (angle below `ang_tol`, in radians);
/// - each face at `v` lies in the plane of one of the two walls (normal
///   within `ang_tol` of the wall normal), thus the moved faces stay in
///   their planes;
/// - each moved face keeps its orientation, its plane and an area above
///   zero;
/// - `u` and `v` have only the two far corners of the removed faces as
///   common neighbors (the mesh stays manifold).
///
/// Only the triangulation of the two walls changes; the surface moves by
/// less than `ang_tol` times the local edge length. Returns the number of
/// vertices removed.
pub fn remove_fold_line_vertices(mesh: &mut Mesh, ang_tol: f64) -> usize {
    let cos_tol = 1.0 - 0.5 * ang_tol * ang_tol;
    let nf = mesh.triangles.len();
    let mut nrm: Vec<Vec3> = (0..nf).map(|f| unit_normal(mesh, f)).collect();
    let mut area: Vec<f64> = (0..nf)
        .map(|f| {
            let [a, b, c] = mesh.tri_pos(f);
            tri_area(a, b, c)
        })
        .collect();
    let mut vfaces: Vec<Vec<u32>> = vec![Vec::new(); mesh.vertices.len()];
    for (f, t) in mesh.triangles.iter().enumerate() {
        for &x in t {
            vfaces[x as usize].push(f as u32);
        }
    }
    let mut dead = vec![false; nf];
    // The fold edges at v: (other end, the two faces).
    let fold_edges = |v: u32, vfaces: &[Vec<u32>], tris: &[[u32; 3]], nrm: &[Vec3]| -> Option<Vec<(u32, [u32; 2])>> {
        let mut by_other: HashMap<u32, Vec<u32>> = HashMap::new();
        for &f in &vfaces[v as usize] {
            for &x in &tris[f as usize] {
                if x != v {
                    by_other.entry(x).or_default().push(f);
                }
            }
        }
        let mut out = Vec::new();
        for (x, fs) in by_other {
            if fs.len() != 2 {
                return None; // not manifold here
            }
            if dot(nrm[fs[0] as usize], nrm[fs[1] as usize]) < FOLD_DOT {
                out.push((x, [fs[0], fs[1]]));
            }
        }
        Some(out)
    };
    let mut queue: Vec<u32> = {
        let ef = mesh.edge_faces();
        let mut q: Vec<u32> = Vec::new();
        for (&(a, b), fs) in &ef {
            if fs.len() == 2 && dot(nrm[fs[0] as usize], nrm[fs[1] as usize]) < FOLD_DOT {
                q.push(a);
                q.push(b);
            }
        }
        q.sort_unstable();
        q.dedup();
        q.reverse();
        q
    };
    let mut total = 0;
    let mut gone_v = vec![false; mesh.vertices.len()];
    let mut steps = 0usize;
    while let Some(v) = queue.pop() {
        steps += 1;
        if steps > 50 * nf.max(1) || gone_v[v as usize] {
            continue;
        }
        let Some(es) = fold_edges(v, &vfaces, &mesh.triangles, &nrm) else {
            continue;
        };
        if es.len() != 2 {
            continue;
        }
        let (u, w) = (es[0].0, es[1].0);
        let pv = mesh.vertices[v as usize];
        let (d1, d2) = (sub(mesh.vertices[u as usize], pv), sub(mesh.vertices[w as usize], pv));
        let (l1, l2) = (norm(d1), norm(d2));
        if l1 == 0.0 || l2 == 0.0 || dot(d1, d2) >= 0.0 || norm(cross(d1, d2)) > ang_tol * l1 * l2 {
            continue;
        }
        let walls = [nrm[es[0].1[0] as usize], nrm[es[0].1[1] as usize]];
        let faces_v = vfaces[v as usize].clone();
        if !faces_v.iter().all(|&f| walls.iter().any(|&n| dot(nrm[f as usize], n) > cos_tol)) {
            continue;
        }
        // Collapse v into u: the two faces with u and v go.
        let gone: Vec<u32> = es[0].1.to_vec();
        let far: Vec<u32> = gone
            .iter()
            .map(|&f| *mesh.triangles[f as usize].iter().find(|&&x| x != u && x != v).unwrap())
            .collect();
        let ring = |x: u32| {
            let mut r: Vec<u32> = vfaces[x as usize].iter().flat_map(|&f| mesh.triangles[f as usize]).filter(|&y| y != x).collect();
            r.sort_unstable();
            r.dedup();
            r
        };
        let (ru, rv) = (ring(u), ring(v));
        let common: Vec<u32> = rv.iter().copied().filter(|x| ru.binary_search(x).is_ok()).collect();
        if common.len() != 2 || !far.iter().all(|x| common.contains(x)) {
            continue;
        }
        // Each moved face keeps its orientation, its plane and an area.
        let pu = mesh.vertices[u as usize];
        let mut new_n: Vec<(u32, Vec3, f64)> = Vec::new();
        let mut ok = true;
        for &f in &faces_v {
            if gone.contains(&f) {
                continue;
            }
            let t = mesh.triangles[f as usize];
            let q: Vec<Vec3> = t.iter().map(|&x| if x == v { pu } else { mesh.vertices[x as usize] }).collect();
            let n = cross(sub(q[1], q[0]), sub(q[2], q[0]));
            let a = 0.5 * norm(n);
            if a <= 1e-3 * area[f as usize] || dot(scale(n, 0.5 / a), nrm[f as usize]) < cos_tol {
                ok = false;
                break;
            }
            new_n.push((f, scale(n, 0.5 / a), a));
        }
        if !ok {
            continue;
        }
        for &f in &gone {
            dead[f as usize] = true;
            for &x in &mesh.triangles[f as usize] {
                vfaces[x as usize].retain(|&g| g != f);
            }
        }
        for (f, n, a) in new_n {
            for x in mesh.triangles[f as usize].iter_mut() {
                if *x == v {
                    *x = u;
                }
            }
            nrm[f as usize] = n;
            area[f as usize] = a;
            vfaces[u as usize].push(f);
        }
        vfaces[v as usize].clear();
        gone_v[v as usize] = true;
        total += 1;
        // The line at u and at w changed: test them again.
        queue.push(u);
        queue.push(w);
    }
    let mut i = 0;
    mesh.triangles.retain(|_| {
        i += 1;
        !dead[i - 1]
    });
    mesh.compact();
    total
}

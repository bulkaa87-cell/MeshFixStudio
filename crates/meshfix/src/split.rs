//! Split a surface into its separate parts (the "Split" command).
//!
//! Two parts are one part when they share an edge. A split only by shared
//! vertices or shared edges does not separate two solids that touch on a
//! face: at the boundary of the contact area, one edge has four faces (two
//! of each solid). Blender ("Separate by loose parts") keeps such solids as
//! one object. Bambu Studio separates them.
//!
//! The rule at an edge with more than two faces (radial pairing): sort the
//! faces by their angle around the edge. A face that has the edge in the
//! reverse direction (b→a) starts a solid wedge, and the next face in the
//! positive direction of rotation closes it. When two faces have the same
//! angle (two solids touch on a face), the closing face comes first. Thus
//! two touching solids stay two parts, and the two coincident faces do not
//! become a separate shell of zero thickness. An edge where the forward and
//! reverse faces do not balance joins all its faces (no safe pairing).
//!
//! A closed shell with a negative volume (a cavity) stays with the smallest
//! positive shell whose box contains its box.
//!
//! The vertices are first merged by bit-identical position. The triangle
//! order does not change: the result is one part index for each input face.

use crate::math::*;
use std::collections::HashMap;

struct Dsu(Vec<u32>);

impl Dsu {
    fn find(&mut self, mut x: u32) -> u32 {
        while self.0[x as usize] != x {
            let p = self.0[self.0[x as usize] as usize];
            self.0[x as usize] = p;
            x = p;
        }
        x
    }
    fn join(&mut self, a: u32, b: u32) {
        let (ra, rb) = (self.find(a), self.find(b));
        if ra != rb {
            self.0[ra.max(rb) as usize] = ra.min(rb);
        }
    }
}

fn fbits(x: f64) -> u64 {
    if x == 0.0 {
        0
    } else {
        x.to_bits()
    }
}

/// Two angles nearer than this (radians) are the same half-plane.
const TIE: f64 = 1e-9;

/// Angle in [0, 2π) of each face around the edge pa→pb.
fn radial_angles(pa: Vec3, pb: Vec3, thirds: &[Vec3]) -> Option<Vec<f64>> {
    let d = sub(pb, pa);
    let l = norm(d);
    if l <= 0.0 {
        return None;
    }
    let u = scale(d, 1.0 / l);
    let perp = |c: Vec3| {
        let w = sub(c, pa);
        sub(w, scale(u, dot(w, u)))
    };
    let e1 = thirds.iter().map(|&c| perp(c)).find(|w| norm(*w) > 0.0)?;
    let e1 = scale(e1, 1.0 / norm(e1));
    let e2 = cross(u, e1);
    Some(
        thirds
            .iter()
            .map(|&c| {
                let w = perp(c);
                let a = dot(w, e2).atan2(dot(w, e1));
                let a = if a < 0.0 { a + std::f64::consts::TAU } else { a };
                // Just below 2π is the same half-plane as 0 (a tie).
                if a > std::f64::consts::TAU - TIE {
                    0.0
                } else {
                    a
                }
            })
            .collect(),
    )
}

/// Pair the faces of one non-manifold edge. `faces`: (face, forward) where
/// forward means the face has the edge as a→b. Returns false when the
/// faces do not pair (the caller then joins them all).
fn pair_radial(dsu: &mut Dsu, pa: Vec3, pb: Vec3, faces: &[(u32, bool, Vec3)]) -> bool {
    let fw = faces.iter().filter(|f| f.1).count();
    if fw * 2 != faces.len() {
        return false;
    }
    let thirds: Vec<Vec3> = faces.iter().map(|f| f.2).collect();
    let Some(ang) = radial_angles(pa, pb, &thirds) else { return false };
    // Same angle: forward (closing) face first.
    let mut order: Vec<usize> = (0..faces.len()).collect();
    order.sort_by(|&i, &j| ang[i].total_cmp(&ang[j]));
    let mut s = 0;
    while s < order.len() {
        let mut e = s + 1;
        while e < order.len() && ang[order[e]] - ang[order[s]] <= TIE {
            e += 1;
        }
        order[s..e].sort_by_key(|&i| !faces[i].1);
        s = e;
    }
    let n = order.len();
    let mut pairs = Vec::with_capacity(n / 2);
    for k in 0..n {
        let (i, j) = (order[k], order[(k + 1) % n]);
        if !faces[i].1 {
            if !faces[j].1 {
                return false;
            }
            pairs.push((faces[i].0, faces[j].0));
        }
    }
    for (a, b) in pairs {
        dsu.join(a, b);
    }
    true
}

/// The result of `split_parts`.
#[derive(Debug, Clone)]
pub struct Split {
    /// Number of parts.
    pub n_parts: usize,
    /// Part index of each input face. Part 0 has the most faces.
    pub labels: Vec<u32>,
    /// Number of edges with more than two faces.
    pub shared_edges: usize,
    /// Number of cavity shells that stay with their outer shell.
    pub cavities: usize,
}

/// Split a triangle surface into its separate parts (see the module text).
pub fn split_parts(pts: &[Vec3], tris: &[[u32; 3]]) -> Split {
    let nf = tris.len();
    let mut seen: HashMap<[u64; 3], u32> = HashMap::with_capacity(pts.len());
    let canon: Vec<u32> = pts
        .iter()
        .enumerate()
        .map(|(i, p)| *seen.entry([fbits(p[0]), fbits(p[1]), fbits(p[2])]).or_insert(i as u32))
        .collect();
    let ct: Vec<[u32; 3]> = tris
        .iter()
        .map(|t| [canon[t[0] as usize], canon[t[1] as usize], canon[t[2] as usize]])
        .collect();

    // Undirected edge → (face, forward, third vertex).
    let mut edges: HashMap<(u32, u32), Vec<(u32, bool, u32)>> = HashMap::with_capacity(nf * 3 / 2 + 1);
    for (f, t) in ct.iter().enumerate() {
        for i in 0..3 {
            let (a, b, c) = (t[i], t[(i + 1) % 3], t[(i + 2) % 3]);
            if a == b {
                continue;
            }
            let key = if a < b { (a, b) } else { (b, a) };
            edges.entry(key).or_default().push((f as u32, a < b, c));
        }
    }

    let mut dsu = Dsu((0..nf as u32).collect());
    let mut shared_edges = 0;
    for (&(a, b), list) in &edges {
        match list.len() {
            0 | 1 => {}
            2 => dsu.join(list[0].0, list[1].0),
            _ => {
                shared_edges += 1;
                let faces: Vec<(u32, bool, Vec3)> =
                    list.iter().map(|&(f, fw, c)| (f, fw, pts[c as usize])).collect();
                if !pair_radial(&mut dsu, pts[a as usize], pts[b as usize], &faces) {
                    for w in list.windows(2) {
                        dsu.join(w[0].0, w[1].0);
                    }
                }
            }
        }
    }
    // A face with a collapsed edge only (all three vertices the same) has no
    // edge in the map: it stays a part of its own. That is correct.

    let mut root_of: HashMap<u32, usize> = HashMap::new();
    let mut groups: Vec<Vec<u32>> = Vec::new();
    for f in 0..nf as u32 {
        let r = dsu.find(f);
        let g = *root_of.entry(r).or_insert_with(|| {
            groups.push(Vec::new());
            groups.len() - 1
        });
        groups[g].push(f);
    }

    // Closed shells with a negative volume go to the smallest positive
    // shell whose box contains their box.
    let info: Vec<(f64, Vec3, Vec3, bool)> = groups
        .iter()
        .map(|g| {
            let mut lo = [f64::INFINITY; 3];
            let mut hi = [f64::NEG_INFINITY; 3];
            let mut vol = 0.0;
            let mut ecount: HashMap<(u32, u32), i32> = HashMap::new();
            let p0 = pts[ct[g[0] as usize][0] as usize];
            for &f in g {
                let t = ct[f as usize];
                let [a, b, c] = [pts[t[0] as usize], pts[t[1] as usize], pts[t[2] as usize]];
                for p in [a, b, c] {
                    for k in 0..3 {
                        lo[k] = lo[k].min(p[k]);
                        hi[k] = hi[k].max(p[k]);
                    }
                }
                vol += det3(sub(a, p0), sub(b, p0), sub(c, p0)) / 6.0;
                for i in 0..3 {
                    let (x, y) = (t[i], t[(i + 1) % 3]);
                    let key = if x < y { (x, y) } else { (y, x) };
                    *ecount.entry(key).or_default() += if x < y { 1 } else { -1 };
                }
            }
            let closed = ecount.values().all(|&v| v == 0);
            (vol, lo, hi, closed)
        })
        .collect();
    let inside = |i: usize, j: usize| {
        (0..3).all(|k| info[j].1[k] <= info[i].1[k] && info[i].2[k] <= info[j].2[k])
    };
    let mut owner: Vec<usize> = (0..groups.len()).collect();
    let mut cavities = 0;
    for i in 0..groups.len() {
        let (vol, _, _, closed) = info[i];
        if !closed || vol >= 0.0 {
            continue;
        }
        let best = (0..groups.len())
            .filter(|&j| j != i && info[j].0 > -vol && inside(i, j))
            .min_by(|&x, &y| info[x].0.total_cmp(&info[y].0));
        if let Some(j) = best {
            owner[i] = j;
            cavities += 1;
        }
    }

    // Number the parts: the most faces first, then the first face.
    let mut size = vec![0usize; groups.len()];
    for (i, g) in groups.iter().enumerate() {
        size[owner[i]] += g.len();
    }
    let mut tops: Vec<usize> = (0..groups.len()).filter(|&i| owner[i] == i).collect();
    tops.sort_by(|&x, &y| size[y].cmp(&size[x]).then(groups[x][0].cmp(&groups[y][0])));
    let mut index = vec![0u32; groups.len()];
    for (k, &g) in tops.iter().enumerate() {
        index[g] = k as u32;
    }
    let mut labels = vec![0u32; nf];
    for (i, g) in groups.iter().enumerate() {
        for &f in g {
            labels[f as usize] = index[owner[i]];
        }
    }
    Split { n_parts: tops.len(), labels, shared_edges, cavities }
}

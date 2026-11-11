//! Python module `meshfix._native`: repair(points, tris) and the geometry
//! check (mesh_check, shell_projections) for the package `meshfix`.

use crate::{mesh_info, repair as do_repair, Mesh, MeshInfo, Method, RepairOptions};
use numpy::{IntoPyArray, PyArrayMethods};
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use pyo3::types::{PyDict, PyList};

fn info_dict<'py>(py: Python<'py>, i: &MeshInfo) -> PyResult<Bound<'py, PyDict>> {
    let d = PyDict::new(py);
    d.set_item("vertices", i.vertices)?;
    d.set_item("edges", i.edges)?;
    d.set_item("faces", i.faces)?;
    d.set_item("boundary_edges", i.boundary_edges)?;
    d.set_item("non_manifold_edges", i.non_manifold_edges)?;
    d.set_item("flipped_edges", i.flipped_edges)?;
    d.set_item("shells", i.shells)?;
    Ok(d)
}

/// Repair a triangle mesh. points (N,3) float, tris (M,3) int.
/// Returns (points (K,3), tris (L,3), report dict). Units go in and come
/// back the same. The tolerances apply to mm (see meshfix.md).
/// alpha_wrap: fallback 1, an alpha wrap when the 12 steps leave defects.
/// alpha, offset: ball radius and offset of that wrap in the units of the
/// points (None = from the model). volume: fallback 2, the volumetric
/// remesh. method: "meshfix" (the 12 steps and the fallbacks), or one
/// forced method, "alphawrap" or "volume" (see lib.rs `Method`).
#[pyfunction]
#[pyo3(signature = (points, tris, normalize=true, wrap=true, stop_after=None, alpha_wrap=true, alpha=None, offset=None, volume=true, method="meshfix"))]
#[allow(clippy::too_many_arguments)]
fn repair<'py>(
    py: Python<'py>,
    points: numpy::PyReadonlyArray2<'py, f64>,
    tris: numpy::PyReadonlyArray2<'py, i64>,
    normalize: bool,
    wrap: bool,
    stop_after: Option<&str>,
    alpha_wrap: bool,
    alpha: Option<f64>,
    offset: Option<f64>,
    volume: bool,
    method: &str,
) -> PyResult<(Bound<'py, PyAny>, Bound<'py, PyAny>, Bound<'py, PyDict>)> {
    let method = Method::from_name(method)
        .ok_or_else(|| PyValueError::new_err(format!("method: no method {method}")))?;
    let stop = match stop_after {
        None => None,
        Some(name) => Some(
            crate::PIPELINE
                .iter()
                .copied()
                .find(|s| s.name() == name)
                .ok_or_else(|| PyValueError::new_err(format!("stop_after: no step {name}")))?,
        ),
    };
    let p = points.as_array();
    if p.ncols() != 3 {
        return Err(PyValueError::new_err("points: need (N, 3)"));
    }
    let t = tris.as_array();
    if t.ncols() != 3 {
        return Err(PyValueError::new_err("tris: need (M, 3)"));
    }
    let n = p.nrows() as i64;
    let mut tri = Vec::with_capacity(t.nrows());
    for r in t.rows() {
        if r.iter().any(|&i| i < 0 || i >= n) {
            return Err(PyValueError::new_err("tris: index out of range"));
        }
        tri.push([r[0] as u32, r[1] as u32, r[2] as u32]);
    }
    let verts: Vec<[f64; 3]> = p.rows().into_iter().map(|r| [r[0], r[1], r[2]]).collect();
    let opts = RepairOptions {
        normalize_scale: normalize,
        enable_wrap: wrap,
        stop_after: stop,
        alpha_wrap,
        wrap_alpha: alpha,
        wrap_offset: offset,
        volume_fallback: volume,
        method,
        ..Default::default()
    };
    let (mesh, report) = py.detach(move || {
        let mut m = Mesh::new(verts, tri);
        let r = do_repair(&mut m, &opts, |_, _| {});
        (m, r)
    });
    let report = report.map_err(|e| PyValueError::new_err(e.to_string()))?;

    let nv = mesh.vertices.len();
    let nf = mesh.triangles.len();
    let flat_p: Vec<f64> = mesh.vertices.iter().flat_map(|v| v.iter().copied()).collect();
    let flat_t: Vec<i64> = mesh.triangles.iter().flat_map(|t| t.iter().map(|&i| i as i64)).collect();
    let pts = flat_p.into_pyarray(py).reshape([nv, 3])?.into_any();
    let tr = flat_t.into_pyarray(py).reshape([nf, 3])?.into_any();

    let d = PyDict::new(py);
    d.set_item("before", info_dict(py, &report.before)?)?;
    d.set_item("after", info_dict(py, &report.after)?)?;
    d.set_item("scale", report.scale)?;
    let steps = PyList::empty(py);
    for s in &report.stages {
        steps.append((s.stage.name(), s.count, s.time.as_secs_f64()))?;
    }
    d.set_item("stages", steps)?;
    let u = PyDict::new(py);
    u.set_item("pairs", report.union.pairs)?;
    u.set_item("degenerate", report.union.degenerate)?;
    u.set_item("cut_faces", report.union.cut_faces)?;
    u.set_item("removed_patches", report.union.removed_patches)?;
    u.set_item("failed_faces", report.union.failed_faces)?;
    u.set_item("panicked", report.union.panicked)?;
    u.set_item("contact", report.union.contact)?;
    u.set_item("rolled_back", report.union.rolled_back)?;
    u.set_item("bad_edges", report.union.bad_edges)?;
    u.set_item("skipped_clusters", report.union.skipped_clusters)?;
    d.set_item("union", u)?;
    let undone: Vec<&str> = report.undone.iter().map(|s| s.name()).collect();
    d.set_item("undone", undone)?;
    d.set_item("fallback", report.fallback.map(|s| s.name()))?;
    d.set_item("method", method.name())?;
    if let Some(w) = &report.alpha_wrap {
        let a = PyDict::new(py);
        a.set_item("used", report.fallback == Some(crate::Stage::AlphaWrap))?;
        // alpha, offset in the units of the input (not normalized).
        a.set_item("alpha", w.alpha / report.scale)?;
        a.set_item("offset", w.offset / report.scale)?;
        a.set_item("points", w.points)?;
        a.set_item("faces", w.faces)?;
        a.set_item("pockets", w.pockets)?;
        a.set_item("stopped", w.stopped)?;
        a.set_item("refined", w.refined)?;
        a.set_item("crossing_faces", w.crossing_faces)?;
        a.set_item("t_wrap", w.t_wrap)?;
        a.set_item("t_shrink", w.t_shrink)?;
        a.set_item("bad", (w.bad_open, w.bad_nm, w.bad_flipped, w.bad_shells))?;
        d.set_item("alpha_wrap", a)?;
    }
    if let Some(v) = &report.volume {
        let vd = PyDict::new(py);
        vd.set_item("used", report.fallback == Some(crate::Stage::VolumeRemesh))?;
        vd.set_item("h", v.h / report.scale)?;
        vd.set_item("dims", v.dims.to_vec())?;
        vd.set_item("surface_cells", v.surface_cells)?;
        vd.set_item("mt_faces", v.mt_faces)?;
        vd.set_item("faces", v.faces)?;
        vd.set_item("clean", v.clean)?;
        vd.set_item("dropped_shells", v.dropped_shells)?;
        vd.set_item("volume_ratio", v.volume_ratio)?;
        let t = PyDict::new(py);
        for (k, s) in &v.times {
            t.set_item(*k, *s)?;
        }
        vd.set_item("times", t)?;
        d.set_item("volume", vd)?;
    }
    Ok((pts, tr, d))
}

/// Counts of a mesh without a repair: the same dict as report["after"].
#[pyfunction]
fn info<'py>(
    py: Python<'py>,
    points: numpy::PyReadonlyArray2<'py, f64>,
    tris: numpy::PyReadonlyArray2<'py, i64>,
) -> PyResult<Bound<'py, PyDict>> {
    let p = points.as_array();
    let t = tris.as_array();
    if p.ncols() != 3 || t.ncols() != 3 {
        return Err(PyValueError::new_err("need (N, 3) points and (M, 3) tris"));
    }
    let n = p.nrows() as i64;
    if t.iter().any(|&i| i < 0 || i >= n) {
        return Err(PyValueError::new_err("tris: index out of range"));
    }
    let m = Mesh::new(
        p.rows().into_iter().map(|r| [r[0], r[1], r[2]]).collect(),
        t.rows().into_iter().map(|r| [r[0] as u32, r[1] as u32, r[2] as u32]).collect(),
    );
    info_dict(py, &mesh_info(&m))
}

/// The faces that cross another face, or that fold onto a face on a
/// common edge (exact signs; see alphawrap::crossing_faces). For checks of
/// a result.
#[pyfunction]
fn crossings<'py>(
    py: Python<'py>,
    points: numpy::PyReadonlyArray2<'py, f64>,
    tris: numpy::PyReadonlyArray2<'py, i64>,
) -> PyResult<Vec<u32>> {
    let p = points.as_array();
    let t = tris.as_array();
    if p.ncols() != 3 || t.ncols() != 3 {
        return Err(PyValueError::new_err("need (N, 3) points and (M, 3) tris"));
    }
    let n = p.nrows() as i64;
    if t.iter().any(|&i| i < 0 || i >= n) {
        return Err(PyValueError::new_err("tris: index out of range"));
    }
    let m = Mesh::new(
        p.rows().into_iter().map(|r| [r[0], r[1], r[2]]).collect(),
        t.rows().into_iter().map(|r| [r[0] as u32, r[1] as u32, r[2] as u32]).collect(),
    );
    Ok(py.detach(move || crate::alphawrap::crossing_faces(&m)))
}

/// Generalized winding number of the mesh at each query point (fast tree
/// sum). For diagnosis.
#[pyfunction]
fn winding<'py>(
    py: Python<'py>,
    points: numpy::PyReadonlyArray2<'py, f64>,
    tris: numpy::PyReadonlyArray2<'py, i64>,
    queries: numpy::PyReadonlyArray2<'py, f64>,
) -> PyResult<Vec<f64>> {
    let p = points.as_array();
    let t = tris.as_array();
    let q = queries.as_array();
    if p.ncols() != 3 || t.ncols() != 3 || q.ncols() != 3 {
        return Err(PyValueError::new_err("need (N, 3) points, (M, 3) tris, (K, 3) queries"));
    }
    let n = p.nrows() as i64;
    if t.iter().any(|&i| i < 0 || i >= n) {
        return Err(PyValueError::new_err("tris: index out of range"));
    }
    let m = Mesh::new(
        p.rows().into_iter().map(|r| [r[0], r[1], r[2]]).collect(),
        t.rows().into_iter().map(|r| [r[0] as u32, r[1] as u32, r[2] as u32]).collect(),
    );
    let qs: Vec<[f64; 3]> = q.rows().into_iter().map(|r| [r[0], r[1], r[2]]).collect();
    Ok(py.detach(move || {
        use rayon::prelude::*;
        let all: Vec<u32> = (0..m.triangles.len() as u32).collect();
        let fwn = crate::union::Fwn::new(&m, &all);
        qs.par_iter().map(|&x| fwn.eval(x, None)).collect()
    }))
}

fn rows3(a: &numpy::PyReadonlyArray2<'_, f64>, what: &str) -> PyResult<Vec<[f64; 3]>> {
    let v = a.as_array();
    if v.ncols() != 3 {
        return Err(PyValueError::new_err(format!("{what}: need (N, 3)")));
    }
    Ok(v.rows().into_iter().map(|r| [r[0], r[1], r[2]]).collect())
}

fn tri_rows(tris: &numpy::PyReadonlyArray2<'_, i64>, n: usize) -> PyResult<Vec<[u32; 3]>> {
    let t = tris.as_array();
    if t.ncols() != 3 {
        return Err(PyValueError::new_err("tris: need (M, 3)"));
    }
    let mut out = Vec::with_capacity(t.nrows());
    for r in t.rows() {
        if r.iter().any(|&i| i < 0 || i as usize >= n) {
            return Err(PyValueError::new_err("tris: index out of range"));
        }
        out.push([r[0] as u32, r[1] as u32, r[2] as u32]);
    }
    Ok(out)
}

/// Geometry check of a triangle surface (see check.rs). Returns a dict:
/// open_edges, non_manifold_edges, bad_winding, n_regions, regions (M,),
/// area, degenerate, part_volumes, signed_volume, edge_stats (4),
/// hole_sizes (largest first, at most hole_limit).
#[pyfunction]
#[pyo3(signature = (points, tris, hole_limit=400))]
fn mesh_check<'py>(py: Python<'py>, points: numpy::PyReadonlyArray2<'py, f64>,
                   tris: numpy::PyReadonlyArray2<'py, i64>, hole_limit: usize)
                   -> PyResult<Bound<'py, PyDict>> {
    let pts = rows3(&points, "points")?;
    let tri = tri_rows(&tris, pts.len())?;
    let r = py.detach(move || crate::check::check(&pts, &tri, hole_limit));
    let d = PyDict::new(py);
    d.set_item("open_edges", r.open_edges)?;
    d.set_item("non_manifold_edges", r.non_manifold_edges)?;
    d.set_item("bad_winding", r.bad_winding)?;
    d.set_item("n_regions", r.n_regions)?;
    d.set_item("regions", r.regions.into_pyarray(py))?;
    d.set_item("area", r.area)?;
    d.set_item("degenerate", r.degenerate)?;
    d.set_item("part_volumes", r.part_volumes.into_pyarray(py))?;
    d.set_item("signed_volume", r.signed_volume)?;
    d.set_item("edge_stats", r.edge_stats.to_vec())?;
    d.set_item("hole_sizes", r.hole_sizes)?;
    Ok(d)
}

/// Silhouette projections of the surface voxels (vtkVoxelModeller rule):
/// (along X (ny,nz), along Y (nx,nz), along Z (nx,ny)) uint8 arrays.
#[pyfunction]
fn shell_projections<'py>(py: Python<'py>, points: numpy::PyReadonlyArray2<'py, f64>,
                          tris: numpy::PyReadonlyArray2<'py, i64>,
                          origin: (f64, f64, f64), dims: (usize, usize, usize),
                          voxel: f64, max_dist: f64)
                          -> PyResult<(Bound<'py, PyAny>, Bound<'py, PyAny>, Bound<'py, PyAny>)> {
    let pts = rows3(&points, "points")?;
    let tri = tri_rows(&tris, pts.len())?;
    let (nx, ny, nz) = dims;
    if nx * ny * nz == 0 {
        return Err(PyValueError::new_err("dims: zero"));
    }
    let (px, pyy, pz) = py.detach(move || crate::check::shell_projections(
        &pts, &tri, [origin.0, origin.1, origin.2], [nx, ny, nz], voxel, max_dist));
    Ok((px.into_pyarray(py).reshape([ny, nz])?.into_any(),
        pyy.into_pyarray(py).reshape([nx, nz])?.into_any(),
        pz.into_pyarray(py).reshape([nx, ny])?.into_any()))
}

#[pymodule]
#[pyo3(name = "_native")]
fn meshfix_native(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(repair, m)?)?;
    m.add_function(wrap_pyfunction!(crossings, m)?)?;
    m.add_function(wrap_pyfunction!(winding, m)?)?;
    m.add_function(wrap_pyfunction!(info, m)?)?;
    m.add_function(wrap_pyfunction!(mesh_check, m)?)?;
    m.add_function(wrap_pyfunction!(shell_projections, m)?)?;
    m.add("__version__", env!("CARGO_PKG_VERSION"))?;
    Ok(())
}

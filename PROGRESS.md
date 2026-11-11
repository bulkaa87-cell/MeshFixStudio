# Progress (T32)

The work of the first local steps. Delete this file before the first release,
or keep it as a short changelog.

## Done

1. The workspace: `crates/meshfix` (repair + the geometry check, moved from the
   foamrs crate), `crates/foamview` (the wgpu view). The native modules are
   `meshfix._native` and `foamview._native`.
2. The core package `meshfix` (staging copy of fs_meshfix, fs_repair, fs_winfix,
   the mesh part of fs_geometry, fs_i18n, RepairWorker and end_process).
3. `tests/test_core.py`: the check (Rust = VTK), the repair of all test meshes,
   the method list, the languages. Result: 0 problems (Windows, 2026-11-11).

## Next

1. The app test (`tests/test_app.py`), offscreen.
2. The PyInstaller spec and one Windows build.
3. The CI workflow, README, CONTRIBUTING, docs/PLAN.md.

## How to test

    python -m venv .venv
    .venv\Scripts\python -m pip install maturin PySide6 pyvista pyvistaqt vtk numpy six
    .venv\Scripts\maturin develop --release -m crates\meshfix\Cargo.toml
    .venv\Scripts\maturin develop --release -m crates\foamview\Cargo.toml
    .venv\Scripts\python tests\test_core.py

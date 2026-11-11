# Progress (T32)

A short log of the first steps. Delete this file at the first release, or
keep it as a changelog.

## Done

1. The workspace: `crates/meshfix` (the repair, and the geometry check that
   came from the foamrs crate), `crates/foamview` (the wgpu view). The native
   modules are `meshfix._native` and `foamview._native`.
2. The packages `meshfix` and `foamview`, and the program `app/meshfix_studio`
   (a staging copy of the OpenFOAM Studio code, see PLAN.md).
3. Tests, all on Windows 2026-11-11, 0 problems: `cargo test -p meshfix
   --no-default-features` (53), `tests/test_core.py`, `tests/test_app.py`,
   `tests/test_built_app.py` on the PyInstaller build (483 MB folder).
4. The packaging: PyInstaller spec, Inno Setup script, macOS dmg script,
   AppImage script, icons drawn at build time, the CI workflow.
5. PLAN.md (the design), README.md, CONTRIBUTING.md.

## Next

1. The first CI run on GitHub: fix what fails on macOS and Linux.
2. A draft release v0.1.0 when all four CI rows are green.
3. Port the T31 change of OpenFOAM Studio (STL-safe output) into
   `crates/meshfix` (PLAN.md, section 8).
4. The switch of OpenFOAM Studio to the pinned packages (PLAN.md, section 5).

## How to test (Windows)

    py -3.12 -m venv .venv
    .venv\Scripts\python -m pip install maturin pyinstaller pillow six
    .venv\Scripts\maturin develop --release -m crates\meshfix\Cargo.toml
    .venv\Scripts\maturin develop --release -m crates\foamview\Cargo.toml
    .venv\Scripts\python tests\test_core.py
    .venv\Scripts\python tests\test_app.py
    .venv\Scripts\python packaging\icons\make_icons.py
    .venv\Scripts\pyinstaller --noconfirm --distpath build\dist --workpath build\work packaging\pyinstaller\meshfix_studio.spec
    .venv\Scripts\python tests\test_built_app.py "build\dist\MeshFix Studio\MeshFix Studio.exe"

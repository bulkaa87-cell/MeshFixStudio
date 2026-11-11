# MeshFix Studio

MeshFix Studio repairs triangle meshes: STL, OBJ and PLY files from CAD,
3D scans and 3D printing. Open a mesh, see its problems in 3D, repair it,
and export a binary STL.

- Problems in the 3D view: holes (open edges, red), flipped parts (magenta),
  non-manifold edges (yellow), degenerate triangles (green). «Next Problem»
  moves the camera to the next problem.
- Repair methods:
  - **meshfix**: the steps of the Windows 3D-print repair, in Rust. It
    stitches gaps, removes duplicates, makes the normals consistent, closes
    holes, merges bodies that cut into each other, and removes tiny shells.
    The surface stays in place.
  - **alpha wrap**: one closed shell around the whole model, shrunk onto
    the surface.
  - **Windows**: the repair service of Windows (the same as «Fix model» in
    the slicers). Windows only.
  - **volume rebuild**: a new closed surface from a cell grid, for very
    dirty models.
- Units: the program guesses the units from the size (mm, cm, m, in). The
  export keeps the units of the input file.
- Undo and Reset. Languages: English and Ukrainian.
- The 3D view works on all GPUs and without a GPU: wgpu (DX12, Vulkan,
  Metal), software adapters (WARP, lavapipe, llvmpipe), VTK, and a CPU
  renderer.

The same repair is in [OpenFOAM Studio](https://github.com/bulkaa87-cell/OpenFoamStudio):
both programs use the packages of this repository.

## Download

There is no release yet. The installers will be on the
[Releases](https://github.com/bulkaa87-cell/MeshFixStudio/releases) page:

| System | File | First start |
|---|---|---|
| Windows 10, 11 (x64) | `MeshFix-Studio-<version>-windows-x64-setup.exe` | The installer has no code signature yet: in «Windows protected your PC», click «More info», then «Run anyway». |
| macOS 11 or newer (Apple silicon or Intel) | `MeshFix-Studio-<version>-macos-arm64.dmg` or `-x86_64.dmg` | The app is not notarized yet: right click the app, then «Open». Or System Settings > Privacy & Security > «Open Anyway». |
| Linux x86_64 (glibc 2.35 or newer) | `MeshFix-Studio-<version>-linux-x86_64.AppImage` | `chmod +x MeshFix-Studio-*.AppImage`, then start it. |

The program does not need Python.

## Build from the source code

You need Python 3.10 or newer and Rust (stable).

    python -m venv .venv
    .venv/bin/python -m pip install maturin pyinstaller pillow six
    .venv/bin/maturin develop --release -m crates/meshfix/Cargo.toml
    .venv/bin/maturin develop --release -m crates/foamview/Cargo.toml
    PYTHONPATH=app .venv/bin/python -m meshfix_studio

On Windows, use `.venv\Scripts\` instead of `.venv/bin/`, and
`set PYTHONPATH=app`.

The tests:

    .venv/bin/python tests/test_core.py
    .venv/bin/python tests/test_app.py
    cargo test --release -p meshfix --no-default-features

The program, and its test:

    .venv/bin/python packaging/icons/make_icons.py
    .venv/bin/pyinstaller --noconfirm packaging/pyinstaller/meshfix_studio.spec
    .venv/bin/python tests/test_built_app.py "dist/MeshFix Studio/MeshFix Studio"

GitHub Actions builds the installers for all systems
(`.github/workflows/build.yml`).

## The repository

| Folder | Content |
|---|---|
| `crates/meshfix` | The repair and the geometry check (Rust), and the Python package `meshfix` (wheel `meshfix-core`) |
| `crates/foamview` | The 3D view (Rust, wgpu), and the Python package `foamview` |
| `app` | The window program `meshfix_studio` |
| `packaging` | PyInstaller, Inno Setup, the macOS disk image, the AppImage |
| `tests` | The tests |

`PLAN.md` describes the design: what came from OpenFOAM Studio, how
OpenFOAM Studio uses these packages, and the installers.

## License

GNU General Public License version 3. See `LICENSE`.

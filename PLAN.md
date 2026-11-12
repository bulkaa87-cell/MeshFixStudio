# MeshFix Studio as a separate program: the design

Status: 2026-11-11. The prototype in this repository works on Windows (see
"Status of the prototype"). The code in `crates/*/python` and `app/` is a
STAGING COPY of OpenFOAM Studio (OFS) code. OFS does not use this repository
yet.

## 1. Decisions of the owner

1. The core lives in this repository: the Rust crate `meshfix`, the Python
   modules that were `fs_meshfix`, `fs_repair` and `fs_winfix`, and the
   mesh part of `fs_geometry`. OFS depends on the core at a pinned version.
   There is one code. A change goes to OFS through a new version.
2. Each operating system gets an installer that GitHub Actions builds:
   a Windows `.exe` installer, a macOS `.dmg`, a Linux AppImage. The user
   does not need Python.
3. The license is GPL-3.0 (the `LICENSE` file of this repository). The
   owner selected «version 3 or later» on 2026-11-12: SPDX
   `GPL-3.0-or-later` in each package and crate.

## 2. Repository layout

```
Cargo.toml                  Rust workspace (crates/meshfix, crates/foamview)
crates/meshfix/             Rust: the repair + the geometry check (check.rs)
  pyproject.toml            maturin: wheel "meshfix-core", module meshfix._native
  python/meshfix/           Python package "meshfix" (no Qt in the core)
    methods.py              was fs_repair.py: METHODS, repair_meshes()
    repair.py               was fs_meshfix.py: the meshfix repair, its report
    winfix.py               was fs_winfix.py: the Windows service (Windows only)
    check.py                the mesh part of fs_geometry.py + problem_layers()
    i18n.py                 was fs_i18n.py: the translation engine
    qt.py                   was foam_studio.RepairWorker + end_process (PySide6)
    i18n/uk/meshfix.json    the Ukrainian texts of the core
crates/foamview/            Rust: the wgpu view (GPU, software adapter, CPU)
  pyproject.toml            maturin: wheel "foamview", module foamview._native
  python/foamview/
    level.py                was fs_view3d.py: the renderer chain, Plotter
    qtwidget.py             was fs_view3d_qt.py: the Qt widget
    viewport.py             was foam_studio.Viewport (without the CFD layers)
                            + fs_panels.FlowLayout
    i18n/uk/foamview.json
app/                        the program (pure Python, setuptools)
  meshfix_studio/window.py  was fs_meshfix_app.py
  meshfix_studio/i18n/uk/meshfix_studio.json
packaging/
  pyinstaller/              meshfix_studio.spec + entry.py (one spec, 3 systems)
  windows/meshfix_studio.iss   Inno Setup
  macos/make_dmg.sh         .app -> .dmg (ad-hoc signature)
  linux/make_appimage.sh    AppImage (AppRun, .desktop)
  icons/meshfix-studio.svg  the logo; make_icons.py makes the PNG/ICO/ICNS,
                            the installer pictures and the social preview
                            from it (the files are in git)
tests/
  test_core.py              the core, no window
  test_app.py               the window, off-screen
  test_built_app.py         the BUILT program: start, window, close, smoke test
  make_smoke_stl.py         the small input model of the smoke test
.github/workflows/build.yml the CI matrix, the installers, the release
```

Names:

- The import name of the core is `meshfix`, as the owner asked. The
  distribution name is `meshfix-core`: the name `meshfix` can be taken on
  PyPI, and the wheels go to GitHub Releases first, not to PyPI.
- The native modules are `meshfix._native` and `foamview._native` (the
  `#[pymodule]` has `#[pyo3(name = "_native")]`). Thus the Python package
  and the native module do not have the same name, as `meshfix.pyd` and
  `foamview.pyd` have in OFS now.

## 3. The 3D view: one shared package

Decision: `foamview` (the Rust crate and `fs_view3d*.py`) moves into this
repository as a separate package. OFS depends on it at the same pinned
version as the core. Reasons:

1. The owner wants one code. A second copy of the viewer drifts at once:
   the graphics rules of OFS (all GPUs, software adapters, HiDPI, device
   loss) cost many fixes, and each fix would be needed two times.
2. MeshFix Studio uses the whole chain (GPU -> software adapter -> VTK ->
   CPU). The frozen program needs it more than OFS: it runs on unknown
   computers.

The cost: a change to the OFS «3D» tab (for example a new layer type in
foamview for results) needs a release here. Two ways keep this small:

- OFS develops against a local clone: `maturin develop -m
  ../MeshFixStudio/crates/foamview/Cargo.toml` puts the local build in the
  OFS `.venv`. Only the commit of OFS that needs it bumps the pin.
- The CFD layers stay in OFS. `foamview.viewport.Viewport` has the model,
  the problem layers, the ruler and the view buttons. OFS makes
  `class CaseViewport(Viewport)` with `EXTRA_CHECKS` (domain, refinement,
  point in flow, flow direction) and its methods (`show_domain`,
  `show_boxes`, `show_point`, `show_flow`, `show_rotor_axis`,
  `show_scalar`, `show_ghosts`, `refresh_scene`, `clear_results`).

If later the viewer changes much more often than the repair, move
`crates/foamview` to a third repository. The package names stay the same,
so OFS and this program only change a pin.

`tools/gpucheck` of OFS moves here with foamview (it tests foamview on each
backend). The rule of the OFS CLAUDE.md «Graphics portability» moves into
`CONTRIBUTING.md` of this repository.

## 4. Languages: one engine

`fs_i18n.py` is the engine of both programs. It moves to `meshfix.i18n`.
Its Qt part imports PySide6 only in `install()`, thus the core has no Qt.
Two changes make it shared:

- `I18N_DIRS`: a list of catalogue folders. Each package has its own
  `i18n/uk/*.json`. A program adds its folder with
  `add_catalogue_dir(folder)` (first, its entries win).
- `set_language_source(fn)`: the program gives the function that reads its
  language setting. It replaces the import of `fs_settings`.

The rule of the OFS CLAUDE.md «Interface languages» stays: each text in
English and Ukrainian, in the same commit, in the package that has the text.

## 5. What moves, and what OFS must change

| OFS now | Here | OFS after the switch |
|---|---|---|
| `rust/meshfix` | `crates/meshfix` | removed, also `meshfix.pyd` |
| `rust/foamrs/src/topo.rs` (mesh_check, shell_projections) | `crates/meshfix/src/check.rs` | `foamrs` keeps field reading and logs only |
| `rust/foamview` | `crates/foamview` | removed, also `foamview.pyd` |
| `fs_meshfix.py` | `meshfix.repair` | alias module (below) |
| `fs_repair.py` | `meshfix.methods` | alias module |
| `fs_winfix.py` | `meshfix.winfix` | alias module |
| `fs_geometry.py`: Diagnosis, load_surface, guess_scale, apply_scale, diagnose, the layer data, problem_spots, display_mesh, write_stl | `meshfix.check` | imports them from `meshfix.check`, keeps the CFD parts, adds its notes with `meshfix.check.NOTE_HOOKS.append(_add_notes)`, calls `diagnose(mesh, projected=True)` |
| `MainWindow._problem_layers` | `meshfix.check.problem_layers` | calls it |
| `RepairWorker`, `end_process` | `meshfix.qt` | imports them, sets `meshfix.qt.crash_note = fs_crashlog.note`, `crash_finish = fs_crashlog.finish` |
| `foam_studio.Viewport` | `foamview.viewport.Viewport` | `CaseViewport(Viewport)` with the CFD layers |
| `fs_panels.FlowLayout` | `foamview.viewport.FlowLayout` | imports it |
| `fs_view3d.py`, `fs_view3d_qt.py` | `foamview.level`, `foamview.qtwidget` | alias modules, `level.configure(app_name="OpenFOAM Studio", forced=fs_settings.view3d_forced)` |
| `fs_i18n.py` | `meshfix.i18n` | alias module + `add_catalogue_dir(APP_DIR / "i18n")` + `set_language_source(lambda: fs_settings.get("ui_language"))` |
| `fs_meshfix_app.py`, `MeshFix Studio.bat` | `app/meshfix_studio` | removed from OFS |
| `tests/test_meshfix.py`, part of `test_meshfix_studio.py`, `meshfix_cases.py` | `tests/` | OFS keeps one test: its «Repair» button calls `meshfix.methods.repair_meshes` |

An alias module keeps the old name for the other OFS modules and the tests
(also for monkeypatching, because it is the same module object):

```python
# fs_meshfix.py in OFS after the switch
import sys
import meshfix.repair as _m
sys.modules[__name__] = _m
```

Other OFS changes:

- `requirements.txt`: the pins of `meshfix-core` and `foamview` (section 7).
- `tools/build_rust.ps1`: no build of `meshfix` and `foamview`.
- The GitHub export of OFS: fewer files (no `rust/meshfix`, `rust/foamview`).
- Two texts changed here, with their Ukrainian translations: the tooltip
  of the meshfix method (no reference to `devlog/meshfix.md`) and the
  `why_not()` text (`meshfix.repair._OFS_TEXT = True` gives the old OFS
  text with `tools\build_rust.ps1`).

## 6. Dependencies, and what can go

The prototype keeps pyvista and VTK, as OFS has them. MeshFix Studio uses
VTK for:

| Use | Where | Without VTK |
|---|---|---|
| read STL, OBJ, PLY, VTP | `check.load_surface` (`pv.read`) | numpy readers for STL (binary and ASCII), OBJ, PLY: about 300 lines. VTP needs VTK: drop it, or keep it optional |
| open and non-manifold edges of the layers | `extract_feature_edges` | `meshfix._native` gives the edge lists (the check already finds them) |
| parts, holes when the Rust check is missing | `vtkPolyDataConnectivityFilter` | not needed: the native module is always in the package |
| normals for the view | `display_mesh` (`compute_normals`) | numpy (face normals, split at sharp edges) |
| marker sphere, ruler line | `pv.Sphere`, `pv.Line` | numpy |
| the mesh object | `pv.PolyData` everywhere | a small `Mesh(points, tris)` class |
| the VTK fallback renderer | `pyvistaqt.QtInteractor` (needs matplotlib) | the chain becomes GPU -> software adapter -> CPU |
| write STL | `pv.save` | numpy (50 lines) |

The size of the Windows prototype (PyInstaller folder, measured): 483 MB.
VTK is 286 MB of it (`vtk.libs` 243 MB, `vtkmodules` 43 MB), PySide6 100 MB,
numpy 26 MB, matplotlib 14 MB, Pillow 11 MB, foamview 7 MB, meshfix 2 MB.
A zip of the folder is 159 MB. The Inno Setup installer (LZMA2) that CI
built is 106.6 MB.

Without VTK, pyvista, matplotlib and Pillow, and with only the used Qt
modules, the folder is about 150 MB and the installer about 50 to 60 MB
(estimate). Do this in a second step: it changes the data type of the
whole core (`pv.PolyData` -> `Mesh`), thus OFS must change at the same
time. A first, small step: exclude the VTK DLLs that pyvista does not
load (`vtk.libs` has all modules of VTK).

## 7. How OFS pins the core, and how a change flows

The pin (OFS `requirements.txt`): the abi3 wheels of a GitHub Release. One
wheel for each system and processor works for Python 3.9 and newer.

```
meshfix-core @ https://github.com/bulkaa87-cell/MeshFixStudio/releases/download/v0.2.0/meshfix_core-0.2.0-cp39-abi3-win_amd64.whl ; sys_platform == "win32"
foamview @ https://github.com/bulkaa87-cell/MeshFixStudio/releases/download/v0.2.0/foamview-0.2.0-cp39-abi3-win_amd64.whl ; sys_platform == "win32"
```

(The same two lines for Linux and macOS when OFS runs there. Later a PyPI
upload makes the lines short: `meshfix-core==0.2.0`.)

A change:

1. Change the code here (a pull request). CI runs the tests on the three
   systems.
2. Change the version in `crates/meshfix/Cargo.toml`, `crates/foamview/Cargo.toml`,
   the `__version__` lines and `app/meshfix_studio/__init__.py`.
3. Write `RELEASE_NOTES.md`, then push a tag `vX.Y.Z`. CI publishes the
   release with the installers and the wheels of the rows that passed. Its
   notes name the systems whose build failed.
4. In OFS: change the version in the two pin lines, `pip install -r
   requirements.txt`, run the OFS tests of the repair and of the 3D view.
   Commit: "Use meshfix-core X.Y.Z".

The new text for the OFS CLAUDE.md «Mesh repair: one code for two
programs» (replaces the old section):

> The repair, the geometry check, the 3D view and the language engine are
> the packages `meshfix` and `foamview` of the MeshFix Studio repository
> (https://github.com/bulkaa87-cell/MeshFixStudio). OFS pins their version
> in `requirements.txt`. Do not change `fs_meshfix`, `fs_repair`,
> `fs_winfix`, `fs_view3d*` or `fs_i18n` in OFS: they are aliases. Make the
> change in the MeshFix Studio repository, release a version, then move the
> pin in OFS and run the OFS tests. For development, `maturin develop` from
> a local clone of that repository into the OFS `.venv`.

## 8. The work of T31 (STL-safe output)

T31 changes `rust/meshfix` in OFS now. This repository has the version of
OFS commit `19ba416`. After T31 is in OFS master:

1. `git format-patch 19ba416..master -- rust/meshfix` in OFS.
2. Here: `git am -p3 --directory=crates/meshfix <patches>` (the paths start
   with `crates/meshfix/` instead of `rust/meshfix/`).
3. Run `cargo test -p meshfix --no-default-features`, `tests/test_core.py`,
   `tests/test_app.py`.

From the switch on, `rust/meshfix` in OFS gets no more changes.

## 9. Packaging

| Tool | For | Against |
|---|---|---|
| PyInstaller (selected) | mature hooks for PySide6, VTK, numpy. One spec for 3 systems. Fast build (2 min) | big output. Antivirus programs sometimes flag its bootloader |
| Briefcase | makes the installers itself (MSI, DMG, AppImage) | weak support for VTK and native wheels. Less control of the files |
| Nuitka | compiles Python to C, faster start, smaller | builds take 20 to 60 minutes. Problems with PySide6 plugins and VTK are common |

The installers:

- Windows: Inno Setup (`packaging/windows/meshfix_studio.iss`). It installs
  for the user only (no administrator) or for all users, makes a Start menu
  entry, and on request a desktop icon and «Open with» for `.stl`, `.obj`,
  `.ply`. It has an uninstaller. It has no code signature. Windows
  SmartScreen shows «Windows protected your PC»: the person clicks «More
  info», then «Run anyway». The owner selected free tools without an
  application (2026-11-12). A code signing certificate without cost and
  without an application does not exist, thus this warning stays.
- macOS: the PyInstaller `.app` in a `.dmg` (`packaging/macos/make_dmg.sh`),
  two builds: arm64 (Apple silicon) and x86_64 (Intel). The app has an
  ad-hoc signature (free; arm64 needs a signature to start at all). It has
  no Developer ID signature and no notarization (both need a paid Apple
  Developer Program account). macOS says that it "cannot check the app".
  The person opens it one time in System Settings > Privacy & Security >
  «Open Anyway» (on macOS 14 and older also with right click > «Open»).
- Linux: an AppImage (`packaging/linux/make_appimage.sh`). The person makes
  it executable and starts it. It needs glibc 2.35 or newer (built on Ubuntu
  22.04), and the usual X11 or Wayland libraries of a desktop. A `.deb` or
  a Flatpak can come later.
- All systems, free: the release has `SHA256SUMS.txt`, and CI makes a
  build provenance attestation (`actions/attest-build-provenance`) for each
  installer and wheel. `gh attestation verify <file> --repo
  bulkaa87-cell/MeshFixStudio` shows that this repository built the file.
  README.md tells the steps.

## 10. CI (`.github/workflows/build.yml`)

- Triggers: a push to `main`, a pull request, a tag `v*`, a manual start.
- Job `rust`: `cargo test -p meshfix --no-default-features` (Ubuntu).
- Job `build`, a matrix: `windows-latest` (x64), `ubuntu-22.04` (x86_64),
  `macos-15` (arm64), `macos-15-intel` (x86_64). GitHub no longer runs
  `macos-14` (measured 2026-11-11). Each: the two wheels with
  maturin, the tests of the core and of the window off-screen, the
  icons, PyInstaller, the test of the BUILT program, the installer. The
  installer and the wheels are workflow artifacts (14 days).
- Software rendering on the runners: WARP on Windows, lavapipe and llvmpipe
  (Mesa) on Linux, the paravirtual Metal GPU or the CPU renderer on macOS.
  The test of the built program on Linux runs under Xvfb with the xcb
  platform of Qt: it then also finds a missing system library.
- Job `release` (tags only): a GitHub Release with the installers and
  the wheels of the rows that passed, and `RELEASE_NOTES.md` as the text.
  A failed row does not stop the release: the notes name the missing
  system.
- `macos-15-intel` is the Intel runner label of GitHub in 2026. If GitHub
  removes it, remove the row: Intel Macs then use an older release.

## 11. The Windows-only method

The method «Windows» (`winfix`, the Printing3D service through pywinrt):

- `meshfix.winfix.available()` is False when the system is not Windows or
  the `winrt` packages are missing. `why_not()` gives the reason.
- The window shows the method gray, with the reason as the tooltip. The
  method cannot start (`methods.repair_meshes` raises the reason).
- The `winrt` dependencies have the marker `sys_platform == 'win32'`
  (extra `meshfix-core[windows]`). The PyInstaller spec collects `winrt`
  only on Windows.

## 12. Status of the prototype (Windows, 2026-11-11)

- `cargo test -p meshfix --no-default-features`: 53 tests pass.
- `tests/test_core.py`: 0 problems. The Rust check and the VTK check give
  the same counts on all test meshes, and the repair closes all test meshes.
- `tests/test_app.py`: 0 problems (off-screen window, drag and drop,
  repair, export and read again, undo, reset, live language change, close
  during a repair).
- PyInstaller one-folder build: 483 MB. `tests/test_built_app.py`: 0
  problems.
  - The window comes up with the file in its title after 22.6 s on the
    first start. The program probes the GPUs one time, then it uses the
    cache.
  - The window closes with exit code 0.
  - The smoke test repairs a copy of a small STL (1 204 triangles, 24 open
    edges, 12 flipped faces). Result: 0/0/0/0, and the exported file has
    the same counts.
  - The forced levels VTK, CPU and software (WARP) also repair.
- Not built here: the Inno Setup installer, macOS, Linux. CI builds them.
  The first CI run (2026-11-11) built the Windows installer (106.6 MB) and
  the macOS x86_64 disk image (213 MB with zlib, now LZMA: smaller), and
  the tests of the built program passed on both.

## 13. Next steps

The release v0.1.0 is out (2026-11-11), with the files of all four
systems. CI is green on all four rows.

1. T31 into `crates/meshfix` (section 8).
2. The switch of OFS (section 5), in one OFS branch, with the OFS tests.
3. Translate the Ukrainian code comments of the staging copy to English.
4. Make the build smaller (section 6).

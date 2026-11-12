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
   2026-11-11: the logo (packaging/icons/meshfix-studio.svg) replaces the
   drawn icon; the icon files are in git (see "Logo" below).
5. PLAN.md (the design), README.md, CONTRIBUTING.md.

6. Release v0.1.0 (2026-11-11):
   https://github.com/bulkaa87-cell/MeshFixStudio/releases/tag/v0.1.0
   Windows installer 107 MB (installed per user, started, repaired, and
   removed again on Windows 10), macOS arm64 dmg 124 MB, macOS x86_64 dmg
   146 MB, Linux AppImage 235 MB, and the wheels of all four systems. The
   Linux files come from the build of b1107b8 (the tag build did not get the
   Linux packages; the program code is the same).
7. CI: all four rows green on main (b1107b8).

8. History rewrite (2026-11-12): the identity of the web commit «Initial
   commit» is now the noreply address. All trees stay the same. The tag
   v0.1.0 and its release moved to the new commits.
9. Branch wip/free-signing: build provenance attestations, SHA256SUMS.txt
   in the release, the ad-hoc macOS signature (it was there), a retry of
   hdiutil, the «First start» and «Check the download» parts of README.md
   and RELEASE_NOTES.md.

## Next

1. Port the T31 change of OpenFOAM Studio (STL-safe output) into
   `crates/meshfix` (PLAN.md, section 8).
2. The switch of OpenFOAM Studio to the pinned packages (PLAN.md, section 5).
3. Make the program smaller (PLAN.md, section 6).
4. Test the macOS and Linux files on real computers (CI tests them only
   on the runners, without a real GPU).

## How to test (Windows)

    py -3.12 -m venv .venv
    .venv\Scripts\python -m pip install maturin pyinstaller pillow six
    .venv\Scripts\maturin develop --release -m crates\meshfix\Cargo.toml
    .venv\Scripts\maturin develop --release -m crates\foamview\Cargo.toml
    .venv\Scripts\python tests\test_core.py
    .venv\Scripts\python tests\test_app.py
    .venv\Scripts\pyinstaller --noconfirm --distpath build\dist --workpath build\work packaging\pyinstaller\meshfix_studio.spec
    .venv\Scripts\python tests\test_built_app.py "build\dist\MeshFix Studio\MeshFix Studio.exe"

## Logo (branch wip/t33-logos, 2026-11-11)

Done:
- The logo `packaging/icons/meshfix-studio.svg`: a triangle in 4 parts on
  a dark tile, the middle part green (the patch of a repair).
- `packaging/icons/make_icons.py` makes all files from the SVG: .ico
  (16-256, each size drawn at its size), .icns, PNG 16-1024, the window
  icons in `app/meshfix_studio/icons/`, the installer pictures and
  `social-preview.png` (1280 x 640, for the GitHub settings; not set).
  The files are in git; CI does not make them.
- The window icon (also in «About»), the exe icon, the installer icon and
  wizard pictures, the .app icon, the AppImage icons (hicolor 16-512 and
  scalable), the README header.

Next: merge to main after a check of the CI artifacts (installer, dmg,
AppImage). No new release.

How to test: `tests/test_app.py` checks the window icon. Build the exe
(see below) and look at the icon in Explorer and on the taskbar.

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

10. Release v0.1.1 (2026-11-12): wip/t33-logos (the logo) and
    wip/free-signing merged into main, version 0.1.1.

11. Branch wip/stlsafe (v0.1.2, not tagged): the StlSafe step of OpenFOAM
    Studio (T31), the new wording about the Windows repair (the same as in
    OpenFOAM Studio), tools/build_wheels.py with --remap-path-prefix (CI
    uses it). Checked: 56 Rust tests, tests/test_core.py and
    tests/test_app.py 0 problems; copies of two large aircraft models
    stay 0/0/0/0 after the export to STL and a read.

12. Release v0.1.2 (2026-11-12, Latest): wip/stlsafe merged into main.
    The Windows installer of the release: SHA256 = SHA256SUMS.txt,
    attestation found, installed, repaired models with pinched edges and a
    copy of a large aircraft model: 0/0/0/0 after the STL export and a read.

13. Branch wip/t48-shared (version 0.2.0, not tagged; the owner decides
    about the release):
    - The code of both programs compared: the Rust crates meshfix and
      foamview are the same (only the docs, the module name `_native`,
      check.rs and the Cargo metadata differ); the Python modules repair,
      methods, winfix and the window are the same code (only the imports,
      the docstrings and the build text). The OpenFOAM Studio test of the
      fallback text was missing here: it is in tests/test_core.py now.
    - The repair steps have our own names: ids stitch_seams,
      fill_tiny_holes, remove_duplicates, fix_orientation,
      fill_tiny_holes_again, stitch_seams_again, fix_orientation_again,
      fill_holes, merge_bodies, fix_degenerate_faces, remove_tiny_shells,
      split_t_junctions, alpha_wrap, volume_rebuild, stl_safe_output.
      English and Ukrainian names in meshfix.repair.STEPS. The old ids
      still work as input: LEGACY_STEP_IDS (Python), LEGACY_STAGE_IDS and
      Stage::from_name (Rust).
    - The tooltip of «What the repair did» lists the steps.
    - The open and export dialogs: texts through tr().
    - meshfix.check.READERS / WRITERS / write_mesh(): one table of the file
      formats (more formats come later, in a separate task).
    - Checked: 57 Rust tests, tests/test_core.py and tests/test_app.py
      0 problems.
    - tools/build_wheels.py also remaps CARGO_TARGET_DIR ("target"): a
      target folder outside the repository put its path into
      foamview._native (generated sources of a build script). CI builds
      inside the repository, thus the released files did not have it.
    - OpenFOAM Studio (its branch wip/t48-shared) runs with these wheels:
      its repair tests, the full delta test, gpucheck (11 PASS, also
      lavapipe and llvmpipe) and the frozen program are green.
    - The PyInstaller build of 0.2.0 on Windows: tests/test_built_app.py
      0 problems (start with a file, smoke test 24/12 -> 0/0/0/0, the
      exported file has the same counts).

14. Branch wip/t50-formats (version 0.3.0, not tagged; the owner decides
    about the release):
    - meshfix.formats: open and export STL (binary, ASCII), 3MF, OBJ, PLY
      (binary, ASCII), OFF, glTF (.glb, .gltf), VTP, legacy VTK. Own
      readers and writers (numpy and the standard library) for 3MF, OBJ,
      PLY, OFF, glTF and the ASCII STL; VTK for the binary STL and VTK.
    - Bodies (the cell array meshfix_body and the names): 3MF objects,
      OBJ `o`, ASCII STL `solid`, glTF nodes, VTK arrays. The window
      repairs each body alone and keeps the names.
    - Units: 3MF is written in mm, glTF in m; the readers give the unit
      of the file (guess_scale). The other formats: the unit of the input
      file, and a note in the log.
    - The step stl_safe_output: the window repairs without it
      (`repair_meshes(..., stl_safe=False)`, native `stl_safe=False`), and
      save_mesh applies it to the file coordinates for STL and glTF
      (float32). glTF needs it: 3 faces of a large aircraft model became
      degenerate without it.
    - Checked (Windows): 57 Rust tests; tests/test_core.py and
      tests/test_app.py 0 problems; copies of two large aircraft models
      (251 292 and 274 282 triangles): repaired 0/0/0/0, then each format
      (mm and m) read again 0/0/0/0 with the same triangles
      (`tests/test_core.py --big FOLDER`). OrcaSlicer (2.5.0-rc) reads the 3MF
      (two objects, the sizes in mm, manifold); Blender 5.2 reads the
      glTF (two objects, Z up, m), OBJ, PLY and STL; our reader reads a
      3MF project that OrcaSlicer wrote (components in other model files,
      the object names).
    - meshfix.methods.repair_bodies(): the repair of each body, for both
      programs.
    - CI on the branch (workflow_dispatch, 68dcc6e): all four rows green,
      also tests/test_built_app.py with each export format and a 3MF input
      in the frozen program.
    - OpenFOAM Studio (its branch wip/t50-formats) uses the formats when
      the installed meshfix-core has them (fs_geometry.formats()); its pin
      stays 0.2.0 until a release of 0.3.0 (the owner decides).

## Next

1. The switch of OpenFOAM Studio to the pinned packages (PLAN.md, section
   5): in work (OpenFOAM Studio branch wip/t48-shared).
2. Make the program smaller (PLAN.md, section 6).
3. Test the macOS and Linux files on real computers (CI tests them only
   on the runners, without a real GPU).

## How to test (Windows)

    py -3.12 -m venv .venv
    .venv\Scripts\python -m pip install maturin pyinstaller pillow six
    .venv\Scripts\python tools\build_wheels.py --develop
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

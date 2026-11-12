<p align="center"><img src="packaging/icons/png/meshfix-studio-128.png" width="96" height="96" alt="MeshFix Studio logo"></p>

# MeshFix Studio

MeshFix Studio repairs triangle meshes: STL, 3MF, OBJ, PLY, OFF, glTF and
VTK files from CAD, 3D scans and 3D printing. Open a mesh, see its
problems in 3D, repair it, and export it in one of these formats.

- Problems in the 3D view: holes (open edges, red), flipped parts (magenta),
  non-manifold edges (yellow), degenerate triangles (green). «Next Problem»
  moves the camera to the next problem.
- Repair methods:
  - **meshfix**: a repair in Rust. The result is close to the Windows
    3D-model repair; this is checked by measurements on test meshes. It
    stitches gaps, removes duplicates, makes the normals consistent, closes
    holes, merges bodies that cut into each other, and removes tiny shells.
    The surface stays in place.
    The 12 steps, in this order: stitch seams, fill tiny holes, remove
    duplicates, fix orientation, fill tiny holes (2), stitch seams (2),
    fix orientation (2), fill holes, merge bodies, fix degenerate faces,
    remove tiny shells, split T-junctions. When the mesh is still not
    closed: alpha wrap, then volume rebuild. The tooltip of «What the
    repair did» shows each step with its count.
  - **alpha wrap**: one closed shell around the whole model, shrunk onto
    the surface.
  - **Windows**: the repair service of Windows (the same as «Fix model» in
    the slicers). Windows only.
  - **volume rebuild**: a new closed surface from a cell grid, for very
    dirty models.
- Units: the program guesses the units from the size (mm, cm, m, in). A
  3MF or glTF file gives its unit. The export keeps the units of the input
  file. 3MF is always in mm (the unit of the slicers), glTF in m.
- Formats (open and export): STL (binary and ASCII), 3MF, OBJ, PLY (binary
  and ASCII), OFF, glTF (.glb and .gltf), VTK (.vtp and legacy .vtk).
- Bodies: the objects of a 3MF, OBJ, ASCII STL or glTF file are separate
  bodies. The repair repairs each body alone. The export keeps them as
  objects in 3MF, OBJ, ASCII STL, glTF and VTK; the other formats get one
  merged body.
- STL-safe output: STL and glTF keep float32 coordinates, and an STL reader
  joins points at the same place. Before such an export, the program moves
  the points that the rounding would join or make into a flat triangle, by
  about 0.001 mm. Thus the file keeps the counts of the repaired mesh. The
  other formats keep the points as they are.
- Undo and Reset. Languages: English and Ukrainian.
- The 3D view works on all GPUs and without a GPU: wgpu (DX12, Vulkan,
  Metal), software adapters (WARP, lavapipe, llvmpipe), VTK, and a CPU
  renderer.

The same repair is in [OpenFOAM Studio](https://github.com/bulkaa87-cell/OpenFoamStudio):
both programs use the packages of this repository.

## Download

The installers are on the
[Releases](https://github.com/bulkaa87-cell/MeshFixStudio/releases) page:

| System | File |
|---|---|
| Windows 10, 11 (x64) | `MeshFix-Studio-<version>-windows-x64-setup.exe` |
| macOS 11 or newer, Apple silicon | `MeshFix-Studio-<version>-macos-arm64.dmg` |
| macOS 11 or newer, Intel | `MeshFix-Studio-<version>-macos-x86_64.dmg` |
| Linux x86_64 (glibc 2.35 or newer) | `MeshFix-Studio-<version>-linux-x86_64.AppImage` |

The program does not need Python.

## First start

The program has no paid code signature. Thus each system asks one time:

- Windows: SmartScreen shows «Windows protected your PC». Click «More info»,
  then «Run anyway». Windows keeps this warning for each version: a free
  code signing certificate without an application does not exist.
- macOS: the app has an ad-hoc signature, but it is not notarized. macOS
  says that it cannot check the app. Open System Settings > Privacy &
  Security, and click «Open Anyway». On macOS 14 and older, you can also
  right click the app, then «Open».
- Linux: make the AppImage executable, then start it:
  `chmod +x MeshFix-Studio-<version>-linux-x86_64.AppImage`.
- The first start takes about 20 seconds: the program tests the GPUs of
  the computer one time, and then it remembers the result.

## Check the download

Each release has the file `SHA256SUMS.txt`, and GitHub keeps a build
provenance attestation for each installer: a signed record that GitHub
Actions of this repository built the file from the source code of the tag.

1. Compare the SHA256 of the file with its line in `SHA256SUMS.txt`:
   - Windows (PowerShell): `Get-FileHash .\MeshFix-Studio-<version>-windows-x64-setup.exe`
   - macOS: `shasum -a 256 MeshFix-Studio-<version>-macos-arm64.dmg`
   - Linux: `sha256sum -c SHA256SUMS.txt --ignore-missing`
2. Examine the attestation with the GitHub CLI:

       gh attestation verify MeshFix-Studio-<version>-windows-x64-setup.exe --repo bulkaa87-cell/MeshFixStudio

## Build from the source code

You need Python 3.10 or newer and Rust (stable).

    python -m venv .venv
    .venv/bin/python -m pip install maturin pyinstaller pillow six
    .venv/bin/python tools/build_wheels.py --develop
    PYTHONPATH=app .venv/bin/python -m meshfix_studio

On Windows, use `.venv\Scripts\` instead of `.venv/bin/`, and
`set PYTHONPATH=app`.

The tests:

    .venv/bin/python tests/test_core.py
    .venv/bin/python tests/test_app.py
    cargo test --release -p meshfix --no-default-features

The program, and its test:

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

MeshFix Studio is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by the
Free Software Foundation, either version 3 of the License, or (at your
option) any later version. See `LICENSE` (SPDX: `GPL-3.0-or-later`).

MeshFix Studio repairs triangle meshes (STL, 3MF, OBJ, PLY, OFF, glTF,
VTK): open a mesh, see its problems in 3D, repair it, and export it.

The program does not need Python.

## What is new in 0.3.1

- Fewer folded faces (two neighbor triangles folded onto each other at
  about 180 degrees). The repair removes the extra vertices on straight
  fold lines; only the triangles of the two walls change. On a large
  aircraft model: 15 855 -> 13 225 folded faces, the shape moves by at
  most 0.001 mm. All counts of the check, the crossing faces and the
  distance to the input stay the same.

## What is new in 0.3.0

- Open and export: STL (binary and ASCII), 3MF, OBJ, PLY (binary and
  ASCII), OFF, glTF (.glb, .gltf), VTP and legacy VTK. The export dialog
  has a filter for each format; the extension selects the format.
- 3MF: millimetres, one object for each body, the names of the bodies. The
  reader takes the unit of the file, the components and transforms, and
  the object names of Bambu Studio and OrcaSlicer.
- Bodies: the objects of a file stay separate bodies. The repair repairs
  each body alone. A format without bodies gets one merged body, and the
  dialog and the log say so.
- Units: 3MF and glTF give their unit; the other formats are written in
  the units of the input file, and the log says that the format keeps no
  unit.
- The step «STL-safe output» runs at the export to STL and glTF (float32
  coordinates), on the coordinates of the file. The other formats keep the
  points of the repair as they are.
- API: `meshfix.formats`, `meshfix.check.save_mesh()`, `format_for()`,
  `export_filters()`, `split_bodies()`, `join_bodies()`;
  `repair_meshes(..., stl_safe=False)` and `_native.repair(...,
  stl_safe=False)`. `write_mesh()` stays as in 0.2.0.
- OpenFOAM Studio uses the file formats of this version too.

## What was new in 0.2.0

- The repair steps have new names. Each step has an id (ASCII) and a name
  in English and Ukrainian: stitch seams, fill tiny holes, remove
  duplicates, fix orientation, fill holes, merge bodies, fix degenerate
  faces, remove tiny shells, split T-junctions, STL-safe output. The
  report of the native module (`stages`, `fallback`, `undone`) and
  `stop_after` use the new ids. The old ids still work as input
  (`meshfix.repair.LEGACY_STEP_IDS`, `Stage::from_name` in Rust).
- The text «What the repair did» shows each step with its count and time
  as a tooltip.
- The open and export dialogs show their texts in Ukrainian too.
- `meshfix.check.READERS` and `WRITERS`: one table of the file formats for
  reading and writing. `write_mesh()` writes with the writer of the suffix.
- OpenFOAM Studio uses the packages `meshfix-core` and `foamview` of this
  version: one repair code for both programs.

## What was new in 0.1.2

- A repaired mesh keeps its counts after the export to STL (the last
  repair step, now «STL-safe output»).
- meshfix: the result is close to the Windows 3D-model repair; this is
  checked by measurements on test meshes.
- The native modules keep no folder of the build computer.

## Download

| System | File |
|---|---|
| Windows 10, 11 (x64) | `MeshFix-Studio-<version>-windows-x64-setup.exe` |
| macOS, Apple silicon | `MeshFix-Studio-<version>-macos-arm64.dmg` |
| macOS, Intel | `MeshFix-Studio-<version>-macos-x86_64.dmg` |
| Linux x86_64 (glibc 2.35 or newer) | `MeshFix-Studio-<version>-linux-x86_64.AppImage` |

The `.whl` files are the Python packages `meshfix-core` and `foamview`
(for OpenFOAM Studio and for developers). You do not need them for the
program.

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

## Known limits

- The program is large (about 107 MB to download on Windows): it contains
  VTK, the fallback renderer of the 3D view. A smaller build comes later.
- The «Windows» repair method works on Windows only. On macOS and Linux it
  is gray in the list.

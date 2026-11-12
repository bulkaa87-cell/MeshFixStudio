MeshFix Studio repairs triangle meshes (STL, OBJ, PLY): open a mesh, see
its problems in 3D, repair it, and export a binary STL.

The program does not need Python.

## What is new in 0.1.2

- A repaired mesh keeps its counts after the export to STL. STL keeps
  float32 coordinates, and a reader joins points at the same place. Thus
  two copies of a pinched edge or vertex became one point again, and the
  file showed non-manifold edges or degenerate faces that the mesh in the
  program did not have. A last repair step (StlSafe) now moves such copies
  apart by a few float32 steps (about 0.001 mm on a model of 3 m).
- meshfix: the result is close to the Windows 3D-model repair; this is
  checked by measurements on test meshes.
- The same repair code as in OpenFOAM Studio.

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

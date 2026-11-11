MeshFix Studio repairs triangle meshes (STL, OBJ, PLY): open a mesh, see
its problems in 3D, repair it, and export a binary STL.

This is the first release. The program does not need Python.

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

- Windows: the installer has no code signature yet. In «Windows protected
  your PC», click «More info», then «Run anyway». The installer asks: for
  you only (no administrator rights) or for all users.
- macOS: the app is not notarized yet. Right click the app, then «Open»,
  or System Settings > Privacy & Security > «Open Anyway».
- Linux: `chmod +x MeshFix-Studio-*.AppImage`, then start it.
- The first start takes about 20 seconds: the program tests the GPUs of
  the computer one time, and then it remembers the result.

## Known limits

- The program is large (about 107 MB to download on Windows): it contains
  VTK, the fallback renderer of the 3D view. A smaller build comes later.
- The «Windows» repair method works on Windows only. On macOS and Linux it
  is gray in the list.

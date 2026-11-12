# Contributing

Thank you for your help. Read this page before you open a pull request.

## One code for two programs

OpenFOAM Studio uses the packages `meshfix` and `foamview` of this
repository at a pinned version. Thus:

- Put each change to the repair in `crates/meshfix` (Rust) or in
  `crates/meshfix/python/meshfix`. Do not repair a mesh in the window
  module (`app/meshfix_studio/window.py`).
- `meshfix.methods` has the method list and `repair_meshes()`. Each program
  calls `repair_meshes()`.
- Do not break the API of `meshfix` and `foamview` without a new minor
  version. OpenFOAM Studio calls it.

## The 3D view (foamview)

foamview must work on Windows, Linux (X11 and Wayland) and macOS, on Intel,
AMD, NVIDIA and Apple GPUs, and on software adapters (WARP, llvmpipe,
lavapipe). In each change to `crates/foamview` or `foamview/*.py`:

- Request only what wgpu guarantees on all backends
  (`Limits::downlevel_webgl2_defaults()`). Check an optional feature first,
  and keep a path without it.
- A wgpu error must not become a Rust panic. If there is no adapter, no
  device, or the first frame is wrong, use the next level (VTK, then the
  CPU renderer). The view must always show a picture.
- Multiply line widths and text sizes by the device pixel ratio.

## Languages

The texts in the code are English. Each text that a person sees needs a
Ukrainian translation in the same commit, in the catalogue of its package:
`crates/meshfix/python/meshfix/i18n/uk/`, `crates/foamview/python/foamview/i18n/uk/`
or `app/meshfix_studio/i18n/uk/`. Use `tr("Cells: {n}", n=cells)` for a
text with values, not an f-string. The module docstring of
`meshfix/i18n.py` tells the rules.

## Tests

Run these before a pull request:

    python tests/test_core.py
    python tests/test_app.py
    cargo test --release -p meshfix --no-default-features

After a change to the packaging, build the program and run
`tests/test_built_app.py` on it. A test must not change the settings of
the person: the tests import `tests/_isolate.py` first.

## Commits and files

- Write commit messages and comments in clear, simple English.
- Do not commit built files (`.pyd`, `.so`, `.exe`, installers, wheels).
  CI builds them.
- Do not commit personal data: no user names, host names, IP addresses,
  local paths or e-mail addresses.

## License

Your contribution is under the license of this repository: the GNU
General Public License, version 3 or (at your option) any later version
(`GPL-3.0-or-later`).

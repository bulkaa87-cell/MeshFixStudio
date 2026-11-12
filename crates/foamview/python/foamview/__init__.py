"""foamview: the 3D view of MeshFix Studio and OpenFOAM Studio.

- foamview.level: the chain of renderers (GPU, software adapter, VTK, CPU),
  the probe in a child process, and the Plotter with the pyvista calls;
- foamview.qtwidget: the Qt widget that foamview draws into;
- foamview.viewport: the Viewport widget (the model, the problem layers,
  the view buttons) that both programs use;
- foamview._native: the Rust crate crates/foamview (wgpu).
"""

from __future__ import annotations

from pathlib import Path

__version__ = "0.1.2"

try:
    from meshfix import i18n as _i18n
except ImportError:                       # pragma: no cover - no core
    _i18n = None
if _i18n is not None:
    _i18n.add_catalogue_dir(Path(__file__).resolve().with_name("i18n"),
                            first=False)

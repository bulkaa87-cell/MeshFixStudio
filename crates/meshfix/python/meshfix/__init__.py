"""meshfix: repair and check of triangle surface meshes.

The modules:

- meshfix.methods: the method list (METHODS) and repair_meshes(), the one
  call that each program uses for a repair;
- meshfix.repair: the meshfix repair (Rust) and its report;
- meshfix.winfix: the repair service of Windows (Windows only);
- meshfix.check: reading a file, the units, the geometry check
  (diagnose) and the data of the problem layers;
- meshfix.i18n: the interface languages (English keys, catalogues);
- meshfix.qt: the worker thread and the end of the process (PySide6).

The native module meshfix._native is the Rust crate crates/meshfix.
"""

from __future__ import annotations

__version__ = "0.1.2"


def native_version() -> str | None:
    """The version of the native module, or None if it is missing."""
    try:
        from . import _native
    except ImportError:
        return None
    return getattr(_native, "__version__", "?")

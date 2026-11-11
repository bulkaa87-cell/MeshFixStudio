"""A fix for six + PySide6. Import it FIRST.

PySide6 installs an import hook (shibokensupport.feature) that calls
inspect.getsource on each new module. six.moves is a namespace module, and
its repr needs the attribute _path of its loader. six._SixMetaPathImporter
does not have it:

    AttributeError: '_SixMetaPathImporter' object has no attribute '_path'

Then each import of six.moves after PySide6 fails (for example matplotlib
through dateutil). The order of the imports is not a safe fix, thus this
module adds the attribute. It was fs_compat.py of OpenFOAM Studio.
"""

from __future__ import annotations


def apply() -> bool:
    """Повертає True, якщо шим застосовано або він не потрібен."""
    try:
        import six
    except Exception:
        return True
    cls = getattr(six, "_SixMetaPathImporter", None)
    if cls is None:
        return True
    if not hasattr(cls, "_path"):
        try:
            cls._path = []
        except Exception:
            return False
    return True


apply()

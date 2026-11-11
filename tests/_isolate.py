"""Keep a test run away from the settings of the user.

Each tests/test_*.py imports this module first. It makes a new temporary
folder for this test process and sets:
- MESHFIX_SETTINGS_DIR: MeshFix Studio writes its settings (an INI file)
  there, not to the registry or to the settings folder of the user;
- FS_3D_CACHE: the cache of the 3D level probe goes there;
- FS_SYSTEM_LANG=uk: the "language of the computer" is Ukrainian on each
  computer. MeshFix Studio must still start in English.
It also puts the source folders on sys.path, for a run without
installation. The native modules must be installed (pip install of the
wheels, or maturin develop).
The folder is removed at the end of the process.
"""

import atexit
import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for sub in ("app", "tests"):
    path = os.path.join(ROOT, sub)
    if path not in sys.path:
        sys.path.insert(0, path)

DIR = tempfile.mkdtemp(prefix="meshfix-test-settings-")
os.environ["MESHFIX_SETTINGS_DIR"] = DIR
os.environ["FS_3D_CACHE"] = os.path.join(DIR, "view3d.json")
os.environ["FS_SYSTEM_LANG"] = "uk"
os.environ.pop("FS_LANG", None)

for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding="utf-8")
    except AttributeError:
        pass


@atexit.register
def _cleanup():
    shutil.rmtree(DIR, ignore_errors=True)


problems: list = []


def check(name, ok, detail=""):
    """Print one result line and keep a failure."""
    print("  %-4s %s%s" % ("ok" if ok else "FAIL", name,
                           "" if ok else "  <- " + str(detail)), flush=True)
    if not ok:
        problems.append(name)

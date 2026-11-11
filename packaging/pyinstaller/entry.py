"""The entry point of the frozen program (PyInstaller).

The same as «python -m meshfix_studio»: main() also handles the probe
child process of the 3D view («--foamview-probe»), because sys.executable
of a frozen program is the program itself.
"""

import os
import sys

os.environ.setdefault("QT_API", "pyside6")

if __name__ == "__main__":
    from meshfix_studio.window import main
    main(sys.argv)

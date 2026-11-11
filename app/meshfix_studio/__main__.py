"""python -m meshfix_studio [file]"""

import os
import sys

os.environ.setdefault("QT_API", "pyside6")


def main() -> None:
    from meshfix_studio.window import main as run
    run(sys.argv)


if __name__ == "__main__":
    main()

"""Build the wheels of meshfix-core and foamview (maturin), without local
paths in the native modules.

    python tools/build_wheels.py [OUT_DIR]          (default: wheels/)
    python tools/build_wheels.py --develop          (maturin develop)

rustc writes the paths of the source files into the binary (panic
messages, debug data). --remap-path-prefix replaces the folder of this
repository with "src", the Cargo home with "cargo" and a CARGO_TARGET_DIR
with "target". Thus a built .pyd or .so does not show a user name or a
local folder. CI uses this script too.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CRATES = ("meshfix", "foamview")


def cargo_home() -> Path:
    if os.environ.get("CARGO_HOME"):
        return Path(os.environ["CARGO_HOME"]).resolve()
    return (Path.home() / ".cargo").resolve()


def rustflags() -> str:
    flags = [f"--remap-path-prefix={ROOT}=src",
             f"--remap-path-prefix={cargo_home()}=cargo"]
    # A target folder outside the repository (CARGO_TARGET_DIR): the
    # generated sources of the build scripts are there.
    target = os.environ.get("CARGO_TARGET_DIR")
    if target:
        flags.insert(0, f"--remap-path-prefix={Path(target).resolve()}=target")
    old = os.environ.get("RUSTFLAGS", "").strip()
    return " ".join(([old] if old else []) + flags)


def main(argv: list[str]) -> int:
    develop = "--develop" in argv
    args = [a for a in argv if not a.startswith("--")]
    out = Path(args[0]).resolve() if args else ROOT / "wheels"
    env = dict(os.environ, RUSTFLAGS=rustflags())
    for crate in CRATES:
        manifest = str(ROOT / "crates" / crate / "Cargo.toml")
        if develop:
            cmd = [sys.executable, "-m", "maturin", "develop", "--release",
                   "-m", manifest]
        else:
            cmd = [sys.executable, "-m", "maturin", "build", "--release",
                   "-m", manifest, "-o", str(out)]
        print("+", " ".join(cmd), flush=True)
        rc = subprocess.call(cmd, env=env, cwd=str(ROOT))
        if rc:
            return rc
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

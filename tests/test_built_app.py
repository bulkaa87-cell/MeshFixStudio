"""The test of the BUILT program (PyInstaller folder or the installed copy).

Run it after each build, before somebody else starts the program:

    python tests/test_built_app.py "dist/MeshFix Studio/MeshFix Studio.exe"
    python tests/test_built_app.py "dist/MeshFix Studio.app/Contents/MacOS/MeshFix Studio"
    python tests/test_built_app.py "squashfs-root/AppRun"

1. A normal start with a file (a COPY of a small STL): the main window
   must come up with the file name in its title, and must close with exit
   code 0 (Windows: the test finds the window and sends WM_CLOSE).
   A start error of the frozen program («Unhandled exception in script»,
   a missing module) is a FAIL with the text of the error dialog.
2. «--smoke-test IN OUT»: open, repair with meshfix, export, read the file
   again (the result is OUT.json). Exit code 0 and "ok": true.

On Linux and macOS without a screen, set QT_QPA_PLATFORM=offscreen: part 1
then only checks that the process lives and ends when it is stopped.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

problems = []


def check(name, ok, detail=""):
    print("  %-4s %s%s" % ("ok" if ok else "FAIL", name,
                           "" if ok else "  <- " + str(detail)), flush=True)
    if not ok:
        problems.append(name)


# ------------------------------------------------------------ Windows only
def _windows_of(pid: int) -> list:
    """[(hwnd, title)] of the visible top windows of the process `pid`."""
    import ctypes
    from ctypes import wintypes
    user32 = ctypes.windll.user32
    out = []
    proto = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def each(hwnd, _lparam):
        owner = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value == pid and user32.IsWindowVisible(hwnd):
            n = user32.GetWindowTextLengthW(hwnd)
            buf = ctypes.create_unicode_buffer(n + 1)
            user32.GetWindowTextW(hwnd, buf, n + 1)
            out.append((hwnd, buf.value))
        return True
    user32.EnumWindows(proto(each), 0)
    return out


def _dialog_text(hwnd) -> str:
    """The texts of the child controls of a dialog (an error box)."""
    import ctypes
    from ctypes import wintypes
    user32 = ctypes.windll.user32
    texts = []
    proto = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def each(child, _lparam):
        n = user32.GetWindowTextLengthW(child)
        if n:
            buf = ctypes.create_unicode_buffer(n + 1)
            user32.GetWindowTextW(child, buf, n + 1)
            texts.append(buf.value)
        return True
    user32.EnumChildWindows(hwnd, proto(each), 0)
    return " | ".join(texts)[:600]


def part_start_windows(exe: str, src: str, env: dict) -> None:
    import ctypes
    print("1. normal start with a file (Windows)")
    proc = subprocess.Popen([exe, src], env=env)
    want = os.path.basename(src)
    found, error, t0 = None, None, time.monotonic()
    while time.monotonic() - t0 < 120 and proc.poll() is None:
        for hwnd, title in _windows_of(proc.pid):
            if "Unhandled exception" in title or "Error" in title:
                error = f"{title}: {_dialog_text(hwnd)}"
            elif want in title and "MeshFix Studio" in title:
                found = (hwnd, title)
        if found or error:
            break
        time.sleep(0.5)
    sec = time.monotonic() - t0
    check("no start error dialog", error is None, error)
    check("the window shows the file in its title", found is not None,
          f"exit code {proc.poll()}, windows {_windows_of(proc.pid)}")
    if found:
        print(f"      window after {sec:.1f} s: {found[1]}", flush=True)
        time.sleep(3.0)                     # the load in the worker thread
        ctypes.windll.user32.PostMessageW(found[0], 0x0010, 0, 0)  # WM_CLOSE
    try:
        rc = proc.wait(60)
    except subprocess.TimeoutExpired:
        proc.kill()
        rc = "hung"
    check("closes with exit code 0", rc == 0, rc)


def part_start_other(exe: str, src: str, env: dict) -> None:
    print("1. normal start with a file")
    proc = subprocess.Popen([exe, src], env=env, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT)
    time.sleep(15)
    alive = proc.poll() is None
    out = ""
    if not alive:
        out = proc.stdout.read().decode("utf-8", "replace")[-800:]
    check("the program runs 15 s after the start", alive,
          f"exit code {proc.poll()}: {out}")
    if alive:
        proc.terminate()
        try:
            proc.wait(30)
        except subprocess.TimeoutExpired:
            proc.kill()


def part_smoke(exe: str, src: str, tmp: str, env: dict) -> None:
    print("2. --smoke-test: open, repair, export, read again")
    out = os.path.join(tmp, "repaired.stl")
    try:
        rc = subprocess.run([exe, "--smoke-test", src, out], env=env,
                            timeout=600).returncode
    except subprocess.TimeoutExpired:
        rc = "timeout"
    res = {}
    if os.path.isfile(out + ".json"):
        with open(out + ".json", encoding="utf-8") as fh:
            res = json.load(fh)
    print(f"      3D: {res.get('level')}", flush=True)
    print(f"      before {res.get('before')} after {res.get('after')}",
          flush=True)
    check("exit code 0", rc == 0, rc)
    check("repaired, closed, the file has the same counts",
          res.get("ok") is True, res)


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    exe = os.path.abspath(sys.argv[1])
    if not os.path.isfile(exe):
        print(f"not found: {exe}")
        return 2
    tmp = tempfile.mkdtemp(prefix="meshfix-built-")
    env = dict(os.environ)
    env["MESHFIX_SETTINGS_DIR"] = os.path.join(tmp, "settings")
    env["FS_3D_CACHE"] = os.path.join(tmp, "view3d.json")
    env.pop("PYTHONPATH", None)
    import make_smoke_stl
    src = os.path.join(tmp, "small model.stl")
    make_smoke_stl.main(src)
    copy = os.path.join(tmp, "small model copy.stl")
    shutil.copyfile(src, copy)                 # never the original
    t0 = time.time()
    try:
        if os.name == "nt":
            part_start_windows(exe, copy, env)
        else:
            part_start_other(exe, copy, env)
        part_smoke(exe, copy, tmp, env)
    finally:
        cache = env["FS_3D_CACHE"]
        if os.path.isfile(cache):
            with open(cache, encoding="utf-8") as fh:
                print("      level cache:", fh.read()[:300], flush=True)
        shutil.rmtree(tmp, ignore_errors=True)
    print(f"\n{len(problems)} problems, {time.time() - t0:.0f} s"
          + ("" if not problems else ": " + ", ".join(problems)))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())

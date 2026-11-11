"""MeshFix Studio (meshfix_studio.window): the window, the repair, the
export, and the close during a repair. The windows open off-screen
(QT_QPA_PLATFORM=offscreen).

1. The window: English by default (the computer language of the test is
   Ukrainian), the buttons, the method list of meshfix.methods, the
   Windows method gray when the service is not on this computer, no CFD
   layers in the view.
2. A small model with a hole: open (also by drag and drop), repair with
   meshfix -> 0 holes / flipped / non-manifold / degenerate and closed,
   export -> load the STL again -> the same counts and triangles, the
   units of the input file; Undo and Reset; the Ukrainian interface.
3. Close during a repair: in this process (the result is ignored, no
   error), and in a child process (it ends with exit code 0, without
   "QThread: Destroyed").

    python tests/test_app.py [-v] [--shots DIR]
"""

import _isolate  # noqa: F401  — first: temp settings, sys.path
import os
import shutil
import subprocess
import sys
import tempfile
import time
import traceback

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
if os.name == "nt":                     # fonts for the off-screen pictures
    os.environ.setdefault("QT_QPA_FONTDIR", os.path.join(
        os.environ.get("WINDIR", "C:\\Windows"), "Fonts"))
os.environ.setdefault("QT_API", "pyside6")

import numpy as np                                           # noqa: E402
import pyvista as pv                                         # noqa: E402
from PySide6 import QtCore, QtGui, QtWidgets                 # noqa: E402

from _isolate import ROOT, check, problems                   # noqa: E402

_asked = []
for _n, _r in (("question", QtWidgets.QMessageBox.Yes),
               ("warning", QtWidgets.QMessageBox.Ok),
               ("information", QtWidgets.QMessageBox.Ok),
               ("critical", QtWidgets.QMessageBox.Ok)):
    def _stub(*a, _r=_r, _n=_n, **k):
        _asked.append((_n, str(a[2])[:120] if len(a) > 2 else ""))
        return _r
    setattr(QtWidgets.QMessageBox, _n, staticmethod(_stub))

from meshfix import check as geo                             # noqa: E402
from meshfix import i18n                                     # noqa: E402
from meshfix import methods                                  # noqa: E402
from meshfix import winfix                                   # noqa: E402
import meshfix_cases as mc                                   # noqa: E402

VERBOSE = "-v" in sys.argv
SHOTS = (sys.argv[sys.argv.index("--shots") + 1] if "--shots" in sys.argv
         else None)

app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
TMP = tempfile.mkdtemp(prefix="meshfix_app_")


def pump(ms=200):
    end = QtCore.QDeadlineTimer(ms)
    while not end.hasExpired():
        app.processEvents(QtCore.QEventLoop.AllEvents, 30)


def wait(win, limit_ms=300_000):
    end = QtCore.QDeadlineTimer(limit_ms)
    while win.busy_now and not end.hasExpired():
        app.processEvents(QtCore.QEventLoop.AllEvents, 50)
    pump(300)
    return not win.busy_now


def poly(p_mm, t):
    """A mesh in mm units in the file (as most STL files from CAD)."""
    t = np.asarray(t, np.int64)
    return pv.PolyData(np.asarray(p_mm, float),
                       np.hstack([np.full((len(t), 1), 3), t]).ravel())


def counts(d):
    return methods.counts(d)


def hole_cube(name="hole.stl", size=40.0):
    """A cube of `size` mm with one triangle missing (3 open edges)."""
    p, t = mc.cube(size)
    path = os.path.join(TMP, name)
    poly(p, np.delete(t, 2, 0)).save(path)
    return path


def new_window():
    from meshfix_studio import window as mfa
    mfa.start_language()
    win = mfa.MeshFixWindow()
    win.resize(1280, 800)
    win.show()
    pump(500)
    return win


def shot(win, name):
    if not SHOTS:
        return None
    os.makedirs(SHOTS, exist_ok=True)
    path = os.path.join(SHOTS, name)
    win.grab().save(path)
    return path


def part_window():
    print("1. the window")
    win = new_window()
    check("English by default (computer language uk)",
          i18n.language() == "en", i18n.language())
    check("title", win.windowTitle() == "MeshFix Studio", win.windowTitle())
    texts = {b.text() for b in win.findChildren(QtWidgets.QPushButton)}
    want = {"Open…", "Repair", "Export…", "Undo", "Reset"}
    check("buttons Open, Repair, Export, Undo, Reset", want <= texts,
          sorted(texts))
    keys = [win.cmb_method.itemData(i) for i in range(win.cmb_method.count())]
    check("method list = meshfix.methods.METHODS", tuple(keys) == methods.KEYS,
          keys)
    check("meshfix is the default", win.method() == "meshfix", win.method())
    row = keys.index("winfix")
    item = win.cmb_method.model().item(row)
    check("Windows item follows winfix.available()",
          item.isEnabled() == winfix.available()
          and (item.isEnabled() or winfix.why_not() in item.toolTip()),
          (item.isEnabled(), item.toolTip()[:80]))
    check("no model: Repair and Export disabled",
          not win.btn_repair.isEnabled() and not win.btn_export.isEnabled())
    extra = [k for k in ("domain", "box", "point", "flow") if k in win.view.chk]
    check("no CFD layers in the view", not extra, extra)
    shown = [k for k in ("holes", "flip", "nm", "degen")
             if win.view.chk[k].isVisibleTo(win)]
    check("problem layer toggles shown", len(shown) == 4, shown)
    check("no «All» button", not win.view.btn_fit_all.isVisibleTo(win))
    print(f"      3D: {win.lbl_3d.text()}", flush=True)
    return win


def part_small(win):
    print("2. a small model with a hole")
    src = hole_cube()
    mime = QtCore.QMimeData()
    mime.setUrls([QtCore.QUrl.fromLocalFile(src)])
    ev = QtGui.QDropEvent(QtCore.QPointF(50, 50), QtCore.Qt.CopyAction, mime,
                          QtCore.Qt.LeftButton, QtCore.Qt.NoModifier)
    win.dropEvent(ev)
    check("drop starts the load", win.busy_now)
    check("load ends", wait(win))
    d0 = win.state.diag if win.state else None
    check("model loaded", d0 is not None, _asked)
    if d0 is None:
        return
    check("units guessed: mm", win.units_text() == "mm", win.units_text())
    check("hole before", d0.open_edges == 3 and not d0.closed, counts(d0))
    check("holes layer in the view",
          "holes" in win.view.actors and win.view.chk["holes"].isEnabled())
    check("layer toggle in English with its count",
          win.view.chk["holes"].text() == "Holes 3",
          win.view.chk["holes"].text())
    _asked.clear()
    t0 = time.perf_counter()
    check("repair starts", win.repair("meshfix"))
    check("window stays live (repair in a thread)", win.busy_now
          and not win.btn_repair.isEnabled() and win.busy.isVisibleTo(win))
    check("repair ends", wait(win))
    d1 = win.state.diag
    check("after: 0/0/0/0 and closed", methods.clean(d1) and d1.closed,
          counts(d1))
    check("no dialog", not _asked, _asked)
    check("holes layer gone", "holes" not in win.view.actors)
    info = {k: v.text() for k, v in win.info.items()}
    check("info: before -> after", info["open_edges"] == "3 → 0"
          and info["closed"] == "no → yes", info)
    check("info: method and time", info["method"] == "meshfix"
          and info["time"].endswith(" s"), info)
    check("summary text", len(win.lbl_summary.text()) > 3,
          win.lbl_summary.text())
    if VERBOSE:
        print("     ", info, round(time.perf_counter() - t0, 2), "s")
    shot(win, "small-after.png")

    _asked.clear()
    out = win.export_file(os.path.join(TMP, "hole_fixed.stl"))
    check("export written", out is not None and out.is_file())
    wait(win)
    ec = win.export_check
    check("export check in the window: the same counts",
          ec is not None and counts(ec) == counts(d1)
          and ec.n_triangles == d1.n_triangles and not _asked,
          (ec and counts(ec), _asked))
    back = geo.load_surface(str(out))
    d2 = geo.diagnose(back)
    check("export: same triangles", d2.n_triangles == d1.n_triangles,
          (d2.n_triangles, d1.n_triangles))
    check("export: same counts", counts(d2) == counts(d1), counts(d2))
    span = max(d2.size)
    check("export: units of the input file (mm)", abs(span - 40.0) < 0.05,
          span)
    raw = pv.read(str(out))
    with open(out, "rb") as fh:
        head = fh.read(5)
    check("export: binary STL", head != b"solid"
          and raw.n_cells == d1.n_triangles)

    win.undo()
    check("undo: hole is back", win.state.diag.open_edges == 3,
          counts(win.state.diag))
    check("undo: info without repair", win.info["method"].text() == "—")
    win.repair("meshfix")
    wait(win)
    win.reset()
    check("reset: the loaded mesh", win.state is win.loaded
          and win.state.diag.open_edges == 3)
    win.undo()
    check("undo after reset: the repair", win.state.diag.closed)

    win.set_language("uk")
    pump(200)
    texts = {b.text() for b in win.findChildren(QtWidgets.QPushButton)}
    check("uk: Полагодити, Відкрити…", {"Полагодити", "Відкрити…"} <= texts,
          sorted(texts))
    check("uk: info names", any(lab.text() == "Трикутників" for lab in
                                win.findChildren(QtWidgets.QLabel)))
    check("uk: a view toggle", win.view.chk["body"].text() != "Model",
          win.view.chk["body"].text())
    win.set_language("en")
    pump(200)
    texts = {b.text() for b in win.findChildren(QtWidgets.QPushButton)}
    check("en again", {"Repair", "Open…"} <= texts, sorted(texts))


CHILD = '''
import os, sys, time
sys.path.insert(0, {tests!r})
import _isolate
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtCore, QtWidgets
from meshfix import methods
from meshfix_studio import window as mfa
slow = {slow!r}
real = methods.repair_meshes
def repair_meshes(*a, **k):
    time.sleep(slow)
    return real(*a, **k)
methods.repair_meshes = repair_meshes
mfa.fs_repair.repair_meshes = repair_meshes
app = QtWidgets.QApplication([])
mfa.start_language()
win = mfa.MeshFixWindow(); win.show()
win.open_file({path!r})
def go():
    if win.busy_now:
        QtCore.QTimer.singleShot(100, go); return
    win.repair("meshfix")
    print("REPAIR", win.busy_now, flush=True)
    QtCore.QTimer.singleShot(1500, lambda: (print("CLOSE", win.busy_now, flush=True), win.close()))
QtCore.QTimer.singleShot(100, go)
mfa.run(app, win, grace_ms=500)
'''


def part_close():
    print("3. close during a repair")
    from meshfix_studio import window as mfa
    real = methods.repair_meshes

    def slow(*a, **k):
        time.sleep(2.0)
        return real(*a, **k)
    mfa.fs_repair.repair_meshes = slow
    try:
        win = new_window()
        win.open_file(hole_cube("close.stl"))
        wait(win)
        before = win.state
        _asked.clear()
        win.repair("meshfix")
        pump(300)
        check("repair runs", win.busy_now)
        win.close()
        pump(200)
        check("window closed at once", not win.isVisible())
        check("thread not destroyed while it runs",
              win._thread is not None and win._thread.isRunning())
        ok = wait(win, 30000)
        check("thread ends after the close", ok and win._thread is None)
        check("result ignored after the close", win.state is before)
        check("no dialog after the close", not _asked, _asked)
        win.deleteLater()
        pump(200)
    finally:
        mfa.fs_repair.repair_meshes = real

    script = os.path.join(TMP, "child_close.py")
    with open(script, "w", encoding="utf-8") as fh:
        fh.write(CHILD.format(tests=os.path.join(ROOT, "tests"),
                              path=hole_cube("child.stl"), slow=30))
    env = dict(os.environ)
    env.pop("MESHFIX_SETTINGS_DIR", None)       # the child makes its own
    t0 = time.monotonic()
    try:
        res = subprocess.run([sys.executable, "-X", "utf8", script],
                             capture_output=True, text=True, timeout=180,
                             env=env, encoding="utf-8", errors="replace")
        rc, out = res.returncode, res.stdout + res.stderr
    except subprocess.TimeoutExpired as exc:
        rc, out = "timeout", str(exc.stdout) + str(exc.stderr)
    sec = time.monotonic() - t0
    check("child: repair ran when closed", "CLOSE True" in out, out[-400:])
    check("child: exit code 0", rc == 0, (rc, out[-400:]))
    check("child: no QThread fatal", "QThread: Destroyed" not in out
          and "FATAL" not in out, out[-400:])
    check("child: ends soon after the close (< 60 s)", sec < 60, sec)


def main():
    t0 = time.time()
    try:
        win = part_window()
        part_small(win)
        win.close()
        pump(200)
        part_close()
    except Exception:                                     # noqa: BLE001
        traceback.print_exc()
        problems.append("exception")
    print(f"\n{len(problems)} problems, {time.time() - t0:.0f} s"
          + ("" if not problems else ": " + ", ".join(problems)))
    shutil.rmtree(TMP, ignore_errors=True)
    return 1 if problems else 0


if __name__ == "__main__":
    rc = main()
    sys.stdout.flush()
    os._exit(rc)

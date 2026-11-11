"""Qt helpers that MeshFix Studio and OpenFOAM Studio share: the worker of
a long job, and the end of the process while a job still runs.

SHARED CODE: RepairWorker and end_process were in foam_studio.py of
OpenFOAM Studio. This module imports PySide6: the repair core (meshfix,
meshfix.check, meshfix.methods) does not import it.
"""

from __future__ import annotations

import os
import sys
import time

from PySide6 import QtCore

# fn(text) that writes a line to the crash log of the program, and fn()
# that closes the log. OpenFOAM Studio sets them (fs_crashlog).
crash_note = None
crash_finish = None


class RepairWorker(QtCore.QObject):
    """A repair (or another long job) outside the thread of the window.

    The repair of an assembly with 775 000 triangles takes 15 s. A window
    that does not move for that time looks dead, and people then end the
    program. Thus each long job runs here: job(meshes, step) in a QThread.
    """

    ready = QtCore.Signal(object)      # the result of the job
    failed = QtCore.Signal(str)
    step = QtCore.Signal(str)

    def __init__(self, job, meshes):
        super().__init__()
        self.job = job
        self.meshes = meshes

    @QtCore.Slot()
    def run(self):
        try:
            self.ready.emit(self.job(self.meshes, self.step.emit))
        except Exception as exc:                          # noqa: BLE001
            self.failed.emit(f"{exc}")


def _note(text: str) -> None:
    if crash_note is not None:
        try:
            crash_note(text)
        except Exception:                                 # noqa: BLE001
            pass


def _finish() -> None:
    if crash_finish is not None:
        try:
            crash_finish()
        except Exception:                                 # noqa: BLE001
            pass


def end_process(win, rc: int, grace_ms: int = 5000, settings=None) -> None:
    """End the process after app.exec() without a qFatal.

    closeEvent waits a limited time for each worker thread. A thread that
    still runs after that is a child of the window, and the end of Python
    destroys the window and its children: QThread::~QThread on a running
    thread is qFatal("QThread: Destroyed while thread ... is still running"),
    then abort(). So: wait a short time more, and if a thread still runs,
    write it to the crash log and end the process with os._exit, without
    the destruction of the window. `settings` (a QSettings) is synced first.
    """
    running = [t for t in win.findChildren(QtCore.QThread) if t.isRunning()]
    deadline = time.monotonic() + grace_ms / 1000.0
    for t in running:
        t.quit()
        t.wait(max(0, int((deadline - time.monotonic()) * 1000)))
    still = [t for t in running if t.isRunning()]
    if still:
        names = ", ".join(t.objectName() or type(t).__name__ for t in still)
        _note(f"exit: QThread still running ({names}); "
              "os._exit instead of a qFatal")
        _finish()
        if settings is not None:
            try:
                settings.sync()
            except Exception:                             # noqa: BLE001
                pass
        for stream in (sys.stdout, sys.stderr):
            try:
                if stream is not None:
                    stream.flush()
            except Exception:                             # noqa: BLE001
                pass
        os._exit(rc)
    _finish()
    sys.exit(rc)

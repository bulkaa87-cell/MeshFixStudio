"""The version badge and the update with one click (update.py).

1. Versions: «v0.4.10» is newer than «0.4.9», a tag without a number is not.
2. The JSON of GitHub: the installer and SHA256SUMS.txt of the release.
3. A download from a local server: the progress goes from 0 to the size,
   the file is the same; a cancel stops it.
4. The arguments of the installer: silent, /WAITPID, /RELAUNCH=1, the
   language, /ALLUSERS only for a folder in Program Files.
5. The badge: «v…» at the start, «Update to X» after a newer release, the
   latest version gives the plain version; a click on a copy from source
   opens the page (not an install).

    python tests/test_update.py
"""
import _isolate  # noqa: F401  (temp settings, NO_UPDATE_CHECK=1)

import hashlib
import http.server
import json
import os
import sys
import tempfile
import threading
import time

from PySide6 import QtCore, QtWidgets

from meshfix_studio import update as up

FAILS = []


def check(name, ok, detail=""):
    print(("  ok   " if ok else "  FAIL ") + name
          + ("" if ok else f"  ({detail})"))
    if not ok:
        FAILS.append(name)


def serve(folder):
    class H(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a, **kw):
            super().__init__(*a, directory=folder, **kw)

        def log_message(self, *a):
            pass

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
    srv.handle_error = lambda *a: None      # a cancelled download
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}"


def main():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    print("1. versions")
    check("0.4.10 > 0.4.9", up.newer("v0.4.10", "0.4.9"))
    check("0.4.3 = 0.4.3.0 is not newer", not up.newer("0.4.3", "0.4.3.0"))
    check("an older one is not newer", not up.newer("v0.4.2", "0.4.3"))
    check("a tag without a number is not newer", not up.newer("latest", "0.4"))

    print("2. the JSON of a release")
    tmp = tempfile.mkdtemp(prefix="meshfix-update-")
    name = "MeshFix-Studio-9.9.9-windows-x64-setup.exe"
    payload = os.urandom(3 * 1024 * 1024 + 123)
    with open(os.path.join(tmp, name), "wb") as fh:
        fh.write(payload)
    sha = hashlib.sha256(payload).hexdigest()
    with open(os.path.join(tmp, "SHA256SUMS.txt"), "w") as fh:
        fh.write(f"{'0' * 64}  other.whl\n{sha}  {name}\n")
    srv, base = serve(tmp)
    data = {"tag_name": "v9.9.9", "html_url": base + "/page",
            "assets": [
                {"name": "x.whl", "browser_download_url": base + "/x.whl",
                 "size": 1},
                {"name": name, "browser_download_url": f"{base}/{name}",
                 "size": len(payload)},
                {"name": "SHA256SUMS.txt",
                 "browser_download_url": base + "/SHA256SUMS.txt",
                 "size": 10}]}
    with open(os.path.join(tmp, "latest.json"), "w") as fh:
        json.dump(data, fh)
    os.environ["UPDATE_API_URL"] = base + "/latest.json"
    rel = up.latest("x/y", "-windows-x64-setup.exe", "test")
    check("version and installer",
          rel.version == "9.9.9" and rel.setup_name == name
          and rel.setup_size == len(payload), rel)
    check("SHA256SUMS.txt", rel.sums_url.endswith("/SHA256SUMS.txt"), rel)
    check("the hash of the installer line",
          up.expected_sha(open(os.path.join(tmp, "SHA256SUMS.txt")).read(),
                          name) == sha)
    check("no line: empty", up.expected_sha("abc  other\n", name) == "")

    print("3. download")
    seen = []
    dest = os.path.join(tmp, "down.exe")
    up.download(rel.setup_url, dest, "test", rel.setup_size,
                lambda d, t: seen.append((d, t)))
    check("the file is the same", up.sha256_of(dest) == sha)
    check("progress from 0 to the size, total known",
          seen[0][0] == 0 and seen[-1][0] == len(payload)
          and all(t == len(payload) for _d, t in seen) and len(seen) > 5,
          seen[:3])
    check("no .part file stays", not os.path.exists(dest + ".part"))
    ev = threading.Event()
    ev.set()
    try:
        up.download(rel.setup_url, dest + "2", "test", 0, None, ev)
        check("cancel stops the download", False)
    except InterruptedError:
        check("cancel stops the download, no file stays",
              not os.path.exists(dest + "2")
              and not os.path.exists(dest + "2.part"))
    text = str(up.progress_text(50 * 1024 * 1024, 200 * 1024 * 1024, 10.0))
    check("progress text: MB of MB and the speed",
          "50.0" in text and "200.0" in text and "5.0" in text, text)

    print("4. installer arguments")
    pf = os.environ.get("ProgramFiles", r"C:\Program Files")
    a = up.installer_args(os.path.join(pf, "MeshFix Studio"), "uk", 1234)
    check("silent, wait, start again, Ukrainian, all users",
          {"/SILENT", "/WAITPID=1234", "/RELAUNCH=1", "/LANG=uk",
           "/ALLUSERS"} <= set(a), a)
    a = up.installer_args(os.path.join(tempfile.gettempdir(), "MF"), "en", 1)
    check("a user folder: this user only, English",
          "/CURRENTUSER" in a and "/LANG=en" in a and "/ALLUSERS" not in a, a)

    print("5. the badge")
    win = QtWidgets.QMainWindow()
    opened = []
    badge = up.add_badge(win, app_name="MeshFix Studio", version="0.4.3",
                         repo="x/y", frozen=False)
    badge.open_page = lambda: opened.append(True)
    check("in the corner of the menu bar",
          win.menuBar().cornerWidget(QtCore.Qt.TopRightCorner) is badge)
    check("the version at the start", badge.text() == "v0.4.3", badge.text())
    badge.check()
    t0 = time.monotonic()
    while badge.state == "checking" and time.monotonic() - t0 < 15:
        app.processEvents(QtCore.QEventLoop.AllEvents, 50)
    check("a newer release: «Update to 9.9.9»",
          badge.state == "new" and "9.9.9" in badge.text(), badge.text())
    badge.click()
    app.processEvents()
    check("a copy from source opens the page", opened == [True], opened)
    os.environ["UPDATE_AS_VERSION"] = "9.9.9"
    badge.check()
    t0 = time.monotonic()
    while badge.state == "checking" and time.monotonic() - t0 < 15:
        app.processEvents(QtCore.QEventLoop.AllEvents, 50)
    check("the latest version: the plain version",
          badge.state == "latest" and badge.text() == "v0.4.3",
          (badge.state, badge.text()))
    os.environ.pop("UPDATE_AS_VERSION")
    os.environ["UPDATE_API_URL"] = base + "/missing.json"
    badge.check()
    t0 = time.monotonic()
    while badge.state == "checking" and time.monotonic() - t0 < 15:
        app.processEvents(QtCore.QEventLoop.AllEvents, 50)
    check("an error: the plain version, the error in the tooltip",
          badge.state == "failed" and badge.text() == "v0.4.3"
          and "404" in badge.toolTip(), badge.toolTip())
    srv.shutdown()
    win.close()
    print("FAILED: " + ", ".join(FAILS) if FAILS else "update: all checks passed")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())

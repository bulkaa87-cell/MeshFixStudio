"""Make the icon files of MeshFix Studio from the logo (meshfix-studio.svg).

The files are in git, so a build does not run this script. Run it only
after a change to the SVG, then commit the files that it writes:

    python packaging/icons/make_icons.py      (needs PySide6 and Pillow)

It writes:
- packaging/icons/meshfix-studio.ico     Windows: the exe and the installer
- packaging/icons/meshfix-studio.icns    macOS: the .app
- packaging/icons/meshfix-studio.png     Linux: the AppImage (256 px)
- packaging/icons/png/meshfix-studio-<n>.png     16 .. 1024 px
- packaging/icons/wizard-large-<pct>.bmp, wizard-small-<pct>.bmp
                                          the pictures of the installer
- packaging/icons/social-preview.png     1280 x 640, for the GitHub page
- app/meshfix_studio/icons/meshfix-studio-<n>.png   the window icon

The picture: a triangle in 4 parts on a dark tile. The middle part is
green: the patch of a repair.
"""

import io
import os
import sys

from PIL import Image
from PySide6 import QtCore, QtGui, QtSvg

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
SVG = os.path.join(HERE, "meshfix-studio.svg")
NAME = "meshfix-studio"
PNG_SIZES = [16, 24, 32, 48, 64, 128, 256, 512, 1024]
ICO_SIZES = [16, 20, 24, 32, 40, 48, 64, 128, 256]
ICNS_SIZES = [16, 32, 64, 128, 256, 512, 1024]
WINDOW_SIZES = [16, 24, 32, 48, 64, 128, 256]
TILE = QtGui.QColor("#16233F")
# The pictures of the installer (Inno Setup, WizardStyle=modern) for
# 100 % and 200 % display scale (Inno Setup selects the nearest).
WIZARD_LARGE = {100: (164, 314), 200: (328, 604)}
WIZARD_SMALL = {100: (55, 55), 200: (110, 106)}


def qimage_to_pil(img: QtGui.QImage) -> Image.Image:
    buf = QtCore.QBuffer()
    buf.open(QtCore.QIODevice.WriteOnly)
    img.save(buf, "PNG")
    return Image.open(io.BytesIO(bytes(buf.data()))).convert("RGBA")


def canvas(w: int, h: int, fill=None) -> QtGui.QImage:
    img = QtGui.QImage(w, h, QtGui.QImage.Format_ARGB32_Premultiplied)
    img.fill(fill if fill is not None else QtCore.Qt.transparent)
    return img


def paint_logo(img: QtGui.QImage, rect: QtCore.QRectF) -> None:
    painter = QtGui.QPainter(img)
    painter.setRenderHint(QtGui.QPainter.Antialiasing)
    QtSvg.QSvgRenderer(SVG).render(painter, rect)
    painter.end()


def logo(size: int) -> Image.Image:
    img = canvas(size, size)
    paint_logo(img, QtCore.QRectF(0, 0, size, size))
    return qimage_to_pil(img)


def wizard_large(w: int, h: int) -> Image.Image:
    img = canvas(w, h, TILE)
    side = w * 0.72
    paint_logo(img, QtCore.QRectF((w - side) / 2, h * 0.30 - side / 2,
                                  side, side))
    return qimage_to_pil(img).convert("RGB")


def wizard_small(w: int, h: int) -> Image.Image:
    img = canvas(w, h, QtGui.QColor("#FFFFFF"))
    side = min(w, h)
    paint_logo(img, QtCore.QRectF((w - side) / 2, (h - side) / 2, side, side))
    return qimage_to_pil(img).convert("RGB")


def social_preview(w: int = 1280, h: int = 640) -> Image.Image:
    img = canvas(w, h, TILE)
    side = 360
    paint_logo(img, QtCore.QRectF(110, (h - side) / 2, side, side))
    painter = QtGui.QPainter(img)
    painter.setRenderHint(QtGui.QPainter.Antialiasing)
    painter.setRenderHint(QtGui.QPainter.TextAntialiasing)
    font = QtGui.QFont(["Segoe UI", "Helvetica Neue", "DejaVu Sans", "Arial"])
    font.setPixelSize(92)
    font.setWeight(QtGui.QFont.Bold)
    painter.setFont(font)
    painter.setPen(QtGui.QColor("#F4F7FB"))
    painter.drawText(QtCore.QRectF(540, 190, 720, 120),
                     QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter,
                     "MeshFix Studio")
    font.setPixelSize(40)
    font.setWeight(QtGui.QFont.Normal)
    painter.setFont(font)
    painter.setPen(QtGui.QColor("#4ADE80"))
    painter.drawText(QtCore.QRectF(544, 320, 720, 120),
                     QtCore.Qt.AlignLeft | QtCore.Qt.AlignTop,
                     "Repair triangle meshes:\nSTL, OBJ, PLY")
    painter.end()
    return qimage_to_pil(img).convert("RGB")


def main() -> None:
    app = QtGui.QGuiApplication.instance() or QtGui.QGuiApplication(sys.argv[:1])
    assert app is not None
    pngs = {n: logo(n) for n in sorted(set(PNG_SIZES + ICO_SIZES))}

    out = os.path.join(HERE, "png")
    os.makedirs(out, exist_ok=True)
    for n in PNG_SIZES:
        pngs[n].save(os.path.join(out, f"{NAME}-{n}.png"), optimize=True)
    pngs[256].save(os.path.join(HERE, f"{NAME}.png"), optimize=True)

    # Each size of the .ico and the .icns is drawn at its size (not scaled
    # down from one big picture): the lines stay sharp at 16 px.
    big = pngs[256]
    big.save(os.path.join(HERE, f"{NAME}.ico"),
             sizes=[(n, n) for n in ICO_SIZES],
             append_images=[pngs[n] for n in ICO_SIZES if n != 256])
    pngs[1024].save(os.path.join(HERE, f"{NAME}.icns"),
                    append_images=[pngs[n] for n in ICNS_SIZES if n != 1024])

    for pct, (w, h) in WIZARD_LARGE.items():
        wizard_large(w, h).save(os.path.join(HERE, f"wizard-large-{pct}.bmp"))
    for pct, (w, h) in WIZARD_SMALL.items():
        wizard_small(w, h).save(os.path.join(HERE, f"wizard-small-{pct}.bmp"))
    social_preview().save(os.path.join(HERE, "social-preview.png"),
                          optimize=True)

    win = os.path.join(ROOT, "app", "meshfix_studio", "icons")
    os.makedirs(win, exist_ok=True)
    for n in WINDOW_SIZES:
        pngs[n].save(os.path.join(win, f"{NAME}-{n}.png"), optimize=True)
    print("icons in", HERE, "and", win)


if __name__ == "__main__":
    main()

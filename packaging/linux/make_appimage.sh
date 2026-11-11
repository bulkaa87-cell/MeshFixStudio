#!/bin/sh
# Make the Linux AppImage from the PyInstaller folder.
#
#   sh packaging/linux/make_appimage.sh 0.1.0
#
# Input: "dist/MeshFix Studio/" and packaging/icons/meshfix-studio.png.
# Output: dist/MeshFix-Studio-<version>-linux-x86_64.AppImage.
# appimagetool is downloaded once to build/ (it runs without FUSE through
# APPIMAGE_EXTRACT_AND_RUN). Build on the oldest Linux that you support:
# the AppImage needs the glibc of the build system or newer.
set -eu
VERSION="${1:-0.1.0}"
SRC="dist/MeshFix Studio"
APPDIR="build/AppDir"
OUT="dist/MeshFix-Studio-${VERSION}-linux-x86_64.AppImage"
TOOL="build/appimagetool-x86_64.AppImage"
test -d "$SRC"
rm -rf "$APPDIR"
mkdir -p "$APPDIR/usr/lib" "$APPDIR/usr/share/applications" \
         "$APPDIR/usr/share/icons/hicolor/256x256/apps"
cp -R "$SRC" "$APPDIR/usr/lib/meshfix-studio"
cp packaging/linux/AppRun "$APPDIR/AppRun"
chmod +x "$APPDIR/AppRun"
cp packaging/linux/meshfix-studio.desktop "$APPDIR/meshfix-studio.desktop"
cp packaging/linux/meshfix-studio.desktop "$APPDIR/usr/share/applications/"
cp packaging/icons/meshfix-studio.png "$APPDIR/meshfix-studio.png"
cp packaging/icons/meshfix-studio.png "$APPDIR/usr/share/icons/hicolor/256x256/apps/"
mkdir -p build
if [ ! -x "$TOOL" ]; then
    curl -fsSL -o "$TOOL" \
        https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-x86_64.AppImage
    chmod +x "$TOOL"
fi
rm -f "$OUT"
ARCH=x86_64 APPIMAGE_EXTRACT_AND_RUN=1 "$TOOL" "$APPDIR" "$OUT"
echo "$OUT"

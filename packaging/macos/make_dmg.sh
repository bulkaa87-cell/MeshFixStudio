#!/bin/sh
# Make the macOS disk image from the PyInstaller bundle.
#
#   sh packaging/macos/make_dmg.sh 0.1.0 arm64     (or x86_64)
#
# Input: "dist/MeshFix Studio.app". Output:
# dist/MeshFix-Studio-<version>-macos-<arch>.dmg.
#
# The app has only an ad-hoc signature (codesign -s -), not a Developer ID
# signature, and it is not notarized. macOS then blocks the first start:
# the person must open it with right click > Open, or allow it in System
# Settings > Privacy & Security. A Developer ID signature and notarization
# need an Apple Developer account (see PLAN.md).
set -eu
VERSION="${1:-0.1.0}"
ARCH="${2:-$(uname -m)}"
APP="dist/MeshFix Studio.app"
OUT="dist/MeshFix-Studio-${VERSION}-macos-${ARCH}.dmg"
test -d "$APP"
codesign --force --deep --sign - "$APP"
STAGE="$(mktemp -d)"
cp -R "$APP" "$STAGE/"
ln -s /Applications "$STAGE/Applications"
rm -f "$OUT"
hdiutil create -volname "MeshFix Studio" -srcfolder "$STAGE" -ov -format ULMO "$OUT"
rm -rf "$STAGE"
echo "$OUT"

#!/bin/sh
# The app icon from make_icon.swift: icon.iconset/ (every size macOS asks for) and AppIcon.icns, in this folder.
# Usage: frontend/make_icon.sh   (then copy AppIcon.icns into NS Port Builder.app/Contents/Resources/)
set -e
cd "$(dirname "$0")"
tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT
swift make_icon.swift "$tmp/master.png"
mkdir -p icon.iconset
for s in 16 32 64 128 256 512; do
  sips -z $s $s "$tmp/master.png" --out "icon.iconset/icon_${s}x${s}.png" >/dev/null
  sips -z $((s * 2)) $((s * 2)) "$tmp/master.png" --out "icon.iconset/icon_${s}x${s}@2x.png" >/dev/null
done
iconutil -c icns icon.iconset -o AppIcon.icns
echo "AppIcon.icns"

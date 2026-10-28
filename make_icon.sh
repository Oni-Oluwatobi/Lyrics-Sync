#!/usr/bin/env bash
#
# Lyric Sync — generate the macOS app icon (assets/LyricSync.icns) from a
# single square PNG. lyricsync_mac.spec picks the .icns up automatically if
# present; without it the app uses the default PyInstaller icon.
#
#   ./make_icon.sh [path/to/icon_1024.png]
#
# The PNG should be 1024x1024 (brand: orange #FF6A00 on deep charcoal,
# per the TKG brand constitution). No PNG? The build still works without it.
#
set -euo pipefail
cd "$(dirname "$0")"

SRC="${1:-assets/LyricSync_1024.png}"
OUT="assets/LyricSync.icns"
WORK="assets/icon.iconset"

if [[ ! -f "$SRC" ]]; then
  echo "error: source icon not found: $SRC" >&2
  echo "usage: ./make_icon.sh [path/to/1024x1024.png]" >&2
  exit 1
fi

echo "==> creating icon set from $SRC"
mkdir -p "$WORK"
for size in 16 32 128 256 512; do
  sips -z "$size" "$size" "$SRC" --out "$WORK/icon_${size}x${size}.png" >/dev/null
  dbl=$((size * 2))
  sips -z "$dbl" "$dbl" "$SRC" --out "$WORK/icon_${size}x${size}@2x.png" >/dev/null
done

echo "==> compiling $OUT"
iconutil -c icns "$WORK" -o "$OUT"
rm -rf "$WORK"

echo "done: $OUT (picked up by the next ./build_mac.sh run)"

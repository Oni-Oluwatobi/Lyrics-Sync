#!/usr/bin/env bash
#
# Lyric Sync — macOS build script.
#
# Run this ON A MAC (PyInstaller cannot cross-compile; the Windows build is
# produced on Windows from lyricsync.spec + LyricSync.iss and is unaffected
# by this script).
#
#   ./build_mac.sh
#
# Result: dist/LyricSync.app  (Finder-launchable; drag to /Applications)
#
# Optional environment variables:
#   PYTHON=python3.12     interpreter to build with (must be 3.10+)
#   MAKE_DMG=1            also produce dist/LyricSync-<version>.dmg
#   CODESIGN_IDENTITY="Developer ID Application: ..."   sign the bundle
#   NOTARIZE_PROFILE=my-profile   notarize via `notarytool` keychain profile
#                                 (requires a signed build; see MACOS_BUILD.md)
#
set -euo pipefail
cd "$(dirname "$0")"

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "error: this script builds the macOS app and must run on macOS." >&2
  echo "hint: the Windows version is built on Windows with lyricsync.spec." >&2
  exit 1
fi

PYTHON="${PYTHON:-python3}"
VERSION="$(sed -n 's/^VERSION = "\(.*\)"/\1/p' lyric_sync/app/config.py | head -n1)"
VERSION="${VERSION:-1.5.0}"
APP="dist/LyricSync.app"
BIN="$APP/Contents/MacOS/LyricSync"

echo "==> Lyric Sync $VERSION macOS build"
echo "==> interpreter: $($PYTHON --version 2>&1) ($PYTHON)"

# --- 1. Dependencies -------------------------------------------------------
echo "==> installing dependencies (PySide6 + PyInstaller)"
"$PYTHON" -m pip install --quiet --upgrade pip
"$PYTHON" -m pip install --quiet -r requirements.txt pyinstaller

# --- 2. Build the .app bundle ---------------------------------------------
echo "==> running PyInstaller (lyricsync_mac.spec)"
"$PYTHON" -m PyInstaller --clean --noconfirm lyricsync_mac.spec

[[ -x "$BIN" ]] || { echo "error: build produced no executable at $BIN" >&2; exit 1; }
echo "==> built: $APP"
echo "==> bundle architecture: $(file -b "$BIN" | head -c 120)"

# --- 3. Smoke test (self-check) -------------------------------------------
# Resolves the database, loads search_engine.py and runs one real search.
# The report is written to the user-data directory (no console in GUI builds).
echo "==> running packaged self-check"
if "$BIN" --self-check; then
  echo "==> self-check PASSED"
else
  echo "==> self-check reported a problem (often: no database inside the app yet)."
  echo "    See: ~/Library/Application Support/LyricSync/self_check.txt"
  echo "    To supply the database, either rebuild with data/lyric_sync_gospel.lsdb"
  echo "    present in the project, or copy it to:"
  echo "      ~/Library/Application Support/LyricSync/data/lyric_sync_gospel.lsdb"
fi
[[ -f "$HOME/Library/Application Support/LyricSync/self_check.txt" ]] \
  && cat "$HOME/Library/Application Support/LyricSync/self_check.txt"

# --- 4. Optional: DMG ------------------------------------------------------
if [[ "${MAKE_DMG:-0}" == "1" ]]; then
  echo "==> creating DMG"
  STAGE="$(mktemp -d)"
  trap 'rm -rf "$STAGE"' EXIT
  cp -R "$APP" "$STAGE/"
  ln -s /Applications "$STAGE/Applications"
  hdiutil create -volname "Lyric Sync" -srcfolder "$STAGE" -ov -format UDZO \
    "dist/LyricSync-$VERSION.dmg" >/dev/null
  echo "==> dist/LyricSync-$VERSION.dmg"
fi

# --- 5. Optional: codesign + notarize --------------------------------------
if [[ -n "${CODESIGN_IDENTITY:-}" ]]; then
  echo "==> codesigning with: $CODESIGN_IDENTITY"
  codesign --deep --force --options runtime --timestamp \
    --sign "$CODESIGN_IDENTITY" "$APP"
  codesign --verify --deep --strict "$APP" && echo "==> signature valid"
  if [[ -n "${NOTARIZE_PROFILE:-}" ]]; then
    echo "==> notarizing (keychain profile: $NOTARIZE_PROFILE)"
    ZIP="$(mktemp -d)/LyricSync.zip"
    ditto -c -k --keepParent "$APP" "$ZIP"
    xcrun notarytool submit "$ZIP" --keychain-profile "$NOTARIZE_PROFILE" --wait
    xcrun stapler staple "$APP"
    echo "==> notarized + stapled"
  fi
fi

echo ""
echo "Done. Drag $APP to /Applications, or run MAKE_DMG=1 ./build_mac.sh for an installer image."

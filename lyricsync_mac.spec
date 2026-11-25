# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for Lyric Sync (macOS desktop build).

Build ON A MAC (PyInstaller does not cross-compile):

    python3 -m PyInstaller --clean --noconfirm lyricsync_mac.spec

or simply run ``./build_mac.sh`` from the project root.

Output: ``dist/LyricSync.app`` — a Finder-launchable bundle. The Windows
build stays defined by ``lyricsync.spec`` + ``LyricSync.iss`` and is not
touched by this file.

Feature parity with Windows: identical hiddenimports, Qt exclusions and
data files (search engine + optional database / dev fixture / Firebase
config). The only macOS additions are the BUNDLE step and the Info.plist.
"""

from PyInstaller.utils.hooks import collect_submodules

# Only the Qt modules Lyric Sync actually imports. Keeps the build small and
# avoids dragging QtWebEngine/3D/QML into the package. (Same list as the
# Windows spec — keep both files in sync.)
QT_EXCLUDES = [
    "PySide6.QtWebEngineCore",
    "PySide6.QtWebEngineWidgets",
    "PySide6.QtQuick",
    "PySide6.QtQuick3D",
    "PySide6.QtQml",
    "PySide6.Qt3DCore",
    "PySide6.Qt3DRender",
    "PySide6.QtCharts",
    "PySide6.QtDataVisualization",
    "PySide6.QtMultimedia",
    "PySide6.QtMultimediaWidgets",
    "PySide6.QtOpenGL",
    "PySide6.QtOpenGLWidgets",
    "PySide6.QtPdf",
    "PySide6.QtPdfWidgets",
    "PySide6.QtPositioning",
    "PySide6.QtLocation",
    "PySide6.QtSensors",
    "PySide6.QtSerialPort",
    "PySide6.QtSql",
    "PySide6.QtTest",
    "PySide6.QtUiTools",
    "PySide6.QtWebChannel",
    "PySide6.QtWebSockets",
    "PySide6.QtDesigner",
    "PySide6.QtHelp",
    "PySide6.QtNetworkAuth",
    "PySide6.QtRemoteObjects",
    "PySide6.QtScxml",
    "PySide6.QtSpatialAudio",
    "PySide6.QtTextToSpeech",
    "PySide6.QtStateMachine",
    "PySide6.QtTools",
]

hiddenimports = (
    collect_submodules("lyric_sync")
    + collect_submodules("PySide6.QtCore")
    + collect_submodules("PySide6.QtGui")
    + collect_submodules("PySide6.QtWidgets")
)

import os

_datas = []
# The downloaded search engine must ship with the app: the loader looks for it
# inside the packaged resources, so it lands at the bundle resource root.
if os.path.isfile("search_engine.py"):
    _datas.append(("search_engine.py", "."))
# Production database, when present in the source tree, ships inside the app.
# It is accepted both in the canonical data/ folder and at the project root.
# (Users can also drop the database into
#  ~/Library/Application Support/LyricSync/data/ at any later time.)
_prod_data = os.path.join("data", "lyric_sync_gospel.lsdb")
_prod_root = "lyric_sync_gospel.lsdb"
if os.path.isfile(_prod_data):
    _datas.append((_prod_data, "data"))
elif os.path.isfile(_prod_root):
    _datas.append((_prod_root, "data"))
# Ships the development fixture as data/lyric_sync_dev_fixture.lsdb so the
# packaged app can be exercised without a production database.
_fixture = os.path.join("tests", "fixtures", "lyric_sync_dev_fixture.lsdb")
if os.path.isfile(_fixture):
    _datas.append((_fixture, "data"))
# Public Firebase web configuration (API key only — no secrets). Optional at
# runtime: without it the app runs exactly as before, just signed out.
if os.path.isfile("firebase_config.json"):
    _datas.append(("firebase_config.json", "."))

# Optional branded icon: generate assets/LyricSync.icns with make_icon.sh.
# Without it the bundle simply uses the default PyInstaller icon.
_icon = os.path.join("assets", "LyricSync.icns")
_icon = _icon if os.path.isfile(_icon) else None

APP_NAME = "Lyric Sync"
BUNDLE_IDENTIFIER = "com.kreadivegalaxy.lyricsync"
# Keep in sync with lyric_sync.app.config.VERSION.
VERSION = "1.5.4"

info_plist = {
    "CFBundleName": APP_NAME,
    "CFBundleDisplayName": APP_NAME,
    "CFBundleIdentifier": BUNDLE_IDENTIFIER,
    "CFBundleShortVersionString": VERSION,
    "CFBundleVersion": VERSION,
    "LSMinimumSystemVersion": "10.14",
    "LSApplicationCategoryType": "public.app-category.music",
    # Retina support; Qt needs this to render at native resolution.
    "NSHighResolutionCapable": True,
    "NSPrincipalClass": "NSApplication",
    "NSHumanReadableCopyright": "Copyright \u00a9 2026 The Kreadive Galaxy.",
}
if _icon:
    info_plist["CFBundleIconFile"] = "LyricSync"

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=[],
    datas=_datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=QT_EXCLUDES,
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="LyricSync",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="LyricSync",
)

# The step the Windows spec deliberately omits: a real macOS .app bundle.
# PyInstaller ad-hoc signs automatically on Apple Silicon; set an identity via
# build_mac.sh (CODESIGN_IDENTITY) for distribution.
app = BUNDLE(
    coll,
    name="LyricSync.app",
    icon=_icon,
    bundle_identifier=BUNDLE_IDENTIFIER,
    version=VERSION,
    info_plist=info_plist,
)

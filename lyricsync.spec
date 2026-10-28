# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for Lyric Sync (Windows desktop build).

Build:

    python -m PyInstaller --clean --noconfirm lyricsync.spec

Output: ``dist/LyricSync/LyricSync.exe`` (folder build — start-up is fast and
the Gospel database can be dropped into ``dist/LyricSync/data/``).
"""

from PyInstaller.utils.hooks import collect_submodules

# Only the Qt modules Lyric Sync actually imports. Keeps the build small and
# avoids dragging QtWebEngine/3D/QML into the package.
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
# next to the packaged resources, so it lands at the bundle root.
if os.path.isfile("search_engine.py"):
    _datas.append(("search_engine.py", "."))
# Production database, when present in the source tree, ships next to the app.
# It is accepted both in the canonical data/ folder and at the project root.
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

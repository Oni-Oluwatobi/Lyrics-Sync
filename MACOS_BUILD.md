# Lyric Sync — Building the Two Desktop Versions

Lyric Sync ships as **two separate builds of the same codebase**:

| Version | Build files | Output | Built on |
|---|---|---|---|
| **Windows laptop** | `lyricsync.spec` + `LyricSync.iss` (Inno Setup) | `dist/LyricSync/LyricSync.exe` + installer | Windows |
| **MacBook (macOS)** | `lyricsync_mac.spec` + `build_mac.sh` | `dist/LyricSync.app` (+ optional DMG) | macOS |

Both versions have **full feature parity** — identical search, favourites,
preferences, theming (light/dark/system), session sign-in and self-check.
Nothing was stripped for portability. PyInstaller does not cross-compile,
so each build must run on its own OS; the source tree is shared unchanged.

---

## What changed in the code for macOS (all additive)

Three small edits, each Windows-safe — the Windows build behaves exactly as
before:

1. **`lyric_sync/app/theme.py`** — `system_is_dark()` now also reads the macOS
   preference (`defaults read -g AppleInterfaceStyle`) for headless detection
   before `QApplication` exists. In-app "system" theme follows macOS dark/light.
2. **`lyric_sync/app/config.py`** — `candidate_database_paths()` gained two
   *user-data* candidates (`~/Library/Application Support/LyricSync/data/…`,
   and the same folder flat). Needed because signed `.app` bundles are
   read-only, so users need a writable drop-in location for the database.
   These are checked **last**, so all existing lookup orders are unchanged.
3. **`lyric_sync/app/self_check.py`** — docstring now names both platforms.

Everything else was already cross-platform: `config.user_data_dir()` has a
`darwin` branch, and `secure_store.py` guards DPAPI behind `sys.platform`.

---

## macOS prerequisites

- A Mac (Intel or Apple Silicon) on macOS 10.14+
- Python 3.10 or newer (`python3 --version`)
- Xcode Command Line Tools (`xcode-select --install`) — for `codesign`/`hdiutil`

## No MacBook? Build on GitHub's Macs (free)

You do **not** need to own a Mac to produce the macOS version. The repo ships
`.github/workflows/macos-build.yml`, which builds `LyricSync.app` + a DMG on
Apple's hosted macOS runners and hands them back to you as a download.

1. Push this folder to a **private** GitHub repository
   (`git init && git add -A && git commit -m "Lyric Sync"`, then create the
   repo on github.com and push). Keep it private — it contains your product.
2. On GitHub: **Actions → macOS build → Run workflow** (or push a `v*` tag).
3. When the run finishes, open the run → **Artifacts → LyricSync-macOS** →
   download the zip or dmg. Total build time is about 5–10 minutes.

Notes:

* The runner builds an **Apple Silicon** app (every Mac sold since 2020).
  For an Intel-only Mac, run `./build_mac.sh` once on any borrowed Mac.
* Builds are **ad-hoc signed** — the person downloading right-clicks →
  Open once. No Apple account is needed to build or to use it yourself.
* If the checkout contains `lyric_sync_gospel.lsdb`, it is bundled and the
  workflow **enforces a passing self-check** (a real search runs on Apple's
  server). Without it, the build still succeeds and users drop the database
  into `~/Library/Application Support/LyricSync/data/`.
* When you later sell/distribute widely, add a *Developer ID* certificate
  ($99/yr Apple Developer account) as repo secrets and extend the workflow
  with the codesign/notarize steps — same commands as `build_mac.sh`.

Other ways to get a Mac build: borrow any Mac briefly and run
`./build_mac.sh`, or use a cloud-Mac rental service. Running macOS in a
virtual machine on a Windows PC violates Apple's licence and is not
something I'll help set up.

## Build the Mac version (on a Mac)

```bash
cd "Lyrics Sync"
./build_mac.sh
```

The script: installs PySide6 + PyInstaller → runs `lyricsync_mac.spec` →
produces `dist/LyricSync.app` → runs the packaged **self-check** (resolves the
database, loads `search_engine.py`, performs a real search; report written to
`~/Library/Application Support/LyricSync/self_check.txt`).

Manual equivalent:

```bash
python3 -m pip install -r requirements.txt pyinstaller
python3 -m PyInstaller --clean --noconfirm lyricsync_mac.spec
```

Optional flags (env vars for `build_mac.sh`):

```bash
MAKE_DMG=1 ./build_mac.sh                  # also build dist/LyricSync-1.0.0.dmg
CODESIGN_IDENTITY="Developer ID Application: Your Name (TEAMID)" ./build_mac.sh
NOTARIZE_PROFILE=lyricsync ./build_mac.sh  # notarize via notarytool profile
```

## Shipping the Gospel database with the Mac app

The app searches these locations in order (first hit wins):

1. `LYRIC_SYNC_DATABASE` environment variable (explicit override)
2. The folder you launch from / the source checkout (`data/…`)
3. **Inside the app bundle** — if `data/lyric_sync_gospel.lsdb` exists in the
   project at build time, it is bundled automatically (same rule as Windows)
4. **`~/Library/Application Support/LyricSync/data/lyric_sync_gospel.lsdb`**
   — the writable drop-in location; copy the database here any time, no
   rebuild needed

The database file is `lyric_sync_gospel.lsdb` (~35 MB, currently v3.3.0,
5,131 songs / 57,616 lyric lines).

## App icon (optional)

The repo ships no icon assets, so the bundle uses the default PyInstaller
icon. To brand it:

```bash
./make_icon.sh path/to/LyricSync_1024.png   # 1024x1024 PNG, brand orange #FF6A00
./build_mac.sh                              # picks up assets/LyricSync.icns
```

## Signing & distribution notes

- On Apple Silicon, PyInstaller **ad-hoc signs** automatically — the app runs
  locally. For distribution outside your own machines you need a *Developer
  ID Application* certificate (`CODESIGN_IDENTITY=…`) and, on macOS 10.15+,
  notarization (`NOTARIZE_PROFILE=…`, a `notarytool` keychain profile).
- Gatekeeper first-run: unsigned/ad-hoc builds require right-click → Open on
  first launch (or `xattr -dr com.apple.quarantine dist/LyricSync.app`).

## Honest feature-parity caveats

- **Session storage:** on Windows, Firebase session tokens are encrypted with
  DPAPI (tied to the user account). macOS has no DPAPI, so the app uses its
  documented fallback: tokens + email stored unencrypted in
  `~/Library/Application Support/LyricSync/` — **never the password**. A
  macOS Keychain upgrade is a possible follow-up.
- **Self-check command:** `LyricSync.exe --self-check` (Windows) ↔
  `LyricSync.app/Contents/MacOS/LyricSync --self-check` (macOS). Identical
  logic and report file.

## Windows build (unchanged)

```bat
python -m PyInstaller --clean --noconfirm lyricsync.spec
iscc LyricSync.iss
```

`lyricsync.spec` and `LyricSync.iss` were not modified; the macOS spec is a
separate file that mirrors them (same Qt exclusions, hidden imports and data
files) plus the `BUNDLE` step.

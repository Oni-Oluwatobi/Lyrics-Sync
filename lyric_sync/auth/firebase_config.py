"""Runtime loading of the public Firebase web configuration.

The configuration file contains only public web-app values (the API key is
designed to ship in client bundles) — never service-account keys or other
secrets.  If the file is missing the application simply runs without
account sign-in.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from lyric_sync.app import config as app_config

ENV_FIREBASE_CONFIG = "LYRIC_SYNC_FIREBASE_CONFIG"
CONFIG_FILENAME = "firebase_config.json"


def candidate_paths() -> list[Path]:
    """Ordered locations searched for ``firebase_config.json``."""
    paths: list[Path] = []
    override = os.environ.get(ENV_FIREBASE_CONFIG)
    if override:
        paths.append(Path(override))
    paths.append(app_config.project_root() / CONFIG_FILENAME)
    bundle = app_config.bundle_dir()
    if bundle is not None:
        paths.append(bundle / CONFIG_FILENAME)
    paths.append(app_config.executable_dir() / CONFIG_FILENAME)
    paths.append(app_config.user_data_dir() / CONFIG_FILENAME)
    return paths


def load_firebase_config(path: Path | None = None) -> dict | None:
    """Return the configuration dict, or ``None`` when unavailable."""
    candidates = [path] if path is not None else candidate_paths()
    for candidate in candidates:
        if candidate is None:
            continue
        try:
            data = json.loads(Path(candidate).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(data, dict) and data.get("apiKey"):
            return data
    return None


def is_configured() -> bool:
    return load_firebase_config() is not None

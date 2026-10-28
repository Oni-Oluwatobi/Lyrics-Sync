"""Locate and import the downloaded Lyric Sync search engine module.

The production search engine (``search_engine.py``) ships next to the
application, in the source checkout and inside the packaged resources. It is
loaded by path so the same code works in development and inside a PyInstaller
build without ``sys.path`` tricks.
"""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path
from types import ModuleType

from lyric_sync.app import config

ENGINE_FILENAME = "search_engine.py"
ENGINE_CLASS = "LyricSyncSearchEngine"
ENV_ENGINE_PATH = "LYRIC_SYNC_ENGINE"
_MODULE_NAME = "lyric_sync_downloaded_engine"

_loaded: ModuleType | None = None
_loaded_from: Path | None = None


class SearchEngineUnavailable(RuntimeError):
    """The downloaded search engine module could not be found or imported."""

    def __init__(self, message: str, *, user_message: str, path: Path | None = None) -> None:
        super().__init__(message)
        self.user_message = user_message
        self.path = path


def candidate_paths() -> list[Path]:
    """Ordered locations checked for ``search_engine.py``."""
    candidates: list[Path] = []
    seen: set[Path] = set()

    def add(path: Path) -> None:
        try:
            resolved = Path(path)
        except (TypeError, ValueError):
            return
        if resolved not in seen:
            seen.add(resolved)
            candidates.append(resolved)

    env = os.environ.get(ENV_ENGINE_PATH)
    if env:
        add(Path(env))
    add(config.project_root() / ENGINE_FILENAME)
    add(Path.cwd() / ENGINE_FILENAME)
    add(config.executable_dir() / ENGINE_FILENAME)
    bundle = config.bundle_dir()
    if bundle is not None:
        add(bundle / ENGINE_FILENAME)
    return candidates


def find_engine_file() -> Path | None:
    for path in candidate_paths():
        if path.is_file():
            return path
    return None


def load_engine_module(*, force: bool = False) -> ModuleType:
    """Import (once) and return the downloaded search engine module."""
    global _loaded, _loaded_from
    if _loaded is not None and not force:
        return _loaded

    path = find_engine_file()
    if path is None:
        searched = "\n".join(f"  - {item}" for item in candidate_paths())
        raise SearchEngineUnavailable(
            f"{ENGINE_FILENAME} was not found. Searched:\n{searched}",
            user_message=(
                f"The Lyric Sync search engine ({ENGINE_FILENAME}) could not be "
                "found next to the application."
            ),
        )

    try:
        spec = importlib.util.spec_from_file_location(_MODULE_NAME, path)
        if spec is None or spec.loader is None:
            raise ImportError(f"cannot create an import spec for {path}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[_MODULE_NAME] = module
        spec.loader.exec_module(module)
    except Exception as exc:  # noqa: BLE001 - reported to the UI as a friendly error
        sys.modules.pop(_MODULE_NAME, None)
        raise SearchEngineUnavailable(
            f"failed to import {path}: {exc.__class__.__name__}: {exc}",
            user_message=(
                f"The Lyric Sync search engine ({ENGINE_FILENAME}) could not be loaded."
            ),
            path=path,
        ) from exc

    if not hasattr(module, ENGINE_CLASS):
        sys.modules.pop(_MODULE_NAME, None)
        raise SearchEngineUnavailable(
            f"{path} does not define {ENGINE_CLASS}()",
            user_message=(
                f"The Lyric Sync search engine ({ENGINE_FILENAME}) is not the expected "
                f"module: {ENGINE_CLASS} is missing."
            ),
            path=path,
        )

    _loaded = module
    _loaded_from = path
    return module


def loaded_from() -> Path | None:
    return _loaded_from

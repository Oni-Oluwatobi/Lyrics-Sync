"""Service-level error handling: friendly messages, no crashes, no tracebacks."""

from __future__ import annotations

from pathlib import Path

import pytest

from lyric_sync.app import config
from lyric_sync.search import engine_loader
from lyric_sync.search.lyric_search_service import (
    DatabaseMissingError,
    EngineUnavailableError,
    LyricSearchService,
    ServiceError,
)


def test_open_missing_database_raises_database_missing(tmp_path: Path) -> None:
    service = LyricSearchService()
    with pytest.raises(DatabaseMissingError) as excinfo:
        service.open(tmp_path / "absent.lsdb")
    message = excinfo.value.user_message
    assert "not installed" in message.lower()
    assert "Traceback" not in excinfo.value.detail
    service.close()


def test_missing_search_engine_raises_engine_unavailable(
    tmp_path: Path, monkeypatch
) -> None:
    fake_db = tmp_path / "any.lsdb"
    fake_db.write_bytes(b"sqlite placeholder")

    monkeypatch.setenv(engine_loader.ENV_ENGINE_PATH, str(tmp_path / "nowhere.py"))
    monkeypatch.setattr(config, "project_root", lambda: tmp_path)
    monkeypatch.setattr(config, "executable_dir", lambda: tmp_path)
    monkeypatch.setattr(config, "bundle_dir", lambda: None)
    monkeypatch.chdir(tmp_path)
    # Force a fresh lookup even if a previous test already loaded the engine.
    monkeypatch.setattr(engine_loader, "_loaded", None)
    monkeypatch.setattr(engine_loader, "_loaded_from", None)

    service = LyricSearchService()
    with pytest.raises(EngineUnavailableError) as excinfo:
        service.open(fake_db)
    assert "search_engine.py" in excinfo.value.user_message
    assert "Traceback" not in excinfo.value.detail
    service.close()


def test_empty_and_malformed_queries_do_not_raise() -> None:
    service = LyricSearchService()
    for query in ("", "   ", "\t\n", "🙂"):
        response = service.search(query)
        assert response.results == []
        assert response.database_available is False  # no database attached
    service.close()


def test_search_on_closed_service_returns_unavailable() -> None:
    service = LyricSearchService()
    response = service.search("Way Maker")
    assert response.database_available is False
    assert response.note == "database_unavailable"


def test_invalid_song_ids_are_graceful() -> None:
    service = LyricSearchService()
    assert service.get_song(None) is None  # type: ignore[arg-type]
    assert service.get_song("") is None
    lyrics = service.get_lyrics(None)  # type: ignore[arg-type]
    assert lyrics.is_empty
    assert service.get_songs([]) == {}
    service.close()


def test_worker_exception_keeps_friendly_and_developer_errors_apart(
    tmp_path: Path, monkeypatch
) -> None:
    """Users get a friendly sentence; developer.log gets the traceback."""
    from lyric_sync.app import dev_log

    log_path = tmp_path / "developer.log"
    monkeypatch.setattr(dev_log, "dev_log_path", lambda: log_path)

    class ExplodingEngine:
        conn = None

        def search(self, *_args, **_kwargs):
            raise ValueError("engine exploded")

        def close(self) -> None:  # pragma: no cover - not reached
            pass

    service = LyricSearchService()
    service._engine = ExplodingEngine()
    service._path = tmp_path / "any.lsdb"
    service._song_count = 73
    service._tables = frozenset({"songs", "lyrics"})

    with pytest.raises(ServiceError) as excinfo:
        service.search("Way Maker")

    message = str(excinfo.value)
    assert "Traceback" not in message
    assert "The search could not be completed" in message

    logged = log_path.read_text(encoding="utf-8")
    assert "engine exploded" in logged
    assert "Traceback" in logged
    service.close()

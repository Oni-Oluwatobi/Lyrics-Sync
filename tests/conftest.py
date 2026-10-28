"""Shared pytest fixtures."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.fixture_builder import build_fixture
from lyric_sync.database.lsdb_manager import LSDBManager
from lyric_sync.search.search_engine import LyricSearchEngine


@pytest.fixture(scope="session")
def fixture_db(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Path to the generated development fixture database."""
    target = tmp_path_factory.mktemp("lsdb") / "lyric_sync_dev_fixture.lsdb"
    return build_fixture(target)


@pytest.fixture()
def manager(fixture_db: Path) -> LSDBManager:
    instance = LSDBManager(fixture_db)
    instance.open()
    try:
        yield instance
    finally:
        instance.close()


@pytest.fixture()
def engine(manager: LSDBManager) -> LyricSearchEngine:
    return LyricSearchEngine(manager)


@pytest.fixture()
def missing_db(tmp_path: Path) -> Path:
    return tmp_path / "not_installed.lsdb"

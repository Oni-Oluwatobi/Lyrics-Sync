"""Database discovery and user-data path resolution."""

from __future__ import annotations

from pathlib import Path

from lyric_sync.app import config


def test_environment_variable_is_first_candidate(tmp_path, monkeypatch):
    db = tmp_path / "env_songbook.lsdb"
    db.write_bytes(b"")
    monkeypatch.setenv(config.ENV_DATABASE, str(db))

    path, label = config.resolve_database_path()
    assert path == db
    assert label == f"environment: {config.ENV_DATABASE}"


def test_existing_file_wins_over_canonical_location(tmp_path, monkeypatch):
    monkeypatch.delenv(config.ENV_DATABASE, raising=False)
    override = tmp_path / "picked.lsdb"
    override.write_bytes(b"")

    path, label = config.resolve_database_path(override)
    assert path == override
    assert label == "configured override"


def test_missing_database_reports_canonical_path(monkeypatch, tmp_path):
    monkeypatch.delenv(config.ENV_DATABASE, raising=False)
    monkeypatch.chdir(tmp_path)  # avoid picking up ./data from the repo
    # Simulate a checkout that has no database anywhere.
    monkeypatch.setattr(config, "project_root", lambda: tmp_path / "checkout")

    path, label = config.resolve_database_path()
    assert label is None
    assert path.name == config.DATABASE_FILENAME
    assert path.parent.name == config.DATABASE_DIRNAME
    assert config.expected_database_display_path() == (
        f"{config.DATABASE_DIRNAME}/{config.DATABASE_FILENAME}"
    )


def test_candidates_include_application_directory(monkeypatch, tmp_path):
    monkeypatch.delenv(config.ENV_DATABASE, raising=False)
    monkeypatch.chdir(tmp_path)  # keep ./data out of the candidate list

    labels = [label for label, _ in config.candidate_database_paths()]

    assert labels[0] == "current directory"
    for expected in (
        "project data directory",
        "package data directory",
        "application directory",
        "application directory (flat)",
    ):
        assert expected in labels


def test_bundle_dir_absent_outside_pyinstaller():
    assert config.bundle_dir() is None


def test_user_data_dir_honours_override(monkeypatch, tmp_path):
    target = tmp_path / "userdata"
    monkeypatch.setenv(config.ENV_USER_DATA, str(target))

    resolved = config.user_data_dir()
    assert resolved == target
    assert resolved.is_dir()
    assert config.preferences_path() == resolved / config.PREFERENCES_FILENAME
    assert config.favorites_path() == resolved / config.FAVORITES_FILENAME


def test_database_resolution_never_creates_files(tmp_path, monkeypatch):
    monkeypatch.delenv(config.ENV_DATABASE, raising=False)
    before = sorted(p.name for p in tmp_path.iterdir())

    config.resolve_database_path(tmp_path / "ghost.lsdb")

    assert sorted(p.name for p in tmp_path.iterdir()) == before
    assert not Path(tmp_path / "ghost.lsdb").exists()

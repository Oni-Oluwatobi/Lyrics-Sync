"""CLI entry points: source resolution, fail-fast behaviour, root launcher."""

from __future__ import annotations

import subprocess
import sys

import pytest

from conftest import AGL_URL, PACKAGE_ROOT

ROOT = PACKAGE_ROOT.parents[1]


def test_unknown_source_fails_before_staging_is_created(tmp_path):
    from lyrics_scraper.cli import main

    output = tmp_path / "out"
    with pytest.raises(SystemExit) as exc:
        main(["--output-dir", str(output), "single",
              "https://example.com/song/"])
    assert "example.com" in str(exc.value)
    assert "opengospellyrics" in str(exc.value)
    assert not (output / "staging" / "staging.sqlite").exists()


def test_mismatched_source_fails_before_staging_is_created(tmp_path):
    from lyrics_scraper.cli import main

    output = tmp_path / "out"
    with pytest.raises(SystemExit) as exc:
        main(["--output-dir", str(output), "--source", "opengospellyrics",
              "single", AGL_URL])
    assert "does not match" in str(exc.value)
    assert not (output / "staging" / "staging.sqlite").exists()


def test_mangled_url_is_rejected_with_a_clear_message(tmp_path):
    from lyrics_scraper.cli import main

    output = tmp_path / "out"
    with pytest.raises(SystemExit) as exc:
        main(["--output-dir", str(output), "crawl",
              "0https://africangospellyrics.com/x/", "--depth", "1"])
    message = str(exc.value)
    assert "not an http(s) URL" in message
    assert "0https://africangospellyrics.com/x/" in message
    assert not (output / "staging" / "staging.sqlite").exists()


def test_root_shim_runs_the_package():
    """`python -m lyrics_scraper --help` must work from the project root."""
    shim = ROOT / "lyrics_scraper.py"
    if not shim.exists():                          # pragma: no cover
        pytest.skip("root shim not present")
    result = subprocess.run(
        [sys.executable, "-m", "lyrics_scraper", "--help"],
        cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8",
        errors="replace", timeout=120)
    assert result.returncode == 0, result.stderr
    assert "usage: lyrics_scraper" in result.stdout
    assert "ui" in result.stdout


def test_root_launcher_runs_the_package():
    launcher = ROOT / "lyrics-scraper.cmd"
    if not launcher.exists():                      # pragma: no cover
        pytest.skip("root launcher not present")
    result = subprocess.run(
        [str(launcher), "stats"], cwd=str(ROOT), capture_output=True,
        text=True, encoding="utf-8", errors="replace", timeout=120)
    assert result.returncode == 0, result.stderr
    assert "songs" in result.stdout
    assert "lyric_lines" in result.stdout

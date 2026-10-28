"""Desktop UI smoke tests (Tk window created and driven programmatically)."""

from __future__ import annotations

import shutil
import sqlite3
import time
from pathlib import Path

import pytest

tk = pytest.importorskip("tkinter")

from conftest import AGL_URL, PACKAGE_ROOT  # noqa: E402

RAW_CACHE = PACKAGE_ROOT / "output" / "raw"


@pytest.fixture
def ui_env(tmp_path):
    """A fresh output folder seeded with the offline page cache."""
    if not RAW_CACHE.exists():
        pytest.skip("page cache missing — run a scrape once first")
    shutil.copytree(RAW_CACHE, tmp_path / "raw")
    return tmp_path


def _make_app(output_dir: Path):
    from lyrics_scraper.ui import App

    last_error: Exception | None = None
    for attempt in range(3):
        try:
            app = App(output_dir=output_dir, cache_only=True, delay=0.0,
                      timeout=10.0)
            app.update()
            return app
        except tk.TclError as exc:                # pragma: no cover
            last_error = exc
            time.sleep(0.4)
    pytest.skip(f"window could not be created: {last_error}")


def _pump(app, deadline: float = 120.0) -> int:
    """Run the event loop until the child process exits and output drains."""
    end = time.time() + deadline
    while app.runner.running or not app.runner.events.empty():
        app.update()
        time.sleep(0.02)
        if time.time() > end:                     # pragma: no cover
            pytest.fail("command did not finish in time")
    for _ in range(5):
        app.update()
        time.sleep(0.02)
    assert app.runner.last_code is not None
    return app.runner.last_code


def test_app_builds_and_reads_staging(ui_env):
    app = _make_app(ui_env)
    try:
        assert "staging" in str(app.staging_path())
        assert app.runner.running is False
        # no staging database yet -> friendly hint, no crash
        assert "no staging database" in str(app.table_hint.cget("text"))
        app.update()
        assert app.counts_var.get() in (
            "no staging database yet", "empty staging database")
    finally:
        app.destroy()


def test_ui_rejects_a_mangled_url_without_running(ui_env, monkeypatch):
    """`0https://...` is refused up front instead of spawning a process."""
    app = _make_app(ui_env)
    warnings: list[str] = []
    try:
        monkeypatch.setattr(
            app, "_show_warning",
            lambda title, message: warnings.append(f"{title}: {message}"),
            raising=False)
        import lyrics_scraper.ui as ui_module
        monkeypatch.setattr(
            ui_module.messagebox, "showwarning",
            lambda title, message, **kw: warnings.append(
                f"{title}: {message}"))

        app.url_var.set("0https://africangospellyrics.com/x/")
        app._run_fetch("crawl")

        assert app.runner.running is False
        assert app.runner.last_code is None
        assert warnings and warnings[0].startswith("Bad URL")
        assert "0https://" in warnings[0]
        assert "stray character" in warnings[0]
    finally:
        app.destroy()


def test_ui_runs_a_cached_scrape(ui_env):
    app = _make_app(ui_env)
    try:
        app.url_var.set(AGL_URL)
        app._run_fetch("single")
        assert app.runner.running is True
        assert str(app.run_buttons[0].cget("state")) == "disabled"
        assert str(app.stop_button.cget("state")) == "normal"

        code = _pump(app)
        assert code == 0, app.runner.last_code
        assert str(app.run_buttons[0].cget("state")) == "normal"
        log = app.log.get("1.0", "end")
        assert "single" in log
        assert "songs=1" in log
        assert "africangospellyrics" in log
        assert "[exit 0]" in log

        # staging was written and the table now shows the song
        assert app.staging_path().exists()
        children = app.tree.get_children()
        assert len(children) == 1
        values = app.tree.item(children[0], "values")
        assert values[0] == "Good God"
        assert values[2] == "African Gospel Lyrics"

        # detail + review round trip
        app.tree.selection_set(children[0])
        app._on_select()
        app.update()
        detail = app.detail.get("1.0", "end")
        assert "Minister Guc" in detail
        assert "Sunmisola Agbebi" in detail
        assert "Yoruba" in detail

        song_id = app.selected_song_id
        app._review("approve")
        connection = sqlite3.connect(app.staging_path())
        status = connection.execute(
            "SELECT review_status FROM songs WHERE song_id = ?",
            (song_id,)).fetchone()[0]
        connection.close()
        assert status == "approved"
        assert "approved" in str(app.tree.item(children[0], "values"))
    finally:
        app.destroy()


def test_ui_filters_and_stats(ui_env):
    app = _make_app(ui_env)
    try:
        app.filter_source_var.set("African Gospel Lyrics")
        app.filter_review_var.set("flagged")
        app.filter_search_var.set("good")
        clauses, params = app._filters()
        assert clauses == ["s.source_site = ?", "s.review_status = ?",
                           "(s.title LIKE ? OR s.artist LIKE ?)"]
        assert params == ["African Gospel Lyrics", "flagged",
                          "%good%", "%good%"]

        app._refresh_songs()
        assert "staging" in str(app.table_hint.cget("text"))
        assert app.counts_var.get() in (
            "no staging database yet", "empty staging database")
    finally:
        app.destroy()


def test_cli_rejects_ui_without_tkinter():
    """``ui`` must fail loudly (not silently) when tkinter is missing."""
    import lyrics_scraper.ui as ui_module
    assert callable(ui_module.launch)
    assert "App" in dir(ui_module)


def test_bare_invocation_opens_the_ui(monkeypatch):
    """`python -m lyrics_scraper` with no command launches the window."""
    import lyrics_scraper.ui as ui_module

    called: dict = {}
    monkeypatch.setattr(ui_module, "launch",
                        lambda **kwargs: called.update(kwargs) or 0)
    from lyrics_scraper.cli import build_parser, main

    assert build_parser().parse_args([]).command is None
    assert main([]) == 0
    assert called.get("source") == "auto"
    assert called.get("cache_only") is False
    assert called.get("ignore_robots") is False
    # explicit commands still work
    assert build_parser().parse_args(["stats"]).command == "stats"


def test_root_launcher_exists():
    launcher = PACKAGE_ROOT.parents[1] / "lyrics-scraper.cmd"
    if not launcher.exists():                      # pragma: no cover
        pytest.skip("root launcher not present")
    text = launcher.read_text(encoding="utf-8", errors="replace")
    assert "tools\\lyrics-scraper" in text
    assert "python -m lyrics_scraper" in text

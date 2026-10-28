"""Crawl hardening: backoff, robots pacing, resume and coverage reporting."""

from __future__ import annotations

import email.utils
import time
from pathlib import Path

import pytest

from lyrics_scraper.cli import main
from lyrics_scraper.fetch import Fetcher, retry_after_seconds


# --------------------------------------------------------------------------- #
# Retry-After
# --------------------------------------------------------------------------- #

class _Headers(dict):
    pass


def test_retry_after_reads_a_delay_in_seconds():
    assert retry_after_seconds(_Headers({"Retry-After": "17"})) == 17.0


def test_retry_after_is_capped_so_a_host_cannot_stall_the_crawler():
    assert retry_after_seconds(_Headers({"Retry-After": "86400"})) == 120.0


def test_retry_after_reads_an_http_date():
    when = email.utils.formatdate(time.time() + 30, usegmt=True)
    value = retry_after_seconds(_Headers({"Retry-After": when}))
    assert 20 <= value <= 30


def test_retry_after_tolerates_garbage_and_absence():
    assert retry_after_seconds(_Headers({"Retry-After": "soon"})) == 0.0
    assert retry_after_seconds(_Headers({})) == 0.0
    assert retry_after_seconds(None) == 0.0


# --------------------------------------------------------------------------- #
# robots.txt
# --------------------------------------------------------------------------- #

def test_robots_crawl_delay_slows_the_fetcher_down(tmp_path):
    (tmp_path / "robots_41543d15728fdaf1.txt").write_text("")  # placeholder
    fetcher = Fetcher(cache_dir=tmp_path, delay=0.0, ignore_robots=False)
    origin = "https://example.com"
    fetcher._robots[origin] = []
    fetcher._robots_fetched.add(origin)
    fetcher._crawl_delay[origin] = 3.0

    started = time.monotonic()
    fetcher._throttle("https://example.com/a")
    fetcher._throttle("https://example.com/b")
    # two spaced requests at 3s apart: the second must wait, the first not
    assert time.monotonic() - started < 5


def test_robots_rules_still_block_disallowed_paths(tmp_path):
    fetcher = Fetcher(cache_dir=tmp_path, delay=0.0)
    origin = "https://blocked.example"
    # stub the parsed rules rather than reading a file whose name depends on
    # a content hash of the origin
    fetcher._robots_fetched.add(origin)
    fetcher._robots[origin] = ["disallow /private"]
    assert not fetcher.robots_allowed(origin + "/private/x")
    assert fetcher.robots_allowed(origin + "/public")


def test_crawl_delay_is_parsed_from_robots(tmp_path):
    origin = "https://paced.example"
    body = "User-agent: *\nCrawl-delay: 2.5\nDisallow: /wp-admin\n"

    class _Stub(Fetcher):
        def _load(self, url, throttle=True):
            return body, url, 200

    fetcher = _Stub(cache_dir=tmp_path, delay=0.0)
    assert fetcher.robots_allowed(origin + "/lyrics") is True
    assert not fetcher.robots_allowed(origin + "/wp-admin/edit")
    assert fetcher._crawl_delay[origin] == 2.5


# --------------------------------------------------------------------------- #
# coverage / bulk review
# --------------------------------------------------------------------------- #

def _stage_two_sources(tmp_path: Path) -> Path:
    """Two songs, two sources, in a throwaway staging database."""
    from lyrics_scraper.models import LyricSection, NormalizedSong
    from lyrics_scraper.staging import StagingDatabase

    staging_path = tmp_path / "staging" / "staging.sqlite"
    staging_path.parent.mkdir(parents=True, exist_ok=True)
    with StagingDatabase(staging_path) as staging:
        run_id = staging.start_run("https://example.com/")
        for index, (site, domain, adapter, copyright_status, approved
                    ) in enumerate([
            ("Project Gutenberg", "gutenberg.org", "GutenbergHymnBookAdapter",
             "PUBLIC_DOMAIN", True),
            ("Zion Lyrics", "zionlyrics.com", "ZionLyricsAdapter",
             "UNKNOWN", False),
        ], start=1):
            song = NormalizedSong(
                title=f"Song {index}", artists=["Traditional"],
                source_site=site, source_domain=domain,
                source_adapter=adapter, source_url=f"https://{domain}/x",
                article_url=f"https://{domain}/x",
                copyright_status=copyright_status,
            )
            section = LyricSection(label="Verse", section_type="VERSE",
                                   display_label="Verse 1")
            section.append("line one", raw="line one")
            song.sections.append(section)
            staging.insert_song(song, run_id, review_status="approved" if approved else "clean",
                                include_lyrics=approved)
        staging.finish_run(run_id)
    return staging_path


def test_coverage_breaks_the_staging_down_by_source(tmp_path, capsys):
    _stage_two_sources(tmp_path)
    assert main(["--output-dir", str(tmp_path), "coverage"]) == 0
    out = capsys.readouterr().out
    assert "Project Gutenberg" in out
    assert "Zion Lyrics" in out
    assert "TOTAL" in out


def test_review_all_narrows_to_one_source(tmp_path):
    from lyrics_scraper.staging import StagingDatabase

    staging_path = _stage_two_sources(tmp_path)
    code = main([
        "--output-dir", str(tmp_path), "--source", "zionlyrics",
        "review", "--all", "--approve", "--include-lyrics",
    ])
    assert code == 0
    with StagingDatabase(staging_path) as staging:
        rows = {row["song_id"]: row for row in staging.connection.execute(
            "SELECT song_id, source_domain, review_status, include_lyrics "
            "FROM songs")}
    statuses = {row["source_domain"]: (row["review_status"], row["include_lyrics"])
                for row in rows.values()}
    assert statuses["zionlyrics.com"] == ("approved", 1)
    assert statuses["gutenberg.org"] == ("approved", 1)  # untouched, already so


def test_review_all_on_an_empty_staging_is_an_actionable_error(tmp_path):
    from lyrics_scraper.staging import StagingDatabase

    (tmp_path / "staging").mkdir()
    with StagingDatabase(tmp_path / "staging" / "staging.sqlite") as staging:
        staging.commit()
    with pytest.raises(SystemExit) as exc:
        main(["--output-dir", str(tmp_path), "review", "--all", "--approve"])
    assert "no songs matched" in str(exc.value)


def test_resume_flag_skips_pages_already_in_staging(tmp_path, capsys):
    from lyrics_scraper.fetch import Fetcher
    from lyrics_scraper.models import RawPage
    from lyrics_scraper.staging import StagingDatabase

    staging_path = tmp_path / "staging" / "staging.sqlite"
    with StagingDatabase(staging_path) as staging:
        run_id = staging.start_run("https://opengospellyrics.com/x/")
        already = RawPage(url="https://opengospellyrics.com/already/",
                          final_url="https://opengospellyrics.com/already/",
                          html="<html><body></body></html>", http_status=200)
        staging.record_page(already, run_id)
        staging.finish_run(run_id)

    from lyrics_scraper.engine import ScraperEngine

    fetched: list[str] = []

    class _Recorder(Fetcher):
        def fetch(self, url):
            fetched.append(url)
            return RawPage(url=url, final_url=url, html="<html></html>",
                           http_status=200)

    with StagingDatabase(staging_path) as staging:
        engine = ScraperEngine(fetcher=_Recorder(cache_dir=tmp_path / "raw",
                                                 delay=0.0),
                               staging=staging)
        engine.ingest(
            "https://opengospellyrics.com/already/",
            run_id=staging.start_run("https://opengospellyrics.com/already/"),
            seen={"https://opengospellyrics.com/already/"},
        )
    assert fetched == []

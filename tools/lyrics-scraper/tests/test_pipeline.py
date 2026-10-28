"""Staging → validation → dedupe → export pipeline (offline, tmp dirs)."""

from __future__ import annotations

import json

import pytest

from lyrics_scraper.adapters import get_adapter
from lyrics_scraper.dedupe import INSERT_FLAGGED, MERGE, decide
from lyrics_scraper.export import ExportError, content_digest, export_staging
from lyrics_scraper.models import NormalizedSong
from lyrics_scraper.staging import StagingDatabase
from lyrics_scraper.validate import validate_song


def _stage(staging: StagingDatabase, run_id: str, *pages) -> list:
    """Parse pages through their adapters and stage every song."""
    from lyrics_scraper.validate import severity_rank

    staged = []
    for page in pages:
        adapter = get_adapter(
            "africangospellyrics" if "africangospellyrics" in page.url
            else "opengospellyrics")
        result = adapter.parse(page)
        staging.record_page(page, run_id)
        staging.update_page(page.page_id, result.page_type,
                            result.article_title)
        for song in result.songs:
            warnings = validate_song(song)
            song_id = staging.insert_song(
                song, run_id, review_status=severity_rank(warnings),
                warning_count=len(warnings))
            staged.append((song_id, song, warnings))
    staging.commit()
    return staged


def test_stage_both_sources(tmp_path, ogl_page, agl_page):
    with StagingDatabase(tmp_path / "staging.sqlite") as staging:
        run_id = staging.start_run("test", "command=test")
        staged = _stage(staging, run_id, ogl_page, agl_page)
        counts = staging.counts()
        assert counts["songs"] == 11
        assert counts["pages"] == 2
        assert counts["sources"] == 11

        sites = dict(staging.connection.execute(
            "SELECT source_site, COUNT(*) FROM songs GROUP BY source_site"))
        assert sites == {"OpenGospelLyrics": 10, "African Gospel Lyrics": 1}

        agl = staging.connection.execute(
            "SELECT * FROM songs WHERE source_site LIKE 'African%'").fetchone()
        assert agl["artists"] == json.dumps(
            ["Minister Guc", "Sunmisola Agbebi"])
        assert agl["featured_artists"] == json.dumps(["Sunmisola Agbebi"])
        assert agl["languages"] == json.dumps(["English", "Yoruba"])
        assert agl["language_confidence"] == "explicit"
        assert agl["countries"] == json.dumps(["Nigeria"])
        assert json.loads(agl["source_meta"])["domain"] == \
            "africangospellyrics.com"
        assert len(staged) == 11


def test_artist_roles_and_tags(tmp_path, agl_page):
    with StagingDatabase(tmp_path / "staging.sqlite") as staging:
        run_id = staging.start_run("test")
        _stage(staging, run_id, agl_page)
        song_id = staging.connection.execute(
            "SELECT song_id FROM songs").fetchone()[0]
        rows = staging.connection.execute(
            "SELECT a.artist_name, sa.role FROM song_artists sa "
            "JOIN artists a ON a.artist_id = sa.artist_id "
            "WHERE sa.song_id = ? ORDER BY sa.role", (song_id,)).fetchall()
        roles = {row["artist_name"]: row["role"] for row in rows}
        assert roles == {"Minister Guc": "primary",
                         "Sunmisola Agbebi": "featured"}
        tags = [row[0] for row in staging.connection.execute(
            "SELECT normalized FROM tags ORDER BY normalized")]
        assert "nigeria" in tags and "yoruba" in tags


def test_sections_keep_markers_roundtrip(tmp_path, agl_page):
    from lyrics_scraper.cli import _load_song_draft

    with StagingDatabase(tmp_path / "staging.sqlite") as staging:
        run_id = staging.start_run("test")
        staged = _stage(staging, run_id, agl_page)
        original = staged[0][1]
        rebuilt = _load_song_draft(staging, staged[0][0])
        assert rebuilt is not None
        assert len(rebuilt.sections) == len(original.sections)
        for source_section, stored_section in zip(original.sections,
                                                   rebuilt.sections):
            assert source_section.label == stored_section.label
            assert len(source_section.entries) == len(stored_section.entries)
            for left, right in zip(source_section.entries,
                                   stored_section.entries):
                assert left.text == right.text
                assert left.raw == right.raw
                assert left.repeat == right.repeat
                assert left.repeat_unknown == right.repeat_unknown
                assert left.marker == right.marker
                assert left.target == right.target
                assert left.translation == right.translation


def test_validation_finds_broken_drafts():
    empty = NormalizedSong(title="", artists=[], source_url="")
    codes = {warning.code for warning in validate_song(empty)}
    assert codes, "an empty draft must produce validation warnings"
    good = NormalizedSong(title="Fine", artists=["Someone"],
                          source_url="https://example.com/fine",
                          raw_text="line one\nline two\nline three")
    from lyrics_scraper.models import LyricSection
    section = LyricSection(label="Verse", section_type="VERSE")
    for line in ("line one", "line two", "line three"):
        section.append(line)
    good.sections = [section]
    assert not [w for w in validate_song(good) if w.severity == "error"]


def test_cross_source_merge_keeps_both_sources(tmp_path, agl_page):
    with StagingDatabase(tmp_path / "staging.sqlite") as staging:
        run_id = staging.start_run("test")
        staged = _stage(staging, run_id, agl_page)
        song_id, original, _ = staged[0]
        lyrics = original.sections

        clone = NormalizedSong(
            title=original.title, artists=list(original.artists),
            source_site="OpenGospelLyrics",
            source_domain="opengospellyrics.com",
            source_adapter="OpenGospelLyricsAdapter",
            source_name="OpenGospelLyrics",
            source_url="https://opengospellyrics.com/good-god/",
            article_url="https://opengospellyrics.com/good-god/",
            page_id="page_alt_1", sections=lyrics)
        decision = decide(clone, staging.index())
        assert decision.action == MERGE, decision
        staging.add_existing_song_source(song_id, clone)
        staging.commit()
        sources = staging.connection.execute(
            "SELECT url, relation FROM song_sources WHERE song_id=? "
            "ORDER BY relation", (song_id,)).fetchall()
        assert len(sources) == 2
        assert {row["relation"] for row in sources} == {"primary", "additional"}
        assert staging.connection.execute(
            "SELECT source_site FROM songs WHERE song_id=?",
            (song_id,)).fetchone()[0] == "African Gospel Lyrics"


def test_conflicting_lyrics_are_flagged_not_merged(tmp_path, agl_page):
    with StagingDatabase(tmp_path / "staging.sqlite") as staging:
        run_id = staging.start_run("test")
        staged = _stage(staging, run_id, agl_page)
        original = staged[0][1]

        changed = [section for section in original.sections]
        changed[0].entries[0].text = "Totally different wording"
        changed[0].entries[0].raw = "Totally different wording"
        variant = NormalizedSong(
            title=original.title, artists=list(original.artists),
            source_site="OpenGospelLyrics",
            source_domain="opengospellyrics.com",
            source_adapter="OpenGospelLyricsAdapter",
            source_url="https://opengospellyrics.com/good-god-alt/",
            sections=changed)
        decision = decide(variant, staging.index())
        assert decision.action == INSERT_FLAGGED
        assert any(w.code == "duplicate_review" for w in decision.warnings)


def test_export_metadata_only(tmp_path, agl_page, prod_db_path):
    staging_path = tmp_path / "staging.sqlite"
    with StagingDatabase(staging_path) as staging:
        run_id = staging.start_run("test")
        _stage(staging, run_id, agl_page)

    before = content_digest(_connect(prod_db_path))
    out_path = tmp_path / "exported.lsdb"
    summary = export_staging(staging_path, out_path, prod_path=prod_db_path,
                             include_flagged=True)

    assert summary["songs"] == 1
    assert summary["lyrics"] == 0
    assert summary["metadata_only"] == 1
    assert summary["include_lyrics"] is False

    import sqlite3
    exported = sqlite3.connect(out_path)
    exported.row_factory = sqlite3.Row
    song = exported.execute("SELECT * FROM songs").fetchone()
    assert song["title"] == "Good God"
    assert song["artist"] == "Minister Guc"
    assert song["language"] == "English"
    assert song["country"] == "Nigeria"
    assert song["source"].startswith("African Gospel Lyrics")
    assert song["source_url"] == agl_page.url
    assert song["verified"] == 0
    assert song["verification_status"] == "UNVERIFIED"
    manifest = exported.execute(
        "SELECT source_key, url FROM build_manifest").fetchall()
    assert [row["source_key"] for row in manifest] == ["africangospellyrics"]
    assert manifest[0]["url"] == "https://africangospellyrics.com/"
    exported.close()
    assert content_digest(_connect(prod_db_path)) == before


def test_export_refuses_to_write_production(tmp_path, agl_page, prod_db_path):
    staging_path = tmp_path / "staging.sqlite"
    with StagingDatabase(staging_path) as staging:
        run_id = staging.start_run("test")
        _stage(staging, run_id, agl_page)
    with pytest.raises(ExportError):
        export_staging(staging_path, prod_db_path, prod_path=prod_db_path,
                       overwrite=True)


def _connect(path):
    import sqlite3
    connection = sqlite3.connect(path)
    return connection

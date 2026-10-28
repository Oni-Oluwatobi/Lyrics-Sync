"""Adapter layer: detection, source identity and per-site parsing."""

from __future__ import annotations

import pytest

from lyrics_scraper.adapters import (
    ADAPTERS,
    AfricanGospelLyricsAdapter,
    GutenbergHymnBookAdapter,
    OpenGospelLyricsAdapter,
    UnsupportedSource,
    ZionLyricsAdapter,
    adapter_for,
    available_sources,
    detect_adapter,
    get_adapter,
)

BANNED_FURNITURE = [
    "Subscribe to get the latest posts", "Type your email", "Leave a Comment",
    "Discover more from", "Share the Lyrics", "Trending Lyrics",
    "Search for Lyrics", "Follow Us", "WordPress.com", "wp-block-group",
]


def test_registry_lists_every_source():
    assert set(available_sources()) == {
        "opengospellyrics", "africangospellyrics", "zionlyrics", "gutenberg"}
    assert {adapter.name for adapter in ADAPTERS} == set(available_sources())


def test_detection_by_domain():
    assert isinstance(
        detect_adapter("https://opengospellyrics.com/2025/11/15/x/"),
        OpenGospelLyricsAdapter)
    assert isinstance(
        detect_adapter("https://www.africangospellyrics.com/2026/01/27/x/"),
        AfricanGospelLyricsAdapter)
    assert isinstance(
        detect_adapter("https://zionlyrics.com/song/example-lyrics"),
        ZionLyricsAdapter)
    assert isinstance(
        detect_adapter("https://www.gutenberg.org/cache/epub/46041/pg46041.txt"),
        GutenbergHymnBookAdapter)


def test_detection_ignores_lookalike_hosts():
    with pytest.raises(UnsupportedSource):
        detect_adapter("https://opengospellyrics.com.evil.example/x/")


def test_explicit_source_wins():
    adapter = adapter_for("https://africangospellyrics.com/2026/01/27/x/",
                          "africangospellyrics")
    assert isinstance(adapter, AfricanGospelLyricsAdapter)
    with pytest.raises(UnsupportedSource):
        adapter_for("https://africangospellyrics.com/x/", "opengospellyrics")


def test_unsupported_source_message_is_actionable():
    with pytest.raises(UnsupportedSource) as exc:
        detect_adapter("https://example.com/lyrics/")
    message = str(exc.value)
    assert "example.com" in message
    for source in available_sources():
        assert source in message


def test_get_adapter_by_key():
    assert get_adapter("opengospellyrics").domain == "opengospellyrics.com"


# -- OpenGospelLyrics -------------------------------------------------------
def test_ogl_adapter_identity(ogl_page):
    result = get_adapter("opengospellyrics").parse(ogl_page)
    assert result.source_site == "OpenGospelLyrics"
    assert result.source_domain == "opengospellyrics.com"
    assert result.adapter_name == "OpenGospelLyricsAdapter"
    assert result.page_type in ("archive", "article")
    assert "Christmas Carols" in result.article_title
    assert len(result.songs) == 10
    for song in result.songs:
        assert song.source_site == "OpenGospelLyrics"
        assert song.source_adapter == "OpenGospelLyricsAdapter"
        assert song.source_domain == "opengospellyrics.com"
        assert song.source_url.startswith(ogl_page.url)
        assert song.article_date.startswith("2025-11-15")
        assert song.title and song.artist
        assert song.line_count > 5
        assert len(song.sections) >= 1
    assert any(w.code == "truncated_at_furniture" for w in result.warnings)


def test_ogl_lyrics_free_of_page_furniture(ogl_page):
    result = get_adapter("opengospellyrics").parse(ogl_page)
    joined = "\n".join(line for song in result.songs for line in song.all_lines)
    for phrase in BANNED_FURNITURE:
        assert phrase.lower() not in joined.lower(), phrase


def test_ogl_metadata_and_section_labels(ogl_page):
    result = get_adapter("opengospellyrics").parse(ogl_page)
    carol = next(s for s in result.songs if s.title == "Deck the Halls")
    assert carol.category
    assert "carol" in [tag.lower() for tag in carol.tags]
    displays = [section.display_label for section in carol.sections]
    assert displays == ["Verse 1", "Verse 2", "Verse 3"], displays

    jingle = next(s for s in result.songs if s.title == "Jingle Bells")
    assert [section.display_label
            for section in jingle.sections] == ["Verse 1", "Chorus"]
    assert [section.section_type
            for section in jingle.sections] == ["VERSE", "CHORUS"]

    stanza = next(s for s in result.songs
                  if s.title.startswith("Silent Night"))
    assert [section.display_label for section in stanza.sections] == [
        "Verse 1", "Verse 2", "Verse 3"]
    assert all(section.label.startswith("Stanza")
               for section in stanza.sections)


# -- African Gospel Lyrics --------------------------------------------------
def test_agl_adapter_identity(agl_page):
    result = get_adapter("africangospellyrics").parse(agl_page)
    assert result.source_site == "African Gospel Lyrics"
    assert result.source_domain == "africangospellyrics.com"
    assert result.adapter_name == "AfricanGospelLyricsAdapter"
    assert result.page_type == "single"
    assert len(result.songs) == 1

    song = result.songs[0]
    assert song.title == "Good God"
    assert song.artists == ["Minister Guc", "Sunmisola Agbebi"]
    assert song.featured_artists == ["Sunmisola Agbebi"]
    assert song.source_url == agl_page.url
    assert song.article_date == "2026-01-27"
    assert result.published_at.startswith("2026-01-27T08:07:07")


def test_agl_languages_and_countries_stay_separate(agl_page):
    song = get_adapter("africangospellyrics").parse(agl_page).songs[0]
    assert song.languages == ["English", "Yoruba"]
    assert song.language_confidence == "explicit"
    assert song.language == "English"
    assert song.countries == ["Nigeria"]
    assert song.taxonomy["languages"] == ["Yoruba"]
    assert song.taxonomy["countries"] == ["Nigeria"]
    assert "Minister Guc" in song.taxonomy["artists"]


def test_agl_repeat_markers_are_recorded_not_expanded(agl_page):
    song = get_adapter("africangospellyrics").parse(agl_page).songs[0]
    entries = [entry for section in song.sections for entry in section.entries]
    repeats = [entry for entry in entries if entry.repeat > 1]
    assert {entry.repeat for entry in repeats} >= {2, 3, 4}
    for entry in repeats:
        assert f"x{entry.repeat}" in entry.raw, entry.raw
    section_markers = [entry for entry in entries if entry.marker == "section"]
    assert section_markers, "(Refrain) style markers must be kept"
    assert all(target.target for target in section_markers)
    unknown = [entry for entry in entries if entry.repeat_unknown]
    assert unknown, "x? lines must keep their unknown count flag"
    assert not any(entry.text.lower().startswith("x") for entry in entries)


def test_agl_glosses_stay_raw_with_optional_translation(agl_page):
    song = get_adapter("africangospellyrics").parse(agl_page).songs[0]
    glossed = [entry for entry in
               (line for section in song.sections for line in section.entries)
               if entry.translation]
    assert glossed
    for entry in glossed:
        assert entry.translation in entry.raw
        assert entry.translation != entry.text or entry.text == entry.raw


def test_agl_section_labels_are_generic(agl_page):
    song = get_adapter("africangospellyrics").parse(agl_page).songs[0]
    labels = [section.display_label for section in song.sections]
    assert labels == ["Verse", "Refrain", "Repeat"]
    for section in song.sections:
        assert section.label == "" or section.label.startswith(
            section.display_label), (section.label, section.display_label)
        assert not any(line.text == section.display_label
                       for line in section.entries if line.text)


def test_agl_excludes_comments_forms_and_sidebars(agl_page):
    result = get_adapter("africangospellyrics").parse(agl_page)
    song = result.songs[0]
    joined = "\n".join(song.all_lines).lower()
    for phrase in BANNED_FURNITURE:
        assert phrase.lower() not in joined, phrase
    assert "rain" not in [name.lower() for name in song.artists]
    assert any(w.code == "truncated_at_furniture" for w in result.warnings)

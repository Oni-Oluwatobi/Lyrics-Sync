"""Zion Lyrics adapter: JSON API first, HTML fallback second."""

from __future__ import annotations

import json

from lyrics_scraper.adapters import ZionLyricsAdapter
from lyrics_scraper.adapters.zionlyrics import parse_lyrics_text
from lyrics_scraper.models import RawPage

API = "https://zionlyrics.com/api/v1/songs"
SONG_URL = "https://zionlyrics.com/song/my-god-mercy-chinwo-lyrics"


def api_page(payload, url=API + "?page=1") -> RawPage:
    return RawPage(url=url, final_url=url, html=json.dumps(payload),
                   http_status=200)


DETAIL = {
    "data": {
        "id": 36444,
        "slug": "my-god-mercy-chinwo-lyrics",
        "title": "My God",
        "artists": [{"id": 2398, "slug": "mercy-chinwo", "name": "Mercy Chinwo",
                     "primaryGenre": ""}],
        "verified": True,
        "language": None,
        "canonicalUrl": SONG_URL,
        "updatedAt": "2026-09-28T14:00:05+00:00",
        "lyrics": ("[Verse 1]\nMy God, You are good\nYou never fail me\n\n"
                   "[Chorus]\nMy God, You are good\nMy God, You are great"),
    },
    "meta": {},
}

INDEX = {
    "data": [
        {"id": 1, "slug": "my-god-mercy-chinwo-lyrics", "title": "My God",
         "artists": [{"name": "Mercy Chinwo"}], "canonicalUrl": SONG_URL},
        {"id": 2, "slug": "good-father-sinach-lyrics", "title": "Good Father",
         "artists": [{"name": "Sinach"}],
         "canonicalUrl": "https://zionlyrics.com/song/good-father-sinach-lyrics"},
    ],
    "meta": {"page": 3, "perPage": 20, "total": 5206, "lastPage": 261},
}


# --------------------------------------------------------------------------- #
# lyrics payload
# --------------------------------------------------------------------------- #

def test_bracket_labels_become_sections():
    sections = parse_lyrics_text("[Verse 1]\nline one\nline two\n[Chorus]\nrepeat")
    assert [s.section_type for s in sections] == ["VERSE", "CHORUS"]
    assert sections[0].display_label == "Verse 1"
    assert sections[0].clean_lines == ["line one", "line two"]


def test_an_unlabelled_payload_is_one_verse():
    sections = parse_lyrics_text("just a line\nand another")
    assert len(sections) == 1
    assert sections[0].section_type == "VERSE"
    assert sections[0].clean_lines == ["just a line", "and another"]


def test_a_label_on_its_own_line_never_becomes_lyric_text():
    sections = parse_lyrics_text("[Verse]\nHello")
    assert sections[0].clean_lines == ["Hello"]


# --------------------------------------------------------------------------- #
# JSON API
# --------------------------------------------------------------------------- #

def test_detail_endpoint_yields_one_fully_attributed_song():
    result = ZionLyricsAdapter().parse(api_page(DETAIL, SONG_URL))
    assert result.page_type == "api-song"
    assert len(result.songs) == 1
    song = result.songs[0]
    assert song.title == "My God"
    assert song.artists == ["Mercy Chinwo"]
    assert song.source_url == SONG_URL
    assert [s.section_type for s in song.sections] == ["VERSE", "CHORUS"]
    assert song.extra["verified"] is True


def test_index_endpoint_yields_links_not_songs():
    result = ZionLyricsAdapter().parse(api_page(INDEX))
    assert result.page_type == "api-index"
    assert result.songs == []
    assert "https://zionlyrics.com/api/v1/songs/my-god-mercy-chinwo-lyrics" in result.links
    assert "https://zionlyrics.com/api/v1/songs/good-father-sinach-lyrics" in result.links


def test_index_endpoint_offers_the_next_page():
    result = ZionLyricsAdapter().parse(api_page(INDEX))
    assert "https://zionlyrics.com/api/v1/songs?page=4" in result.links


def test_query_links_are_allowed_so_pagination_can_be_walked():
    adapter = ZionLyricsAdapter()
    assert adapter.allows_link("https://zionlyrics.com/api/v1/songs?page=2")
    assert not adapter.allows_link("https://zionlyrics.com/wp-admin/x")


def test_a_record_without_lyrics_is_reported_not_invented():
    payload = {"data": {"title": "Empty", "artists": [], "lyrics": ""}}
    result = ZionLyricsAdapter().parse(api_page(payload))
    assert result.songs == []
    assert [w.code for w in result.warnings] == ["missing_lyrics"]


def test_invalid_json_is_reported_as_an_api_error():
    bad = RawPage(url=API, final_url=API, html="{not json", http_status=200)
    result = ZionLyricsAdapter().parse(bad)
    assert result.songs == []
    assert [w.code for w in result.warnings] == ["api_payload_error"]


# --------------------------------------------------------------------------- #
# HTML fallback
# --------------------------------------------------------------------------- #

HTML_PAGE = RawPage(
    url=SONG_URL, final_url=SONG_URL, http_status=200,
    html="""
    <html><head><title>My God - Mercy Chinwo Lyrics | Zion Lyrics</title></head>
    <body>
    <section class="song-hero">
      <h1>My God</h1>
      <p class="song-meta-line">By <a href="/artist/mercy-chinwo">Mercy Chinwo</a></p>
    </section>
    <article class="lyrics">
      <p>[Verse]<br />My God, You are good<br />You never fail me</p>
      <p>[Chorus]<br />My God, You are good</p>
    </article>
    <aside class="song-sidebar"><a href="/song/other-song-lyrics">Other</a></aside>
    </body></html>
    """)


def test_html_fallback_reads_the_lyrics_article():
    result = ZionLyricsAdapter().parse(HTML_PAGE)
    assert result.page_type == "single"
    song = result.songs[0]
    assert song.title == "My God"
    assert song.artists == ["Mercy Chinwo"]
    assert song.clean_lines == [
        "My God, You are good", "You never fail me", "My God, You are good"]


def test_html_fallback_collects_song_links_from_the_whole_page():
    result = ZionLyricsAdapter().parse(HTML_PAGE)
    assert "https://zionlyrics.com/song/other-song-lyrics" in result.links


def test_ads_and_sidebars_never_reach_the_lyrics():
    song = ZionLyricsAdapter().parse(HTML_PAGE).songs[0]
    joined = " ".join(song.clean_lines)
    assert "Other" not in joined
    assert "sidebar" not in joined.lower()


def test_staged_songs_stay_metadata_only():
    song = ZionLyricsAdapter().parse(HTML_PAGE).songs[0]
    assert song.copyright_status == "UNKNOWN"

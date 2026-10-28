"""Project Gutenberg hymn books: layout detection and song assembly.

Every fixture here is a miniature of a real print layout — the header shape,
blank-line rhythm and indentation come straight from the source books — so a
regression in any of the three parsers is caught without network access.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from lyrics_scraper.adapters import GutenbergHymnBookAdapter
from lyrics_scraper.gutenberg import detect_profile, parse_page
from lyrics_scraper.models import RawPage

PG_DIR = Path(__import__("os").environ.get("TEMP", "")) / "opencode" / "pg"
BOOK_URL = "https://www.gutenberg.org/cache/epub/00000/pg00000.txt"


def page(text: str, url: str = BOOK_URL) -> RawPage:
    return RawPage(url=url, final_url=url, html=text, http_status=200)


def chb_header(number: int, metre: str, width: int = 70) -> str:
    left = str(number)
    return left + " " * (width - len(left) - len(metre)) + metre


def bh_header(number: int, metre: str, author: str = "") -> str:
    return f"{number}.".ljust(26) + metre.ljust(20) + author


def otb_header(number: int, tune: str) -> str:
    return f"{number:<6}{tune}"


CHB_BOOK = "\n".join([
    "*** START OF THE PROJECT GUTENBERG EBOOK THE CHRISTIAN HYMN BOOK ***",
    "",
    "                          THE",
    "                      CHRISTIAN HYMN BOOK.",
    "",
    "",
    chb_header(1, "L. M."),
    "                     The works and the word of God.",
    "                                     Psalm 19.",
    "",
    "  The heavens declare thy glory, Lord!",
    "    In every star thy wisdom shines;",
    "",
    "  2 The rolling sun, the changing light,",
    "    And nights and days, thy power confess;",
    "",
    "                                CHORUS.",
    "",
    "  3 Sun, moon, and stars, convey thy praise",
    "    And fill the world with light.",
    "",
    "",
    chb_header(2, "C. M."),
    "                      Divine love displayed.",
    "",
    "  To thee my heart, Eternal King!",
    "    Would now its thankful tribute bring;",
    "",
    "                                CHORUS.",
    "",
    "  Praise him, ye servants of the Lord!",
    "",
    "",
    "CONTENTS.",
    "",
    "INDEX OF FIRST LINES",
    "",
    "  The heavens declare thy glory, Lord!        _Isaac Watts._ 1",
    "  To thee my heart, Eternal King!             _C. Wesley._ 2",
    "",
    "*** END OF THE PROJECT GUTENBERG EBOOK THE CHRISTIAN HYMN BOOK ***",
])

BH_BOOK = "\n".join([
    "*** START OF THE PROJECT GUTENBERG EBOOK BOOK OF HYMNS ***",
    "",
    "                      PREFACE",
    "INDEX OF FIRST LINES",
    "  Come to the house of prayer,          *Emily Taylor.* 1",
    "",
    "HYMNS.",
    "I. PUBLIC WORSHIP.",
    "",
    "",
    "",
    bh_header(1, "S. M.", "*Emily Taylor."),
    "",
    "                                Invitation.",
    "",
    "",
    "  1   Come to the house of prayer,",
    "      O ye afflicted, come!",
    "",
    "  2 The God of peace shall meet you there,",
    "      He makes his promise good.",
    "",
    "",
    "",
    "",
    bh_header(2, "P. M."),
    "",
    "                             Call to Prayer.",
    "",
    "",
    "  1 To prayer, to prayer!--for the morning breaks,",
    "  And earth in her Maker's smile awakes.",
    "",
    "",
    "",
    "*** END OF THE PROJECT GUTENBERG EBOOK BOOK OF HYMNS ***",
])

OTB_BOOK = "\n".join([
    "*** START OF THE PROJECT GUTENBERG EBOOK THE OTTERBEIN HYMNAL ***",
    "",
    "                      THE OTTERBEIN HYMNAL.",
    "",
    "",
    otb_header(1, "Old Hundred. L.M."),
    "",
    "_Doxology._",
    "",
    "Praise God, from whom all blessings flow;",
    "Praise him, all creatures here below;",
    "",
    "     Isaac Watts, 1709.",
    "",
    "",
    otb_header(2, "Webb. 7s & 6s. D."),
    "",
    "_Salvation Through Christ._",
    "",
    "Tell me the story of Jesus,",
    "Write on my heart every word;",
    "",
    "Cho.--Tell me the story of Jesus,",
    "  Fairest that ever was told.",
    "",
    "     Charles Wesley.",
    "",
    "",
    "INDEX OF FIRST LINES.",
    "  Praise God, from whom all blessings flow,   _Isaac Watts._ 1",
    "",
    "*** END OF THE PROJECT GUTENBERG EBOOK THE OTTERBEIN HYMNAL ***",
])

HTML_BOOK = "\n".join([
    "<html><head><title>The Christian Hymn Book</title></head><body>",
    '<div id="c1" class="hymn"><h3>1</h3>',
    '<p class="meter">L. M.</p>',
    '<p class="ttl">The works and the word of God.<br />'
    '<span class="rightish"><span class="scripRef">Psalm 19.</span></span></p>',
    '<div class="verse">',
    '<p class="t0">The heavens declare thy glory, Lord!</p>',
    '<p class="t">In every star thy wisdom shines;</p>',
    "</div>",
    '<div class="verse">',
    '<p class="t0"><span class="vn">2 </span>The rolling sun, the changing light,</p>',
    '<p class="t">And nights and days, thy power confess;</p>',
    "</div>",
    '<div class="author">Watts.</div>',
    "</div>",
    '<div id="c2" class="hymn"><h3>2</h3>',
    '<p class="meter">C. M.</p>',
    '<p class="ttl">Divine love displayed.</p>',
    '<div class="verse">',
    '<p class="t0">To thee my heart, Eternal King!</p>',
    "</div>",
    "</div>",
    "</body></html>",
])


# --------------------------------------------------------------------------- #
# layout detection
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("text,key", [
    (CHB_BOOK, "chb"),
    (BH_BOOK, "bh"),
    (OTB_BOOK, "otb"),
])
def test_detect_profile_picks_the_print_layout(text, key):
    from lyrics_scraper.gutenberg import _body_lines

    lines, _title = _body_lines(text)
    assert detect_profile(lines).key == key


# --------------------------------------------------------------------------- #
# The Christian Hymn Book layout
# --------------------------------------------------------------------------- #

def test_chb_book_yields_one_song_per_hymn():
    result = parse_page(page(CHB_BOOK))
    assert result.page_type == "book"
    assert result.article_title == "THE CHRISTIAN HYMN BOOK"
    assert [song.extra["hymn_number"] for song in result.songs] == [1, 2]


def test_chb_title_comes_from_the_centred_line():
    songs = parse_page(page(CHB_BOOK)).songs
    assert songs[0].title == "The works and the word of God"
    assert songs[1].title == "Divine love displayed"


def test_chb_scripture_reference_is_not_part_of_the_title():
    songs = parse_page(page(CHB_BOOK)).songs
    assert "Psalm" not in songs[0].title
    assert songs[0].sections[0].lines[0] == "The heavens declare thy glory, Lord!"


def test_chb_stanza_numbers_are_stripped_from_the_lyrics():
    songs = parse_page(page(CHB_BOOK)).songs
    second = songs[0].sections[1]
    assert second.display_label == "Verse 2"
    assert second.clean_lines[0] == "The rolling sun, the changing light,"
    # the raw wording keeps the printed number
    assert second.lines[0].startswith("2 ")


def test_chb_centred_chorus_marker_relabels_the_next_stanza():
    songs = parse_page(page(CHB_BOOK)).songs
    kinds = [section.section_type for section in songs[0].sections]
    assert kinds == ["VERSE", "VERSE", "CHORUS"]
    assert songs[0].sections[-1].display_label == "Chorus"


def test_chb_authors_come_from_the_index_of_first_lines():
    songs = parse_page(page(CHB_BOOK)).songs
    assert songs[0].author == "Isaac Watts"
    assert songs[1].author == "C. Wesley"


# --------------------------------------------------------------------------- #
# A Book of Hymns layout
# --------------------------------------------------------------------------- #

def test_bh_book_carries_the_author_on_the_header():
    songs = parse_page(page(BH_BOOK)).songs
    assert [song.extra["hymn_number"] for song in songs] == [1, 2]
    assert songs[0].author == "Emily Taylor."
    assert songs[1].author is None          # this header printed no credit
    assert songs[0].title == "Invitation"
    assert songs[0].extra["metre"] == "S. M."


def test_bh_stanza_one_is_numbered_in_the_source_and_still_labelled_verse_1():
    songs = parse_page(page(BH_BOOK)).songs
    first = songs[0].sections[0]
    assert first.display_label == "Verse 1"
    assert first.clean_lines[0] == "Come to the house of prayer,"
    assert first.lines[0].startswith("1 ")


def test_bh_front_index_does_not_become_a_hymn():
    songs = parse_page(page(BH_BOOK)).songs
    assert all(song.title not in ("INDEX OF FIRST LINES", "PREFACE")
               for song in songs)


# --------------------------------------------------------------------------- #
# The Otterbein Hymnal layout
# --------------------------------------------------------------------------- #

def test_otb_title_comes_from_the_italic_line():
    songs = parse_page(page(OTB_BOOK)).songs
    assert songs[0].title == "Doxology"
    assert songs[1].title == "Salvation Through Christ"
    assert songs[0].extra["tune"] == "Old Hundred. L.M."


def test_otb_author_is_the_indented_credit_after_the_last_stanza():
    songs = parse_page(page(OTB_BOOK)).songs
    assert songs[0].author == "Isaac Watts, 1709."
    assert songs[1].author == "Charles Wesley."
    assert songs[0].clean_lines[-1] == "Praise him, all creatures here below;"


def test_otb_cho_prefix_starts_a_chorus_section():
    songs = parse_page(page(OTB_BOOK)).songs
    chorus = songs[1].sections[1]
    assert chorus.section_type == "CHORUS"
    assert chorus.clean_lines[0] == "Tell me the story of Jesus,"
    assert chorus.lines[0].startswith("Cho.--")


def test_otb_does_not_mistake_a_chant_line_for_an_author():
    text = OTB_BOOK.replace(
        "     Isaac Watts, 1709.", "     world without end.")
    songs = parse_page(page(text)).songs
    # the indented chant line is lyric text, so it must survive as lyrics
    assert songs[0].clean_lines[-1] == "world without end."


# --------------------------------------------------------------------------- #
# HTML shape
# --------------------------------------------------------------------------- #

def test_html_book_uses_the_hymn_divs_and_their_authors():
    result = parse_page(page(HTML_BOOK, "https://www.gutenberg.org/files/1/1-h/1-h.htm"))
    songs = result.songs
    assert [song.extra["hymn_number"] for song in songs] == [1, 2]
    assert songs[0].title == "The works and the word of God"
    assert songs[0].author == "Watts."
    assert songs[1].author is None
    assert songs[0].clean_lines == [
        "The heavens declare thy glory, Lord!",
        "In every star thy wisdom shines;",
        "The rolling sun, the changing light,",
        "And nights and days, thy power confess;",
    ]


def test_html_book_keeps_the_stanza_numbers_out_of_the_text():
    songs = parse_page(page(HTML_BOOK)).songs
    assert songs[0].sections[1].clean_lines[0].startswith("The rolling")


# --------------------------------------------------------------------------- #
# adapter contract
# --------------------------------------------------------------------------- #

def test_adapter_stamps_public_domain_on_every_song():
    adapter = GutenbergHymnBookAdapter()
    result = adapter.parse(page(CHB_BOOK))
    assert result.source_site == "Project Gutenberg"
    assert result.source_domain == "gutenberg.org"
    assert {song.copyright_status for song in result.songs} == {"PUBLIC_DOMAIN"}
    assert {song.source_adapter for song in result.songs} == {
        "GutenbergHymnBookAdapter"}


def test_a_book_without_hymns_fails_loudly():
    result = parse_page(page("*** START OF THE PROJECT GUTENBERG EBOOK A NOVEL ***\n"
                             "It was the best of times.\n"
                             "*** END OF THE PROJECT GUTENBERG EBOOK A NOVEL ***"))
    assert result.songs == []
    assert {warning.code for warning in result.warnings} == {"no_hymns_found"}


# --------------------------------------------------------------------------- #
# the real books, when they happen to be on this machine
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("filename,expected", [
    ("pg46041.txt", 1324),
    ("pg16455.txt", 547),
    ("pg33180.txt", 600),
    ("46041-h.htm", 1324),
])
def test_real_gutenberg_books_parse(filename, expected):
    path = PG_DIR / filename
    if not path.exists():
        pytest.skip(f"{filename} not downloaded")
    result = parse_page(page(path.read_text(encoding="utf-8", errors="replace")))
    assert len(result.songs) == expected
    assert all(song.sections and song.line_count >= 2 for song in result.songs)
    assert all(song.title for song in result.songs)

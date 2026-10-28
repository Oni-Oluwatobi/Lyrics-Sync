"""Highlighting tests."""

from __future__ import annotations

from lyric_sync.search.highlighter import best_line, find_highlights, highlighted_html


def test_finds_word_spans():
    spans = find_highlights("You are the mighty God", ["mighty", "god"])
    assert [text for text in _slices("You are the mighty God", spans)] == [
        "mighty",
        "God",
    ]


def test_highlight_survives_punctuation_and_case():
    spans = find_highlights("MIGHTY God, great I AM", ["mighty", "god"])
    assert len(spans) == 2
    assert spans[0].start == 0


def test_highlight_handles_apostrophes():
    spans = find_highlights("You're holding on", ["youre", "holding"])
    assert len(spans) == 2


def test_no_matches_returns_empty():
    assert find_highlights("nothing here", ["mighty"]) == ()


def test_html_escapes_markup():
    html = highlighted_html("Grace & <mercy> flows", ["grace"])
    assert "&amp;" in html
    assert "&lt;mercy&gt;" in html
    assert "grace" in html.lower()


def test_html_wraps_matches_with_accent_colour():
    html = highlighted_html("mighty God", ["mighty"], "#FF7A1A")
    assert 'style="color:#FF7A1A; font-weight:600;"' in html
    assert html.count("<span") == 1


def test_best_line_prefers_matching_line():
    lines = ["first line", "you are the mighty God", "third line"]
    index, line = best_line(lines, ["mighty"])
    assert index == 1
    assert line == "you are the mighty God"


def test_best_line_without_matches_returns_first_non_empty():
    index, line = best_line(["", "alpha", "beta"], ["zzz"])
    assert index == 1
    assert line == "alpha"


def _slices(text: str, spans) -> list[str]:
    return [text[span.start:span.end] for span in spans]

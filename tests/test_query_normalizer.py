"""Query normalization tests."""

from __future__ import annotations

from lyric_sync.search.query_normalizer import (
    content_tokens,
    contraction_variants,
    like_pattern,
    normalize_query,
    normalize_text,
    normalize_with_map,
    tokenize,
)


def test_capitalization_is_folded():
    assert normalize_text("YOU ARE THE MIGHTY GOD") == "you are the mighty god"


def test_punctuation_is_removed():
    assert normalize_text("YOU ARE THE MIGHTY GOD!!!") == "you are the mighty god"
    assert normalize_text("Holy, holy... (Lord of all)?") == "holy holy lord of all"


def test_whitespace_is_collapsed():
    assert normalize_text("   mighty \t \n  god   ") == "mighty god"


def test_apostrophe_variants_are_unified():
    assert normalize_text("you’re mine") == "youre mine"
    assert normalize_text("you're mine") == "youre mine"
    assert normalize_text("don`t go") == "dont go"


def test_contractions_are_canonicalised():
    query = normalize_query("Don't stop believing")
    assert query.tokens == ("dont", "stop", "believing")
    assert contraction_variants("dont") == ["do", "not"]
    assert contraction_variants("god") == []


def test_unicode_diacritics_are_optional():
    assert normalize_text("café praise") == "cafe praise"
    assert normalize_text("café praise", strip_accents=False) == "café praise"
    assert normalize_text("CAFÉ praise") == "cafe praise"


def test_tokenize_helper():
    assert tokenize("Mighty  GOD,") == ["mighty", "god"]


def test_content_tokens_drop_stopwords():
    tokens = tokenize("you are the mighty god")
    assert content_tokens(tokens) == ["mighty", "god"]


def test_content_tokens_fall_back_when_all_stopwords():
    tokens = tokenize("you are the")
    assert content_tokens(tokens) == ["you", "are", "the"]


def test_like_pattern_wraps_and_cleans():
    assert like_pattern("Mighty God!") == "%mighty god%"
    assert like_pattern("") == "%"


def test_normalize_query_properties():
    query = normalize_query("  Mighty   GOD!!!  ")
    assert query.normalized == "mighty god"
    assert query.tokens == ("mighty", "god")
    assert query.is_empty is False
    assert query.display == "mighty god"

    empty = normalize_query("   ")
    assert empty.is_empty is True
    assert empty.tokens == ()


def test_generic_single_word_query_is_flagged():
    assert normalize_query("god").is_generic is True
    assert normalize_query("mighty god").is_generic is False


def test_normalize_with_map_tracks_original_indices():
    text = "You’re the MIGHTY God!"
    normalized, index_map = normalize_with_map(text)
    assert normalized == "youre the mighty god"
    assert len(index_map) == len(normalized)
    # 'mighty' in the normalized string maps back onto the original word
    start = normalized.index("mighty")
    assert text[index_map[start]: index_map[start] + 6].lower() == "mighty"

"""End-to-end search tests against the development fixture."""

from __future__ import annotations

import pytest

from lyric_sync.models.song import METADATA_ONLY, PUBLIC_DOMAIN
from lyric_sync.search.search_engine import LyricSearchEngine


def ids(response) -> list[int]:
    return [result.song.id for result in response.results]


def test_exact_phrase_returns_target_song(engine):
    response = engine.search("you are the mighty god")
    assert response.results
    assert response.results[0].song.id == 1
    assert response.results[0].label.value == "Strong match"
    assert "mighty" in response.results[0].snippet.lower()


def test_partial_query_still_finds_song(engine):
    response = engine.search("mighty god")
    assert 1 in ids(response)
    assert response.results[0].song.id == 1


def test_multi_word_title_query(engine):
    response = engine.search("anchor of peace")
    assert response.results
    assert response.results[0].song.id == 2


def test_fuzzy_typo_tolerated(engine):
    response = engine.search("mighty god graet")
    assert 1 in ids(response)
    top = next(result for result in response.results if result.song.id == 1)
    assert top.fuzzy_terms == ("graet",)


def test_no_results(engine):
    response = engine.search("quantum banana zebra")
    assert response.results == []
    assert response.candidate_count >= 0
    assert response.database_available is True


def test_empty_query_returns_nothing(engine):
    response = engine.search("    ")
    assert response.is_empty
    assert response.query.is_empty


def test_ranking_places_title_match_first(engine):
    response = engine.search("great i am")
    assert response.results
    assert response.results[0].song.id == 1


def test_metadata_artist_search(engine):
    response = engine.search("fixture voices")
    found = ids(response)
    assert 2 in found
    assert 4 in found


def test_metadata_only_song_appears_without_lyrics(engine):
    response = engine.search("faithful still")
    assert 3 in ids(response)
    match = next(result for result in response.results if result.song.id == 3)
    assert match.song.copyright_status == METADATA_ONLY
    assert match.song.lyrics_displayable is False
    assert match.has_lyrics is False


def test_alias_search(engine):
    response = engine.search("sunrise everyday")
    assert 6 in ids(response)


def test_public_domain_song_has_displayable_lyrics(engine):
    response = engine.search("amazing grace")
    assert response.results[0].song.id == 5
    assert response.results[0].song.copyright_status == PUBLIC_DOMAIN
    assert response.results[0].song.lyrics_displayable is True


def test_result_limit_marks_truncation(manager):
    engine = LyricSearchEngine(manager, result_limit=1)
    response = engine.search("lord")
    assert len(response.results) == 1
    assert response.truncated is True


def test_strict_sensitivity_still_returns_exact_title(manager):
    engine = LyricSearchEngine(manager, sensitivity="strict")
    response = engine.search("morning light")
    assert response.results
    assert response.results[0].song.id == 6


def test_engine_without_database(manager):
    engine = LyricSearchEngine(None)
    response = engine.search("mighty god")
    assert response.database_available is False
    assert response.note == "database_unavailable"
    assert response.results == []


def test_query_is_never_interpolated_into_sql(engine):
    for hostile in ("' OR 1=1 --", "100% ; DROP TABLE songs;", '"quoted" phrase', "a" * 1500):
        response = engine.search(hostile)
        assert response.results == [] or isinstance(response.results[0].song.title, str)


def test_highlights_point_at_matched_words(engine):
    response = engine.search("mighty god")
    match = response.results[0]
    assert match.highlights
    for span in match.highlights:
        assert match.snippet[span.start:span.end].lower() in {"mighty", "god"}


def test_response_reports_timing(engine):
    response = engine.search("mighty god")
    assert response.elapsed_ms >= 0
    assert response.candidate_count > 0


@pytest.mark.parametrize("query", ["God", "the", "you", "i"])
def test_generic_single_word_queries_are_controlled(engine, query):
    response = engine.search(query)
    # Generic queries must never flood the results.
    assert len(response.results) <= 12


def test_match_labels_are_threshold_tiers_never_percentages(engine):
    tiers = {"Strong match": 3, "Good match": 2, "Possible match": 1}

    exact = engine.search("you are the mighty god").results[0]
    alias = next(
        result for result in engine.search("sunrise everyday").results
        if result.song.id == 6
    )

    for match in (exact, alias):
        assert match.label.value in tiers
        assert "%" not in match.label.value

    # A verbatim lyric phrase must never rank below a bare alias lookup.
    assert tiers[exact.label.value] >= tiers[alias.label.value]


def test_result_carries_evidence_not_a_fake_confidence(engine):
    match = engine.search("you are the mighty god").results[0]
    assert match.score >= 0
    assert match.score <= 1
    assert match.matched_fields
    assert not any("%" in field for field in match.matched_fields)

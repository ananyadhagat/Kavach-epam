"""Unit tests for :mod:`app.comparators.text_comparator`."""

from __future__ import annotations

import math

import pytest

from app.comparators.text_comparator import TextComparator
from app.schemas.complaint import Complaint
from app.schemas.duplicate_response import SignalStatus


def _complaint(complaint_id: str, description: str | None = None) -> Complaint:
    return Complaint(complaint_id=complaint_id, description=description)


@pytest.fixture()
def comparator() -> TextComparator:
    return TextComparator()


# -- identical / near-identical -------------------------------------------- #
def test_identical_descriptions_score_one(comparator: TextComparator) -> None:
    text = "Large pothole on the main road near the central market"
    result = comparator.compare_texts(text, text)
    assert result.status is SignalStatus.AVAILABLE
    assert result.score == pytest.approx(1.0)
    assert result.reason == "TEXT_SIMILARITY"


def test_case_and_whitespace_differences_score_one(
    comparator: TextComparator,
) -> None:
    a = "Overflowing  garbage bin   at the park"
    b = "overflowing garbage bin at the park"
    result = comparator.compare_texts(a, b)
    assert result.status is SignalStatus.AVAILABLE
    assert result.score == pytest.approx(1.0)


# -- overlapping vocabulary ------------------------------------------------ #
def test_overlapping_wording_is_partial(comparator: TextComparator) -> None:
    a = "Broken streetlight near the north gate of the market"
    b = "Streetlight not working close to the market north entrance"
    result = comparator.compare_texts(a, b)
    assert result.status is SignalStatus.AVAILABLE
    assert result.score is not None
    assert 0.0 < result.score < 1.0


def test_paraphrase_without_shared_tokens_scores_low(
    comparator: TextComparator,
) -> None:
    # Documents the lexical limitation: synonyms are invisible to TF-IDF.
    a = "Broken streetlight"
    b = "Lamp not working"
    result = comparator.compare_texts(a, b)
    assert result.status is SignalStatus.AVAILABLE
    assert result.score == pytest.approx(0.0)


# -- unrelated ------------------------------------------------------------- #
def test_unrelated_descriptions_score_zero(comparator: TextComparator) -> None:
    a = "Overflowing garbage bin beside playground"
    b = "Deep pothole highway shoulder"
    result = comparator.compare_texts(a, b)
    assert result.status is SignalStatus.AVAILABLE
    assert result.score == pytest.approx(0.0)


def test_shared_stopwords_do_not_imply_similarity(
    comparator: TextComparator,
) -> None:
    # Two unrelated reports that happen to share only the token "the" should
    # score very low (not zero, because TF-IDF is purely lexical).
    a = "Overflowing garbage bin near the playground"
    b = "Deep pothole on the highway shoulder"
    result = comparator.compare_texts(a, b)
    assert result.status is SignalStatus.AVAILABLE
    assert result.score is not None and result.score < 0.2


# -- missing / blank / punctuation ----------------------------------------- #
@pytest.mark.parametrize(
    "left, right",
    [
        (None, "a real description"),
        ("a real description", None),
        (None, None),
        ("", "a real description"),
        ("a real description", "   "),
    ],
)
def test_missing_or_blank_is_unavailable(
    comparator: TextComparator, left: object, right: object
) -> None:
    result = comparator.compare_texts(left, right)
    assert result.status is SignalStatus.UNAVAILABLE
    assert result.score is None
    assert result.reason == "TEXT_UNAVAILABLE"


@pytest.mark.parametrize("punctuation", ["...", "!!! ???", "--- ,,, ;;", "   .   "])
def test_punctuation_only_is_unavailable(
    comparator: TextComparator, punctuation: str
) -> None:
    result = comparator.compare_texts(punctuation, "a real description")
    assert result.status is SignalStatus.UNAVAILABLE
    assert result.score is None
    assert result.reason in {"TEXT_NO_TOKENS", "TEXT_EMPTY_VOCABULARY", "TEXT_UNAVAILABLE"}


def test_both_punctuation_only_is_unavailable(comparator: TextComparator) -> None:
    result = comparator.compare_texts("...", "!!!")
    assert result.status is SignalStatus.UNAVAILABLE
    assert result.score is None


# -- malformed ------------------------------------------------------------- #
@pytest.mark.parametrize("bad", [123, 4.5, ["text"], {"a": 1}])
def test_malformed_description_is_invalid(
    comparator: TextComparator, bad: object
) -> None:
    result = comparator.compare_texts(bad, "a real description")
    assert result.status is SignalStatus.INVALID
    assert result.score is None
    assert result.reason == "TEXT_INVALID"


# -- bounds & determinism -------------------------------------------------- #
def test_score_is_finite_and_bounded(comparator: TextComparator) -> None:
    pairs = [
        ("pothole on main road", "pothole on main road today"),
        ("garbage overflow", "streetlight broken"),
        ("water logging in underpass", "sewage water in underpass"),
    ]
    for a, b in pairs:
        result = comparator.compare_texts(a, b)
        assert result.status is SignalStatus.AVAILABLE
        assert result.score is not None
        assert math.isfinite(result.score)
        assert 0.0 <= result.score <= 1.0


def test_results_are_deterministic(comparator: TextComparator) -> None:
    a = "Broken streetlight near the north gate"
    b = "Streetlight near north gate is broken"
    first = comparator.compare_texts(a, b)
    second = comparator.compare_texts(a, b)
    assert first.score == second.score
    assert first.details == second.details


def test_symmetric(comparator: TextComparator) -> None:
    a = "garbage overflow near the school"
    b = "overflow garbage near school building"
    assert comparator.compare_texts(a, b).score == comparator.compare_texts(
        b, a
    ).score


# -- record-level ---------------------------------------------------------- #
def test_compare_reads_complaint_description(comparator: TextComparator) -> None:
    result = comparator.compare(
        _complaint("NEW-1", "large pothole on the main road"),
        _complaint("CMP-1", "large pothole on the main road"),
    )
    assert result.status is SignalStatus.AVAILABLE
    assert result.score == pytest.approx(1.0)


def test_bigram_configuration_changes_score() -> None:
    unigram = TextComparator(ngram_range=(1, 1))
    bigram = TextComparator(ngram_range=(1, 2))
    a = "broken streetlight north gate"
    b = "broken streetlight south gate"
    u = unigram.compare_texts(a, b).score
    g = bigram.compare_texts(a, b).score
    assert u is not None and g is not None
    assert u != g  # bigrams add order-sensitive evidence

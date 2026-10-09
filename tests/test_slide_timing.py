"""Tests for pure script -> slide-duration timing rules."""

import pytest

from app.core.slide_timing import calculate_slide_durations_from_script as calc


def test_single_slide():
    assert calc("anything", 1, 10.0) == [10.0]
    assert calc("anything", 1, 0.5) == [1.5]


def test_rejects_invalid_inputs():
    with pytest.raises(ValueError):
        calc("x", 0, 5.0)
    with pytest.raises(ValueError):
        calc("x", 2, 0.0)


def test_explicit_slide_markers_are_word_weighted():
    script = "[Slide 1] one two three four five six seven eight\n[Slide 2] one two"
    durations = calc(script, 2, 30.0)
    assert len(durations) == 2
    assert sum(durations) == pytest.approx(30.0)
    assert durations[0] > durations[1]  # 8 words vs 2 words


def test_paragraphs_match_slide_count():
    script = "first part has several words here\n\nsecond short"
    durations = calc(script, 2, 20.0)
    assert len(durations) == 2
    assert sum(durations) == pytest.approx(20.0)
    assert durations[0] > durations[1]


def test_equal_fallback():
    durations = calc("one single paragraph", 4, 20.0)
    assert durations == [5.0, 5.0, 5.0, 5.0]


def test_pathological_short_total_stays_sane():
    durations = calc("plain text without markers", 3, 2.0)
    assert len(durations) == 3
    assert all(d >= 0.5 for d in durations)
    assert sum(durations) == pytest.approx(2.0)

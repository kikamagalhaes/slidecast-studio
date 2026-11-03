"""Tests for pure script -> slide-duration timing rules."""
import pytest
from app.core.slide_timing import (
    calculate_slide_durations_from_script as calc,
    uniform_durations, weighted_durations, validate_durations, boundaries)

def test_single_slide():
    assert calc("anything", 1, 10.0) == [10.0]
    assert calc("anything", 1, 0.5) == [0.5]

def test_rejects_invalid_inputs():
    with pytest.raises(ValueError): calc("x", 0, 5.0)
    with pytest.raises(ValueError): calc("x", 2, 0.0)
    with pytest.raises(ValueError): calc("x", 2, float("inf"))

def test_explicit_slide_markers_are_word_weighted():
    script = "[Slide 1] one two three four five six seven eight\n[Slide 2] one two"
    durations = calc(script, 2, 30.0)
    assert sum(durations) == pytest.approx(30.0)
    assert durations[0] > durations[1]
    assert durations == pytest.approx([24.0, 6.0])

def test_paragraphs_match_slide_count():
    durations = calc("first part has several words here\n\nsecond short", 2, 20.0)
    assert durations[0] > durations[1]

def test_equal_fallback():
    assert calc("one single paragraph", 4, 20.0) == [5.0, 5.0, 5.0, 5.0]

def test_uniform_acceptance_values():
    assert uniform_durations(3, 60.0) == [20.0, 20.0, 20.0]
    assert weighted_durations([1, 2, 3], 60.0) == pytest.approx([10.0, 20.0, 30.0])

def test_locks_only_redistribute_remainder():
    assert weighted_durations([1, 1, 1], 60.0, locked={0: 20.0}) == pytest.approx([20.0, 20.0, 20.0])
    with pytest.raises(ValueError): weighted_durations([1, 1], 10.0, locked={0: 9.9})

def test_insufficient_duration_raises_not_negative():
    with pytest.raises(ValueError): calc("plain", 3, 1.0)
    with pytest.raises(ValueError): uniform_durations(3, 1.0)

def test_empty_script_uniform_and_marker_out_of_range():
    assert calc("", 2, 10.0) == [5.0, 5.0]
    with pytest.raises(ValueError): calc("[Slide 9] x", 2, 10.0)

def test_validate_and_boundaries():
    assert boundaries([10.0, 20.0, 30.0]) == [0.0, 10.0, 30.0, 60.0]
    with pytest.raises(ValueError): validate_durations([5.0, -1.0], 4.0)

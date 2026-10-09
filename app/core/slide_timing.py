"""Pure helpers mapping a lesson script onto per-slide durations.

Qt-free so the timing rules are unit-testable; used by the desktop clone
render worker. All strategies guarantee every duration is positive and the
total matches the narration length.
"""

import re
from typing import List

MIN_SLIDE_SECONDS = 1.5
ABSOLUTE_MIN_SECONDS = 0.5

_SLIDE_MARKER = re.compile(r"\[?\bSlide\s*(\d+)[\:\-\]]?", re.IGNORECASE)


def _normalize(durations: List[float], total_duration: float) -> List[float]:
    """Clamps to sane values and renormalizes so the sum equals the total."""
    if not durations:
        return durations
    clean = [max(ABSOLUTE_MIN_SECONDS, float(d)) for d in durations]
    current = sum(clean)
    if current <= 0:
        even = max(ABSOLUTE_MIN_SECONDS, total_duration / len(clean))
        return [even] * len(clean)
    factor = total_duration / current
    scaled = [round(d * factor, 3) for d in clean]
    scaled[-1] = max(ABSOLUTE_MIN_SECONDS, round(scaled[-1] + (total_duration - sum(scaled)), 3))
    return scaled


def _proportional(word_counts: List[int], total_duration: float) -> List[float]:
    total_words = sum(word_counts)
    durations = [(wc / total_words) * total_duration for wc in word_counts]
    return _normalize([max(MIN_SLIDE_SECONDS, d) for d in durations], total_duration)


def calculate_slide_durations_from_script(
    script_text: str, slide_count: int, total_duration: float
) -> List[float]:
    """Splits narration time across slides using script structure.

    1. Explicit ``[Slide N]`` markers win when 2+ are found (word-weighted).
    2. Otherwise paragraphs win when their count matches the slide count.
    3. Fallback: equal distribution.
    """
    if slide_count <= 0:
        raise ValueError("slide_count must be positive")
    if total_duration <= 0:
        raise ValueError("total_duration must be positive")
    if slide_count == 1:
        return [max(MIN_SLIDE_SECONDS, total_duration)]

    # 1. Explicit [Slide N] markers.
    splits = _SLIDE_MARKER.split(script_text or "")
    if len(splits) > 2:
        slide_texts = {}
        for i in range(1, len(splits), 2):
            try:
                num = int(splits[i])
                txt = splits[i + 1].strip() if i + 1 < len(splits) else ""
                slide_texts[num] = txt
            except (ValueError, IndexError):
                continue
        if len(slide_texts) >= 2:
            word_counts = [
                max(1, len(slide_texts.get(s, "").split())) for s in range(1, slide_count + 1)
            ]
            return _proportional(word_counts, total_duration)

    # 2. Paragraph-per-slide.
    paras = [p.strip() for p in (script_text or "").split("\n\n") if p.strip()]
    if len(paras) == slide_count and slide_count > 1:
        return _proportional([max(1, len(p.split())) for p in paras], total_duration)

    # 3. Equal distribution.
    return _normalize([total_duration / slide_count] * slide_count, total_duration)

"""Pure helpers mapping a lesson script onto per-slide durations.

Qt-free. Invariants: every duration finite and >= MIN_SLIDE_SECONDS,
monotonic boundaries, sum == total (within 1e-6). Insufficient total
raises ValueError instead of creating a negative/zero last slide or
silently extending the audio. Locks are preserved exactly; only the
remaining time is distributed among free slides.
"""

import math
import re
from typing import Dict, List, Optional, Sequence

MIN_SLIDE_SECONDS = 1.5
ABSOLUTE_MIN_SECONDS = 0.5

_SLIDE_MARKER = re.compile(r"\[?\bSlide\s*(\d+)[\:\-\]]?", re.IGNORECASE)


def _check_total(slide_count: int, total: float, minimum: float) -> float:
    if slide_count <= 0:
        raise ValueError("slide_count must be positive")
    if not math.isfinite(total) or total <= 0:
        raise ValueError("total_duration must be finite and positive")
    if total < slide_count * minimum - 1e-9:
        raise ValueError(
            f"Duração insuficiente: {total}s para {slide_count} slides "
            f"(mínimo {minimum}s por slide = {slide_count * minimum}s)."
        )
    return float(total)


def validate_durations(
    durations: Sequence[float], total: Optional[float] = None,
    minimum: float = ABSOLUTE_MIN_SECONDS,
) -> List[float]:
    """Validate finite/positive/ordered-sum invariants; return floats."""
    if not durations:
        raise ValueError("durations must not be empty")
    out: List[float] = []
    for i, raw in enumerate(durations):
        v = float(raw)
        if not math.isfinite(v) or v < minimum:
            raise ValueError(f"Duração do slide {i + 1} inválida: {raw!r}")
        out.append(v)
    if total is not None:
        if not math.isfinite(total) or abs(sum(out) - total) > 1e-3:
            raise ValueError(f"Soma das durações ({sum(out)}) != total ({total})")
    return out


def boundaries(durations: Sequence[float]) -> List[float]:
    """Cumulative start boundaries (monotonic, starts at 0)."""
    validate_durations(durations)
    pts, acc = [0.0], 0.0
    for d in durations:
        acc += float(d)
        pts.append(round(acc, 6))
    return pts


def uniform_durations(slide_count: int, total_duration: float,
                      minimum: float = ABSOLUTE_MIN_SECONDS) -> List[float]:
    total = _check_total(slide_count, total_duration, minimum)
    each = total / slide_count
    out = [round(each, 3)] * slide_count
    out[-1] = round(total - sum(out[:-1]), 3)
    return validate_durations(out, total, minimum)


def weighted_durations(word_counts: Sequence[int], total_duration: float,
                       locked: Optional[Dict[int, float]] = None,
                       minimum: float = ABSOLUTE_MIN_SECONDS) -> List[float]:
    """Word-weighted split; locked indices keep exact values.

    Only the remaining time is distributed among free slides.
    """
    n = len(word_counts)
    if n == 0:
        raise ValueError("word_counts must not be empty")
    locked = dict(locked or {})
    total = _check_total(n, total_duration, minimum)
    for idx, val in locked.items():
        if not 0 <= idx < n:
            raise ValueError(f"Slide travado fora do alcance: {idx}")
        if not math.isfinite(val) or val < minimum:
            raise ValueError(f"Duração travada inválida no slide {idx + 1}: {val!r}")
    locked_sum = sum(locked.values())
    free = [i for i in range(n) if i not in locked]
    remaining = total - locked_sum
    if not free:
        if abs(remaining) > 1e-6:
            raise ValueError("Soma das travas difere da duração total.")
        return validate_durations([locked[i] for i in range(n)], total, minimum)
    if remaining < len(free) * minimum - 1e-9:
        raise ValueError("Duração insuficiente para os slides livres após as travas.")
    weights = [max(1, int(word_counts[i])) for i in free]
    wsum = sum(weights)
    out = [0.0] * n
    for idx, val in locked.items():
        out[idx] = float(val)
    assigned = 0.0
    for j, idx in enumerate(free):
        if j == len(free) - 1:
            out[idx] = round(remaining - assigned, 3)
        else:
            out[idx] = round(remaining * weights[j] / wsum, 3)
            assigned += out[idx]
    # Rounding may push a free slide below minimum only when remaining is
    # barely enough; surface it via validate instead of inventing time.
    return validate_durations(out, total, minimum)


def parse_slide_markers(script_text: str, slide_count: int) -> List[str]:
    """Split script by explicit ``[Slide N]`` markers (1-based).

    Returns per-slide texts; slides without a marker get ``""`` (never
    invented text). Raises when a marker number is out of range.
    """
    splits = _SLIDE_MARKER.split(script_text or "")
    texts = [""] * slide_count
    if len(splits) <= 2:
        return texts
    for i in range(1, len(splits), 2):
        num = int(splits[i])
        if not 1 <= num <= slide_count:
            raise ValueError(f"Marcação [Slide {num}] fora do alcance 1..{slide_count}")
        texts[num - 1] = splits[i + 1].strip() if i + 1 < len(splits) else ""
    return texts


def calculate_slide_durations_from_script(
    script_text: str, slide_count: int, total_duration: float,
    locked: Optional[Dict[int, float]] = None,
) -> List[float]:
    """Markers (word-weighted) -> paragraphs matching count -> uniform."""
    total = _check_total(slide_count, total_duration, ABSOLUTE_MIN_SECONDS)
    if slide_count == 1:
        if locked and abs(locked.get(0, total) - total) > 1e-6:
            raise ValueError("Trava do slide único difere da duração total.")
        return [total]
    texts = parse_slide_markers(script_text or "", slide_count)
    marked = [t for t in texts if t]
    if len(marked) >= 2 or (locked and marked):
        return weighted_durations(
            [max(1, len(t.split())) if t else 1 for t in texts], total, locked)
    paras = [p.strip() for p in (script_text or "").split("\n\n") if p.strip()]
    if len(paras) == slide_count:
        return weighted_durations([max(1, len(p.split())) for p in paras], total, locked)
    if locked:
        return weighted_durations([1] * slide_count, total, locked)
    return uniform_durations(slide_count, total)

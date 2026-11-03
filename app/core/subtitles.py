"""SRT/VTT subtitles supplied/edited by the user. No transcription."""

import re
from dataclasses import asdict, dataclass
from typing import List

_TS = re.compile(r"(\d+):(\d{2}):(\d{2})[.,](\d{3})")


@dataclass
class Cue:
    index: int
    start: float
    end: float
    text: str

    def validate(self) -> None:
        if not (self.start >= 0 and self.end > self.start):
            raise ValueError(f"Legenda {self.index}: fim deve ser maior que início.")


def _parse_ts(value: str) -> float:
    m = _TS.search(value.strip())
    if not m:
        raise ValueError(f"Timestamp inválido: {value!r}")
    h, mi, s, ms = (int(x) for x in m.groups())
    return h * 3600 + mi * 60 + s + ms / 1000


def _fmt(seconds: float, sep: str) -> str:
    ms = int(round(seconds * 1000))
    h, ms = divmod(ms, 3600000)
    mi, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{mi:02d}:{s:02d}{sep}{ms:03d}"


def validate_cues(cues: List[Cue]) -> List[Cue]:
    prev_end = 0.0
    for i, cue in enumerate(cues):
        cue.index = i + 1
        cue.validate()
        if cue.start < prev_end - 1e-9:
            raise ValueError("Legendas fora de ordem ou sobrepostas.")
        if not cue.text.strip():
            raise ValueError(f"Legenda {cue.index} sem texto.")
        prev_end = cue.end
    return cues


def parse_subtitles(content: str, fmt: str = "srt") -> List[Cue]:
    blocks = re.split(r"\n\s*\n", (content or "").replace("\r\n", "\n").strip())
    cues: List[Cue] = []
    for block in blocks:
        lines = [ln for ln in block.splitlines() if ln.strip()]
        if fmt.lower() == "vtt" and lines and lines[0].startswith("WEBVTT"):
            lines = lines[1:]
        time_lines = [ln for ln in lines if "-->" in ln]
        if not time_lines:
            continue
        start_s, end_s = time_lines[0].split("-->", 1)
        text_lines = lines[lines.index(time_lines[0]) + 1:]
        cues.append(Cue(len(cues) + 1, _parse_ts(start_s),
                        _parse_ts(end_s.split()[0]), "\n".join(text_lines)))
    return validate_cues(cues)


def export_subtitles(cues: List[Cue], fmt: str = "srt") -> str:
    validate_cues(list(cues))
    fmt = fmt.lower()
    if fmt not in ("srt", "vtt"):
        raise ValueError("Formato deve ser 'srt' ou 'vtt'.")
    sep = "," if fmt == "srt" else "."
    out = ["WEBVTT\n"] if fmt == "vtt" else []
    for c in cues:
        out.append(f"{c.index}\n{_fmt(c.start, sep)} --> {_fmt(c.end, sep)}\n{c.text}\n")
    return "\n".join(out)


def cues_to_dicts(cues: List[Cue]) -> list:
    return [asdict(c) for c in cues]

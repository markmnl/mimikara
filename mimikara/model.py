"""The JSON contract shared by every stage.

A document is ``{"title": str, "lines": [Line, ...]}``.  Each line has cue times,
Japanese tokens and English tokens.  Stages 1-3 produce it, the renderer consumes
it, and the timing editor edits it.  All ``*_ms`` values inside a line are
relative to the line's ``start``.

Token timing fields, in order of priority when the renderer times a line:

* ``start_ms``  - manual anchor (hand-edited or from the editor).  Always wins.
* ``align_ms``  - ``[t0, t1]`` from forced alignment, with ``align_score``.
* ``cue_ms``    - start of the sub-cue this token began, when cues were merged.
* otherwise the gap between anchors is spread by mora count.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Iterable


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------

_TIME_RE = re.compile(r"^\s*(?:(\d+):)?(?:(\d+):)?(\d+)(?:[.,](\d+))?\s*$")


def parse_time(s: str | int | float) -> int:
    """'H:MM:SS.cc', 'HH:MM:SS,mmm', 'MM:SS.cc', 'SS.cc' or a number of ms -> ms."""
    if isinstance(s, (int, float)):
        return int(round(s))
    m = _TIME_RE.match(s)
    if not m:
        raise ValueError(f"bad time: {s!r}")
    a, b, secs, frac = m.groups()
    if a is not None and b is not None:
        hours, mins = int(a), int(b)
    elif a is not None:
        hours, mins = 0, int(a)
    else:
        hours = mins = 0
    ms = 0
    if frac:
        ms = int(round(int(frac) / 10 ** len(frac) * 1000))
    return ((hours * 60 + mins) * 60 + int(secs)) * 1000 + ms


def ass_time(ms: int) -> str:
    """ms -> ASS 'H:MM:SS.cc' (centiseconds)."""
    cs = int(round(ms / 10))
    h, cs = divmod(cs, 360000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def srt_time(ms: int) -> str:
    """ms -> SRT 'HH:MM:SS,mmm'."""
    h, rem = divmod(int(ms), 3_600_000)
    m, rem = divmod(rem, 60_000)
    s, ms = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


# ---------------------------------------------------------------------------
# Tokens and lines
# ---------------------------------------------------------------------------

@dataclass
class JaToken:
    text: str
    romaji: str = ""
    role: str = "word"                 # word | particle | aux | punct
    kana: str = ""                     # katakana reading, when known
    pos: str = ""                      # UniDic pos1, when known
    start_ms: int | None = None        # manual anchor, relative to line start
    end_ms: int | None = None          # manual end anchor (optional)
    align_ms: list[int] | None = None  # [t0, t1] from forced alignment
    align_score: float | None = None
    cue_ms: int | None = None          # sub-cue start when cues were merged
    # computed by timing.time_line(); not part of the stored contract
    t0: int = field(default=0, compare=False)
    t1: int = field(default=0, compare=False)
    color: str | None = field(default=None, compare=False)

    def to_json(self) -> dict[str, Any]:
        d: dict[str, Any] = {"text": self.text, "romaji": self.romaji}
        if self.role != "word":
            d["role"] = self.role
        if self.kana:
            d["kana"] = self.kana
        if self.pos:
            d["pos"] = self.pos
        for k in ("start_ms", "end_ms", "align_ms", "align_score", "cue_ms"):
            v = getattr(self, k)
            if v is not None:
                d[k] = v
        return d

    @classmethod
    def from_json(cls, d: dict[str, Any]) -> "JaToken":
        return cls(
            text=d["text"], romaji=d.get("romaji", ""), role=d.get("role", "word"),
            kana=d.get("kana", ""), pos=d.get("pos", ""),
            start_ms=d.get("start_ms"), end_ms=d.get("end_ms"),
            align_ms=list(d["align_ms"]) if d.get("align_ms") is not None else None,
            align_score=d.get("align_score"), cue_ms=d.get("cue_ms"),
        )


@dataclass
class EnToken:
    text: str
    ja: list[int] = field(default_factory=list)
    attach: str = "next"               # unlinked tokens ride along: next | prev
    break_before: bool = False         # a line break (\N) precedes this token
    # computed
    reveal_ms: int = field(default=0, compare=False)
    color: str | None = field(default=None, compare=False)

    def to_json(self) -> dict[str, Any]:
        d: dict[str, Any] = {"text": self.text, "ja": list(self.ja)}
        if not self.ja and self.attach != "next":
            d["attach"] = self.attach
        if self.break_before:
            d["break_before"] = True
        return d

    @classmethod
    def from_json(cls, d: dict[str, Any]) -> "EnToken":
        return cls(text=d["text"], ja=[int(j) for j in d.get("ja", [])],
                   attach=d.get("attach", "next"), break_before=bool(d.get("break_before", False)))


@dataclass
class Cue:
    """A single subtitle cue as read from an .srt/.ass file."""
    start: int
    end: int
    text: str

    @property
    def duration(self) -> int:
        return self.end - self.start


@dataclass
class Line:
    start: int
    end: int
    ja: list[JaToken] = field(default_factory=list)
    en: list[EnToken] = field(default_factory=list)
    ja_text: str = ""
    en_text: str = ""
    en_original: str | None = None     # official English before literal rewriting
    speech_start_ms: int | None = None
    speech_end_ms: int | None = None
    ja_cues: list[Cue] = field(default_factory=list)   # source cues, if merged
    en_cues: list[Cue] = field(default_factory=list)
    timing: str = ""                   # mora | whisperx | mfa | manual (informational)
    warnings: list[str] = field(default_factory=list)
    id: int | None = None

    @property
    def duration(self) -> int:
        return self.end - self.start

    @property
    def speech_window(self) -> tuple[int, int]:
        s = self.speech_start_ms if self.speech_start_ms is not None else 0
        e = self.speech_end_ms if self.speech_end_ms is not None else self.duration
        return s, e

    def validate(self) -> None:
        for e in self.en:
            for j in e.ja:
                if not 0 <= j < len(self.ja):
                    raise ValueError(
                        f"line {self.id}: English token {e.text!r} links to missing Japanese token {j}")

    def to_json(self) -> dict[str, Any]:
        d: dict[str, Any] = {}
        if self.id is not None:
            d["id"] = self.id
        d["start"] = ass_time(self.start)
        d["end"] = ass_time(self.end)
        if self.ja_text:
            d["ja_text"] = self.ja_text
        if self.en_text:
            d["en_text"] = self.en_text
        if self.en_original is not None:
            d["en_original"] = self.en_original
        if self.speech_start_ms is not None:
            d["speech_start_ms"] = self.speech_start_ms
        if self.speech_end_ms is not None:
            d["speech_end_ms"] = self.speech_end_ms
        if self.timing:
            d["timing"] = self.timing
        if self.ja_cues:
            d["ja_cues"] = [asdict(c) for c in self.ja_cues]
        if self.en_cues:
            d["en_cues"] = [asdict(c) for c in self.en_cues]
        d["ja"] = [t.to_json() for t in self.ja]
        d["en"] = [t.to_json() for t in self.en]
        if self.warnings:
            d["warnings"] = list(self.warnings)
        return d

    @classmethod
    def from_json(cls, d: dict[str, Any]) -> "Line":
        line = cls(
            start=parse_time(d["start"]), end=parse_time(d["end"]),
            ja=[JaToken.from_json(t) for t in d.get("ja", [])],
            en=[EnToken.from_json(t) for t in d.get("en", [])],
            ja_text=d.get("ja_text", ""), en_text=d.get("en_text", ""),
            en_original=d.get("en_original"),
            speech_start_ms=d.get("speech_start_ms"), speech_end_ms=d.get("speech_end_ms"),
            ja_cues=[Cue(**c) for c in d.get("ja_cues", [])],
            en_cues=[Cue(**c) for c in d.get("en_cues", [])],
            timing=d.get("timing", ""), warnings=list(d.get("warnings", [])),
            id=d.get("id"),
        )
        if not line.ja_text:
            line.ja_text = "".join(t.text for t in line.ja)
        if not line.en_text:
            line.en_text = " ".join(t.text for t in line.en)
        line.validate()
        return line


@dataclass
class Document:
    title: str = ""
    lines: list[Line] = field(default_factory=list)
    notes: str = ""
    source: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        d: dict[str, Any] = {"title": self.title, "version": 1}
        if self.notes:
            d["notes"] = self.notes
        if self.source:
            d["source"] = self.source
        d["lines"] = [ln.to_json() for ln in self.lines]
        return d

    @classmethod
    def from_json(cls, d: dict[str, Any]) -> "Document":
        doc = cls(title=d.get("title", ""), notes=d.get("notes", ""), source=dict(d.get("source", {})))
        doc.lines = [Line.from_json(ln) for ln in d.get("lines", [])]
        for i, ln in enumerate(doc.lines, 1):
            if ln.id is None:
                ln.id = i
        return doc

    def save(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps(self.to_json(), ensure_ascii=False, indent=2) + "\n",
                              encoding="utf-8")

    @classmethod
    def load(cls, path: str | Path) -> "Document":
        return cls.from_json(json.loads(Path(path).read_text(encoding="utf-8")))


def number_lines(lines: Iterable[Line]) -> None:
    for i, ln in enumerate(lines, 1):
        ln.id = i

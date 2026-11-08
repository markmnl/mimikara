"""Read .srt and .ass subtitle files into plain cues."""
from __future__ import annotations

import re
from pathlib import Path

from .model import Cue, parse_time

_SRT_TIME = re.compile(r"(\d+:\d+:\d+[,.]\d+)\s*-->\s*(\d+:\d+:\d+[,.]\d+)")
_TAG_RE = re.compile(r"<[^>]+>|\{[^}]*\}")


def clean_text(text: str) -> str:
    """Strip HTML/ASS tags, collapse whitespace, keep line breaks."""
    text = text.replace("\\N", "\n").replace("\\n", "\n").replace("\\h", " ")
    text = _TAG_RE.sub("", text)
    lines = [re.sub(r"[ \t]+", " ", ln).strip() for ln in text.split("\n")]
    return "\n".join(ln for ln in lines if ln)


def parse_srt(text: str) -> list[Cue]:
    cues: list[Cue] = []
    text = text.lstrip("﻿")
    for block in re.split(r"\n\s*\n", text.strip()):
        lines = block.strip().split("\n")
        if not lines:
            continue
        # index line is optional
        ti = 0
        if not _SRT_TIME.search(lines[0]):
            ti = 1
        if ti >= len(lines):
            continue
        m = _SRT_TIME.search(lines[ti])
        if not m:
            continue
        body = clean_text("\n".join(lines[ti + 1:]))
        if not body:
            continue
        cues.append(Cue(parse_time(m.group(1)), parse_time(m.group(2)), body))
    return _sorted(cues)


def parse_ass(text: str) -> list[Cue]:
    cues: list[Cue] = []
    fmt: list[str] | None = None
    in_events = False
    for raw in text.lstrip("﻿").splitlines():
        line = raw.strip()
        if line.lower().startswith("[events]"):
            in_events = True
            continue
        if line.startswith("["):
            in_events = False
            continue
        if not in_events:
            continue
        if line.lower().startswith("format:"):
            fmt = [f.strip().lower() for f in line.split(":", 1)[1].split(",")]
            continue
        if not line.lower().startswith("dialogue:"):
            continue
        fields = fmt or ["layer", "start", "end", "style", "name", "marginl", "marginr",
                         "marginv", "effect", "text"]
        parts = line.split(":", 1)[1].split(",", len(fields) - 1)
        if len(parts) < len(fields):
            continue
        rec = dict(zip(fields, [p.strip() for p in parts]))
        body = clean_text(rec["text"])
        if not body:
            continue
        cues.append(Cue(parse_time(rec["start"]), parse_time(rec["end"]), body))
    return _sorted(cues)


def _sorted(cues: list[Cue]) -> list[Cue]:
    return sorted(cues, key=lambda c: (c.start, c.end))


def load_cues(path: str | Path) -> list[Cue]:
    p = Path(path)
    text = p.read_text(encoding="utf-8", errors="replace")
    if p.suffix.lower() in (".ass", ".ssa"):
        return parse_ass(text)
    return parse_srt(text)


def merge_same_time(cues: list[Cue]) -> list[Cue]:
    """Join cues that share identical times (e.g. per-speaker events) into one."""
    out: list[Cue] = []
    for c in cues:
        if out and out[-1].start == c.start and out[-1].end == c.end:
            out[-1] = Cue(c.start, c.end, out[-1].text + "\n" + c.text)
        else:
            out.append(c)
    return out

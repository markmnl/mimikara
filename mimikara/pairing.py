"""Stage 1: pair Japanese and English cues by time overlap.

Cues from the two files rarely segment the same way.  We build connected
groups of cues that overlap in time, then either pair them one-to-one (when
the group splits cleanly) or merge each side into a single line.
"""
from __future__ import annotations

from dataclasses import dataclass

from .model import Cue, Line

MIN_OVERLAP_MS = 150       # ignore brushes shorter than this
MIN_OVERLAP_RATIO = 0.3    # ...or smaller than this share of the shorter cue
GOOD_PAIR_RATIO = 0.5      # 1:1 split needs this much of each cue covered
LONG_LINE_MS = 15_000      # warn when a merged line gets this long


def overlap_ms(a: Cue, b: Cue) -> int:
    return max(0, min(a.end, b.end) - max(a.start, b.start))


def overlaps(a: Cue, b: Cue) -> bool:
    ov = overlap_ms(a, b)
    if ov <= 0:
        return False
    shorter = max(1, min(a.duration, b.duration))
    return ov >= MIN_OVERLAP_MS or ov / shorter >= MIN_OVERLAP_RATIO


@dataclass
class Group:
    ja: list[Cue]
    en: list[Cue]


def group_cues(ja: list[Cue], en: list[Cue]) -> list[Group]:
    """Connected components of the overlap graph, in time order."""
    ja = sorted(ja, key=lambda c: c.start)
    en = sorted(en, key=lambda c: c.start)
    groups: list[Group] = []
    i = j = 0
    cur: Group | None = None

    def flush() -> None:
        nonlocal cur
        if cur:
            groups.append(cur)
        cur = None

    # sweep both lists by start time, extending the current group while anything overlaps
    while i < len(ja) or j < len(en):
        take_ja = j >= len(en) or (i < len(ja) and ja[i].start <= en[j].start)
        c = ja[i] if take_ja else en[j]
        if cur is not None:
            others = cur.en if take_ja else cur.ja
            same = cur.ja if take_ja else cur.en
            if not (any(overlaps(c, o) for o in others) or any(overlaps(c, o) for o in same)):
                flush()
        if cur is None:
            cur = Group([], [])
        (cur.ja if take_ja else cur.en).append(c)
        if take_ja:
            i += 1
        else:
            j += 1
    flush()
    return groups


def _merge(cues: list[Cue]) -> Cue:
    return Cue(min(c.start for c in cues), max(c.end for c in cues),
               "\n".join(c.text for c in cues))


def _try_split(g: Group) -> list[tuple[list[Cue], list[Cue]]] | None:
    """If every JA cue matches exactly one EN cue (and vice versa), split 1:1."""
    if len(g.ja) != len(g.en) or len(g.ja) < 2:
        return None
    pairs = []
    used: set[int] = set()
    for a in g.ja:
        best, best_ov = None, 0
        for k, b in enumerate(g.en):
            if k in used:
                continue
            ov = overlap_ms(a, b)
            if ov > best_ov:
                best, best_ov = k, ov
        if best is None:
            return None
        b = g.en[best]
        if best_ov / max(1, a.duration) < GOOD_PAIR_RATIO or best_ov / max(1, b.duration) < GOOD_PAIR_RATIO:
            return None
        used.add(best)
        pairs.append(([a], [b]))
    return pairs


def _make_line(ja: list[Cue], en: list[Cue]) -> Line:
    cues = ja + en
    jc = _merge(ja) if ja else None
    ec = _merge(en) if en else None
    start = min(c.start for c in cues)
    end = max(c.end for c in cues)
    line = Line(start=start, end=end, ja_text=jc.text if jc else "", en_text=ec.text if ec else "")
    if len(ja) > 1:
        line.ja_cues = list(ja)
    if len(en) > 1:
        line.en_cues = list(en)
    if not ja:
        line.warnings.append("no Japanese cue overlaps this English cue")
    if not en:
        line.warnings.append("no English cue overlaps this Japanese cue")
    if line.duration > LONG_LINE_MS and (len(ja) > 1 or len(en) > 1):
        line.warnings.append(f"merged {len(ja)} JA + {len(en)} EN cues into a {line.duration/1000:.1f}s line")
    return line


def pair_cues(ja: list[Cue], en: list[Cue]) -> list[Line]:
    lines: list[Line] = []
    for g in group_cues(ja, en):
        split = _try_split(g)
        if split:
            for a, b in split:
                lines.append(_make_line(a, b))
        else:
            lines.append(_make_line(g.ja, g.en))
    lines.sort(key=lambda ln: ln.start)
    for n, ln in enumerate(lines, 1):
        ln.id = n
    return lines

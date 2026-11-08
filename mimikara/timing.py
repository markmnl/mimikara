"""Stage 3: decide when each Japanese token is spoken and when each English
token should appear.

Anchors, in priority order: manual ``start_ms`` > forced-alignment ``align_ms``
> sub-cue ``cue_ms``.  Between anchors the time is spread by mora count.
"""
from __future__ import annotations

from .model import JaToken, Line
from .mora import count_morae

MIN_ALIGN_SCORE = 0.4   # forced-alignment anchors below this are ignored


def token_weight(t: JaToken) -> int:
    if t.role == "punct":
        return 0
    return max(1, count_morae(t.romaji, t.kana))


def anchor_of(t: JaToken) -> int | None:
    if t.start_ms is not None:
        return t.start_ms
    if t.align_ms is not None and (t.align_score is None or t.align_score >= MIN_ALIGN_SCORE):
        return t.align_ms[0]
    return t.cue_ms


def time_japanese(line: Line) -> None:
    toks = line.ja
    speech_start, speech_end = line.speech_window
    if not toks:
        return
    # (index, ms) anchors; the first token's anchor replaces the speech start
    anchors: list[tuple[int, int]] = []
    first = anchor_of(toks[0])
    anchors.append((0, first if first is not None else speech_start))
    last_ms = anchors[0][1]
    for i, t in enumerate(toks[1:], 1):
        a = anchor_of(t)
        if a is not None and a >= last_ms:
            anchors.append((i, a))
            last_ms = a
    # end of the last word: manual end, aligned end, or the speech end
    tail = next((t for t in reversed(toks) if t.role != "punct"), toks[-1])
    end = None
    if tail.end_ms is not None:
        end = tail.end_ms
    elif tail.align_ms is not None and (tail.align_score is None or tail.align_score >= MIN_ALIGN_SCORE):
        end = tail.align_ms[1]
    if end is None or end < last_ms:
        end = max(speech_end, last_ms)
    anchors.append((len(toks), end))

    for (a_idx, a_ms), (b_idx, b_ms) in zip(anchors, anchors[1:]):
        seg = toks[a_idx:b_idx]
        weights = [token_weight(t) for t in seg]
        total = sum(weights)
        span = b_ms - a_ms
        if total == 0:
            for t in seg:
                t.t0 = t.t1 = a_ms
            continue
        cursor = float(a_ms)
        for t, w in zip(seg, weights):
            t.t0 = int(round(cursor))
            cursor += span * w / total
            t.t1 = int(round(cursor))
    # punctuation never has its own time; it lights up with the previous word
    for i, t in enumerate(toks):
        if t.role == "punct" and i > 0:
            t.t0 = toks[i - 1].t0
            t.t1 = toks[i - 1].t1


def time_english(line: Line) -> None:
    speech_start, _ = line.speech_window
    for e in line.en:
        if e.ja:
            e.reveal_ms = min(line.ja[j].t0 for j in e.ja if 0 <= j < len(line.ja))
    for i, e in enumerate(line.en):
        if e.ja:
            continue
        order = list(range(i + 1, len(line.en))) if e.attach == "next" else list(range(i - 1, -1, -1))
        fallback = list(range(i - 1, -1, -1)) if e.attach == "next" else list(range(i + 1, len(line.en)))
        for k in order + fallback:
            if line.en[k].ja:
                e.reveal_ms = line.en[k].reveal_ms
                break
        else:
            e.reveal_ms = line.ja[0].t0 if line.ja else speech_start


def time_line(line: Line) -> None:
    time_japanese(line)
    time_english(line)

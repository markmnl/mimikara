#!/usr/bin/env python3
"""
mimikara prototype: turn word-aligned Japanese/English subtitle lines into an
.ass file where each English word appears at the moment its Japanese
counterpart is spoken, while the English stays in normal reading order.

Input:  a JSON file (see examples/luffy.json)
Output: an .ass file playable in mpv / VLC / anything using libass

Usage:
    python3 mimikara.py examples/luffy.json -o out/luffy.ass                  # English only (default)
    python3 mimikara.py examples/luffy.json -o out/luffy.ass --romaji          # + romaji line
    python3 mimikara.py examples/luffy.json -o out/luffy.ass --romaji --kana   # + Japanese script
    python3 mimikara.py examples/luffy.json -o out/luffy.ass --all-modes       # one file per mode

With --all-modes, name the files after the video (e.g. -o ep01.ass gives
ep01.en.ass, ep01.romaji.ass, ep01.japanese.ass). mpv loads them all and
`j` cycles between them while watching.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

# --------------------------------------------------------------------------
# Time helpers
# --------------------------------------------------------------------------

def parse_time(s: str) -> int:
    """'H:MM:SS.cc' (or SS.cc / MM:SS.cc) -> milliseconds."""
    parts = s.split(":")
    secs = float(parts[-1])
    mins = int(parts[-2]) if len(parts) >= 2 else 0
    hours = int(parts[-3]) if len(parts) >= 3 else 0
    return round(((hours * 60 + mins) * 60 + secs) * 1000)


def ass_time(ms: int) -> str:
    """milliseconds -> ASS 'H:MM:SS.cc'."""
    cs = round(ms / 10)
    h, cs = divmod(cs, 360000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


# --------------------------------------------------------------------------
# Mora counting (rough, but good enough to spread a line's duration)
# --------------------------------------------------------------------------

LONG_VOWELS = set("āīūēôōû")
VOWELS = set("aiueo")


def count_morae(romaji: str) -> int:
    r = romaji.lower()
    n = 0
    for i, ch in enumerate(r):
        nxt = r[i + 1] if i + 1 < len(r) else ""
        if ch in LONG_VOWELS:
            n += 2
        elif ch in VOWELS:
            n += 1
        elif ch == "n" and nxt not in VOWELS and nxt not in LONG_VOWELS and nxt != "y":
            n += 1                      # syllabic ん
        elif ch.isalpha() and ch == nxt and ch not in "n":
            n += 1                      # small っ (doubled consonant)
    return n


# --------------------------------------------------------------------------
# Data model
# --------------------------------------------------------------------------

@dataclass
class JaToken:
    text: str
    romaji: str
    role: str = "word"            # "word" | "particle"
    start_ms: int | None = None   # explicit override, relative to cue start
    # filled in:
    t0: int = 0
    t1: int = 0
    color: str | None = None


@dataclass
class EnToken:
    text: str
    ja: list[int]
    attach: str = "next"          # for unlinked tokens: "next" | "prev"
    reveal_ms: int = 0
    color: str | None = None


@dataclass
class Line:
    start: int
    end: int
    speech_start: int
    speech_end: int
    ja: list[JaToken]
    en: list[EnToken]

    @property
    def duration(self) -> int:
        return self.end - self.start


def load(path: Path) -> list[Line]:
    data = json.loads(path.read_text(encoding="utf-8"))
    lines = []
    for raw in data["lines"]:
        start, end = parse_time(raw["start"]), parse_time(raw["end"])
        dur = end - start
        ja = [JaToken(t["text"], t.get("romaji", ""), t.get("role", "word"),
                      t.get("start_ms")) for t in raw["ja"]]
        en = [EnToken(t["text"], list(t.get("ja", [])), t.get("attach", "next"))
              for t in raw["en"]]
        for e in en:
            for j in e.ja:
                if not 0 <= j < len(ja):
                    sys.exit(f"English token {e.text!r} links to missing Japanese token {j}")
        lines.append(Line(start, end,
                          raw.get("speech_start_ms", 0),
                          raw.get("speech_end_ms", dur),
                          ja, en))
    return lines


# --------------------------------------------------------------------------
# Step 1: time every Japanese token
# --------------------------------------------------------------------------

def time_japanese(line: Line) -> None:
    """Spread the speech window over tokens by mora count.

    Any token with an explicit start_ms becomes an anchor; tokens between
    anchors are distributed proportionally. This is the "a little bit of
    work to put the timing right" hook: add start_ms where the estimate is off.
    """
    toks = line.ja
    anchors = [(0, line.speech_start)]
    for i, t in enumerate(toks):
        if t.start_ms is not None and i > 0:
            anchors.append((i, t.start_ms))
    if toks and toks[0].start_ms is not None:
        anchors[0] = (0, toks[0].start_ms)
    anchors.append((len(toks), line.speech_end))

    for (a_idx, a_ms), (b_idx, b_ms) in zip(anchors, anchors[1:]):
        seg = toks[a_idx:b_idx]
        weights = [count_morae(t.romaji) for t in seg]
        total = sum(weights) or 1
        cursor = a_ms
        for t, w in zip(seg, weights):
            t.t0 = round(cursor)
            cursor += (b_ms - a_ms) * w / total
            t.t1 = round(cursor)


# --------------------------------------------------------------------------
# Step 2: decide when each English token appears
# --------------------------------------------------------------------------

def time_english(line: Line) -> None:
    for e in line.en:
        if e.ja:
            e.reveal_ms = min(line.ja[j].t0 for j in e.ja)
    # unlinked tokens ("of the") ride along with a neighbour
    for i, e in enumerate(line.en):
        if e.ja:
            continue
        order = range(i + 1, len(line.en)) if e.attach == "next" else range(i - 1, -1, -1)
        fallback = range(i - 1, -1, -1) if e.attach == "next" else range(i + 1, len(line.en))
        for k in list(order) + list(fallback):
            if line.en[k].ja:
                e.reveal_ms = line.en[k].reveal_ms
                break
        else:
            e.reveal_ms = line.speech_start


# --------------------------------------------------------------------------
# Step 3: colours that pair a Japanese word with its English meaning
# --------------------------------------------------------------------------

# RGB hex; converted to ASS &HBBGGRR& below
PALETTE = ["FFC94D", "FF8A5C", "5EC8FF", "7BE3A8", "C9A2FF", "FF8AC8"]
WHITE, DIM, PARTICLE = "FFFFFF", "6B6F7A", "9AA0AC"


def ass_color(rgb: str) -> str:
    return f"&H{rgb[4:6]}{rgb[2:4]}{rgb[0:2]}&"


def assign_colors(line: Line) -> None:
    n = 0
    for e in line.en:
        if not e.ja:
            continue
        rgb = PALETTE[n % len(PALETTE)]
        n += 1
        e.color = rgb
        for j in e.ja:
            line.ja[j].color = rgb


# --------------------------------------------------------------------------
# Step 4: write ASS
# --------------------------------------------------------------------------

FADE = 120  # ms for a word to fade in / light up

HEADER = """[Script Info]
Title: {title}
ScriptType: v4.00+
WrapStyle: 0
ScaledBorderAndShadow: yes
PlayResX: 1280
PlayResY: 720

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: English,Noto Sans CJK JP,58,&H00FFFFFF,&H00FFFFFF,&H00101010,&H80000000,-1,0,0,0,100,100,0,0,1,3,1,2,40,40,56,1
Style: Romaji,Noto Sans CJK JP,40,&H00FFFFFF,&H00FFFFFF,&H00101010,&H80000000,0,0,0,0,100,100,1,0,1,2.5,1,2,40,40,132,1
Style: Kana,Noto Sans CJK JP,34,&H00FFFFFF,&H00FFFFFF,&H00101010,&H80000000,0,0,0,0,100,100,2,0,1,2.5,1,2,40,40,190,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def esc(text: str) -> str:
    return text.replace("{", "(").replace("}", ")").replace("\n", r"\N")


def light_up(t0: int, base: str, lit: str) -> str:
    """Override block: start in `base` colour, switch to `lit` at t0."""
    return (f"{{\\1c{ass_color(base)}"
            f"\\t({t0},{t0 + FADE},\\1c{ass_color(lit)})}}")


def join_tokens(parts: list[tuple[str, str]], sep: str) -> str:
    out = []
    for i, (tag, text) in enumerate(parts):
        if i and not re.fullmatch(r"[!?.,。、！？]+", text):
            out.append(sep)
        out.append(tag + esc(text))
    return "".join(out)


FLASH, FLASH_HOLD = "FFE27A", 500   # English-only mode: newest word glows for 0.5 s


def build_events(line: Line, layers: set[str], color_mode: str) -> list[str]:
    start, end = ass_time(line.start), ass_time(line.end)
    events = []

    def lit_color(t: JaToken) -> str:
        if t.color:
            return t.color
        return PARTICLE if t.role == "particle" else WHITE

    # Romaji line: every word sits dim, then lights up when spoken.
    if "romaji" in layers:
        romaji = join_tokens([(light_up(t.t0, DIM, lit_color(t)), t.romaji)
                              for t in line.ja], " ")
        events.append(f"Dialogue: 0,{start},{end},Romaji,,0,0,0,,{romaji}")

    if "kana" in layers:
        kana = join_tokens([(light_up(t.t0, DIM, lit_color(t)), t.text)
                            for t in line.ja], "")
        events.append(f"Dialogue: 0,{start},{end},Kana,,0,0,0,,{kana}")

    # English line: words are invisible, but already laid out in English
    # order, so nothing shifts as they appear.
    parts = []
    for e in line.en:
        r = e.reveal_ms
        appear = f"\\alpha&HFF&\\t({r},{r + FADE},\\alpha&H00&)"
        if color_mode == "pairs":
            # keep the colour that matches the Japanese word above
            tag = f"{{{appear}\\1c{ass_color(e.color or WHITE)}}}"
        elif color_mode == "flash":
            # the word you just heard glows, then settles to white
            tag = (f"{{{appear}\\1c{ass_color(FLASH)}"
                   f"\\t({r + FADE + FLASH_HOLD},{r + FADE + FLASH_HOLD + 400},"
                   f"\\1c{ass_color(WHITE)})}}")
        else:
            tag = f"{{{appear}\\1c{ass_color(WHITE)}}}"
        parts.append((tag, e.text))
    events.append(f"Dialogue: 0,{start},{end},English,,0,0,0,,{join_tokens(parts, ' ')}")
    return events


def prepare(lines: list[Line]) -> None:
    for line in lines:
        time_japanese(line)
        time_english(line)
        assign_colors(line)


def render(lines: list[Line], title: str, layers: set[str], color_mode: str) -> str:
    out = [HEADER.format(title=title)]
    for line in lines:
        out.extend(build_events(line, layers, color_mode))
    return "\n".join(out) + "\n"


# Modes written by --all-modes. In mpv, press `j` to cycle between them.
MODES = {
    "en":       ({"en"}, "flash"),
    "romaji":   ({"en", "romaji"}, "pairs"),
    "japanese": ({"en", "romaji", "kana"}, "pairs"),
}


def report(lines: list[Line]) -> None:
    for n, line in enumerate(lines, 1):
        print(f"Line {n}  {ass_time(line.start)} -> {ass_time(line.end)}")
        for t in line.ja:
            print(f"  ja  {t.t0:>5}–{t.t1:<5} ms  {t.text:<4} {t.romaji:<8} morae={count_morae(t.romaji)}")
        for e in sorted(line.en, key=lambda e: e.reveal_ms):
            print(f"  en  {e.reveal_ms:>5} ms        {e.text}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input", type=Path)
    ap.add_argument("-o", "--output", type=Path, required=True,
                    help="output .ass (with --all-modes: base name, mode is added before .ass)")
    ap.add_argument("--romaji", action="store_true", help="show the romaji line")
    ap.add_argument("--kana", action="store_true", help="show the kana/kanji line")
    ap.add_argument("--color", choices=["pairs", "flash", "none"],
                    help="English colouring (default: flash if English only, else pairs)")
    ap.add_argument("--all-modes", action="store_true",
                    help="write one file per mode (en, romaji, japanese) to switch between while watching")
    args = ap.parse_args()

    title = json.loads(args.input.read_text(encoding="utf-8")).get("title", args.input.stem)
    lines = load(args.input)
    prepare(lines)
    report(lines)
    args.output.parent.mkdir(parents=True, exist_ok=True)

    if args.all_modes:
        stem = args.output.with_suffix("")
        for name, (layers, color) in MODES.items():
            path = stem.with_name(f"{stem.name}.{name}.ass")
            path.write_text(render(lines, f"{title} [{name}]", layers, args.color or color),
                            encoding="utf-8")
            print(f"wrote {path}")
        return

    layers = {"en"} | ({"romaji"} if args.romaji else set()) | ({"kana"} if args.kana else set())
    color = args.color or ("flash" if layers == {"en"} else "pairs")
    args.output.write_text(render(lines, title, layers, color), encoding="utf-8")
    print(f"\nwrote {args.output}")


if __name__ == "__main__":
    main()

"""Stage 4: write .ass.

Words never move or scale: every token is laid out from the start of the
cue, invisible, and only its colour/alpha changes over time (``\\t`` tags).
"""
from __future__ import annotations

import re
from pathlib import Path

from .model import Document, Line, JaToken, ass_time
from .timing import time_line

# RGB hex; converted to ASS &HBBGGRR& below
PALETTE = ["FFC94D", "FF8A5C", "5EC8FF", "7BE3A8", "C9A2FF", "FF8AC8"]
WHITE, DIM, PARTICLE = "FFFFFF", "6B6F7A", "9AA0AC"
FLASH, FLASH_HOLD = "FFE27A", 500   # English-only: the newest word glows for 0.5 s
FADE = 120                          # ms for a word to fade in / light up

HEADER = """[Script Info]
Title: {title}
ScriptType: v4.00+
WrapStyle: 0
ScaledBorderAndShadow: yes
PlayResX: 1280
PlayResY: 720

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: English,{font},58,&H00FFFFFF,&H00FFFFFF,&H00101010,&H80000000,-1,0,0,0,100,100,0,0,1,3,1,2,40,40,56,1
Style: EnglishSolo,{font},58,&H00FFFFFF,&H00FFFFFF,&H00101010,&H80000000,-1,0,0,0,100,100,0,0,1,3,1,2,40,40,56,1
Style: Romaji,{font},40,&H00FFFFFF,&H00FFFFFF,&H00101010,&H80000000,0,0,0,0,100,100,1,0,1,2.5,1,2,40,40,132,1
Style: Kana,{font},34,&H00FFFFFF,&H00FFFFFF,&H00101010,&H80000000,0,0,0,0,100,100,2,0,1,2.5,1,2,40,40,190,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

DEFAULT_FONT = "Noto Sans CJK JP"

# Modes written by --all-modes.  In mpv, press `j` to cycle between them.
MODES = {
    "en":       ({"en"}, "flash"),
    "romaji":   ({"en", "romaji"}, "pairs"),
    "japanese": ({"en", "romaji", "kana"}, "pairs"),
}


def ass_color(rgb: str) -> str:
    return f"&H{rgb[4:6]}{rgb[2:4]}{rgb[0:2]}&"


def esc(text: str) -> str:
    return text.replace("{", "(").replace("}", ")").replace("\n", r"\N")


def assign_colors(line: Line) -> None:
    n = 0
    for t in line.ja:
        t.color = None
    for e in line.en:
        e.color = None
        if not e.ja:
            continue
        # reuse the colour if one of our Japanese words is already coloured
        existing = next((line.ja[j].color for j in e.ja if line.ja[j].color), None)
        rgb = existing or PALETTE[n % len(PALETTE)]
        if not existing:
            n += 1
        e.color = rgb
        for j in e.ja:
            line.ja[j].color = rgb


def light_up(t0: int, base: str, lit: str) -> str:
    """Override block: start in `base` colour, switch to `lit` at t0."""
    return f"{{\\1c{ass_color(base)}\\t({t0},{t0 + FADE},\\1c{ass_color(lit)})}}"


_NO_SPACE_BEFORE = re.compile(r"^[!?.,;:。、！？…)\]]+$")


def join_tokens(parts: list[tuple[str, str, bool]], sep: str) -> str:
    out = []
    for i, (tag, text, brk) in enumerate(parts):
        if brk:
            out.append(r"\N")
        elif i and not _NO_SPACE_BEFORE.match(text):
            out.append(sep)
        out.append(tag + esc(text))
    return "".join(out)


def lit_color(t: JaToken) -> str:
    if t.color:
        return t.color
    return PARTICLE if t.role in ("particle", "aux") else WHITE


def english_event(line: Line, color_mode: str, style: str = "English") -> str:
    start, end = ass_time(line.start), ass_time(line.end)
    parts = []
    for e in line.en:
        r = e.reveal_ms
        appear = f"\\alpha&HFF&\\t({r},{r + FADE},\\alpha&H00&)"
        if color_mode == "pairs":
            tag = f"{{{appear}\\1c{ass_color(e.color or WHITE)}}}"
        elif color_mode == "flash":
            tag = (f"{{{appear}\\1c{ass_color(FLASH)}"
                   f"\\t({r + FADE + FLASH_HOLD},{r + FADE + FLASH_HOLD + 400},\\1c{ass_color(WHITE)})}}")
        else:
            tag = f"{{{appear}\\1c{ass_color(WHITE)}}}"
        parts.append((tag, e.text, e.break_before))
    return f"Dialogue: 0,{start},{end},{style},,0,0,0,,{join_tokens(parts, ' ')}"


def build_events(line: Line, layers: set[str], color_mode: str, combined: bool = False) -> list[str]:
    """Events for one line.  ``combined`` writes both English variants (styles
    English = pair colours, EnglishSolo = flash) so a player can pick."""
    start, end = ass_time(line.start), ass_time(line.end)
    events: list[str] = []
    if line.ja and "romaji" in layers:
        romaji = join_tokens([(light_up(t.t0, DIM, lit_color(t)), t.romaji, False)
                              for t in line.ja if t.romaji], " ")
        events.append(f"Dialogue: 0,{start},{end},Romaji,,0,0,0,,{romaji}")
    if line.ja and "kana" in layers:
        kana = join_tokens([(light_up(t.t0, DIM, lit_color(t)), t.text, False) for t in line.ja], "")
        events.append(f"Dialogue: 0,{start},{end},Kana,,0,0,0,,{kana}")
    if line.en and "en" in layers:
        if combined:
            events.append(english_event(line, "pairs", "English"))
            events.append(english_event(line, "flash", "EnglishSolo"))
        else:
            events.append(english_event(line, color_mode, "English"))
    return events


def prepare(doc: Document) -> None:
    for line in doc.lines:
        time_line(line)
        assign_colors(line)


def render(doc: Document, layers: set[str], color_mode: str, title: str | None = None,
           font: str = DEFAULT_FONT, combined: bool = False) -> str:
    prepare(doc)
    out = [HEADER.format(title=title or doc.title or "mimikara", font=font)]
    for line in doc.lines:
        out.extend(build_events(line, layers, color_mode, combined))
    return "\n".join(out) + "\n"


def write_modes(doc: Document, output: Path, color_override: str | None = None,
                font: str = DEFAULT_FONT) -> list[Path]:
    """Write ``<stem>.en.ass``, ``<stem>.romaji.ass``, ``<stem>.japanese.ass`` and
    ``<stem>.all.ass`` (every style, for the browser overlay)."""
    stem = output.with_suffix("")
    written: list[Path] = []
    for name, (layers, color) in MODES.items():
        path = stem.with_name(f"{stem.name}.{name}.ass")
        path.write_text(render(doc, layers, color_override or color, f"{doc.title} [{name}]", font),
                        encoding="utf-8")
        written.append(path)
    path = stem.with_name(f"{stem.name}.all.ass")
    path.write_text(render(doc, {"en", "romaji", "kana"}, "pairs", f"{doc.title} [all]", font,
                           combined=True), encoding="utf-8")
    written.append(path)
    return written


def report(doc: Document) -> str:
    lines = []
    for line in doc.lines:
        lines.append(f"Line {line.id}  {ass_time(line.start)} -> {ass_time(line.end)}"
                     + (f"  [{line.timing}]" if line.timing else ""))
        for t in line.ja:
            lines.append(f"  ja  {t.t0:>5}-{t.t1:<5} ms  {t.text:<6} {t.romaji:<10} morae={token_morae(t)}")
        for e in sorted(line.en, key=lambda e: e.reveal_ms):
            lines.append(f"  en  {e.reveal_ms:>5} ms        {e.text}")
        for w in line.warnings:
            lines.append(f"  !!  {w}")
    return "\n".join(lines)


def token_morae(t: JaToken) -> int:
    from .mora import count_morae
    return count_morae(t.romaji, t.kana)

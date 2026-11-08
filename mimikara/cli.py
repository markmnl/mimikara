"""Command line interface.

    mimikara build ep.ja.srt ep.en.srt -o ep.ass [--audio ep.mkv] [--romaji] [--kana] [--all-modes]
    mimikara render ep.mimikara.json -o ep.ass [--romaji] [--kana] [--all-modes]
    mimikara time ep.mimikara.json --audio ep.mkv [--aligner whisperx|mfa]
    mimikara edit ep.mimikara.json [--audio ep.mkv]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from .model import Document


def _say(msg: str) -> None:
    print(msg, file=sys.stderr)


def add_render_args(ap: argparse.ArgumentParser) -> None:
    ap.add_argument("-o", "--output", type=Path, required=True,
                    help="output .ass (with --all-modes: base name, mode is added before .ass)")
    ap.add_argument("--romaji", action="store_true", help="show the romaji line")
    ap.add_argument("--kana", action="store_true", help="show the kana/kanji line")
    ap.add_argument("--color", choices=["pairs", "flash", "none"],
                    help="English colouring (default: flash if English only, else pairs)")
    ap.add_argument("--all-modes", action="store_true",
                    help="write .en/.romaji/.japanese/.all files; mpv cycles them with j")
    ap.add_argument("--font", default=None, help="font name for the styles (default: Noto Sans CJK JP)")
    ap.add_argument("--report", action="store_true", help="print per-word timing to stdout")


def add_llm_args(ap: argparse.ArgumentParser) -> None:
    ap.add_argument("--literal", action="store_true",
                    help="let the LLM rewrite loose English lines so more words link")
    ap.add_argument("--model", default=None, help="Claude model id for alignment")
    ap.add_argument("--effort", default="medium", choices=["low", "medium", "high"],
                    help="model effort for alignment")
    ap.add_argument("--cache", type=Path, default=None, help="alignment cache dir")
    ap.add_argument("--no-llm", action="store_true", help="skip word alignment (English unlinked)")
    ap.add_argument("--batch-size", type=int, default=None, help="lines per LLM request")


def add_audio_args(ap: argparse.ArgumentParser) -> None:
    ap.add_argument("--audio", type=Path, default=None, help="video/audio file for forced alignment")
    ap.add_argument("--aligner", choices=["whisperx", "mfa"], default="whisperx")
    ap.add_argument("--device", default="cpu", help="device for whisperx (cpu, cuda)")


def do_render(doc: Document, args: argparse.Namespace) -> None:
    from . import render as R
    font = args.font or R.DEFAULT_FONT
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if args.all_modes:
        for p in R.write_modes(doc, args.output, args.color, font):
            _say(f"wrote {p}")
    else:
        layers = {"en"} | ({"romaji"} if args.romaji else set()) | ({"kana"} if args.kana else set())
        color = args.color or ("flash" if layers == {"en"} else "pairs")
        args.output.write_text(R.render(doc, layers, color, None, font), encoding="utf-8")
        _say(f"wrote {args.output}")
    if args.report:
        R.prepare(doc)
        print(R.report(doc))


def do_align(doc: Document, args: argparse.Namespace) -> None:
    from . import align as A
    completer = None
    model = args.model or A.DEFAULT_MODEL
    if not args.no_llm:
        try:
            completer = A.ClaudeCompleter(model=model, effort=args.effort)
        except Exception as e:  # missing SDK or credentials
            _say(f"warning: LLM unavailable ({e}); English will be shown unlinked")
    stats = A.align_lines(doc.lines, completer, model=model, literal=args.literal,
                          cache_dir=args.cache or A.default_cache_dir(),
                          batch_size=args.batch_size or A.BATCH_SIZE, progress=_say)
    _say(f"alignment: {stats}")


def do_time(doc: Document, args: argparse.Namespace) -> None:
    from . import forced_align as F
    backend = F.make_backend(args.aligner, device=args.device)
    audio = args.audio
    if audio.suffix.lower() != ".wav":
        wav = audio.with_suffix(".mimikara.wav")
        if not wav.exists():
            _say(f"extracting audio to {wav}")
            F.extract_audio(audio, wav)
        audio = wav
    stats = F.refine(doc, audio, backend, progress=_say)
    _say(f"forced alignment: {stats}")
    unsure = [ln for ln in doc.lines if any("aligner" in w for w in ln.warnings)]
    if unsure:
        _say(f"{len(unsure)} lines need a look (ids: {', '.join(str(ln.id) for ln in unsure[:30])}"
             + (" ..." if len(unsure) > 30 else "") + ")")


def json_path_for(output: Path, explicit: Path | None) -> Path:
    if explicit:
        return explicit
    stem = output.with_suffix("")
    return stem.with_name(f"{stem.name}.mimikara.json")


def cmd_build(args: argparse.Namespace) -> None:
    from .subs import load_cues, merge_same_time
    from .pairing import pair_cues
    from .tokenize import tokenize_line

    ja = merge_same_time(load_cues(args.ja))
    en = merge_same_time(load_cues(args.en))
    _say(f"read {len(ja)} Japanese and {len(en)} English cues")
    lines = pair_cues(ja, en)
    _say(f"paired into {len(lines)} lines")
    doc = Document(title=args.title or args.output.stem, lines=lines,
                   source={"ja": str(args.ja), "en": str(args.en)})
    for ln in doc.lines:
        tokenize_line(ln, args.romaji_engine)
    do_align(doc, args)
    if args.audio:
        do_time(doc, args)
    jp = json_path_for(args.output, args.json)
    doc.save(jp)
    _say(f"wrote {jp} (edit it with: mimikara edit {jp})")
    do_render(doc, args)


def cmd_render(args: argparse.Namespace) -> None:
    doc = Document.load(args.input)
    do_render(doc, args)


def cmd_pair(args: argparse.Namespace) -> None:
    from .subs import load_cues, merge_same_time
    from .pairing import pair_cues
    from .tokenize import tokenize_line
    lines = pair_cues(merge_same_time(load_cues(args.ja)), merge_same_time(load_cues(args.en)))
    doc = Document(title=args.title or args.output.stem, lines=lines)
    for ln in doc.lines:
        tokenize_line(ln, args.romaji_engine)
        from .align import unlinked_tokens
        ln.en = unlinked_tokens(ln)
    doc.save(args.output)
    _say(f"wrote {args.output} with {len(lines)} lines")


def cmd_align(args: argparse.Namespace) -> None:
    doc = Document.load(args.input)
    do_align(doc, args)
    doc.save(args.output or args.input)
    _say(f"wrote {args.output or args.input}")


def cmd_time(args: argparse.Namespace) -> None:
    doc = Document.load(args.input)
    do_time(doc, args)
    doc.save(args.output or args.input)
    _say(f"wrote {args.output or args.input}")


def cmd_edit(args: argparse.Namespace) -> None:
    from .editor.server import serve
    serve(args.input, args.audio, host=args.host, port=args.port, open_browser=not args.no_browser)


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="mimikara", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--version", action="version", version=f"mimikara {__version__}")
    sub = ap.add_subparsers(dest="cmd", required=True)

    b = sub.add_parser("build", help="subtitles in, .ass out (pair, tokenise, align, time, render)")
    b.add_argument("ja", type=Path, help="Japanese .srt/.ass")
    b.add_argument("en", type=Path, help="English .srt/.ass")
    b.add_argument("--json", type=Path, default=None,
                   help="where to write the intermediate JSON (default: <output>.mimikara.json)")
    b.add_argument("--title", default=None)
    b.add_argument("--romaji-engine", choices=["auto", "cutlet", "builtin"], default="auto")
    add_render_args(b); add_llm_args(b); add_audio_args(b)
    b.set_defaults(func=cmd_build)

    r = sub.add_parser("render", help="JSON in, .ass out")
    r.add_argument("input", type=Path)
    add_render_args(r)
    r.set_defaults(func=cmd_render)

    p = sub.add_parser("pair", help="pair + tokenise only; write JSON with unlinked English")
    p.add_argument("ja", type=Path); p.add_argument("en", type=Path)
    p.add_argument("-o", "--output", type=Path, required=True)
    p.add_argument("--title", default=None)
    p.add_argument("--romaji-engine", choices=["auto", "cutlet", "builtin"], default="auto")
    p.set_defaults(func=cmd_pair)

    a = sub.add_parser("align", help="(re)run LLM word alignment on a JSON file")
    a.add_argument("input", type=Path); a.add_argument("-o", "--output", type=Path, default=None)
    add_llm_args(a)
    a.set_defaults(func=cmd_align)

    t = sub.add_parser("time", help="refine word timing with forced alignment on the audio")
    t.add_argument("input", type=Path); t.add_argument("-o", "--output", type=Path, default=None)
    add_audio_args(t)
    t.set_defaults(func=cmd_time)

    e = sub.add_parser("edit", help="open the timing editor in a browser")
    e.add_argument("input", type=Path)
    e.add_argument("--audio", type=Path, default=None)
    e.add_argument("--host", default="127.0.0.1"); e.add_argument("--port", type=int, default=8765)
    e.add_argument("--no-browser", action="store_true")
    e.set_defaults(func=cmd_edit)
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if getattr(args, "cmd", None) == "time" and args.audio is None:
        build_parser().error("time requires --audio")
    try:
        args.func(args)
    except (RuntimeError, ValueError, FileNotFoundError) as e:
        _say(f"error: {e}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

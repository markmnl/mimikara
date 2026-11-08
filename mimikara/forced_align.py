"""Stage 3b: refine token timing with forced alignment on the audio.

Backends (``whisperx`` or ``mfa``) return spans of text with absolute times;
``apply_spans`` maps them onto the line's tokens and writes ``align_ms`` /
``align_score``.  Manual ``start_ms`` anchors are never touched and still win
at render time (see ``timing.anchor_of``).  Lines where the aligner was unsure
get a warning so the editor can list them.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Protocol

from .model import Document, Line

LOW_SCORE = 0.5      # mean char/word score below this => "aligner unsure" warning
PAD_MS = 300         # audio context around each line when slicing


@dataclass
class Span:
    text: str          # one character (whisperx) or one word (mfa)
    start_ms: int      # absolute, in the audio file
    end_ms: int
    score: float = 1.0


class Backend(Protocol):
    name: str

    def align(self, audio: Path, lines: list[Line]) -> dict[int, list[Span]]:
        """Return spans per line id for the lines it could align."""
        ...


# ---------------------------------------------------------------------------
# Audio
# ---------------------------------------------------------------------------

def extract_audio(video: Path, out_wav: Path, start_ms: int | None = None,
                  end_ms: int | None = None, rate: int = 16000) -> Path:
    """Decode (a slice of) the video's audio to 16 kHz mono WAV with ffmpeg."""
    if shutil.which("ffmpeg") is None:
        raise RuntimeError("ffmpeg not found on PATH")
    cmd = ["ffmpeg", "-y", "-loglevel", "error"]
    if start_ms is not None:
        cmd += ["-ss", f"{start_ms / 1000:.3f}"]
    cmd += ["-i", str(video)]
    if end_ms is not None and start_ms is not None:
        cmd += ["-t", f"{(end_ms - start_ms) / 1000:.3f}"]
    cmd += ["-vn", "-ac", "1", "-ar", str(rate), "-f", "wav", str(out_wav)]
    subprocess.run(cmd, check=True)
    return out_wav


# ---------------------------------------------------------------------------
# Mapping spans onto tokens
# ---------------------------------------------------------------------------

_SKIP = re.compile(r"[\s　]")


def _norm(s: str) -> str:
    return _SKIP.sub("", s)


def apply_spans(line: Line, spans: list[Span], backend: str) -> bool:
    """Map spans (chars or words, in order) onto line.ja; returns True if any token was timed."""
    seq = [s for s in spans if _norm(s.text)]
    if not seq:
        return False
    # flatten spans to characters, each char carrying its span's times
    chars: list[tuple[str, Span]] = []
    for s in seq:
        for ch in _norm(s.text):
            chars.append((ch, s))
    ci = 0
    timed = 0
    scores: list[float] = []
    for t in line.ja:
        if t.role == "punct":
            continue
        target = _norm(t.text)
        if not target:
            continue
        # find target starting at ci (allow skipping unmatched chars, e.g. punctuation)
        found = -1
        for k in range(ci, min(len(chars), ci + 8)):
            if "".join(c for c, _ in chars[k:k + len(target)]) == target:
                found = k
                break
        if found < 0:
            t.align_ms = None
            t.align_score = None
            continue
        used = [sp for _, sp in chars[found:found + len(target)]]
        ci = found + len(target)
        t0 = min(sp.start_ms for sp in used) - line.start
        t1 = max(sp.end_ms for sp in used) - line.start
        sc = sum(sp.score for sp in used) / len(used)
        t.align_ms = [int(t0), int(t1)]
        t.align_score = round(sc, 3)
        scores.append(sc)
        timed += 1
    if timed:
        line.timing = backend
        words = [t for t in line.ja if t.role != "punct"]
        mean = sum(scores) / len(scores)
        if mean < LOW_SCORE:
            line.warnings.append(f"aligner unsure (mean score {mean:.2f})")
        if timed < len(words):
            line.warnings.append(f"aligner timed {timed} of {len(words)} words")
    return bool(timed)


def refine(doc: Document, audio: Path, backend: Backend,
           progress: Callable[[str], None] | None = None) -> dict[str, int]:
    lines = [ln for ln in doc.lines if ln.ja]
    if progress:
        progress(f"{backend.name}: aligning {len(lines)} lines")
    result = backend.align(audio, lines)
    stats = {"timed": 0, "untimed": 0, "unsure": 0}
    for ln in lines:
        spans = result.get(ln.id or -1, [])
        before = len(ln.warnings)
        if apply_spans(ln, spans, backend.name):
            stats["timed"] += 1
            if len(ln.warnings) > before:
                stats["unsure"] += 1
        else:
            stats["untimed"] += 1
            ln.warnings.append("forced alignment produced no timing")
    return stats


# ---------------------------------------------------------------------------
# WhisperX backend
# ---------------------------------------------------------------------------

class WhisperXBackend:
    """Uses whisperx's wav2vec2 alignment model for Japanese (character level)."""
    name = "whisperx"

    def __init__(self, device: str = "cpu"):
        try:
            import whisperx  # noqa: F401
        except ImportError as e:
            raise RuntimeError("whisperx is not installed (pip install 'mimikara[whisperx]')") from e
        self.device = device

    def align(self, audio: Path, lines: list[Line]) -> dict[int, list[Span]]:
        import whisperx
        wav = whisperx.load_audio(str(audio))
        model_a, metadata = whisperx.load_align_model(language_code="ja", device=self.device)
        segments = [{"text": _norm(ln.ja_text), "start": ln.start / 1000, "end": ln.end / 1000}
                    for ln in lines]
        result = whisperx.align(segments, model_a, metadata, wav, self.device,
                                return_char_alignments=True)
        out: dict[int, list[Span]] = {}
        for ln, seg in zip(lines, result["segments"]):
            spans = []
            for ch in seg.get("chars", []):
                if ch.get("start") is None:
                    continue
                spans.append(Span(ch["char"], int(ch["start"] * 1000), int(ch["end"] * 1000),
                                  float(ch.get("score", 1.0))))
            if spans:
                out[ln.id or -1] = spans
        return out


# ---------------------------------------------------------------------------
# Montreal Forced Aligner backend
# ---------------------------------------------------------------------------

class MFABackend:
    """Shells out to ``mfa align`` with the ``japanese_mfa`` dictionary/model."""
    name = "mfa"

    def __init__(self, dictionary: str = "japanese_mfa", acoustic_model: str = "japanese_mfa"):
        if shutil.which("mfa") is None:
            raise RuntimeError("mfa not found on PATH (see montreal-forced-aligner docs)")
        self.dictionary = dictionary
        self.acoustic_model = acoustic_model

    def align(self, audio: Path, lines: list[Line]) -> dict[int, list[Span]]:
        out: dict[int, list[Span]] = {}
        with tempfile.TemporaryDirectory(prefix="mimikara-mfa-") as tmp:
            corpus = Path(tmp) / "corpus"
            corpus.mkdir()
            offsets: dict[str, int] = {}
            for ln in lines:
                name = f"line{ln.id:05d}"
                s = max(0, ln.start - PAD_MS)
                extract_audio(audio, corpus / f"{name}.wav", s, ln.end + PAD_MS)
                (corpus / f"{name}.lab").write_text(
                    " ".join(t.text for t in ln.ja if t.role != "punct"), encoding="utf-8")
                offsets[name] = s
            outdir = Path(tmp) / "aligned"
            subprocess.run(["mfa", "align", "--clean", "--quiet", str(corpus), self.dictionary,
                            self.acoustic_model, str(outdir)], check=True)
            for ln in lines:
                name = f"line{ln.id:05d}"
                tg = outdir / f"{name}.TextGrid"
                if not tg.exists():
                    continue
                words = parse_textgrid_words(tg.read_text(encoding="utf-8"))
                out[ln.id or -1] = [Span(w, int(a * 1000) + offsets[name], int(b * 1000) + offsets[name])
                                    for w, a, b in words if w]
        return out


def parse_textgrid_words(text: str) -> list[tuple[str, float, float]]:
    """Minimal TextGrid reader: returns (word, start, end) from the 'words' tier."""
    words: list[tuple[str, float, float]] = []
    tier = None
    cur: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        m = re.match(r'name = "(.*)"', line)
        if m:
            tier = m.group(1)
            continue
        if tier != "words":
            continue
        for key in ("xmin", "xmax", "text"):
            m = re.match(rf"{key} = (.*)", line)
            if m:
                cur[key] = m.group(1).strip().strip('"')
        if "text" in cur and "xmin" in cur and "xmax" in cur:
            if cur["text"] and cur["text"] not in ("", "<eps>", "sil", "spn"):
                words.append((cur["text"], float(cur["xmin"]), float(cur["xmax"])))
            cur = {}
    return words


def make_backend(name: str, **kw) -> Backend:
    if name == "whisperx":
        return WhisperXBackend(device=kw.get("device", "cpu"))
    if name == "mfa":
        return MFABackend()
    raise ValueError(f"unknown aligner {name!r} (use whisperx or mfa)")

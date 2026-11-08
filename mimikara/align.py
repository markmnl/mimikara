"""Stage 2b: English <-> Japanese word links from an LLM.

Each line is sent as numbered Japanese tokens plus the English cue; the model
returns the English split into tokens, each linked to Japanese token indices.
Results are cached per line (keyed on the texts, mode and prompt version) so
re-running a build costs nothing.

"Literal" mode asks the model to first rewrite loose official translations
into a more literal English line, so more words can be linked.  The official
line is kept in ``en_original``.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Protocol

from .model import EnToken, Line

PROMPT_VERSION = "3"
DEFAULT_MODEL = "claude-opus-5-5"
BATCH_SIZE = 12

SYSTEM_PROMPT = """You align Japanese anime/film subtitle lines with their English subtitles, word by word, for a language-learning subtitle renderer.

For every line you receive the Japanese tokens, numbered from 0, with romaji and a role (word / particle / aux / punct), and the English subtitle text.

Return, for each line, the English text split into tokens in its original order, where each token lists the indices of the Japanese tokens that express it.

Rules:
- Keep the English wording exactly: the tokens, joined with single spaces, must reproduce the English text (whitespace-normalised). Do not add, drop, reorder or respell words. Keep punctuation attached to its word ("Pirates!").
- A token may be one word or a short phrase that maps to one Japanese word ("gonna be" -> なる, "King" -> 王). Prefer single words; group only when the words are inseparable.
- Link an English token to a Japanese token only when it carries that meaning. Verb endings, pronouns that are implied in Japanese, articles, and function words with no counterpart get an empty list. Particles (は, を, に...) and auxiliaries are normally not linked; link them only when an English word genuinely renders them (e.g. "to" <-> に for direction, "?" <-> か).
- One Japanese token may be linked from several English tokens, and one English token from several Japanese tokens.
- Unlinked tokens take "attach": "next" (default) or "prev", saying which neighbour they should appear with ("of the" before "Pirates" -> next; "'s" or "!" after a word -> prev).
- Never link punctuation tokens to anything.
"""

LITERAL_INSTRUCTIONS = """Literal mode is ON. Official subtitles are often loose. Before aligning, rewrite the English into a natural but literal translation of the Japanese line that keeps the official line's register and length, so that as many English words as possible have a Japanese counterpart. Put the rewrite in "literal" and align the tokens to THAT text. If the official line is already literal enough, copy it unchanged into "literal".
"""

OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "lines": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer"},
                    "literal": {"type": ["string", "null"]},
                    "en": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "text": {"type": "string"},
                                "ja": {"type": "array", "items": {"type": "integer"}},
                                "attach": {"type": "string", "enum": ["next", "prev"]},
                            },
                            "required": ["text", "ja", "attach"],
                            "additionalProperties": False,
                        },
                    },
                },
                "required": ["id", "literal", "en"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["lines"],
    "additionalProperties": False,
}


class AlignError(Exception):
    pass


# ---------------------------------------------------------------------------
# Prompt building and validation
# ---------------------------------------------------------------------------

def line_prompt(line: Line, n: int) -> str:
    toks = "\n".join(f"  {i}: {t.text}  ({t.romaji}, {t.role})" for i, t in enumerate(line.ja))
    en = line.en_text.replace("\n", " ")
    return f"Line {n}\nJapanese tokens:\n{toks}\nEnglish: {en}\n"


def normalize_ws(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def parse_result(line: Line, result: dict[str, Any], literal: bool) -> tuple[list[EnToken], str | None]:
    """Validate one line's result; returns (tokens, literal text or None)."""
    lit = result.get("literal") if literal else None
    target = normalize_ws(lit) if lit else normalize_ws(line.en_text)
    toks: list[EnToken] = []
    for raw in result.get("en", []):
        text = normalize_ws(str(raw.get("text", "")))
        if not text:
            continue
        ja = sorted({int(j) for j in raw.get("ja", [])})
        for j in ja:
            if not 0 <= j < len(line.ja):
                raise AlignError(f"token {text!r} links to missing Japanese index {j}")
        ja = [j for j in ja if line.ja[j].role != "punct"]
        toks.append(EnToken(text=text, ja=ja, attach=raw.get("attach", "next") or "next"))
    joined = normalize_ws(" ".join(t.text for t in toks))
    if joined.lower() != target.lower():
        raise AlignError(f"tokens {joined!r} do not reproduce the English line {target!r}")
    if joined != target:
        # same letters, different case: trust the original text
        _recase(toks, target)
    return toks, (lit if lit and normalize_ws(lit) != normalize_ws(line.en_text) else None)


def _recase(toks: list[EnToken], target: str) -> None:
    pos = 0
    for t in toks:
        t.text = target[pos:pos + len(t.text)]
        pos += len(t.text) + 1


def restore_breaks(toks: list[EnToken], original: str) -> None:
    """Mark tokens that started a new line in the original cue text."""
    if "\n" not in original:
        return
    words_per_line = [len(ln.split()) for ln in original.split("\n")]
    starts: set[int] = set()
    acc = 0
    for n in words_per_line[:-1]:
        acc += n
        starts.add(acc)
    wi = 0
    for t in toks:
        if wi in starts and wi > 0:
            t.break_before = True
        wi += len(t.text.split())


def unlinked_tokens(line: Line) -> list[EnToken]:
    """Fallback when alignment is unavailable: every word unlinked."""
    toks = [EnToken(text=w, ja=[]) for w in line.en_text.split()]
    restore_breaks(toks, line.en_text)
    return toks


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------

def default_cache_dir() -> Path:
    base = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    return Path(base) / "mimikara" / "align"


class Cache:
    def __init__(self, directory: Path | None):
        self.dir = directory
        if self.dir:
            self.dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def key(line: Line, model: str, literal: bool) -> str:
        payload = json.dumps({
            "v": PROMPT_VERSION, "model": model, "literal": literal,
            "ja": [(t.text, t.role) for t in line.ja],
            "en": normalize_ws(line.en_text),
        }, ensure_ascii=False, sort_keys=True)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def get(self, key: str) -> dict[str, Any] | None:
        if not self.dir:
            return None
        p = self.dir / f"{key}.json"
        if p.exists():
            try:
                return json.loads(p.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                return None
        return None

    def put(self, key: str, value: dict[str, Any]) -> None:
        if self.dir:
            (self.dir / f"{key}.json").write_text(
                json.dumps(value, ensure_ascii=False, indent=1), encoding="utf-8")


# ---------------------------------------------------------------------------
# LLM client
# ---------------------------------------------------------------------------

class Completer(Protocol):
    """Anything that turns (system, user prompt) into the JSON dict of OUTPUT_SCHEMA."""
    def __call__(self, system: str, user: str) -> dict[str, Any]: ...


@dataclass
class ClaudeCompleter:
    model: str = DEFAULT_MODEL
    effort: str = "medium"

    def __post_init__(self) -> None:
        import anthropic
        self.client = anthropic.Anthropic()

    def __call__(self, system: str, user: str) -> dict[str, Any]:
        resp = self.client.beta.messages.create(
            model=self.model,
            max_tokens=16000,
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": user}],
            output_config={"effort": self.effort,
                           "format": {"type": "json_schema", "schema": OUTPUT_SCHEMA}},
        )
        if resp.stop_reason == "refusal":
            raise AlignError("the model declined to align this batch")
        text = next((b.text for b in resp.content if b.type == "text"), "")
        try:
            return json.loads(text)
        except json.JSONDecodeError as e:
            raise AlignError(f"model returned invalid JSON: {e}") from e


@dataclass
class OllamaCompleter:
    """Local model through Ollama's /api/chat with a JSON-schema ``format``."""
    model: str = "qwen3.8"
    host: str = "http://127.0.0.1:11434"
    timeout: float = 1800.0

    def __call__(self, system: str, user: str) -> dict[str, Any]:
        import urllib.request
        body = json.dumps({
            "model": self.model,
            "stream": False,
            "think": False,
            "format": OUTPUT_SCHEMA,
            "options": {"temperature": 0, "num_ctx": 8192},
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        }).encode("utf-8")
        req = urllib.request.Request(f"{self.host.rstrip('/')}/api/chat", data=body,
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except OSError as e:
            raise AlignError(f"ollama request failed: {e}") from e
        text = (data.get("message") or {}).get("content", "")
        try:
            return json.loads(text)
        except json.JSONDecodeError as e:
            raise AlignError(f"model returned invalid JSON: {e}") from e


def make_completer(backend: str, model: str | None = None, effort: str = "medium",
                   host: str | None = None) -> Completer | None:
    """``claude`` (Anthropic API), ``ollama`` (local), or ``none``."""
    if backend == "none":
        return None
    if backend == "claude":
        return ClaudeCompleter(model=model or DEFAULT_MODEL, effort=effort)
    if backend == "ollama":
        kw = {"model": model or OllamaCompleter.model}
        if host:
            kw["host"] = host
        return OllamaCompleter(**kw)
    raise ValueError(f"unknown LLM backend {backend!r}")


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------

def align_lines(lines: list[Line], completer: Completer | None, *, model: str = DEFAULT_MODEL,
                literal: bool = False, cache_dir: Path | None = None, batch_size: int = BATCH_SIZE,
                progress: Callable[[str], None] | None = None) -> dict[str, int]:
    """Fill ``line.en`` for every line that has both texts.  Returns counts."""
    cache = Cache(cache_dir)
    stats = {"cached": 0, "requested": 0, "failed": 0, "skipped": 0}
    todo: list[tuple[Line, str]] = []
    for line in lines:
        if not line.ja or not line.en_text:
            if line.en_text:
                line.en = unlinked_tokens(line)
            stats["skipped"] += 1
            continue
        key = cache.key(line, model, literal)
        hit = cache.get(key)
        if hit is not None and _apply(line, hit, literal):
            stats["cached"] += 1
            continue
        todo.append((line, key))

    if todo and completer is None:
        for line, _ in todo:
            line.en = unlinked_tokens(line)
            line.warnings.append("not aligned: no LLM available")
        stats["failed"] += len(todo)
        return stats

    for b in range(0, len(todo), batch_size):
        batch = todo[b:b + batch_size]
        if progress:
            progress(f"aligning lines {b + 1}-{b + len(batch)} of {len(todo)}")
        system = SYSTEM_PROMPT + (LITERAL_INSTRUCTIONS if literal else "")
        user = "\n".join(line_prompt(line, n) for n, (line, _) in enumerate(batch, 1))
        results = _request(completer, system, user)
        by_id = {int(r.get("id", -1)): r for r in results}
        for n, (line, key) in enumerate(batch, 1):
            r = by_id.get(n)
            ok = r is not None and _apply(line, r, literal, retry=(completer, system, n))
            if ok:
                cache.put(key, r)  # type: ignore[arg-type]
                stats["requested"] += 1
            else:
                line.en = unlinked_tokens(line)
                line.warnings.append("alignment failed; English shown unlinked")
                stats["failed"] += 1
    return stats


def _request(completer: Completer, system: str, user: str) -> list[dict[str, Any]]:
    try:
        data = completer(system, user)
    except AlignError:
        return []
    return list(data.get("lines", [])) if isinstance(data, dict) else []


def _apply(line: Line, result: dict[str, Any], literal: bool, retry=None) -> bool:
    try:
        toks, lit = parse_result(line, result, literal)
    except AlignError as e:
        if retry is not None:
            completer, system, n = retry
            user = (line_prompt(line, 1) + f"\nYour previous answer was rejected: {e}. "
                    "Return the line again, following the rules exactly.")
            results = _request(completer, system, user)
            if results:
                r = results[0]
                r["id"] = 1
                try:
                    toks, lit = parse_result(line, r, literal)
                    result.clear(); result.update(r)
                except AlignError:
                    return False
            else:
                return False
        else:
            return False
    if lit:
        line.en_original = line.en_text
        line.en_text = lit
    else:
        restore_breaks(toks, line.en_text)
    line.en = toks
    return True

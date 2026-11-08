"""Stage 2a: tokenise Japanese with fugashi + UniDic and romanise each token.

UniDic splits very finely (食べ|たく|ない).  Learners want words, so verb and
adjective stems are merged with the auxiliaries that follow them, prefixes
are merged with the noun they attach to, and suffixes/counters are merged
with what they follow.  Particles stay separate (they have no English word
and are drawn in grey).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache

import jaconv

from .model import Cue, JaToken, Line
from .romaji import get_cutlet, kana_to_romaji, romanize

PUNCT_POS = {"補助記号", "記号", "空白"}
PUNCT_MAP = {"。": ".", "、": ",", "！": "!", "？": "?", "…": "...", "「": "\"", "」": "\"",
             "『": "\"", "』": "\"", "・": "-", "〜": "~", "ー": "-"}
PARTICLE_POS = {"助詞"}
AUX_POS = {"助動詞"}
STEM_POS = {"動詞", "形容詞", "形状詞"}
_RENYOU = re.compile(r"連用形")


@lru_cache(maxsize=1)
def get_tagger():
    import fugashi
    return fugashi.Tagger()


@dataclass
class _Word:
    surface: str
    pos1: str
    pos2: str
    cform: str
    kana: str      # pronunciation (katakana), with ー for long vowels
    romaji: str = ""


def _features(w) -> _Word:
    f = w.feature
    pos1 = getattr(f, "pos1", "") or ""
    pos2 = getattr(f, "pos2", "") or ""
    cform = getattr(f, "cForm", "") or ""
    pron = getattr(f, "pron", None) or getattr(f, "kana", None) or ""
    if pron == "*":
        pron = ""
    if not pron and re.fullmatch(r"[ぁ-ゖァ-ヺー]+", w.surface):
        pron = jaconv.hira2kata(w.surface)
    return _Word(w.surface, pos1, pos2, cform, pron)


def _romaji_for(words: list[_Word], raw_words, engine: str) -> None:
    """Fill ``romaji`` on each word, using cutlet when asked for and available."""
    c = get_cutlet() if engine in ("cutlet", "auto") else None
    if c is not None:
        try:
            toks = c.romaji_tokens(raw_words, capitalize=False)
            if len(toks) == len(words):
                for w, t in zip(words, toks):
                    w.romaji = t.surface
                return
        except Exception:
            pass
    for w in words:
        w.romaji = romanize(w.surface, w.kana, use_cutlet=False)


def _is_punct(w: _Word) -> bool:
    return w.pos1 in PUNCT_POS or not w.surface.strip()


def _group(words: list[_Word]) -> list[list[_Word]]:
    groups: list[list[_Word]] = []
    i = 0
    while i < len(words):
        w = words[i]
        g = [w]
        i += 1
        if _is_punct(w):
            groups.append(g)
            continue
        # prefix (お, ご, 大) attaches to what follows
        if w.pos1 == "接頭辞" and i < len(words) and not _is_punct(words[i]):
            g.append(words[i])
            i += 1
            w = words[i - 1]
        head_is_stem = any(x.pos1 in STEM_POS for x in g)
        while i < len(words):
            nxt = words[i]
            prev = g[-1]
            if _is_punct(nxt):
                break
            if nxt.pos1 == "接尾辞":                        # counters, ～さん, ～的
                g.append(nxt); i += 1; continue
            if head_is_stem or prev.pos1 in AUX_POS:
                if nxt.pos1 in AUX_POS:                      # ます, た, ない, たい
                    g.append(nxt); i += 1; continue
                if nxt.pos1 == "助詞" and nxt.pos2 == "接続助詞" and nxt.surface in ("て", "で") \
                        and _RENYOU.search(prev.cform):     # 行っ + て
                    g.append(nxt); i += 1; continue
                if nxt.pos1 in STEM_POS and nxt.pos2 == "非自立可能" and _RENYOU.search(prev.cform) \
                        and prev.pos1 in AUX_POS | STEM_POS:  # 食べたく + ない
                    g.append(nxt); i += 1; continue
            break
        groups.append(g)
    return groups


def _role(g: list[_Word]) -> str:
    if len(g) == 1:
        w = g[0]
        if _is_punct(w):
            return "punct"
        if w.pos1 in PARTICLE_POS:
            return "particle"
        if w.pos1 in AUX_POS:
            return "aux"
    return "word"


def _join_romaji(g: list[_Word]) -> str:
    parts = [w.romaji for w in g]
    out = ""
    for p in parts:
        if out and out[-1] == "n" and p[:1] in "aiueoy":
            out += "'"
        out += p
    return out


def tokenize_text(text: str, romaji_engine: str = "auto") -> list[JaToken]:
    """Japanese text -> word tokens with romaji, kana reading and role."""
    text = text.replace("\n", " ").strip()
    if not text:
        return []
    raw = list(get_tagger()(text))
    words = [_features(w) for w in raw]
    _romaji_for(words, raw, romaji_engine)
    toks: list[JaToken] = []
    for g in _group(words):
        surface = "".join(w.surface for w in g)
        if not surface.strip():
            continue
        role = _role(g)
        if role == "punct":
            r = jaconv.z2h(surface, kana=False, digit=True, ascii=True)
            r = "".join(PUNCT_MAP.get(ch, ch) for ch in r)
            toks.append(JaToken(text=surface, romaji=r, role="punct", pos=g[0].pos1))
            continue
        kana = "".join(w.kana for w in g)
        romaji = _join_romaji(g) if all(w.romaji for w in g) else kana_to_romaji(kana)
        toks.append(JaToken(text=surface, romaji=romaji, role=role, kana=kana, pos=g[0].pos1))
    return toks


def tokenize_line(line: Line, romaji_engine: str = "auto") -> None:
    """Fill ``line.ja`` from ``line.ja_text`` (per source cue when cues were merged)."""
    cues: list[Cue] = line.ja_cues or ([Cue(line.start, line.end, line.ja_text)] if line.ja_text else [])
    toks: list[JaToken] = []
    for n, cue in enumerate(cues):
        ct = tokenize_text(cue.text, romaji_engine)
        if ct and n > 0:
            ct[0].cue_ms = cue.start - line.start
        toks.extend(ct)
    line.ja = toks

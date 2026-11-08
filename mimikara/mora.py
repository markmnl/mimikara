"""Mora counting, used to spread a line's duration over its tokens."""
from __future__ import annotations

import re

LONG_VOWELS = set("āīūēōâîûêô")
VOWELS = set("aiueo")
SMALL_KANA = set("ァィゥェォャュョヮぁぃぅぇぉゃゅょゎ")
KANA_RE = re.compile(r"[ぁ-ゖァ-ヺー]")


def count_morae_kana(kana: str) -> int:
    """Count morae of a kana string: each kana is one mora except small ya/yu/yo
    which merge with the previous kana.  ー and っ count as one each."""
    n = 0
    for ch in kana:
        if ch in SMALL_KANA and ch not in "ァィゥェォぁぃぅぇぉ":
            continue
        if ch in SMALL_KANA:
            # small vowels after a consonant kana (ティ, ファ) merge too
            continue
        if KANA_RE.match(ch):
            n += 1
    return n


def count_morae_romaji(romaji: str) -> int:
    """Rough mora count from Hepburn romaji (macron = long vowel = 2 morae)."""
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
        elif ch.isalpha() and ch == nxt and ch != "n":
            n += 1                      # small っ (doubled consonant)
    return n


def count_morae(romaji: str = "", kana: str = "") -> int:
    if kana:
        return count_morae_kana(kana)
    return count_morae_romaji(romaji)

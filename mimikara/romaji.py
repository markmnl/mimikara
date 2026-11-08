"""Katakana reading -> Hepburn romaji.

cutlet is used when it imports; otherwise (or for readings cutlet cannot
handle) a small built-in converter does the job.  cutlet needs ``mojimoji``,
which has no wheels for recent Pythons, so a shim built on ``jaconv`` is
installed into ``sys.modules`` before importing it.
"""
from __future__ import annotations

import re
import sys
import types

import jaconv

# --- base syllables ---------------------------------------------------------
_BASE = {
    "ア": "a", "イ": "i", "ウ": "u", "エ": "e", "オ": "o",
    "カ": "ka", "キ": "ki", "ク": "ku", "ケ": "ke", "コ": "ko",
    "サ": "sa", "シ": "shi", "ス": "su", "セ": "se", "ソ": "so",
    "タ": "ta", "チ": "chi", "ツ": "tsu", "テ": "te", "ト": "to",
    "ナ": "na", "ニ": "ni", "ヌ": "nu", "ネ": "ne", "ノ": "no",
    "ハ": "ha", "ヒ": "hi", "フ": "fu", "ヘ": "he", "ホ": "ho",
    "マ": "ma", "ミ": "mi", "ム": "mu", "メ": "me", "モ": "mo",
    "ヤ": "ya", "ユ": "yu", "ヨ": "yo",
    "ラ": "ra", "リ": "ri", "ル": "ru", "レ": "re", "ロ": "ro",
    "ワ": "wa", "ヰ": "i", "ヱ": "e", "ヲ": "o", "ン": "n",
    "ガ": "ga", "ギ": "gi", "グ": "gu", "ゲ": "ge", "ゴ": "go",
    "ザ": "za", "ジ": "ji", "ズ": "zu", "ゼ": "ze", "ゾ": "zo",
    "ダ": "da", "ヂ": "ji", "ヅ": "zu", "デ": "de", "ド": "do",
    "バ": "ba", "ビ": "bi", "ブ": "bu", "ベ": "be", "ボ": "bo",
    "パ": "pa", "ピ": "pi", "プ": "pu", "ペ": "pe", "ポ": "po",
    "ヴ": "vu",
    "ァ": "a", "ィ": "i", "ゥ": "u", "ェ": "e", "ォ": "o",
}
_YOUON = {
    "キャ": "kya", "キュ": "kyu", "キョ": "kyo", "シャ": "sha", "シュ": "shu", "ショ": "sho",
    "チャ": "cha", "チュ": "chu", "チョ": "cho", "ニャ": "nya", "ニュ": "nyu", "ニョ": "nyo",
    "ヒャ": "hya", "ヒュ": "hyu", "ヒョ": "hyo", "ミャ": "mya", "ミュ": "myu", "ミョ": "myo",
    "リャ": "rya", "リュ": "ryu", "リョ": "ryo", "ギャ": "gya", "ギュ": "gyu", "ギョ": "gyo",
    "ジャ": "ja", "ジュ": "ju", "ジョ": "jo", "ヂャ": "ja", "ヂュ": "ju", "ヂョ": "jo",
    "ビャ": "bya", "ビュ": "byu", "ビョ": "byo", "ピャ": "pya", "ピュ": "pyu", "ピョ": "pyo",
    "シェ": "she", "チェ": "che", "ジェ": "je", "ティ": "ti", "ディ": "di", "トゥ": "tu", "ドゥ": "du",
    "ファ": "fa", "フィ": "fi", "フェ": "fe", "フォ": "fo", "フュ": "fyu",
    "ウィ": "wi", "ウェ": "we", "ウォ": "wo", "ヴァ": "va", "ヴィ": "vi", "ヴェ": "ve", "ヴォ": "vo",
    "ツァ": "tsa", "ツィ": "tsi", "ツェ": "tse", "ツォ": "tso", "テュ": "tyu", "デュ": "dyu",
    "イェ": "ye", "クァ": "kwa", "グァ": "gwa",
}
_MACRON = {"a": "ā", "i": "ī", "u": "ū", "e": "ē", "o": "ō"}
_VOWELS = "aiueo"


def kana_to_romaji(kana: str, macrons: bool = True) -> str:
    """Katakana (or hiragana) reading -> Hepburn romaji.

    Long vowels become macrons (トウキョウ -> tōkyō).  Syllabic ん before a vowel
    or y gets an apostrophe (シンヨウ -> shin'yō), and small っ doubles the next
    consonant.
    """
    k = jaconv.hira2kata(kana)
    out: list[str] = []
    i = 0
    n = len(k)
    pending_sokuon = False
    while i < n:
        ch = k[i]
        pair = k[i:i + 2]
        if ch == "ッ":
            pending_sokuon = True
            i += 1
            continue
        if ch == "ー":
            if out and out[-1] and out[-1][-1] in _VOWELS:
                prev = out[-1]
                out[-1] = prev[:-1] + (_MACRON[prev[-1]] if macrons else prev[-1])
            i += 1
            continue
        if pair in _YOUON:
            syl = _YOUON[pair]
            i += 2
        elif ch in _BASE:
            syl = _BASE[ch]
            i += 1
        else:
            syl = ch
            i += 1
        if pending_sokuon and syl and syl[0] not in _VOWELS:
            first = "t" if syl.startswith("ch") else syl[0]
            syl = first + syl
            pending_sokuon = False
        # syllabic n before a vowel / y
        if out and out[-1] == "n" and syl and syl[0] in _VOWELS + "y":
            out[-1] = "n'"
        # long vowels: oo/ou -> ō, uu -> ū, ee/ei stay separate except ee -> ē
        if out and syl in ("u", "o", "a", "i", "e") and out[-1]:
            last = out[-1][-1]
            if (last == "o" and syl in ("o", "u")) or (last == "u" and syl == "u") \
                    or (last == "a" and syl == "a") or (last == "e" and syl == "e") \
                    or (last == "i" and syl == "i"):
                if macrons and not _is_morpheme_edge(out):
                    out[-1] = out[-1][:-1] + _MACRON[last]
                    continue
        out.append(syl)
    if pending_sokuon:
        out.append("")
    return "".join(out)


def _is_morpheme_edge(out: list[str]) -> bool:
    # we only romanise one token at a time, so no boundary information is lost
    return False


# --- cutlet -----------------------------------------------------------------

def _install_mojimoji_shim() -> None:
    if "mojimoji" in sys.modules:
        return
    try:
        import mojimoji  # noqa: F401
        return
    except ImportError:
        pass
    shim = types.ModuleType("mojimoji")

    def zen_to_han(text: str, kana: bool = True, digit: bool = True, ascii: bool = True) -> str:
        return jaconv.z2h(text, kana=kana, digit=digit, ascii=ascii)

    def han_to_zen(text: str, kana: bool = True, digit: bool = True, ascii: bool = True) -> str:
        return jaconv.h2z(text, kana=kana, digit=digit, ascii=ascii)

    shim.zen_to_han = zen_to_han  # type: ignore[attr-defined]
    shim.han_to_zen = han_to_zen  # type: ignore[attr-defined]
    sys.modules["mojimoji"] = shim


_cutlet = None
_cutlet_tried = False


def get_cutlet():
    """Return a cutlet.Cutlet instance, or None when cutlet is unavailable."""
    global _cutlet, _cutlet_tried
    if _cutlet_tried:
        return _cutlet
    _cutlet_tried = True
    try:
        _install_mojimoji_shim()
        import cutlet
        c = cutlet.Cutlet(use_foreign_spelling=False)
        c.use_wo = False          # を is spoken "o"
        _cutlet = c
    except Exception:
        _cutlet = None
    return _cutlet


_LATIN = re.compile(r"^[A-Za-z' \-]+$")


def romanize(surface: str, kana: str, use_cutlet: bool = True) -> str:
    """Romaji for one token given its surface form and katakana reading."""
    if not kana and _LATIN.match(surface or ""):
        return surface
    if use_cutlet:
        c = get_cutlet()
        if c is not None and kana:
            try:
                r = c.map_kana(kana) if hasattr(c, "map_kana") else ""
            except Exception:
                r = ""
            if r:
                return r
    if kana:
        return kana_to_romaji(kana)
    return jaconv.kana2alphabet(jaconv.kata2hira(surface)) if surface else ""

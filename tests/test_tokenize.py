import pytest

pytest.importorskip("fugashi")

from mimikara.tokenize import tokenize_text, tokenize_line
from mimikara.model import Line, Cue
from mimikara.romaji import kana_to_romaji


def test_basic_tokens_and_roles():
    toks = tokenize_text("海賊王におれはなる！")
    assert [t.text for t in toks] == ["海賊", "王", "に", "おれ", "は", "なる", "！"]
    assert [t.role for t in toks] == ["word", "word", "particle", "word", "particle", "word", "punct"]
    assert toks[4].romaji == "wa" and toks[2].romaji == "ni" and toks[-1].romaji == "!"
    assert toks[0].kana == "カイゾク"


def test_verb_and_adjective_chains_are_merged():
    toks = tokenize_text("昨日、東京へ行きました。食べたくないよ。")
    assert [t.text for t in toks] == ["昨日", "、", "東京", "へ", "行きました", "。", "食べたくない", "よ", "。"]
    r = {t.text: t.romaji for t in toks}
    assert r["行きました"] == "ikimashita" and r["食べたくない"] == "tabetakunai" and r["へ"] == "e"


def test_prefix_suffix_and_te_form():
    toks = tokenize_text("お茶を三人で飲んでいる")
    assert [t.text for t in toks] == ["お茶", "を", "三人", "で", "飲んで", "いる"]
    assert toks[1].romaji == "o"


def test_builtin_romaji_engine():
    toks = tokenize_text("東京へ行きました", romaji_engine="builtin")
    assert [t.romaji for t in toks] == ["tōkyō", "e", "ikimashita"]


@pytest.mark.parametrize("kana,romaji", [
    ("カイゾク", "kaizoku"), ("トウキョウ", "tōkyō"), ("シンヨウ", "shin'yō"), ("キップ", "kippu"),
    ("マッチャ", "matcha"), ("ビール", "bīru"), ("オネエサン", "onēsan"), ("センセイ", "sensei"),
    ("ファン", "fan"), ("ティー", "tī"), ("ハ", "ha"),
])
def test_kana_to_romaji(kana, romaji):
    assert kana_to_romaji(kana) == romaji


def test_tokenize_line_sets_cue_anchor_for_merged_cues():
    ln = Line(start=4000, end=7000, ja_text="昨日、\n東京へ行きました。",
              ja_cues=[Cue(4000, 5200, "昨日、"), Cue(5200, 7000, "東京へ行きました。")])
    tokenize_line(ln)
    assert ln.ja[0].cue_ms is None
    first_of_second = next(t for t in ln.ja if t.text == "東京")
    assert first_of_second.cue_ms == 1200

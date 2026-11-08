import re

from mimikara.model import Document, Line, JaToken, EnToken
from mimikara.render import render, write_modes, ass_color, assign_colors, prepare, PALETTE


def test_ass_color():
    assert ass_color("FFC94D") == "&H4DC9FF&"


def test_english_only_default_has_no_romaji_and_flashes(luffy_doc):
    out = render(luffy_doc, {"en"}, "flash")
    assert "[Script Info]" in out and "Style: English," in out
    dialogues = [l for l in out.splitlines() if l.startswith("Dialogue:")]
    assert len(dialogues) == 1 and ",English,," in dialogues[0]
    # every word fades in at its reveal time and the newest word glows then settles to white
    assert dialogues[0].count("\\alpha&HFF&\\t(") == 5
    assert "\\1c&H7AE2FF&" in dialogues[0] and "\\1c&HFFFFFF&" in dialogues[0]


def test_words_never_move_or_scale(luffy_doc):
    out = render(luffy_doc, {"en", "romaji", "kana"}, "pairs")
    assert not re.search(r"\\(fsc[xy]|pos|move|fs\d|org|fr[xyz]?)\b", out)
    # the English line keeps reading order regardless of reveal order
    en = [l for l in out.splitlines() if ",English,," in l][0]
    text = re.sub(r"\{[^}]*\}", "", en.split(",", 9)[9])
    assert text == "I'm gonna be King of the Pirates!"


def test_layers_and_pair_colours(luffy_doc):
    out = render(luffy_doc, {"en", "romaji", "kana"}, "pairs")
    styles = [l.split(",")[3] for l in out.splitlines() if l.startswith("Dialogue:")]
    assert styles == ["Romaji", "Kana", "English"]
    prepare(luffy_doc)
    ln = luffy_doc.lines[0]
    # the English word and its Japanese word share a colour; particles have none
    king = next(e for e in ln.en if e.text == "King")
    assert king.color == ln.ja[1].color
    assert ln.ja[2].color is None and ln.ja[2].role == "particle"
    romaji = [l for l in out.splitlines() if ",Romaji,," in l][0]
    assert "\\1c&H7A6F6B&\\t(1000,1120,\\1c&H" + ass_color(king.color)[2:-1] + "&)}ō" in romaji


def test_timing_tags_are_relative_to_cue_start():
    ln = Line(start=10_000, end=13_000, ja=[JaToken("a", "a", kana="ア"), JaToken("b", "bi", kana="ビ")],
              en=[EnToken("A", [0]), EnToken("B", [1])])
    doc = Document(title="t", lines=[ln])
    out = render(doc, {"en"}, "none")
    en = [l for l in out.splitlines() if ",English,," in l][0]
    assert en.startswith("Dialogue: 0,0:00:10.00,0:00:13.00,English")
    assert "\\t(0,120,\\alpha&H00&)" in en and "\\t(1500,1620,\\alpha&H00&)" in en


def test_line_breaks_and_escaping():
    ln = Line(start=0, end=1000, ja=[JaToken("a", "a", kana="ア")],
              en=[EnToken("Yesterday", [0]), EnToken("I {went}", [], break_before=True)])
    out = render(Document(lines=[ln]), {"en"}, "none")
    en = [l for l in out.splitlines() if ",English,," in l][0]
    assert "Yesterday\\N{" in en and "I (went)" in en


def test_write_modes(tmp_path, luffy_doc):
    paths = write_modes(luffy_doc, tmp_path / "ep01.ass")
    names = sorted(p.name for p in paths)
    assert names == ["ep01.all.ass", "ep01.en.ass", "ep01.japanese.ass", "ep01.romaji.ass"]
    allf = (tmp_path / "ep01.all.ass").read_text()
    styles = [l.split(",")[3] for l in allf.splitlines() if l.startswith("Dialogue:")]
    assert styles == ["Romaji", "Kana", "English", "EnglishSolo"]
    enf = (tmp_path / "ep01.en.ass").read_text()
    assert ",Romaji,," not in enf and ",Kana,," not in enf


def test_colour_reuse_for_shared_japanese_token():
    ln = Line(start=0, end=1000, ja=[JaToken("a", "a", kana="ア")],
              en=[EnToken("x", [0]), EnToken("y", [0])])
    assign_colors(ln)
    assert ln.en[0].color == ln.en[1].color == PALETTE[0]


def test_english_only_line_without_japanese_renders():
    ln = Line(start=0, end=1000, ja=[], en=[EnToken("(door", []), EnToken("slams)", [])])
    out = render(Document(lines=[ln]), {"en", "romaji"}, "pairs")
    assert out.count("Dialogue:") == 1

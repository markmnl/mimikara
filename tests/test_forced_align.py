from pathlib import Path

from mimikara.model import Document, Line, JaToken
from mimikara import forced_align as F
from mimikara.timing import time_japanese


def line():
    ja = [JaToken("海賊", "kaizoku", kana="カイゾク"), JaToken("王", "ō", kana="オー"),
          JaToken("に", "ni", role="particle", kana="ニ"), JaToken("なる", "naru", kana="ナル"),
          JaToken("！", "!", role="punct")]
    return Line(id=1, start=10_000, end=14_000, ja=ja, ja_text="海賊王になる！")


def char_spans(text, start, step, score=0.9):
    return [F.Span(ch, start + i * step, start + (i + 1) * step, score) for i, ch in enumerate(text)]


def test_apply_char_spans_sets_align_ms_relative_to_line():
    ln = line()
    ok = F.apply_spans(ln, char_spans("海賊王になる", 10_200, 100), "whisperx")
    assert ok and ln.timing == "whisperx"
    assert ln.ja[0].align_ms == [200, 400] and ln.ja[1].align_ms == [400, 500]
    assert ln.ja[3].align_ms == [600, 800] and ln.ja[4].align_ms is None
    assert ln.warnings == []
    time_japanese(ln)
    assert [(t.t0, t.t1) for t in ln.ja[:4]] == [(200, 400), (400, 500), (500, 600), (600, 800)]


def test_apply_word_spans_and_unsure_warning():
    ln = line()
    spans = [F.Span("海賊", 10_100, 10_500, 0.3), F.Span("王", 10_500, 10_700, 0.2),
             F.Span("に", 10_700, 10_800, 0.4), F.Span("なる", 10_800, 11_200, 0.3)]
    assert F.apply_spans(ln, spans, "mfa")
    assert ln.ja[0].align_ms == [100, 500] and ln.ja[3].align_ms == [800, 1200]
    assert any("unsure" in w for w in ln.warnings)


def test_partial_spans_warn_and_manual_anchor_still_wins():
    ln = line()
    ln.ja[1].start_ms = 450        # manual anchor
    spans = char_spans("海賊", 10_200, 100) + char_spans("なる", 10_600, 100)   # 王 and に missing
    assert F.apply_spans(ln, spans, "whisperx")
    assert ln.ja[1].align_ms is None and ln.ja[3].align_ms == [600, 800]
    assert any("timed 2 of 4" in w for w in ln.warnings)
    time_japanese(ln)
    assert ln.ja[1].t0 == 450 and ln.ja[0].t1 == 450


def test_refine_with_fake_backend():
    class Fake:
        name = "fake"

        def align(self, audio, lines):
            return {1: char_spans("海賊王になる", 10_200, 100)}

    ln1, ln2 = line(), line()
    ln2.id = 2
    doc = Document(lines=[ln1, ln2])
    stats = F.refine(doc, Path("x.wav"), Fake())
    assert stats == {"timed": 1, "untimed": 1, "unsure": 0}
    assert ln1.timing == "fake" and ln2.warnings


def test_parse_textgrid_words():
    tg = '''File type = "ooTextFile"
Object class = "TextGrid"
item []:
    item [1]:
        class = "IntervalTier"
        name = "words"
        intervals [1]:
            xmin = 0.0
            xmax = 0.31
            text = ""
        intervals [2]:
            xmin = 0.31
            xmax = 0.8
            text = "海賊"
        intervals [3]:
            xmin = 0.8
            xmax = 1.0
            text = "王"
    item [2]:
        class = "IntervalTier"
        name = "phones"
        intervals [1]:
            xmin = 0.31
            xmax = 0.5
            text = "k"
'''
    assert F.parse_textgrid_words(tg) == [("海賊", 0.31, 0.8), ("王", 0.8, 1.0)]

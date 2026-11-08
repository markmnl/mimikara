from mimikara.model import Line, JaToken, EnToken
from mimikara.timing import time_line, time_japanese, anchor_of


def mk(*toks, start=0, end=4000, speech=(None, None)):
    ja = [JaToken(t, r, role=role, kana=k) for t, r, role, k in toks]
    return Line(start=start, end=end, ja=ja, speech_start_ms=speech[0], speech_end_ms=speech[1])


def test_mora_proportional():
    ln = mk(("海賊", "kaizoku", "word", "カイゾク"), ("王", "ō", "word", "オー"),
            ("に", "ni", "particle", "ニ"), ("なる", "naru", "word", "ナル"), speech=(200, 2000))
    time_japanese(ln)
    # 9 morae over 1800ms = 200ms each
    assert [(t.t0, t.t1) for t in ln.ja] == [(200, 1000), (1000, 1400), (1400, 1600), (1600, 2000)]


def test_manual_anchor_wins_over_everything():
    ln = mk(("a", "a", "word", "ア"), ("b", "bi", "word", "ビ"), ("c", "shi", "word", "シ"), speech=(0, 3000))
    ln.ja[1].align_ms = [1500, 2000]
    ln.ja[1].align_score = 0.99
    ln.ja[1].cue_ms = 900
    ln.ja[1].start_ms = 2400
    assert anchor_of(ln.ja[1]) == 2400
    time_japanese(ln)
    assert ln.ja[0].t0 == 0 and ln.ja[0].t1 == 2400
    assert ln.ja[1].t0 == 2400 and ln.ja[1].t1 == 2700
    assert ln.ja[2].t0 == 2700 and ln.ja[2].t1 == 3000


def test_alignment_beats_cue_and_low_score_is_ignored():
    ln = mk(("a", "a", "word", "ア"), ("b", "bi", "word", "ビ"), speech=(0, 2000))
    ln.ja[1].cue_ms = 500
    ln.ja[1].align_ms = [1200, 1900]
    ln.ja[1].align_score = 0.9
    assert anchor_of(ln.ja[1]) == 1200
    ln.ja[1].align_score = 0.1
    assert anchor_of(ln.ja[1]) == 500


def test_first_token_anchor_replaces_speech_start_and_aligned_end_used():
    ln = mk(("a", "a", "word", "ア"), ("b", "bi", "word", "ビ"), speech=(0, 4000))
    ln.ja[0].align_ms = [300, 600]
    ln.ja[0].align_score = 1.0
    ln.ja[1].align_ms = [700, 1000]
    ln.ja[1].align_score = 1.0
    time_japanese(ln)
    assert (ln.ja[0].t0, ln.ja[0].t1) == (300, 700)
    assert (ln.ja[1].t0, ln.ja[1].t1) == (700, 1000)


def test_out_of_order_anchor_is_dropped():
    ln = mk(("a", "a", "word", "ア"), ("b", "bi", "word", "ビ"), ("c", "shi", "word", "シ"), speech=(0, 3000))
    ln.ja[1].start_ms = 2000
    ln.ja[2].start_ms = 1000     # earlier than the previous anchor: ignored
    time_japanese(ln)
    assert ln.ja[1].t0 == 2000 and ln.ja[2].t0 == 2500


def test_punctuation_rides_with_previous_word():
    ln = mk(("なる", "naru", "word", "ナル"), ("！", "!", "punct", ""), speech=(0, 1000))
    time_japanese(ln)
    assert (ln.ja[1].t0, ln.ja[1].t1) == (0, 1000)


def test_english_reveal_and_attach(luffy_doc):
    ln = luffy_doc.lines[0]
    time_line(ln)
    by_text = {e.text: e.reveal_ms for e in ln.en}
    assert by_text["Pirates!"] == 200 and by_text["King"] == 1000
    assert by_text["I'm"] == 1600 and by_text["gonna be"] == 2200
    assert by_text["of the"] == by_text["Pirates!"]        # attach: next


def test_attach_prev_and_fallback():
    ln = Line(start=0, end=2000, ja=[JaToken("a", "a", kana="ア"), JaToken("b", "bi", kana="ビ")],
              en=[EnToken("x", [1]), EnToken("'s", [], attach="prev"), EnToken("y", [0])],
              speech_start_ms=0, speech_end_ms=2000)
    time_line(ln)
    assert ln.en[1].reveal_ms == ln.en[0].reveal_ms == 1000
    ln2 = Line(start=0, end=2000, ja=[JaToken("a", "a", kana="ア")], en=[EnToken("only", [])],
               speech_start_ms=250)
    time_line(ln2)
    assert ln2.en[0].reveal_ms == 250


def test_multi_link_reveals_at_earliest():
    ln = Line(start=0, end=2000, ja=[JaToken("a", "a", kana="ア"), JaToken("b", "bi", kana="ビ")],
              en=[EnToken("ab", [0, 1])])
    time_line(ln)
    assert ln.en[0].reveal_ms == 0

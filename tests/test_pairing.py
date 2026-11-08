from mimikara.model import Cue
from mimikara.pairing import pair_cues, group_cues, overlaps
from mimikara.subs import load_cues


def c(start, end, text):
    return Cue(start, end, text)


def test_one_to_one():
    lines = pair_cues([c(1000, 3000, "ja1"), c(4000, 6000, "ja2")],
                      [c(1100, 3100, "en1"), c(4000, 6000, "en2")])
    assert [(l.ja_text, l.en_text) for l in lines] == [("ja1", "en1"), ("ja2", "en2")]
    assert lines[0].start == 1000 and lines[0].end == 3100
    assert lines[0].id == 1 and lines[1].id == 2


def test_merge_split_japanese_cues():
    # Japanese is cut into two cues where English is one
    lines = pair_cues([c(4000, 5200, "昨日、"), c(5200, 7000, "東京へ行きました。")],
                      [c(4000, 7000, "Yesterday I went to Tokyo.")])
    assert len(lines) == 1
    ln = lines[0]
    assert ln.ja_text == "昨日、\n東京へ行きました。"
    assert len(ln.ja_cues) == 2 and ln.ja_cues[1].start == 5200
    assert ln.en_cues == []
    assert (ln.start, ln.end) == (4000, 7000)


def test_merge_split_english_cues():
    lines = pair_cues([c(0, 4000, "ja")], [c(0, 2000, "en a"), c(2000, 4000, "en b")])
    assert len(lines) == 1
    assert lines[0].en_text == "en a\nen b"
    assert len(lines[0].en_cues) == 2


def test_group_splits_when_cues_pair_cleanly():
    # two JA and two EN cues that touch each other but clearly pair 1:1
    ja = [c(0, 2000, "a"), c(2000, 4000, "b")]
    en = [c(100, 2050, "A"), c(2050, 4100, "B")]
    lines = pair_cues(ja, en)
    assert [(l.ja_text, l.en_text) for l in lines] == [("a", "A"), ("b", "B")]


def test_tiny_overlap_is_ignored():
    # English cue spills 50ms into the next Japanese cue: should not merge
    ja = [c(0, 2000, "a"), c(2000, 4000, "b")]
    en = [c(0, 2050, "A"), c(2100, 4000, "B")]
    assert not overlaps(ja[1], en[0])
    lines = pair_cues(ja, en)
    assert len(lines) == 2


def test_unmatched_cues_become_single_sided_lines():
    lines = pair_cues([c(0, 1000, "ja only")], [c(5000, 6000, "(door slams)")])
    assert len(lines) == 2
    assert lines[0].en_text == "" and lines[0].warnings
    assert lines[1].ja_text == "" and lines[1].warnings


def test_fixture_files(fixtures):
    lines = pair_cues(load_cues(fixtures / "sample.ja.srt"), load_cues(fixtures / "sample.en.srt"))
    texts = [(l.ja_text.replace("\n", "|"), l.en_text.replace("\n", "|")) for l in lines]
    assert texts == [
        ("海賊王におれはなる！", "I'm gonna be King of the Pirates!"),
        ("昨日、|東京へ行きました。", "Yesterday|I went to Tokyo."),
        ("食べたくないよ。", "I don't want to eat it."),
        ("おはよう。", "Good morning."),
        ("元気？", "How are you?"),
        ("", "(door slams)"),
        ("さようなら。", ""),
    ]


def test_group_cues_order():
    groups = group_cues([c(0, 1000, "a"), c(3000, 4000, "b")], [c(500, 1500, "A")])
    assert len(groups) == 2
    assert groups[0].ja[0].text == "a" and groups[0].en[0].text == "A"
    assert groups[1].en == []

from mimikara.subs import parse_srt, parse_ass, load_cues, merge_same_time, clean_text


def test_parse_srt_strips_tags_and_keeps_breaks(fixtures):
    cues = load_cues(fixtures / "sample.en.srt")
    assert len(cues) == 6
    assert cues[0].start == 1000 and cues[0].end == 3500
    assert cues[0].text == "I'm gonna be King of the Pirates!"
    assert cues[1].text == "Yesterday\nI went to Tokyo."


def test_parse_srt_without_index_and_bom():
    text = "\ufeff00:00:01,000 --> 00:00:02,000\nhello\n\n2\n00:00:03.000 --> 00:00:04.000\nworld\n"
    cues = parse_srt(text)
    assert [(c.start, c.end, c.text) for c in cues] == [(1000, 2000, "hello"), (3000, 4000, "world")]


def test_parse_ass():
    text = """[Script Info]
Title: x

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:01.00,0:00:02.50,Default,,0,0,0,,{\\an8}こんにちは\\N世界
Comment: 0,0:00:01.00,0:00:02.50,Default,,0,0,0,,ignored
Dialogue: 0,0:00:00.50,0:00:01.00,Default,,0,0,0,,first, with commas
"""
    cues = parse_ass(text)
    assert [(c.start, c.end, c.text) for c in cues] == [
        (500, 1000, "first, with commas"), (1000, 2500, "こんにちは\n世界")]


def test_merge_same_time():
    from mimikara.model import Cue
    cues = [Cue(0, 1000, "a"), Cue(0, 1000, "b"), Cue(2000, 3000, "c")]
    merged = merge_same_time(cues)
    assert [c.text for c in merged] == ["a\nb", "c"]


def test_clean_text():
    assert clean_text("<i>hi</i>  there {\\b1}x") == "hi there x"

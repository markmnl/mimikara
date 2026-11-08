import json

import pytest

from mimikara.model import Document, Line, JaToken, EnToken, parse_time, ass_time, srt_time


@pytest.mark.parametrize("s,ms", [
    ("0:00:00.50", 500), ("00:01:02,345", 62345), ("1:02:03.04", 3723040),
    ("02:03.5", 123500), ("5.25", 5250), (1234, 1234),
])
def test_parse_time(s, ms):
    assert parse_time(s) == ms


def test_ass_time_round_trip():
    assert ass_time(3723040) == "1:02:03.04"
    assert ass_time(parse_time("0:00:00.50")) == "0:00:00.50"
    assert srt_time(62345) == "00:01:02,345"


def test_document_json_round_trip(tmp_path, luffy_doc):
    p = tmp_path / "x.json"
    luffy_doc.save(p)
    again = Document.load(p)
    assert again.title == luffy_doc.title
    assert again.lines == luffy_doc.lines
    data = json.loads(p.read_text())
    assert data["lines"][0]["ja"][2] == {"text": "に", "romaji": "ni", "role": "particle"}
    assert data["lines"][0]["en"][3] == {"text": "of the", "ja": []}   # attach=next is the default


def test_bad_link_rejected():
    with pytest.raises(ValueError):
        Line.from_json({"start": "0:00:00.00", "end": "0:00:01.00",
                        "ja": [{"text": "a", "romaji": "a"}], "en": [{"text": "x", "ja": [3]}]})


def test_optional_fields_survive():
    t = JaToken("食べ", "tabe", kana="タベ", start_ms=120, align_ms=[100, 300], align_score=0.9, cue_ms=50)
    d = t.to_json()
    assert d["start_ms"] == 120 and d["align_ms"] == [100, 300] and d["cue_ms"] == 50
    assert JaToken.from_json(d) == t
    e = EnToken("x", [], attach="prev", break_before=True)
    assert EnToken.from_json(e.to_json()) == e

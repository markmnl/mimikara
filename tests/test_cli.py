import json

import pytest

pytest.importorskip("fugashi")

from mimikara.cli import main


def test_build_end_to_end_without_llm(tmp_path, fixtures, capsys):
    out = tmp_path / "ep.ass"
    rc = main(["build", str(fixtures / "sample.ja.srt"), str(fixtures / "sample.en.srt"),
               "-o", str(out), "--no-llm", "--all-modes", "--cache", str(tmp_path / "cache")])
    assert rc == 0
    for name in ("ep.en.ass", "ep.romaji.ass", "ep.japanese.ass", "ep.all.ass", "ep.mimikara.json"):
        assert (tmp_path / name).exists(), name
    doc = json.loads((tmp_path / "ep.mimikara.json").read_text())
    assert len(doc["lines"]) == 7
    first = doc["lines"][0]
    assert [t["text"] for t in first["ja"]][:2] == ["海賊", "王"]
    assert first["en_text"] == "I'm gonna be King of the Pirates!"
    japanese = (tmp_path / "ep.japanese.ass").read_text()
    assert japanese.count("Dialogue:") == 5 * 3 + 1 + 2   # 5 full lines, EN-only line, JA-only line


def test_render_from_json(tmp_path):
    from pathlib import Path
    src = Path(__file__).resolve().parent.parent / "examples" / "luffy.json"
    out = tmp_path / "luffy.ass"
    assert main(["render", str(src), "-o", str(out), "--romaji", "--kana", "--report"]) == 0
    text = out.read_text()
    assert ",Romaji,," in text and ",Kana,," in text and ",English,," in text


def test_time_requires_audio(tmp_path):
    with pytest.raises(SystemExit):
        main(["time", "x.json"])

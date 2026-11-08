import json

import pytest

from mimikara.model import Line, JaToken
from mimikara import align as A


def luffy_line():
    ja = [JaToken("海賊", "kaizoku"), JaToken("王", "ō"), JaToken("に", "ni", role="particle"),
          JaToken("おれ", "ore"), JaToken("は", "wa", role="particle"), JaToken("なる", "naru"),
          JaToken("！", "!", role="punct")]
    return Line(start=0, end=4000, ja=ja, ja_text="海賊王におれはなる！", en_text="I'm gonna be King of the Pirates!")


GOOD = {"id": 1, "literal": None, "en": [
    {"text": "I'm", "ja": [3], "attach": "next"}, {"text": "gonna be", "ja": [5], "attach": "next"},
    {"text": "King", "ja": [1], "attach": "next"}, {"text": "of the", "ja": [], "attach": "next"},
    {"text": "Pirates!", "ja": [0, 6], "attach": "next"}]}


class FakeCompleter:
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    def __call__(self, system, user):
        self.calls.append((system, user))
        return self.replies.pop(0)


def test_parse_result_links_and_drops_punct_links():
    ln = luffy_line()
    toks, lit = A.parse_result(ln, GOOD, literal=False)
    assert lit is None
    assert [t.text for t in toks] == ["I'm", "gonna be", "King", "of the", "Pirates!"]
    assert toks[-1].ja == [0]          # link to the "!" token is discarded
    assert toks[0].ja == [3]


def test_parse_result_rejects_rewritten_text():
    ln = luffy_line()
    bad = {"id": 1, "literal": None, "en": [{"text": "I will be King", "ja": [], "attach": "next"}]}
    with pytest.raises(A.AlignError):
        A.parse_result(ln, bad, literal=False)
    bad = {"id": 1, "literal": None, "en": [{"text": "x", "ja": [99], "attach": "next"}]}
    with pytest.raises(A.AlignError):
        A.parse_result(ln, bad, literal=False)


def test_align_lines_uses_completer_and_cache(tmp_path):
    ln = luffy_line()
    fake = FakeCompleter([{"lines": [GOOD]}])
    stats = A.align_lines([ln], fake, cache_dir=tmp_path)
    assert stats["requested"] == 1 and len(fake.calls) == 1
    assert "Line 1" in fake.calls[0][1] and "0: 海賊" in fake.calls[0][1]
    assert [e.ja for e in ln.en] == [[3], [5], [1], [], [0]]
    cached = list(tmp_path.glob("*.json"))
    assert len(cached) == 1 and json.loads(cached[0].read_text())["en"][2]["text"] == "King"

    # second run: no LLM call needed
    ln2 = luffy_line()
    fake2 = FakeCompleter([])
    stats = A.align_lines([ln2], fake2, cache_dir=tmp_path)
    assert stats["cached"] == 1 and fake2.calls == []
    assert ln2.en == ln.en


def test_align_retries_once_then_falls_back(tmp_path):
    ln = luffy_line()
    bad = {"id": 1, "literal": None, "en": [{"text": "nope", "ja": [], "attach": "next"}]}
    fake = FakeCompleter([{"lines": [bad]}, {"lines": [bad]}])
    stats = A.align_lines([ln], fake, cache_dir=tmp_path)
    assert stats["failed"] == 1 and len(fake.calls) == 2
    assert "rejected" in fake.calls[1][1]
    assert [e.text for e in ln.en] == ["I'm", "gonna", "be", "King", "of", "the", "Pirates!"]
    assert all(e.ja == [] for e in ln.en) and ln.warnings
    assert list(tmp_path.glob("*.json")) == []       # failures are not cached


def test_no_llm_leaves_words_unlinked():
    ln = luffy_line()
    stats = A.align_lines([ln], None, cache_dir=None)
    assert stats["failed"] == 1 and all(e.ja == [] for e in ln.en)


def test_literal_mode_rewrites_english(tmp_path):
    ln = luffy_line()
    reply = {"id": 1, "literal": "I will become the Pirate King!", "en": [
        {"text": "I", "ja": [3], "attach": "next"}, {"text": "will become", "ja": [5], "attach": "next"},
        {"text": "the", "ja": [], "attach": "next"}, {"text": "Pirate", "ja": [0], "attach": "next"},
        {"text": "King!", "ja": [1], "attach": "next"}]}
    fake = FakeCompleter([{"lines": [reply]}])
    A.align_lines([ln], fake, literal=True, cache_dir=tmp_path)
    assert "Literal mode is ON" in fake.calls[0][0]
    assert ln.en_original == "I'm gonna be King of the Pirates!"
    assert ln.en_text == "I will become the Pirate King!"
    assert [e.text for e in ln.en] == ["I", "will become", "the", "Pirate", "King!"]
    # cache key differs from non-literal mode
    assert A.Cache.key(ln, A.DEFAULT_MODEL, True) != A.Cache.key(ln, A.DEFAULT_MODEL, False)


def test_batching_and_line_breaks(tmp_path):
    lines = []
    for i in range(3):
        l = luffy_line()
        l.en_text = "I'm gonna be King\nof the Pirates!"
        lines.append(l)
    replies = [{"lines": [dict(GOOD, id=1), dict(GOOD, id=2)]}, {"lines": [dict(GOOD, id=1)]}]
    fake = FakeCompleter(replies)
    stats = A.align_lines(lines, fake, cache_dir=tmp_path, batch_size=2)
    assert stats["requested"] == 3 and len(fake.calls) == 2
    assert [e.break_before for e in lines[0].en] == [False, False, False, True, False]


def test_ollama_completer_request_shape(monkeypatch):
    import io, urllib.request
    seen = {}

    class Resp(io.BytesIO):
        def __enter__(self): return self
        def __exit__(self, *a): return False

    def fake_urlopen(req, timeout=None):
        seen["url"] = req.full_url
        seen["body"] = json.loads(req.data)
        return Resp(json.dumps({"message": {"role": "assistant", "content": json.dumps({"lines": [GOOD]})}}).encode())

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    c = A.make_completer("ollama", "qwen-test", host="http://localhost:11434/")
    out = c("SYS", "USER")
    assert out["lines"][0]["en"][2]["text"] == "King"
    assert seen["url"] == "http://localhost:11434/api/chat"
    assert seen["body"]["model"] == "qwen-test" and seen["body"]["format"] == A.OUTPUT_SCHEMA
    assert seen["body"]["messages"][0] == {"role": "system", "content": "SYS"}
    assert A.make_completer("none") is None


def test_claude_completer_turns_api_errors_into_align_errors(monkeypatch, tmp_path):
    anthropic = pytest.importorskip("anthropic")
    import httpx2 as httpx
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    c = A.ClaudeCompleter(model="claude-opus-5-5")
    resp = httpx.Response(400, request=httpx.Request("POST", "https://api.anthropic.com/v1/messages"),
                          json={"error": {"type": "invalid_request_error", "message": "credit balance too low"}})
    def boom(system, user):
        raise anthropic.BadRequestError("credit balance too low", response=resp, body=None)
    monkeypatch.setattr(c, "_create", boom)
    with pytest.raises(A.AlignError, match="400"):
        c("SYS", "USER")
    # the driver degrades to unlinked English with a warning instead of crashing
    ln = luffy_line()
    stats = A.align_lines([ln], c, cache_dir=tmp_path, progress=lambda m: None)
    assert stats["failed"] == 1 and "400" in ln.warnings[0]

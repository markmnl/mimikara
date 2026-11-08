import json
import struct
import threading
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from pathlib import Path

from mimikara.editor import server as S
from mimikara.model import Document


def write_wav(path: Path, seconds: float = 2.0, rate: int = 8000) -> None:
    import array, math
    n = int(seconds * rate)
    samples = array.array("h", (int(20000 * math.sin(i / 10) * (1 if i > n // 2 else 0.1)) for i in range(n)))
    data = samples.tobytes()
    hdr = b"RIFF" + struct.pack("<I", 36 + len(data)) + b"WAVE" + b"fmt " + struct.pack(
        "<IHHIIHH", 16, 1, 1, rate, rate * 2, 2, 16) + b"data" + struct.pack("<I", len(data))
    path.write_bytes(hdr + data)


def test_read_wav_and_peaks(tmp_path):
    wav = tmp_path / "a.wav"
    write_wav(wav)
    state = S.State(tmp_path / "x.json", wav)
    state.prepare_audio()
    rate, samples = state.pcm()
    assert rate == 8000 and len(samples) == 16000
    peaks = S.peaks_for(state, 0, 2000, buckets=4)
    assert len(peaks) == 4 and peaks[0] < 0.2 and peaks[3] > 0.5


def test_computed_line(luffy_doc):
    d = S.computed_line(luffy_doc.lines[0])
    assert d["ja"][0]["t0"] == 200 and d["ja"][1]["t0"] == 1000
    assert next(e for e in d["en"] if e["text"] == "King")["reveal_ms"] == 1000


def test_http_round_trip(tmp_path, luffy_doc):
    jp = tmp_path / "ep.json"
    luffy_doc.save(jp)
    wav = tmp_path / "a.wav"
    write_wav(wav)
    state = S.State(jp, wav)
    state.prepare_audio()
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), S.make_handler(state))
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    try:
        port = httpd.server_address[1]
        conn = HTTPConnection("127.0.0.1", port)
        conn.request("GET", "/api/doc")
        r = conn.getresponse()
        doc = json.loads(r.read())
        assert r.status == 200 and doc["has_audio"] and doc["lines"][0]["ja"][1]["t0"] == 1000

        conn.request("GET", "/")
        assert b"<html" in conn.getresponse().read().lower()

        conn.request("GET", f"/api/peaks?start=500&end=1500")
        peaks = json.loads(conn.getresponse().read())
        assert peaks["start"] == 0 and len(peaks["peaks"]) == 600

        # drag a token: set a manual anchor, retime, save
        line = doc["lines"][0]
        line["ja"][1]["start_ms"] = 1300
        conn.request("POST", "/api/retime", body=json.dumps(line), headers={"Content-Type": "application/json"})
        retimed = json.loads(conn.getresponse().read())
        assert retimed["ja"][1]["t0"] == 1300 and retimed["ja"][0]["t1"] == 1300

        doc["lines"][0] = retimed
        conn.request("PUT", "/api/doc", body=json.dumps(doc), headers={"Content-Type": "application/json"})
        assert json.loads(conn.getresponse().read())["ok"]
        saved = Document.load(jp)
        assert saved.lines[0].ja[1].start_ms == 1300
        assert "t0" not in json.loads(jp.read_text())["lines"][0]["ja"][0]
    finally:
        httpd.shutdown()

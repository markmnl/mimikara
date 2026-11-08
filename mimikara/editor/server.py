"""A tiny HTTP server for the timing editor.

GET  /                 the editor page
GET  /api/doc          the document, with computed t0/t1/reveal_ms per token
PUT  /api/doc          save the document (whole JSON)
POST /api/retime       body: one line's JSON -> that line with recomputed times
GET  /api/audio        the audio as 16 kHz mono WAV (extracted with ffmpeg)
GET  /api/peaks?line=N waveform peaks for the line's window (plus padding)
"""
from __future__ import annotations

import json
import struct
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from ..model import Document, Line
from ..timing import time_line

STATIC = Path(__file__).parent / "static"
PEAK_PAD_MS = 600


class State:
    def __init__(self, json_path: Path, audio: Path | None):
        self.json_path = json_path
        self.audio = audio
        self.wav: Path | None = None
        self.lock = threading.Lock()
        self._pcm: tuple[int, "array"] | None = None  # type: ignore[name-defined]

    def prepare_audio(self) -> None:
        if not self.audio:
            return
        if self.audio.suffix.lower() == ".wav":
            self.wav = self.audio
        else:
            from ..forced_align import extract_audio
            wav = self.audio.with_suffix(".mimikara.wav")
            if not wav.exists():
                extract_audio(self.audio, wav)
            self.wav = wav

    def pcm(self):
        """(sample_rate, samples as array('h')) decoded from the WAV."""
        if self._pcm is None and self.wav:
            self._pcm = read_wav(self.wav)
        return self._pcm


def read_wav(path: Path):
    import array
    data = path.read_bytes()
    if data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        raise ValueError("not a WAV file")
    pos = 12
    rate, channels, bits = 16000, 1, 16
    samples = array.array("h")
    while pos + 8 <= len(data):
        cid = data[pos:pos + 4]
        size = struct.unpack("<I", data[pos + 4:pos + 8])[0]
        body = data[pos + 8:pos + 8 + size]
        if cid == b"fmt ":
            _, channels, rate = struct.unpack("<HHI", body[:8])
            bits = struct.unpack("<H", body[14:16])[0]
        elif cid == b"data":
            if bits != 16:
                raise ValueError("only 16-bit WAV is supported")
            samples = array.array("h")
            samples.frombytes(body[:len(body) - len(body) % 2])
            if channels > 1:
                samples = array.array("h", samples[::channels])
            break
        pos += 8 + size + (size & 1)
    return rate, samples


def peaks_for(state: State, start_ms: int, end_ms: int, buckets: int = 600) -> list[float]:
    pcm = state.pcm()
    if not pcm:
        return []
    rate, samples = pcm
    a = max(0, int(start_ms * rate / 1000))
    b = min(len(samples), int(end_ms * rate / 1000))
    if b <= a:
        return []
    out = []
    step = (b - a) / buckets
    for i in range(buckets):
        s = a + int(i * step)
        e = max(s + 1, a + int((i + 1) * step))
        chunk = samples[s:e]
        out.append(max(abs(x) for x in chunk) / 32768 if len(chunk) else 0.0)
    return out


def computed_line(line: Line) -> dict[str, Any]:
    time_line(line)
    d = line.to_json()
    for t, tj in zip(line.ja, d["ja"]):
        tj["t0"], tj["t1"] = t.t0, t.t1
    for e, ej in zip(line.en, d["en"]):
        ej["reveal_ms"] = e.reveal_ms
    return d


def make_handler(state: State):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):  # quiet
            pass

        def _send(self, code: int, body: bytes, ctype: str = "application/json") -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, obj: Any, code: int = 200) -> None:
            self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"))

        def do_GET(self):
            url = urlparse(self.path)
            if url.path in ("/", "/index.html"):
                self._send(200, (STATIC / "index.html").read_bytes(), "text/html; charset=utf-8")
            elif url.path == "/editor.js":
                self._send(200, (STATIC / "editor.js").read_bytes(), "text/javascript; charset=utf-8")
            elif url.path == "/api/doc":
                with state.lock:
                    doc = Document.load(state.json_path)
                    data = doc.to_json()
                    data["lines"] = [computed_line(ln) for ln in doc.lines]
                    data["has_audio"] = state.wav is not None
                    data["path"] = str(state.json_path)
                self._json(data)
            elif url.path == "/api/peaks":
                q = parse_qs(url.query)
                s = int(q.get("start", ["0"])[0]) - PEAK_PAD_MS
                e = int(q.get("end", ["0"])[0]) + PEAK_PAD_MS
                self._json({"start": max(0, s), "end": e, "peaks": peaks_for(state, max(0, s), e)})
            elif url.path == "/api/audio":
                if not state.wav:
                    self._json({"error": "no audio"}, 404)
                    return
                self._send(200, state.wav.read_bytes(), "audio/wav")
            else:
                self._send(404, b"not found", "text/plain")

        def _body(self) -> Any:
            n = int(self.headers.get("Content-Length", "0"))
            return json.loads(self.rfile.read(n).decode("utf-8")) if n else None

        def do_PUT(self):
            if urlparse(self.path).path != "/api/doc":
                self._send(404, b"not found", "text/plain")
                return
            data = self._body()
            data.pop("has_audio", None)
            data.pop("path", None)
            doc = Document.from_json(data)
            with state.lock:
                doc.save(state.json_path)
            self._json({"ok": True, "lines": len(doc.lines)})

        def do_POST(self):
            if urlparse(self.path).path != "/api/retime":
                self._send(404, b"not found", "text/plain")
                return
            line = Line.from_json(self._body())
            self._json(computed_line(line))

    return Handler


def serve(json_path: Path, audio: Path | None, host: str = "127.0.0.1", port: int = 8765,
          open_browser: bool = True) -> None:
    Document.load(json_path)  # fail early on a bad file
    state = State(json_path, audio)
    state.prepare_audio()
    httpd = ThreadingHTTPServer((host, port), make_handler(state))
    url = f"http://{host}:{port}/"
    print(f"mimikara editor: {url}  (editing {json_path}; Ctrl-C to stop)")
    if open_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()

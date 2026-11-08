"""Check that mpv cycles the --all-modes files with `j`.

    mimikara build ... -o ep01.ass --all-modes
    python tools/mpv_cycle_check.py ep01.mkv ep01.en.ass ep01.romaji.ass ep01.japanese.ass [--flatpak]

Starts mpv headless with the three files as external subtitle tracks, sends
`j` over the JSON IPC socket, prints the active track after each press and
writes press<N>.png screenshots (with subtitles burned in) next to the video.
"""
import json, os, socket, subprocess, sys, tempfile, time

args = [a for a in sys.argv[1:] if not a.startswith("--")]
video, subs = args[0], args[1:]
outdir = os.path.dirname(os.path.abspath(video))
sock = os.path.join(tempfile.mkdtemp(dir=outdir, prefix=".mpv-"), "mpv.sock")
mpv = ["flatpak", "run", f"--filesystem={outdir}", "io.mpv.Mpv"] if "--flatpak" in sys.argv else ["mpv"]
cmd = mpv + ["--no-config", "--vo=null", "--ao=null", "--pause", "--idle=yes", "--force-window=no",
             "--screenshot-sw=yes", f"--input-ipc-server={sock}", "--sub-files=" + ":".join(subs), video]
p = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
for _ in range(200):
    if os.path.exists(sock):
        break
    time.sleep(0.1)
s = socket.socket(socket.AF_UNIX)
s.connect(sock)
f = s.makefile("rwb", buffering=0)
rid = 0


def send(*command):
    global rid
    rid += 1
    f.write((json.dumps({"command": list(command), "request_id": rid}) + "\n").encode())
    while True:
        line = f.readline()
        if not line:
            raise SystemExit("mpv closed the connection")
        d = json.loads(line)
        if d.get("request_id") == rid:
            return d.get("data")


time.sleep(1.5)
send("set_property", "time-pos", float(os.environ.get("MPV_CHECK_TIME", "2.3")))
time.sleep(0.5)
tracks = [(t["id"], os.path.basename(t.get("external-filename", ""))) for t in send("get_property", "track-list") if t["type"] == "sub"]
print("sub tracks:", tracks)
for n in range(len(subs) + 1):
    sid = send("get_property", "sid")
    name = os.path.basename(send("get_property", "current-tracks/sub/external-filename") or "") if sid else None
    print(f"after {n} presses of j: sid={sid} file={name}")
    send("screenshot-to-file", os.path.join(outdir, f"press{n}.png"), "subtitles")
    send("keypress", "j")      # j = cycle subtitle track in mpv's default input.conf
    time.sleep(0.4)
send("quit")
p.wait(timeout=10)

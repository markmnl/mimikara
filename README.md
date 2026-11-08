# mimikara

Subtitles for Japanese anime and film where **each English word appears at the
moment its Japanese counterpart is spoken**, while the finished line still reads
left to right in normal English. You watch with English subtitles and pick up
Japanese word order and vocabulary incidentally. Optional romaji and kana lines
light up word by word with colours that pair each Japanese word with its English
meaning.

```
 Japanese subs ─┐
                ├─► 1. pair lines ─► 2. word alignment ─► 3. word timing ─► 4. render .ass ─► player
 English subs  ─┘        (by time)       (LLM, cached)      (morae / forced     (colour & alpha   (mpv / VLC /
                                                             alignment / manual)  only, no reflow)  browser overlay)
```

The JSON written between stages (`ep.mimikara.json`, see `examples/luffy.json`) is
the contract: stages 1-3 produce it, the renderer consumes it, the timing editor
edits it.

## Install

```sh
python -m venv .venv && . .venv/bin/activate
pip install -e '.[dev]'          # fugashi + unidic-lite + anthropic + pytest
pip install cutlet               # optional, preferred romaniser (needs a C++ compiler for mojimoji)
```

Needs `ffmpeg` on PATH for anything audio related. Forced alignment is optional:
`pip install whisperx` or install Montreal Forced Aligner (`mfa`) with its
`japanese_mfa` models. On Python 3.14 whisperx's pinned `ctranslate2==4.4.0` has
no wheel; install it as `pip install --no-deps whisperx && pip install
"ctranslate2>=4.6" faster-whisper torch torchaudio transformers pandas nltk
pyannote.audio` instead. The first `--audio` run downloads the Japanese wav2vec2
alignment model (about 1.2 GB) from Hugging Face.

## Build subtitles for an episode

```sh
export ANTHROPIC_API_KEY=...     # or `ant auth login`
mimikara build ep01.ja.srt ep01.en.srt -o ep01.ass                 # English only (default)
mimikara build ep01.ja.srt ep01.en.srt -o ep01.ass --romaji --kana # + romaji and Japanese lines
mimikara build ep01.ja.srt ep01.en.srt -o ep01.ass --all-modes     # ep01.en/.romaji/.japanese/.all.ass
mimikara build ep01.ja.srt ep01.en.srt -o ep01.ass --audio ep01.mkv --all-modes   # + forced alignment
mimikara build ... --literal     # LLM rewrites loose official lines so more words link
mimikara build ... --llm ollama  # use a local model through Ollama instead of the Claude API
mimikara build ... --no-llm      # skip alignment (English appears whole, at speech start)
```

What happens:

1. **Pair** Japanese and English cues by time overlap. Where the two files segment
   differently, cues are merged on one side (sub-cue boundaries become timing
   anchors) or a group is split back into 1:1 pairs when it matches cleanly.
   Cues with no counterpart become one-sided lines and get a warning.
2. **Tokenise** Japanese with fugashi + UniDic. Verb/adjective stems are merged with
   their auxiliaries (食べたくない is one word), prefixes and counters are merged,
   particles stay separate. Romaji comes from cutlet when installed, else a
   built-in Hepburn converter (`--romaji-engine builtin` for macron style).
3. **Align** with an LLM: Claude (`claude-opus-5-5` by default, structured JSON
   output) or, with `--llm ollama [--model qwen3.8]`, a local model through Ollama's
   JSON-schema `format`. Results are cached per line in `~/.cache/mimikara/align/`
   so reruns are free. Answers that do not reproduce the English text are rejected
   and retried once.
4. **Time** each Japanese word: speech window spread by mora count; with `--audio`,
   forced alignment (WhisperX character alignment or MFA word alignment) writes
   `align_ms` per token and flags lines where the aligner was unsure. Manual
   `start_ms` anchors always win.
5. **Render** `.ass` with `\t` alpha/colour animations only. Words are laid out from
   the start and never move or scale.

With `--all-modes`, load the files in mpv (`mpv ep01.mkv --sub-files=ep01.en.ass:ep01.romaji.ass:ep01.japanese.ass`)
and press `j` to cycle English-only → + romaji → + Japanese. `ep01.all.ass` holds
every style and is what the browser extension consumes. `tools/mpv_cycle_check.py`
drives a headless mpv over its IPC socket, presses `j` and screenshots each state.

Other commands: `mimikara render ep01.mimikara.json -o ep01.ass [--romaji --kana --all-modes --report]`,
`mimikara align ep01.mimikara.json [--literal]`, `mimikara time ep01.mimikara.json --audio ep01.mkv --aligner mfa`.

## Fix timing by hand

```sh
mimikara edit ep01.mimikara.json --audio ep01.mkv
```

opens a local page: line list (filter with `!` for warnings), waveform, Japanese
words as draggable blocks. Drag a word to set its `start_ms` (a pin marks a manual
anchor), double-click to clear it, drag the `[` `]` brackets for the speech window,
`space` plays the line, `s` saves back to the JSON. Then `mimikara render` again.

## Watch on a streaming site

`extension/` is a Chrome extension (Manifest V3) that overlays a prebuilt `.all.ass`
on the page's `<video>` with JASSUB, with on-screen toggles for the romaji and
Japanese lines. See `extension/README.md`.

## JSON contract

```jsonc
{ "title": "...", "lines": [ {
    "id": 1, "start": "0:00:00.50", "end": "0:00:04.50",
    "ja_text": "海賊王におれはなる！", "en_text": "I'm gonna be King of the Pirates!",
    "speech_start_ms": 200, "speech_end_ms": 2800,            // optional, relative to start
    "ja": [ { "text": "海賊", "romaji": "kaizoku", "kana": "カイゾク" },
            { "text": "王", "romaji": "ō", "start_ms": 1000 },  // manual anchor
            { "text": "に", "romaji": "ni", "role": "particle" }, ... ],
    "en": [ { "text": "I'm", "ja": [3] }, { "text": "of the", "ja": [], "attach": "next" }, ... ]
} ] }
```

Token timing fields, by priority: `start_ms` (manual) > `align_ms` + `align_score`
(forced alignment) > `cue_ms` (merged sub-cue boundary) > mora estimate.

## Development

```sh
pytest                                   # cue pairing, mora counting, timing, .ass output, alignment, editor
mimikara render examples/luffy.json -o out/luffy.ass --romaji --kana
ffmpeg -f lavfi -i color=c=0x203040:s=1280x720:d=5 -vf subtitles=out/luffy.ass -ss 2.3 -frames:v 1 out/frame.png
```

`prototype/mimikara.py` is the original single-file prototype kept for reference.

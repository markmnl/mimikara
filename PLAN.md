# mimikara — plan

Subtitles where each English word appears at the moment its Japanese counterpart
is spoken, while the finished line still reads left to right in normal English.
Colour pairs each Japanese word with its English meaning.

## Pipeline

```
 Japanese subs ─┐
                ├─► 1. pair lines ─► 2. word alignment ─► 3. word timing ─► 4. render .ass ─► player
 English subs  ─┘        (by time)       (which EN word       (when is each       (mimikara.py)     (mpv / VLC /
                                          ↔ which JA word)     JA word spoken)                       browser overlay)
```

| Stage | Input | Output | Approach |
|---|---|---|---|
| 1. Pair lines | `.ja.srt/.ass`, `.en.srt/.ass` | list of (JA line, EN line, start, end) | Overlap of cue times; merge/split cues when the two files segment differently. |
| 2. Align words | JA line + EN line | tokens with links (the `ja: [...]` field) | Tokenise JA (fugashi + UniDic gives words + readings → romaji via cutlet/pykakasi). Ask an LLM to return the links as JSON. Optional "literal mode": LLM rewrites the EN line to be closer to the JA so more words link. |
| 3. Time words | JA tokens + cue times (+ audio) | `t0/t1` per JA token | **v1:** mora-proportional estimate (done). **v2:** forced alignment on the audio (WhisperX / MFA Japanese model) to get real word times. Manual `start_ms` anchors always win. |
| 4. Render | aligned + timed JSON | `.ass` | Done in prototype: romaji/kana light up in speech order; EN words fade in out of order but are pre-laid-out so nothing moves. |
| 5. Play | video + `.ass` | — | **v1:** mpv/VLC with a local file. **v2:** browser extension overlay using JASSUB (libass in WebAssembly), synced to the page's `<video>` element. |

The JSON in `examples/luffy.json` is the contract between stages: stages 2–3 produce it,
stage 4 consumes it, and a timing editor can edit it.

## Milestones

- **M0 — prototype (done).** One hand-written line → `.ass` → rendered preview.
- **M1 — one episode, offline (done: `mimikara build`).** CLI: `mimikara build ep.ja.srt ep.en.srt -o ep.mimikara.ass`.
  Stages 1, 2 (LLM), 3 (estimate), 4. Cache LLM results per line so reruns are free.
- **M2 — real timing (done: `--audio` / `mimikara time`, WhisperX or MFA backends).** Extract audio from a local video, run forced alignment on the
  Japanese text, write `start_ms` anchors. Report lines where the aligner was unsure.
- **M3 — timing editor (done: `mimikara edit`).** Small web page: waveform + tokens, drag a token to fix its time,
  save back to the JSON. This is the "a little bit of work to put timing right" step.
- **M4 — streaming overlay (done: `extension/`).** Chrome extension that loads a prebuilt `.mimikara.ass`
  and renders it over Crunchyroll's player with JASSUB. Timing comes from the
  subtitle files, not from capturing the stream's audio.
- **M5 — learning features.** Per-word "known" list (stop colouring words you know,
  later hide the English for them), spaced-repetition export of words you met.

## Design decisions so far

- **English-only is the default** (incidental learning). Romaji and kana lines are opt-in:
  `--romaji`, `--kana`. In English-only mode the newest word glows briefly then turns white
  (`--color flash`), since colour pairs mean nothing without the Japanese line.
- **Switching modes while watching:** `--all-modes` writes `.en`, `.romaji`, `.japanese`
  files; mpv cycles them with `j`. The browser overlay (M4) will get a toggle that
  filters events by style (`English` / `Romaji` / `Kana`) before rendering.

- **Unlinked English words** (`of the`) ride along with a neighbour; `attach: "next" | "prev"`.
- **Particles** (`ni`, `wa`) have no English word; shown lit in grey in the romaji line.
- **No scaling/moving effects** on words: scaling changes widths and makes the line reflow.
  Colour and opacity only.
- **One English token may link to several Japanese tokens** (reveal at the earliest);
  several English tokens may link to one Japanese token.

## Open questions

- Official subtitles are often loose translations. How often does alignment find
  nothing useful, and is "literal mode" better for learning than official subs?
- Two-line English cues: handled (`break_before` on a token renders `\N`).
- Overlapping speakers in one cue.
- Sources for Japanese subtitles (e.g. Jimaku) and their licensing; keep generated
  files for personal use rather than redistributing them.

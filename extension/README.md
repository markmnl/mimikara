# mimikara Chrome extension

Overlays a prebuilt `.ass` from `mimikara build --all-modes` (use the `*.all.ass` file)
on any page with a `<video>` and renders it with [JASSUB](https://github.com/ThaUnknown/jassub)
(libass compiled to WebAssembly).  Toggles switch the romaji and Japanese lines on
and off without reloading; when both are off the English line uses the "flash"
colouring from the `.all.ass` file.

## Install

1. `chrome://extensions` → enable *Developer mode* → *Load unpacked* → pick this `extension/` folder.
2. Open the streaming page, start the video, click the mimikara toolbar button.
3. *Load .ass file…* and pick `ep01.all.ass`. The file and the toggles are remembered.

Timing comes from the subtitle file, so if the stream has a different offset
from your subtitle source, adjust *offset* (seconds).

## How it works

`content.js` floats an `overlay.html` iframe (extension origin, so JASSUB's workers
and WASM load without cross-origin trouble) over the largest video on the page and
posts the video's current time every frame.  `overlay.js` filters `Dialogue` events
by style and calls JASSUB's `manualRender`.

`vendor/` holds JASSUB 2.5.36 bundled with esbuild (`jassub.js`, `jassub-main-worker.js`),
its WASM builds, its default font, and Droid Sans Fallback (Apache 2.0) for Japanese glyphs.
To rebuild: `npm i jassub@2.5.36 esbuild && npx esbuild node_modules/jassub/dist/jassub.js
--bundle --format=esm --outfile=vendor/jassub.js` and the same for `dist/worker/worker.js`
→ `vendor/jassub-main-worker.js`, then copy `dist/wasm/*` and `dist/default.woff2`.

## Testing without installing

`dev/dev.html` mirrors `content.js` on a local page: `python -m http.server 8777`
from the `extension/` folder, open `http://localhost:8777/dev/dev.html`.

`dev/test_extension.py` loads the real extension unpacked in Chromium through
Playwright, injects it on `dev/video.html` (or a URL you pass), loads
`dev/luffy.all.ass`, toggles the layers, checks persistence across a reload and
writes screenshots: `pip install playwright && playwright install chromium`, then
`python extension/dev/test_extension.py out/`.

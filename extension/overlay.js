// Runs inside the extension-origin iframe.  Receives the .ass text, layer
// toggles and the video's time from content.js and renders with JASSUB.
import JASSUB from './vendor/jassub.js';

const canvas = document.getElementById('c');
// chrome.runtime is absent in the dev harness (dev/dev.html); fall back to relative URLs
const ext = (p) => (globalThis.chrome?.runtime?.getURL ? chrome.runtime.getURL(p) : new URL(p, import.meta.url).href);
const parent = window.parent;
const say = (msg) => parent.postMessage({ mimikara: 'overlay', ...msg }, '*');

const st = { jassub: null, ass: '', romaji: false, kana: false, english: true, offset: 0, fontData: null,
             family: 'Liberation Sans', size: { width: 0, height: 0, videoWidth: 1280, videoHeight: 720 },
             t: 0, lastDrawn: -1, paused: true };

function filterAss(text, { romaji, kana, english }) {
  // Drop Dialogue events whose style is switched off.  Files written with
  // --all-modes carry both English variants: "EnglishSolo" (flash colouring,
  // for English-only viewing) and "English" (colours paired with the Japanese line).
  const hasSolo = /^Dialogue:[^,]*,[^,]*,[^,]*,EnglishSolo,/m.test(text);
  const solo = hasSolo && !romaji && !kana;
  return text.split(/\r?\n/).filter((line) => {
    if (!line.startsWith('Dialogue:')) return true;
    const style = line.split(',', 4)[3];
    if (style === 'Romaji') return romaji;
    if (style === 'Kana') return kana;
    if (style === 'EnglishSolo') return english && solo;
    if (style === 'English') return english && !solo;
    return true;
  }).join('\n');
}

// Point every style at a font libass will actually find: the user's font (by
// its real family name) or the bundled Liberation Sans for Latin, with Droid
// Sans Fallback as libass's fallback font for kana and kanji.
function retargetFonts(text, family) {
  return text.replace(/^(Style:\s*[^,]*,)[^,]*/gm, `$1${family}`);
}

function trackText() {
  return retargetFonts(filterAss(st.ass, st), st.family);
}

function fonts() {
  const list = [ext('vendor/DroidSansFallbackFull.ttf')];
  if (st.fontData) list.unshift(st.fontData);
  return list;
}

// Family name from a TrueType/OpenType font's "name" table (nameID 1).
function fontFamilyName(bytes) {
  try {
    const dv = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
    let off = 0;
    if (dv.getUint32(0) === 0x74746366) off = dv.getUint32(12);          // 'ttcf': first font
    const numTables = dv.getUint16(off + 4);
    for (let i = 0; i < numTables; i++) {
      const rec = off + 12 + i * 16;
      const tag = String.fromCharCode(dv.getUint8(rec), dv.getUint8(rec + 1), dv.getUint8(rec + 2), dv.getUint8(rec + 3));
      if (tag !== 'name') continue;
      const t = dv.getUint32(rec + 8);
      const count = dv.getUint16(t + 2), strOff = t + dv.getUint16(t + 4);
      let best = null;
      for (let k = 0; k < count; k++) {
        const r = t + 6 + k * 12;
        const platform = dv.getUint16(r), nameId = dv.getUint16(r + 6), len = dv.getUint16(r + 8), so = dv.getUint16(r + 10);
        if (nameId !== 1) continue;
        const raw = new Uint8Array(bytes.buffer, bytes.byteOffset + strOff + so, len);
        const text = platform === 3 || platform === 0 ? new TextDecoder('utf-16be').decode(raw) : new TextDecoder('latin1').decode(raw);
        if (platform === 3 && dv.getUint16(r + 4) === 0x409) return text;  // Windows / English
        best = best ?? text;
      }
      return best;
    }
  } catch (e) { /* not a parseable sfnt (e.g. woff2) */ }
  return null;
}

function dataUrlBytes(url) {
  const bin = atob(url.slice(url.indexOf(',') + 1));
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out;
}

async function create() {
  if (st.jassub) { await st.jassub.destroy(); st.jassub = null; }
  if (!st.ass) { say({ type: 'status', text: 'load a .ass file to start' }); return; }
  st.family = (st.fontData && fontFamilyName(dataUrlBytes(st.fontData))) || 'Liberation Sans';
  const content = trackText();
  st.jassub = new JASSUB({
    canvas,
    subContent: content,
    workerUrl: ext('vendor/jassub-main-worker.js'),
    wasmUrl: ext('vendor/jassub-worker.wasm'),
    modernWasmUrl: ext('vendor/jassub-worker-modern.wasm'),
    wasmWorkerUrl: ext('vendor/jassub-worker.js'),
    modernWasmWorkerUrl: ext('vendor/jassub-worker-modern.js'),
    fonts: fonts(),
    availableFonts: {
      'liberation sans': ext('vendor/default.woff2'),
      'droid sans fallback': ext('vendor/DroidSansFallbackFull.ttf'),
    },
    defaultFont: 'droid sans fallback',
    queryFonts: false,
    timeOffset: st.offset,
    prescaleFactor: 1,
  });
  await st.jassub.ready;
  st.lastDrawn = -1;
  applySize();
  say({ type: 'status', text: `rendering (${content.split('\nDialogue:').length - 1} events, font ${st.family})` });
}

function applySize() {
  const { width, height, videoWidth, videoHeight } = st.size;
  if (!st.jassub || !st.jassub.renderer || !width || !height) return;
  canvas.style.width = width + 'px'; canvas.style.height = height + 'px';
  st.jassub.manualRender({ mediaTime: st.t, expectedDisplayTime: performance.now(), width: videoWidth, height: videoHeight }, true).catch(() => {});
}

window.addEventListener('message', async (ev) => {
  const m = ev.data; if (!m || !m.type) return;
  if (m.type === 'config') {
    if (m.fontData !== undefined && m.fontData !== st.fontData) { st.fontData = m.fontData; if (st.jassub) await create(); }
    if (typeof m.offset === 'number') { st.offset = m.offset; if (st.jassub) st.jassub.timeOffset = m.offset; }
  } else if (m.type === 'track') {
    const changed = m.content !== st.ass;
    st.ass = m.content || ''; st.romaji = !!m.romaji; st.kana = !!m.kana; st.english = m.english !== false;
    if (changed || !st.jassub) await create();
    else if (st.jassub && st.jassub.renderer) {
      const content = trackText();
      await st.jassub.renderer.setTrack(content); st.lastDrawn = -1; applySize();
      say({ type: 'status', text: `rendering (${content.split('\nDialogue:').length - 1} events, font ${st.family})` });
    }
  } else if (m.type === 'size') {
    st.size = { width: m.width, height: m.height, videoWidth: m.videoWidth, videoHeight: m.videoHeight };
    applySize();
  } else if (m.type === 'time') {
    st.t = m.t; st.paused = m.paused;
    if (st.jassub && st.jassub.renderer && st.t !== st.lastDrawn && st.size.width) {
      st.lastDrawn = st.t;
      st.jassub.manualRender({ mediaTime: st.t, expectedDisplayTime: performance.now(),
                               width: st.size.videoWidth, height: st.size.videoHeight }).catch(() => {});
    }
  }
});

say({ type: 'ready' });

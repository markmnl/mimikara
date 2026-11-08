// mimikara content script: finds the page's <video>, floats an overlay iframe
// (extension origin, so JASSUB's workers load without cross-origin trouble)
// over it, keeps the iframe in sync with the video's time, and shows a small
// control panel with the subtitle file picker and layer toggles.
(() => {
  if (window.__mimikara) { window.__mimikara.toggle(); return; }

  const video = pickVideo();
  if (!video) { if (window === window.top) alert('mimikara: no <video> found on this page (yet). Start playback and click again.'); return; }

  const ext = (p) => chrome.runtime.getURL(p);
  const host = document.createElement('div');
  host.style.cssText = 'all:initial; position:fixed; z-index:2147483647; left:0; top:0; width:0; height:0;';
  const shadow = host.attachShadow({ mode: 'open' });
  shadow.innerHTML = `
    <style>
      .panel { position:fixed; right:14px; top:14px; background:rgba(16,18,24,.92); color:#e6e8ec; font:13px/1.4 system-ui,sans-serif;
               border-radius:10px; padding:10px 12px; box-shadow:0 4px 24px rgba(0,0,0,.5); display:flex; flex-direction:column; gap:8px; min-width:230px; }
      .panel.min { min-width:0; padding:6px 10px; }
      .panel.min > :not(.head) { display:none; }
      .head { display:flex; align-items:center; gap:8px; cursor:move; }
      .head b { flex:1; font-weight:600; }
      .head button { background:none; border:0; color:#8a919c; cursor:pointer; font-size:14px; }
      label.row { display:flex; align-items:center; gap:8px; cursor:pointer; }
      input[type=file] { display:none; }
      .btn { background:#2a313c; border:1px solid #3a4250; color:#e6e8ec; border-radius:6px; padding:5px 9px; cursor:pointer; text-align:center; }
      .btn:hover { background:#343c48; }
      .dim { color:#8a919c; font-size:12px; }
      .off { display:flex; align-items:center; gap:6px; }
      .off input { width:64px; background:#0f1216; color:#e6e8ec; border:1px solid #3a4250; border-radius:4px; padding:2px 4px; }
    </style>
    <div class="panel" id="panel">
      <div class="head"><b>mimikara</b><button id="min" title="minimise">–</button><button id="close" title="remove overlay">✕</button></div>
      <label class="btn">Load .ass file… <input type="file" id="file" accept=".ass,.ssa,text/plain"></label>
      <div class="dim" id="name">no subtitle loaded</div>
      <label class="row"><input type="checkbox" id="romaji"> Romaji line</label>
      <label class="row"><input type="checkbox" id="kana"> Japanese line</label>
      <label class="row"><input type="checkbox" id="english" checked> English line</label>
      <div class="off"><span>offset</span><input type="number" id="offset" step="0.1" value="0"><span class="dim">s (+ = later)</span></div>
      <label class="btn" title="optional: a .ttf/.otf with Japanese glyphs; a fallback font is bundled">Font file… <input type="file" id="font" accept=".ttf,.otf,.woff,.woff2"></label>
      <div class="dim" id="status"></div>
    </div>`;
  document.documentElement.appendChild(host);

  const $ = (s) => shadow.querySelector(s);
  // The overlay iframe lives inside the shadow root too: some players
  // (Crunchyroll's, for one) periodically sweep the document for foreign
  // <iframe> elements and remove them, and querySelectorAll does not see
  // into a shadow root.
  const iframe = document.createElement('iframe');
  iframe.src = ext('overlay.html');
  iframe.setAttribute('allowtransparency', 'true');
  iframe.style.cssText = 'position:fixed; border:0; background:transparent; pointer-events:none; z-index:2147483646; left:0; top:0; width:0; height:0;';
  shadow.appendChild(iframe);
  // ...and if something (an ad blocker, the player) still yanks it out, put
  // it back.  Re-inserting reloads overlay.html; its 'ready' message makes
  // pushAll() resend the subtitle, toggles and size, so nothing is lost.
  let reinserts = 0;
  new MutationObserver(() => {
    if (!iframe.isConnected && host.isConnected && !st.destroyed) {
      reinserts += 1;
      console.warn(`mimikara: overlay frame was removed from the page (${reinserts}x); re-inserting`);
      st.ready = false;
      shadow.appendChild(iframe);
    }
  }).observe(shadow, { childList: true });

  const st = { ass: '', fontData: null, romaji: false, kana: false, english: true, offset: 0, ready: false, raf: 0, visible: true, destroyed: false };
  const send = (msg) => iframe.contentWindow && iframe.contentWindow.postMessage(msg, '*');

  window.addEventListener('message', (ev) => {
    if (ev.source !== iframe.contentWindow || !ev.data || ev.data.mimikara !== 'overlay') return;
    if (ev.data.type === 'ready') { st.ready = true; pushAll(); }
    if (ev.data.type === 'status') $('#status').textContent = ev.data.text || '';
  });

  // --- persisted settings
  chrome.storage.local.get(['romaji', 'kana', 'english', 'offset', 'fontData', 'fontName', 'ass', 'assName']).then((v) => {
    for (const k of ['romaji', 'kana', 'english']) if (typeof v[k] === 'boolean') { st[k] = v[k]; $('#' + k).checked = v[k]; }
    if (typeof v.offset === 'number') { st.offset = v.offset; $('#offset').value = v.offset; }
    if (v.fontData) st.fontData = v.fontData;
    if (v.ass) { st.ass = v.ass; $('#name').textContent = (v.assName || 'subtitle') + ' (restored)'; }
    if (st.ready) pushAll();
  }).catch(() => {});

  function pushAll() {
    if (!st.ready) return;
    send({ type: 'config', fontData: st.fontData, offset: st.offset });
    send({ type: 'track', content: st.ass, romaji: st.romaji, kana: st.kana, english: st.english });
    layout();
    startSync();
  }

  // --- controls
  $('#file').addEventListener('change', async (ev) => {
    const f = ev.target.files[0]; if (!f) return;
    st.ass = await f.text();
    $('#name').textContent = f.name;
    chrome.storage.local.set({ ass: st.ass, assName: f.name }).catch(() => {});
    send({ type: 'track', content: st.ass, romaji: st.romaji, kana: st.kana, english: st.english });
  });
  $('#font').addEventListener('change', async (ev) => {
    const f = ev.target.files[0]; if (!f) return;
    const buf = new Uint8Array(await f.arrayBuffer());
    let bin = ''; for (let i = 0; i < buf.length; i += 0x8000) bin += String.fromCharCode.apply(null, buf.subarray(i, i + 0x8000));
    st.fontData = 'data:font/ttf;base64,' + btoa(bin);
    chrome.storage.local.set({ fontData: st.fontData, fontName: f.name }).catch(() => {});
    send({ type: 'config', fontData: st.fontData, offset: st.offset });
    send({ type: 'track', content: st.ass, romaji: st.romaji, kana: st.kana, english: st.english });
  });
  for (const k of ['romaji', 'kana', 'english']) {
    $('#' + k).addEventListener('change', (ev) => {
      st[k] = ev.target.checked;
      chrome.storage.local.set({ [k]: st[k] }).catch(() => {});
      send({ type: 'track', content: st.ass, romaji: st.romaji, kana: st.kana, english: st.english });
    });
  }
  $('#offset').addEventListener('change', (ev) => {
    st.offset = parseFloat(ev.target.value) || 0;
    chrome.storage.local.set({ offset: st.offset }).catch(() => {});
    send({ type: 'config', offset: st.offset });
  });
  $('#min').addEventListener('click', () => $('#panel').classList.toggle('min'));
  $('#close').addEventListener('click', destroy);
  dragPanel($('#panel'), $('.head'));

  // --- geometry + time sync
  function layout() {
    const r = video.getBoundingClientRect();
    // letterbox: fit the video's own aspect inside its element box, like the player does
    let w = r.width, h = r.height, x = r.left, y = r.top;
    if (video.videoWidth && video.videoHeight) {
      const ar = video.videoWidth / video.videoHeight;
      if (w / h > ar) { const nw = h * ar; x += (w - nw) / 2; w = nw; } else { const nh = w / ar; y += (h - nh) / 2; h = nh; }
    }
    const css = `left:${x}px; top:${y}px; width:${w}px; height:${h}px;`;
    if (iframe.dataset.css !== css) {
      iframe.dataset.css = css;
      iframe.style.left = x + 'px'; iframe.style.top = y + 'px'; iframe.style.width = w + 'px'; iframe.style.height = h + 'px';
      send({ type: 'size', width: w, height: h, videoWidth: video.videoWidth || 1280, videoHeight: video.videoHeight || 720 });
    }
  }
  function startSync() {
    cancelAnimationFrame(st.raf);
    const tick = () => {
      if (!document.contains(video)) { destroy(); return; }
      layout();
      send({ type: 'time', t: video.currentTime, paused: video.paused });
      st.raf = requestAnimationFrame(tick);
    };
    st.raf = requestAnimationFrame(tick);
  }
  // fullscreen: move the host (panel + overlay) into the fullscreen element so it stays visible
  document.addEventListener('fullscreenchange', () => {
    (document.fullscreenElement || document.documentElement).appendChild(host);
    setTimeout(layout, 50);
  });

  function destroy() {
    st.destroyed = true; cancelAnimationFrame(st.raf); host.remove(); delete window.__mimikara;
  }
  window.__mimikara = { toggle() { st.visible = !st.visible; host.style.display = st.visible ? '' : 'none'; } };

  function pickVideo() {
    const vids = [...document.querySelectorAll('video')].filter(v => v.getBoundingClientRect().width > 0);
    vids.sort((a, b) => area(b) - area(a));
    return vids[0] || null;
    function area(v) { const r = v.getBoundingClientRect(); return r.width * r.height; }
  }
  function dragPanel(panel, handle) {
    let sx, sy, ox, oy;
    handle.addEventListener('mousedown', (e) => {
      if (e.target.tagName === 'BUTTON') return;
      sx = e.clientX; sy = e.clientY; const r = panel.getBoundingClientRect(); ox = r.left; oy = r.top;
      const mv = (e2) => { panel.style.left = (ox + e2.clientX - sx) + 'px'; panel.style.top = (oy + e2.clientY - sy) + 'px'; panel.style.right = 'auto'; };
      const up = () => { window.removeEventListener('mousemove', mv); window.removeEventListener('mouseup', up); };
      window.addEventListener('mousemove', mv); window.addEventListener('mouseup', up); e.preventDefault();
    });
  }
})();

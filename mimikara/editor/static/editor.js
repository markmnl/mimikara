(() => {
  'use strict';
  const $ = (s) => document.querySelector(s);
  const state = { doc: null, sel: 0, peaks: null, win: null, dirty: false, drag: null, hover: -1, filter: '' };
  const wave = $('#wave'), tok = $('#tokens'), audio = $('#audio');
  const PAD = 600;
  const COLORS = ['#FFC94D', '#FF8A5C', '#5EC8FF', '#7BE3A8', '#C9A2FF', '#FF8AC8'];

  // ---------- data ----------
  async function load() {
    const r = await fetch('/api/doc');
    state.doc = await r.json();
    $('#path').textContent = state.doc.path || '';
    if (state.doc.has_audio) audio.src = '/api/audio';
    renderList();
    select(0);
  }

  function line() { return state.doc.lines[state.sel]; }

  function visibleLines() {
    const f = state.filter.trim().toLowerCase();
    return state.doc.lines.map((ln, i) => [ln, i]).filter(([ln]) => {
      if (!f) return true;
      if (f === '!') return (ln.warnings || []).length > 0;
      return (ln.ja_text || '').toLowerCase().includes(f) || (ln.en_text || '').toLowerCase().includes(f);
    });
  }

  function renderList() {
    const box = $('#lines');
    box.innerHTML = '';
    for (const [ln, i] of visibleLines()) {
      const d = document.createElement('div');
      d.className = 'ln' + (i === state.sel ? ' sel' : '');
      d.dataset.i = i;
      const pins = (ln.ja || []).filter(t => t.start_ms != null).length;
      d.innerHTML = `<div class="t"><span>#${ln.id ?? i + 1} ${ln.start} → ${ln.end}</span><span>${ln.timing || 'mora'}${pins ? `<span class="pin">📌${pins}</span>` : ''}</span></div>
        <div class="ja">${esc(ln.ja_text || '—')}</div><div class="en">${esc(ln.en_text || '—')}</div>
        ${(ln.warnings || []).length ? `<div class="w">⚠ ${esc(ln.warnings.join('; '))}</div>` : ''}`;
      d.onclick = () => select(i);
      box.appendChild(d);
    }
  }

  function esc(s) { return String(s).replace(/[&<>]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' }[c])); }

  async function select(i) {
    state.sel = Math.max(0, Math.min(state.doc.lines.length - 1, i));
    document.querySelectorAll('.ln').forEach(el => el.classList.toggle('sel', +el.dataset.i === state.sel));
    const el = document.querySelector('.ln.sel'); if (el) el.scrollIntoView({ block: 'nearest' });
    const ln = line();
    const s = ms(ln.start), e = ms(ln.end);
    state.win = { start: Math.max(0, s - PAD), end: e + PAD, s, e };
    state.peaks = null;
    renderMeta();
    draw();
    if (state.doc.has_audio) {
      const r = await fetch(`/api/peaks?start=${s}&end=${e}`);
      const p = await r.json();
      if (line() === ln) { state.peaks = p; state.win.start = p.start; state.win.end = p.end; draw(); }
    }
  }

  function renderMeta() {
    const ln = line();
    const warn = (ln.warnings || []).map(w => `<span class="warn">⚠ ${esc(w)}</span>`).join(' ');
    $('#meta').innerHTML = `<span>#${ln.id}</span><span>${ln.start} → ${ln.end}</span><b>${esc(ln.ja_text || '')}</b>
      <span>${esc(ln.en_text || '')}</span>${ln.en_original ? `<span title="official line">(${esc(ln.en_original)})</span>` : ''}
      <span>timing: ${ln.timing || 'mora estimate'}</span>${warn}`;
  }

  // ---------- time helpers ----------
  function ms(t) { // "H:MM:SS.cc" -> ms
    const p = t.split(':').map(Number);
    return Math.round(((p[0] * 60 + p[1]) * 60 + p[2]) * 1000);
  }
  function x2ms(x) { const w = state.win; return w.start + (x / wave.clientWidth) * (w.end - w.start); }
  function ms2x(m) { const w = state.win; return ((m - w.start) / (w.end - w.start)) * wave.clientWidth; }

  // ---------- drawing ----------
  function fit(c) {
    const r = window.devicePixelRatio || 1;
    const w = c.clientWidth, h = c.clientHeight;
    if (c.width !== w * r || c.height !== h * r) { c.width = w * r; c.height = h * r; }
    const g = c.getContext('2d'); g.setTransform(r, 0, 0, r, 0, 0); return [g, w, h];
  }

  function draw() {
    const ln = line(); if (!ln || !state.win) return;
    const [g, w, h] = fit(wave);
    g.clearRect(0, 0, w, h);
    // cue region
    g.fillStyle = '#182029'; g.fillRect(ms2x(state.win.s), 0, ms2x(state.win.e) - ms2x(state.win.s), h);
    if (state.peaks) {
      const pk = state.peaks.peaks, n = pk.length;
      g.fillStyle = '#4b7a9c';
      for (let i = 0; i < n; i++) {
        const x = (i / n) * w, bh = Math.max(1, pk[i] * (h - 6));
        g.fillRect(x, (h - bh) / 2, Math.max(1, w / n), bh);
      }
    } else if (!state.doc.has_audio) {
      g.fillStyle = '#3a4250'; g.font = '12px system-ui'; g.fillText('no audio (start the editor with --audio video.mkv for a waveform)', 10, 18);
    }
    // speech window brackets
    const sw = ln.speech_start_ms ?? 0, ew = ln.speech_end_ms ?? (state.win.e - state.win.s);
    g.strokeStyle = '#7be3a8'; g.lineWidth = 2; g.font = 'bold 14px system-ui'; g.fillStyle = '#7be3a8';
    for (const [m, lbl] of [[sw, '['], [ew, ']']]) {
      const x = ms2x(state.win.s + m); g.beginPath(); g.moveTo(x, 0); g.lineTo(x, h); g.stroke(); g.fillText(lbl, x + (lbl === '[' ? 3 : -11), 14);
    }
    // playhead
    if (!audio.paused) { const x = ms2x(audio.currentTime * 1000); g.strokeStyle = '#fff'; g.lineWidth = 1; g.beginPath(); g.moveTo(x, 0); g.lineTo(x, h); g.stroke(); }
    drawTokens();
  }

  function colorsFor(ln) {
    const jc = {}; let n = 0;
    for (const e of ln.en || []) {
      if (!e.ja.length) continue;
      let c = e.ja.map(j => jc[j]).find(Boolean);
      if (!c) c = COLORS[n++ % COLORS.length];
      e._c = c; for (const j of e.ja) jc[j] = c;
    }
    return jc;
  }

  function drawTokens() {
    const ln = line();
    const [g, w, h] = fit(tok);
    g.clearRect(0, 0, w, h);
    const jc = colorsFor(ln);
    const base = state.win.s;
    const rowY = 10, rowH = 64;
    (ln.ja || []).forEach((t, i) => {
      if (t.role === 'punct') return;
      const x0 = ms2x(base + (state.drag && state.drag.i === i ? state.drag.ms : t.t0)), x1 = ms2x(base + t.t1);
      const c = jc[i] || (t.role === 'particle' || t.role === 'aux' ? '#9aa0ac' : '#e6e8ec');
      g.fillStyle = i === state.hover ? '#2a3442' : '#1b2129'; g.fillRect(x0, rowY, Math.max(2, x1 - x0), rowH);
      g.strokeStyle = c; g.lineWidth = i === state.hover ? 2 : 1; g.strokeRect(x0 + .5, rowY + .5, Math.max(2, x1 - x0) - 1, rowH - 1);
      g.fillStyle = c; g.font = '16px system-ui, "Noto Sans CJK JP"'; g.fillText(t.text, x0 + 5, rowY + 24, Math.max(10, x1 - x0 - 8));
      g.fillStyle = '#b8bec8'; g.font = '12px system-ui'; g.fillText(t.romaji || '', x0 + 5, rowY + 42, Math.max(10, x1 - x0 - 8));
      if (t.start_ms != null) { g.fillStyle = '#ff6b6b'; g.font = '12px system-ui'; g.fillText('📌', x0 + 4, rowY + 58); }
      else if (t.align_ms) { g.fillStyle = '#7a8594'; g.font = '10px system-ui'; g.fillText(`a${t.align_score != null ? ' ' + t.align_score.toFixed(2) : ''}`, x0 + 4, rowY + 58); }
    });
    // English reveal order
    const ey = rowY + rowH + 18;
    g.font = '13px system-ui';
    g.fillStyle = '#8a919c'; g.fillText('English appears:', 4, ey - 4);
    // labels that would overlap drop to the next row (several words often appear together)
    const rowsEnd = [];
    (ln.en || []).forEach(e => {
      const x = ms2x(base + (e.reveal_ms ?? 0));
      const tw = g.measureText(e.text).width + 10;
      let row = rowsEnd.findIndex(end => end <= x);
      if (row < 0) { row = rowsEnd.length; rowsEnd.push(0); }
      rowsEnd[row] = x + tw;
      const y = ey + row * 16;
      g.fillStyle = e._c || '#e6e8ec'; g.fillRect(x, y, 2, 14);
      g.fillText(e.text, x + 5, y + 12);
    });
    // time ruler
    g.fillStyle = '#5b6470'; g.font = '10px system-ui';
    const span = state.win.end - state.win.start, step = span > 8000 ? 1000 : span > 3000 ? 500 : 250;
    for (let m = Math.ceil(state.win.start / step) * step; m < state.win.end; m += step) {
      const x = ms2x(m); g.fillRect(x, h - 10, 1, 10); g.fillText(((m - base) / 1000).toFixed(2), x + 2, h - 2);
    }
  }

  // ---------- interaction ----------
  function hitToken(x) {
    const ln = line(), base = state.win.s;
    for (let i = ln.ja.length - 1; i >= 0; i--) {
      const t = ln.ja[i]; if (t.role === 'punct') continue;
      if (x >= ms2x(base + t.t0) && x <= ms2x(base + t.t1)) return i;
    }
    return -1;
  }

  tok.addEventListener('mousemove', ev => {
    const x = ev.offsetX;
    if (state.drag) { state.drag.ms = clampMs(x2ms(x) - state.win.s - state.drag.off); draw(); return; }
    const h = hitToken(x);
    if (h !== state.hover) { state.hover = h; tok.style.cursor = h >= 0 ? 'ew-resize' : 'default'; drawTokens(); }
  });
  tok.addEventListener('mousedown', ev => {
    const i = hitToken(ev.offsetX); if (i < 0) return;
    const t = line().ja[i];
    state.drag = { i, ms: t.t0, off: x2ms(ev.offsetX) - state.win.s - t.t0 };
  });
  window.addEventListener('mouseup', async () => {
    if (!state.drag) return;
    const { i, ms: m } = state.drag; state.drag = null;
    const ln = line();
    if (ln.ja[i].t0 !== m) { ln.ja[i].start_ms = Math.round(m); await retime(); }
    draw();
  });
  tok.addEventListener('dblclick', async ev => {
    const i = hitToken(ev.offsetX); if (i < 0) return;
    const t = line().ja[i];
    if (t.start_ms != null || t.end_ms != null) { delete t.start_ms; delete t.end_ms; await retime(); }
  });
  tok.addEventListener('mouseleave', () => { if (state.hover >= 0) { state.hover = -1; drawTokens(); } });

  // speech window brackets + click-to-play on the waveform
  wave.addEventListener('mousedown', ev => {
    const ln = line(), x = ev.offsetX;
    const sw = ms2x(state.win.s + (ln.speech_start_ms ?? 0)), ew = ms2x(state.win.s + (ln.speech_end_ms ?? (state.win.e - state.win.s)));
    if (Math.abs(x - sw) < 8) state.drag = { bracket: 'speech_start_ms' };
    else if (Math.abs(x - ew) < 8) state.drag = { bracket: 'speech_end_ms' };
    else { playFrom(x2ms(x)); return; }
    const move = e2 => { ln[state.drag.bracket] = Math.round(clampMs(x2ms(e2.offsetX) - state.win.s)); draw(); };
    const up = async () => { wave.removeEventListener('mousemove', move); window.removeEventListener('mouseup', up); state.drag = null; await retime(); };
    wave.addEventListener('mousemove', move); window.addEventListener('mouseup', up);
  });
  wave.addEventListener('mousemove', ev => {
    const ln = line(); if (!ln || state.drag) return;
    const sw = ms2x(state.win.s + (ln.speech_start_ms ?? 0)), ew = ms2x(state.win.s + (ln.speech_end_ms ?? (state.win.e - state.win.s)));
    wave.style.cursor = (Math.abs(ev.offsetX - sw) < 8 || Math.abs(ev.offsetX - ew) < 8) ? 'ew-resize' : 'pointer';
  });

  function clampMs(m) { return Math.max(-PAD, Math.min(state.win.e - state.win.s + PAD, m)); }

  async function retime() {
    const ln = line();
    const r = await fetch('/api/retime', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(ln) });
    if (!r.ok) { status('retime failed', 'err'); return; }
    const fresh = await r.json();
    Object.assign(ln, fresh);
    ln.timing = ln.ja.some(t => t.start_ms != null) ? 'manual' : (fresh.timing || '');
    state.dirty = true; status('unsaved changes');
    renderMeta(); renderList(); draw();
  }

  async function save() {
    const r = await fetch('/api/doc', { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(state.doc) });
    if (r.ok) { state.dirty = false; status('saved ✓', 'ok'); } else { status('save failed: ' + (await r.text()), 'err'); }
  }

  function status(msg, cls) { const s = $('#status'); s.textContent = msg; s.className = cls || ''; }

  // ---------- playback ----------
  let stopAt = null, raf = 0;
  function playFrom(m, until) {
    if (!state.doc.has_audio) return;
    audio.currentTime = m / 1000; stopAt = until ?? state.win.end; audio.play();
    cancelAnimationFrame(raf);
    const tick = () => { draw(); if (!audio.paused && audio.currentTime * 1000 < stopAt) raf = requestAnimationFrame(tick); else { audio.pause(); draw(); } };
    raf = requestAnimationFrame(tick);
  }
  function playLine() { const w = state.win; if (!audio.paused) { audio.pause(); draw(); return; } playFrom(Math.max(0, w.s - 150), w.e + 150); }

  $('#play').onclick = playLine;
  $('#save').onclick = save;
  $('#prev').onclick = () => step(-1);
  $('#next').onclick = () => step(1);
  $('#filter').oninput = ev => { state.filter = ev.target.value; renderList(); };
  function step(d) {
    const vis = visibleLines().map(([, i]) => i);
    const k = vis.indexOf(state.sel);
    const n = vis[Math.max(0, Math.min(vis.length - 1, (k < 0 ? 0 : k) + d))];
    if (n != null) select(n);
  }
  window.addEventListener('keydown', ev => {
    if (ev.target.tagName === 'INPUT') return;
    if (ev.key === ' ') { ev.preventDefault(); playLine(); }
    else if (ev.key === 'j' || ev.key === 'ArrowDown') { ev.preventDefault(); step(1); }
    else if (ev.key === 'k' || ev.key === 'ArrowUp') { ev.preventDefault(); step(-1); }
    else if (ev.key === 's' && !ev.ctrlKey && !ev.metaKey) save();
    else if ((ev.key === 's' || ev.key === 'S') && (ev.ctrlKey || ev.metaKey)) { ev.preventDefault(); save(); }
  });
  window.addEventListener('beforeunload', ev => { if (state.dirty) { ev.preventDefault(); ev.returnValue = ''; } });
  window.addEventListener('resize', draw);
  load().catch(e => status('load failed: ' + e, 'err'));
})();

// Audio & Voice Line Studio — zero-CLI Wwise .bnk / .wem browser, waveform editor & subtitle linker.
(() => {
  'use strict';

  const DEFAULT_DSP = Object.freeze({
    match_lufs: true,
    gain_db: 0,
    trim_start: 0,
    trim_end: 0,
    fade_in_ms: 0,
    fade_out_ms: 15,
  });

  // ── Pure testable audio & filter helpers ───────────────────────────────────
  function encodePcm16Wav(channels, sampleRate) {
    const chList = Array.isArray(channels) && channels.length ? channels : [new Float32Array(0)];
    const numCh = chList.length;
    const rate = Math.max(8000, Math.round(Number(sampleRate) || 48000));
    const numFrames = chList[0].length;
    const dataBytes = numFrames * numCh * 2;
    const buf = new ArrayBuffer(44 + dataBytes);
    const view = new DataView(buf);
    const writeStr = (off, s) => { for (let i = 0; i < s.length; i++) view.setUint8(off + i, s.charCodeAt(i)); };
    writeStr(0, 'RIFF');
    view.setUint32(4, 36 + dataBytes, true);
    writeStr(8, 'WAVE');
    writeStr(12, 'fmt ');
    view.setUint32(16, 16, true);
    view.setUint16(20, 1, true); // PCM
    view.setUint16(22, numCh, true);
    view.setUint32(24, rate, true);
    view.setUint32(28, rate * numCh * 2, true);
    view.setUint16(32, numCh * 2, true);
    view.setUint16(34, 16, true);
    writeStr(36, 'data');
    view.setUint32(40, dataBytes, true);

    let offset = 44;
    for (let i = 0; i < numFrames; i++) {
      for (let c = 0; c < numCh; c++) {
        let s = chList[c][i] || 0;
        if (s > 1) s = 1;
        else if (s < -1) s = -1;
        view.setInt16(offset, s < 0 ? Math.round(s * 32768) : Math.round(s * 32767), true);
        offset += 2;
      }
    }
    return new Uint8Array(buf);
  }

  function peaksFromChannels(channels, sampleRate, bars = 120) {
    const chList = Array.isArray(channels) && channels.length ? channels : [new Float32Array(0)];
    const numCh = chList.length;
    const frames = chList[0].length;
    const rate = Math.max(1, Number(sampleRate) || 48000);
    const duration = frames / rate;
    if (!frames) return { peaks: [], duration: 0, peak_db: -120, lufs: null };
    const n = Math.max(8, Math.min(bars, frames));
    const peaks = new Array(n);
    let globalPeak = 0;
    for (let i = 0; i < n; i++) {
      const start = Math.floor((i * frames) / n);
      const end = Math.max(start + 1, Math.floor(((i + 1) * frames) / n));
      let mx = 0;
      for (let j = start; j < end; j++) {
        let sum = 0;
        for (let c = 0; c < numCh; c++) sum += Math.abs(chList[c][j] || 0);
        const avg = sum / numCh;
        if (avg > mx) mx = avg;
      }
      if (mx > globalPeak) globalPeak = mx;
      peaks[i] = Math.round(Math.min(1, mx) * 10000) / 10000;
    }
    const peakDb = globalPeak > 1e-6 ? Math.round(20 * Math.log10(globalPeak) * 100) / 100 : -120;
    return { peaks, duration: Math.round(duration * 1000) / 1000, peak_db: peakDb, lufs: null };
  }

  function uint8ToBase64(bytes) {
    let bin = '';
    const chunk = 0x8000;
    for (let i = 0; i < bytes.length; i += chunk) {
      bin += String.fromCharCode.apply(null, bytes.subarray(i, i + chunk));
    }
    return typeof btoa === 'function' ? btoa(bin) : Buffer.from(bytes).toString('base64');
  }

  function formatTime(sec) {
    const s = Math.max(0, Number(sec) || 0);
    const mins = Math.floor(s / 60);
    const rem = s - mins * 60;
    const whole = Math.floor(rem);
    const hundredths = Math.floor((rem - whole) * 100);
    return `${mins}:${String(whole).padStart(2, '0')}.${String(hundredths).padStart(2, '0')}`;
  }

  function formatSize(bytes) {
    const n = Number(bytes) || 0;
    if (n >= 1024 * 1024) return `${(n / (1024 * 1024)).toFixed(1)} MB`;
    if (n >= 1024) return `${Math.round(n / 1024)} KB`;
    return `${n} B`;
  }

  function filterClips(clips, rawQuery) {
    const terms = String(rawQuery || '').trim().toLowerCase().split(/\s+/).filter(Boolean);
    if (!terms.length) return clips || [];
    return (clips || []).filter(c => {
      const hay = `${c.media_id || ''} ${c.subtitle || ''} ${c.label || ''} ${c.event || ''} ${c.codec || ''}`.toLowerCase();
      return terms.every(t => hay.includes(t));
    });
  }

  function filterBanks(banks, rawQuery, category, clipsByBank = {}) {
    const terms = String(rawQuery || '').trim().toLowerCase().split(/\s+/).filter(Boolean);
    return (banks || []).filter(b => {
      if (category && category !== 'all' && category !== 'edited') {
        if (b.category !== category) return false;
      }
      if (!terms.length) return true;
      const bankHay = `${b.stem || ''} ${b.group_label || ''} ${b.hero_id || ''} ${b.bank_rel || ''}`.toLowerCase();
      if (terms.every(t => bankHay.includes(t))) return true;
      const loaded = clipsByBank[b.bank_rel];
      if (loaded && loaded.length) {
        return filterClips(loaded, rawQuery).length > 0;
      }
      return false;
    });
  }

  // Export pure helpers immediately in Node test environments.
  if (typeof module !== 'undefined' && module.exports) {
    module.exports = {
      DEFAULT_DSP,
      encodePcm16Wav,
      peaksFromChannels,
      uint8ToBase64,
      formatTime,
      formatSize,
      filterClips,
      filterBanks,
    };
  }
  if (typeof window === 'undefined' || typeof document === 'undefined') return;

  // ── Browser Studio UI ──────────────────────────────────────────────────────
  const fetchApi = (path, opts) => (window.atelierFetch ? window.atelierFetch(path, opts) : fetch(path, opts));
  const notify = (msg, kind = 'info', ms = 3200) => window.toast?.(msg, kind, ms);

  const PLAY_SVG = '<svg width="13" height="13" viewBox="0 0 16 16" fill="currentColor" aria-hidden="true"><path d="M4 2.5v11l9.5-5.5L4 2.5z"/></svg>';
  const PAUSE_SVG = '<svg width="13" height="13" viewBox="0 0 16 16" fill="currentColor" aria-hidden="true"><rect x="3.5" y="2.5" width="3.5" height="11" rx="0.8"/><rect x="9" y="2.5" width="3.5" height="11" rx="0.8"/></svg>';

  let dlg = null;
  let audioEl = null;
  let rafId = 0;

  const state = {
    catalog: null,
    loadingCatalog: false,
    category: 'all',
    query: '',
    openBanks: new Set(),
    clipsByBank: {},
    loadingBanks: new Set(),
    selectedGameRel: '',
    clip: null,
    loadingClip: false,
    version: 'original', // 'original' | 'edited'
    loop: false,
    pendingWavBytes: null,
    pendingWavUrl: '',
    pendingFileName: '',
    pendingWave: null,
    dsp: { ...DEFAULT_DSP },
    subEditorOpen: false,
    subSearchOpen: false,
    subSearchQuery: '',
    subSearchHits: [],
    subSearchLoading: false,
    saving: false,
    statusText: '',
  };

  function revokePendingUrl() {
    if (state.pendingWavUrl) {
      URL.revokeObjectURL(state.pendingWavUrl);
      state.pendingWavUrl = '';
    }
  }

  function stopPlayback() {
    if (rafId) {
      cancelAnimationFrame(rafId);
      rafId = 0;
    }
    if (audioEl) {
      audioEl.pause();
      audioEl.currentTime = 0;
    }
    updateTransportReadout();
  }

  function ensureAudioEl() {
    if (audioEl) return audioEl;
    audioEl = new Audio();
    audioEl.preload = 'auto';
    audioEl.addEventListener('play', () => {
      updateTransportReadout();
      startPlayheadLoop();
    });
    audioEl.addEventListener('pause', () => {
      if (rafId) { cancelAnimationFrame(rafId); rafId = 0; }
      updateTransportReadout();
      drawWaveform();
    });
    audioEl.addEventListener('ended', () => {
      if (rafId) { cancelAnimationFrame(rafId); rafId = 0; }
      updateTransportReadout();
      drawWaveform();
    });
    audioEl.addEventListener('timeupdate', () => updateTransportReadout());
    audioEl.addEventListener('error', () => {
      if (rafId) { cancelAnimationFrame(rafId); rafId = 0; }
      updateTransportReadout();
    });
    return audioEl;
  }

  function startPlayheadLoop() {
    if (rafId) cancelAnimationFrame(rafId);
    const tick = () => {
      drawWaveform();
      updateTransportReadout();
      if (audioEl && !audioEl.paused && !audioEl.ended) {
        rafId = requestAnimationFrame(tick);
      } else {
        rafId = 0;
      }
    };
    rafId = requestAnimationFrame(tick);
  }

  function activeWave() {
    if (state.version === 'edited') {
      if (state.pendingWave) return state.pendingWave;
      if (state.clip?.edited_wave) return state.clip.edited_wave;
    }
    return state.clip?.original_wave || null;
  }

  function activeAudioUrl() {
    if (!state.clip) return '';
    if (state.version === 'edited') {
      if (state.pendingWavUrl) return state.pendingWavUrl;
      if (state.clip.edited) {
        const proj = encodeURIComponent(window.atelierProject?.() || '');
        return `/api/audio/wav?game_rel=${encodeURIComponent(state.clip.game_rel)}&version=edited&_project=${proj}&t=${Date.now()}`;
      }
      return '';
    }
    if (!state.clip.original_wave) return '';
    const proj = encodeURIComponent(window.atelierProject?.() || '');
    return `/api/audio/wav?game_rel=${encodeURIComponent(state.clip.game_rel)}&version=original&_project=${proj}`;
  }

  async function togglePlay() {
    const el = ensureAudioEl();
    if (!el.paused) {
      el.pause();
      return;
    }
    const url = activeAudioUrl();
    if (!url) {
      setStatus('No preview audio available for this version yet.');
      return;
    }
    if (el.dataset.srcKey !== `${state.clip.game_rel}:${state.version}:${state.pendingWavUrl || state.clip.edited}`) {
      el.src = url;
      el.dataset.srcKey = `${state.clip.game_rel}:${state.version}:${state.pendingWavUrl || state.clip.edited}`;
    }
    el.loop = state.loop;
    try {
      await el.play();
    } catch (err) {
      setStatus(`Playback unavailable: ${err.message}`);
    }
  }

  function seekToFraction(frac) {
    const wave = activeWave();
    const dur = (audioEl && Number.isFinite(audioEl.duration) && audioEl.duration > 0)
      ? audioEl.duration
      : (wave?.duration || 0);
    if (!dur) return;
    const clamped = Math.max(0, Math.min(1, frac));
    const el = ensureAudioEl();
    const url = activeAudioUrl();
    if (!url) return;
    const key = `${state.clip.game_rel}:${state.version}:${state.pendingWavUrl || state.clip.edited}`;
    if (el.dataset.srcKey !== key) {
      el.src = url;
      el.dataset.srcKey = key;
    }
    el.currentTime = clamped * dur;
    drawWaveform();
    updateTransportReadout();
  }

  function updateTransportReadout() {
    if (!dlg) return;
    const btn = dlg.querySelector('#as-play-btn');
    const timeEl = dlg.querySelector('#as-time');
    const wave = activeWave();
    const playing = !!(audioEl && !audioEl.paused && !audioEl.ended);
    if (btn) {
      btn.innerHTML = playing ? `${PAUSE_SVG}<span>Pause</span>` : `${PLAY_SVG}<span>Play</span>`;
      btn.disabled = !activeAudioUrl();
    }
    if (timeEl) {
      const dur = (audioEl && Number.isFinite(audioEl.duration) && audioEl.duration > 0)
        ? audioEl.duration
        : (wave?.duration || state.clip?.wem?.duration || 0);
      const cur = audioEl ? (audioEl.currentTime || 0) : 0;
      timeEl.textContent = `${formatTime(cur)} / ${formatTime(dur)}`;
    }
  }

  function drawWaveform() {
    if (!dlg) return;
    const canvas = dlg.querySelector('#as-wave-canvas');
    if (!canvas) return;
    const rect = canvas.getBoundingClientRect();
    if (!rect.width || !rect.height) return;
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    const w = Math.round(rect.width * dpr);
    const h = Math.round(rect.height * dpr);
    if (canvas.width !== w || canvas.height !== h) {
      canvas.width = w;
      canvas.height = h;
    }
    const ctx = canvas.getContext('2d');
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    const css = getComputedStyle(dlg);
    const bg = css.getPropertyValue('--bg').trim() || '#141517';
    const border = css.getPropertyValue('--border').trim() || '#2c2f36';
    const acc = css.getPropertyValue('--acc').trim() || '#7c9cff';
    const muted = css.getPropertyValue('--muted').trim() || '#8a8f98';
    const text = css.getPropertyValue('--text').trim() || '#eceef2';

    const cw = rect.width;
    const ch = rect.height;
    const mid = ch / 2;
    ctx.fillStyle = bg;
    ctx.fillRect(0, 0, cw, ch);

    // Subtle centre acoustic baseline
    ctx.strokeStyle = border;
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(0, mid + 0.5);
    ctx.lineTo(cw, mid + 0.5);
    ctx.stroke();

    const wave = activeWave();
    const peaks = wave?.peaks || [];
    const dur = (audioEl && Number.isFinite(audioEl.duration) && audioEl.duration > 0)
      ? audioEl.duration
      : (wave?.duration || 0);
    const progress = (dur > 0 && audioEl) ? Math.max(0, Math.min(1, (audioEl.currentTime || 0) / dur)) : 0;

    if (!peaks.length) {
      ctx.fillStyle = muted;
      ctx.font = '12px system-ui, sans-serif';
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      ctx.fillText(
        state.version === 'edited'
          ? 'Drop any WAV, MP3, OGG or FLAC file below to preview your replacement waveform'
          : 'Waveform preview unavailable for this compressed Wwise clip',
        cw / 2,
        mid,
      );
      return;
    }

    const padX = 10;
    const usableW = Math.max(10, cw - padX * 2);
    const maxAmp = (ch - 26) / 2;
    const step = usableW / peaks.length;
    const barW = Math.max(1.5, step * 0.64);

    for (let i = 0; i < peaks.length; i++) {
      const frac = i / peaks.length;
      const amp = Math.max(2, peaks[i] * maxAmp);
      const x = padX + i * step;
      ctx.fillStyle = frac <= progress ? acc : (state.version === 'edited' ? text : muted);
      ctx.globalAlpha = frac <= progress ? 0.96 : 0.62;
      ctx.fillRect(x, mid - amp, barW, amp * 2);
    }
    ctx.globalAlpha = 1;

    // Trim overlay shading when previewing edited version
    if (state.version === 'edited' && dur > 0) {
      const tStart = Math.max(0, Number(state.dsp.trim_start) || 0);
      const tEnd = Math.max(0, Number(state.dsp.trim_end) || 0);
      ctx.fillStyle = 'rgba(0, 0, 0, 0.42)';
      if (tStart > 0) {
        const xStart = padX + Math.min(1, tStart / dur) * usableW;
        ctx.fillRect(padX, 0, xStart - padX, ch);
      }
      if (tEnd > 0) {
        const endFrac = Math.max(0, 1 - tEnd / dur);
        const xEnd = padX + endFrac * usableW;
        ctx.fillRect(xEnd, 0, padX + usableW - xEnd, ch);
      }
      // Subtle fade ramps
      const fi = Math.max(0, Number(state.dsp.fade_in_ms) || 0) / 1000;
      const fo = Math.max(0, Number(state.dsp.fade_out_ms) || 0) / 1000;
      ctx.strokeStyle = acc;
      ctx.lineWidth = 1.5;
      if (fi > 0) {
        const x0 = padX + Math.min(1, tStart / dur) * usableW;
        const x1 = padX + Math.min(1, (tStart + fi) / dur) * usableW;
        ctx.beginPath();
        ctx.moveTo(x0, ch - 8);
        ctx.lineTo(x1, 10);
        ctx.stroke();
      }
      if (fo > 0) {
        const endT = Math.max(0, dur - tEnd);
        const x1 = padX + Math.min(1, endT / dur) * usableW;
        const x0 = padX + Math.max(0, (endT - fo) / dur) * usableW;
        ctx.beginPath();
        ctx.moveTo(x0, 10);
        ctx.lineTo(x1, ch - 8);
        ctx.stroke();
      }
    }

    // Playhead cursor
    if (dur > 0) {
      const px = padX + progress * usableW;
      ctx.strokeStyle = acc;
      ctx.lineWidth = 1.75;
      ctx.beginPath();
      ctx.moveTo(px, 6);
      ctx.lineTo(px, ch - 6);
      ctx.stroke();
      ctx.fillStyle = acc;
      ctx.beginPath();
      ctx.arc(px, 6, 3.5, 0, Math.PI * 2);
      ctx.fill();
    }
  }

  function setStatus(text) {
    state.statusText = text || '';
    const el = dlg?.querySelector('#as-status');
    if (el) el.textContent = state.statusText;
  }

  // ── Seamless browser-native decoding (WAV / MP3 / OGG / FLAC / M4A) ────────
  async function decodeDroppedAudioFile(file) {
    const rawBuf = await file.arrayBuffer();
    const AudioCtx = window.AudioContext || window.webkitAudioContext;
    if (AudioCtx) {
      const ctx = new AudioCtx();
      try {
        const decoded = await ctx.decodeAudioData(rawBuf.slice(0));
        const channels = [];
        for (let c = 0; c < decoded.numberOfChannels; c++) {
          channels.push(decoded.getChannelData(c));
        }
        const wavBytes = encodePcm16Wav(channels, decoded.sampleRate);
        const wave = peaksFromChannels(channels, decoded.sampleRate);
        return { wavBytes, wave, sampleRate: decoded.sampleRate, channels: decoded.numberOfChannels };
      } finally {
        ctx.close?.().catch?.(() => {});
      }
    }
    // Fallback if WebAudio isn't available: accept plain WAV directly.
    const u8 = new Uint8Array(rawBuf);
    const sig = String.fromCharCode(u8[0], u8[1], u8[2], u8[3]);
    if (sig === 'RIFF') {
      return { wavBytes: u8, wave: null, sampleRate: 48000, channels: 2 };
    }
    throw new Error('Could not decode this audio format in this browser — try a .wav or .mp3 file.');
  }

  async function handleDroppedFile(file) {
    if (!state.clip || !file) return;
    setStatus(`Decoding ${file.name}…`);
    try {
      const decoded = await decodeDroppedAudioFile(file);
      stopPlayback();
      revokePendingUrl();
      state.pendingWavBytes = decoded.wavBytes;
      state.pendingFileName = file.name;
      state.pendingWave = decoded.wave;
      state.pendingWavUrl = URL.createObjectURL(new Blob([decoded.wavBytes], { type: 'audio/wav' }));
      state.version = 'edited';
      setStatus(`Ready: ${file.name} — audition above, then click Save edit to add to your Mod tray.`);
      renderStage();
    } catch (err) {
      setStatus(`Could not load ${file.name}: ${err.message}`);
      notify(`Could not decode ${file.name}: ${err.message}`, 'warning', 5000);
    }
  }

  // ── API Actions ────────────────────────────────────────────────────────────
  async function loadCatalog(force = false) {
    if (state.loadingCatalog && !force) return;
    state.loadingCatalog = true;
    renderBrowser();
    try {
      const res = await fetchApi('/api/audio/catalog');
      const data = await res.json();
      if (!res.ok || !data.ok) throw new Error(data.error || 'Could not scan audio banks.');
      state.catalog = data;
      updateToolBadge();
      if (state.openBanks.size === 0 && data.banks?.length) {
        // Auto-expand the first bank for immediate delight so the studio never looks empty.
        const first = data.banks[0];
        state.openBanks.add(first.bank_rel);
        loadBankClips(first.bank_rel);
      }
    } catch (err) {
      setStatus(err.message);
    } finally {
      state.loadingCatalog = false;
      renderBrowser();
    }
  }

  async function loadBankClips(bankRel, force = false) {
    if (!bankRel) return;
    if (!force && state.clipsByBank[bankRel]) return;
    state.loadingBanks.add(bankRel);
    renderBrowser();
    try {
      const res = await fetchApi(`/api/audio/bank?bank_rel=${encodeURIComponent(bankRel)}`);
      const data = await res.json();
      if (!res.ok || !data.ok) throw new Error(data.error || 'Could not read SoundBank.');
      state.clipsByBank[bankRel] = data.clips || [];
    } catch (err) {
      setStatus(err.message);
    } finally {
      state.loadingBanks.delete(bankRel);
      renderBrowser();
    }
  }

  async function selectClip(gameRel) {
    if (!gameRel) return;
    stopPlayback();
    revokePendingUrl();
    state.pendingWavBytes = null;
    state.pendingFileName = '';
    state.pendingWave = null;
    state.selectedGameRel = gameRel;
    state.loadingClip = true;
    state.subEditorOpen = false;
    state.subSearchOpen = false;
    state.subSearchHits = [];
    renderBrowser();
    renderStage();
    try {
      const res = await fetchApi(`/api/audio/clip?game_rel=${encodeURIComponent(gameRel)}`);
      const data = await res.json();
      if (!res.ok || !data.ok) throw new Error(data.error || 'Could not inspect audio clip.');
      state.clip = data;
      state.dsp = { ...DEFAULT_DSP, ...(data.dsp || {}) };
      state.version = data.edited ? 'edited' : 'original';
      setStatus(
        data.edited
          ? 'Saved in your Mod tray — tweak mix or drop a new file anytime.'
          : 'Drop any WAV, MP3, OGG or FLAC file to replace this clip.',
      );
    } catch (err) {
      state.clip = null;
      setStatus(err.message);
    } finally {
      state.loadingClip = false;
      renderStage();
    }
  }

  async function saveCurrentClip() {
    if (!state.clip || state.saving) return;
    if (!state.pendingWavBytes && !state.clip.edited) {
      setStatus('Drop or choose a replacement audio file first.');
      notify('Drop or choose a replacement audio file first.', 'info');
      return;
    }
    state.saving = true;
    renderFooterButtons();
    setStatus('Processing volume matching and saving to Mod tray…');
    try {
      const payload = {
        game_rel: state.clip.game_rel,
        dsp: state.dsp,
        label: state.clip.label || '',
        subtitle: state.clip.subtitle || '',
      };
      if (state.pendingWavBytes) {
        payload.wav_b64 = uint8ToBase64(state.pendingWavBytes);
      }
      const res = await fetchApi('/api/audio/save', {
        method: 'POST',
        body: JSON.stringify(payload),
      });
      const data = await res.json();
      if (!res.ok || !data.ok) throw new Error(data.error || 'Save failed.');
      stopPlayback();
      revokePendingUrl();
      state.pendingWavBytes = null;
      state.pendingFileName = '';
      state.pendingWave = null;
      if (data.clip) {
        state.clip = data.clip;
        state.dsp = { ...DEFAULT_DSP, ...(data.clip.dsp || {}) };
        state.version = 'edited';
      }
      setStatus('Saved to Mod tray — exports automatically in your mod .pak.');
      notify('Audio edit saved to Mod tray', 'success');
      if (state.clip?.bank_rel) await loadBankClips(state.clip.bank_rel, true);
      await loadCatalog(true);
      window.loadSidebar?.();
      renderStage();
    } catch (err) {
      setStatus(`Save error: ${err.message}`);
      notify(`Could not save audio edit: ${err.message}`, 'warning', 5000);
    } finally {
      state.saving = false;
      renderFooterButtons();
    }
  }

  async function resetCurrentClip() {
    if (!state.clip || state.saving) return;
    state.saving = true;
    renderFooterButtons();
    setStatus('Restoring original clip…');
    try {
      const res = await fetchApi('/api/audio/reset', {
        method: 'POST',
        body: JSON.stringify({ game_rel: state.clip.game_rel }),
      });
      const data = await res.json();
      if (!res.ok || !data.ok) throw new Error(data.error || 'Reset failed.');
      stopPlayback();
      revokePendingUrl();
      state.pendingWavBytes = null;
      state.pendingFileName = '';
      state.pendingWave = null;
      if (state.clip.bank_rel) await loadBankClips(state.clip.bank_rel, true);
      await loadCatalog(true);
      window.loadSidebar?.();
      await selectClip(state.clip.game_rel);
      notify('Audio clip restored to original', 'success');
    } catch (err) {
      setStatus(err.message);
    } finally {
      state.saving = false;
      renderFooterButtons();
    }
  }

  async function saveSubtitleNote(subtitle, label) {
    if (!state.clip) return;
    try {
      const res = await fetchApi('/api/audio/subtitle', {
        method: 'POST',
        body: JSON.stringify({
          media_id: state.clip.media_id,
          subtitle: subtitle || '',
          label: label || '',
          event: state.clip.event || '',
        }),
      });
      const data = await res.json();
      if (!res.ok || !data.ok) throw new Error(data.error || 'Could not save subtitle.');
      state.clip.subtitle = subtitle || '';
      state.clip.label = label || '';
      state.clip.subtitle_source = subtitle ? 'custom' : '';
      state.subEditorOpen = false;
      // Update cached bank clip label/subtitle immediately so left pane stays in sync.
      const bankClips = state.clipsByBank[state.clip.bank_rel];
      if (bankClips) {
        const hit = bankClips.find(c => c.game_rel === state.clip.game_rel);
        if (hit) {
          hit.subtitle = state.clip.subtitle;
          hit.label = state.clip.label;
        }
      }
      renderBrowser();
      renderStage();
      notify('Subtitle saved for this clip', 'success');
    } catch (err) {
      notify(err.message, 'warning');
    }
  }

  async function searchHeroSubtitles(query) {
    if (!state.clip) return;
    state.subSearchQuery = query;
    state.subSearchLoading = true;
    renderSubtitleSearchResults();
    try {
      const hero = encodeURIComponent(state.clip.hero_id || '');
      const q = encodeURIComponent(query || '');
      const res = await fetchApi(`/api/audio/subtitles/search?hero_id=${hero}&q=${q}`);
      const data = await res.json();
      state.subSearchHits = data.ok ? (data.lines || []) : [];
    } catch (_) {
      state.subSearchHits = [];
    } finally {
      state.subSearchLoading = false;
      renderSubtitleSearchResults();
    }
  }

  async function handleSubtitleImport(file) {
    if (!file) return;
    try {
      const content = await file.text();
      const res = await fetchApi('/api/audio/subtitles/import', {
        method: 'POST',
        body: JSON.stringify({ content, filename: file.name }),
      });
      const data = await res.json();
      if (!res.ok || !data.ok) throw new Error(data.error || 'Import failed.');
      notify(`Imported ${data.imported} subtitle entries from ${file.name}`, 'success');
      state.clipsByBank = {};
      for (const bankRel of state.openBanks) {
        await loadBankClips(bankRel, true);
      }
      if (state.selectedGameRel) await selectClip(state.selectedGameRel);
    } catch (err) {
      notify(`Subtitle import failed: ${err.message}`, 'warning', 5000);
    }
  }

  // ── DOM Rendering ──────────────────────────────────────────────────────────
  function ensureDialog() {
    if (dlg) return dlg;
    dlg = document.createElement('dialog');
    dlg.id = 'audio-studio-dialog';
    dlg.setAttribute('aria-labelledby', 'as-title');
    dlg.innerHTML = `
      <header class="as-head">
        <div class="as-head-title">
          <span class="as-head-icon" aria-hidden="true"><i data-lucide="folder-audio" size="18"></i></span>
          <div>
            <h2 id="as-title">Audio &amp; Voice Studio</h2>
            <p class="as-head-sub">Browse hero voice lines, read subtitles, and replace audio with automatic volume matching.</p>
          </div>
        </div>
        <div class="as-head-actions">
          <span class="as-tool-pill" id="as-tool-pill" title="Works out of the box with zero Wwise setup"><span class="as-tool-dot" aria-hidden="true"></span><span id="as-tool-label">Built-in PCM · Ready</span></span>
          <button type="button" class="btn" id="as-import-subs-btn" title="Import a JSON, CSV or TSV subtitle mapping sheet"><i data-lucide="folder-open" size="14"></i> Import subtitles</button>
          <input type="file" id="as-import-subs-input" accept=".json,.csv,.tsv,.txt" hidden>
          <button type="button" class="sb-clear" id="as-refresh-btn" title="Refresh audio catalogue" aria-label="Refresh audio catalogue"><i data-lucide="refresh-cw" size="15"></i></button>
          <button type="button" class="sb-clear" id="as-close-btn" title="Close" aria-label="Close Audio Studio"><i data-lucide="x" size="16"></i></button>
        </div>
      </header>
      <div class="as-workbench">
        <aside class="as-browser" aria-label="SoundBank and voice line browser">
          <div class="as-browser-top">
            <div class="as-search-wrap">
              <i data-lucide="search" size="14"></i>
              <input id="as-search-input" type="search" placeholder="Search hero, bank, ID or subtitle…" aria-label="Search audio banks and subtitles" autocomplete="off" spellcheck="false">
            </div>
            <div class="as-cats" id="as-cats" role="group" aria-label="Audio categories">
              <button type="button" class="as-cat-pill" data-cat="all" aria-pressed="true">All</button>
              <button type="button" class="as-cat-pill" data-cat="heroes" aria-pressed="false">Heroes</button>
              <button type="button" class="as-cat-pill" data-cat="ui" aria-pressed="false">UI &amp; Announcer</button>
              <button type="button" class="as-cat-pill" data-cat="music" aria-pressed="false">Music</button>
              <button type="button" class="as-cat-pill" data-cat="edited" aria-pressed="false" id="as-cat-edited">Edited</button>
            </div>
          </div>
          <div class="as-browser-list" id="as-browser-list"></div>
        </aside>
        <section class="as-stage" id="as-stage" aria-label="Clip waveform and mix editor"></section>
      </div>
      <footer class="as-foot">
        <span class="as-status" id="as-status" role="status"></span>
        <div class="as-foot-actions">
          <button type="button" class="btn" id="as-reset-btn" hidden><i data-lucide="rotate-ccw" size="13"></i> Reset to original</button>
          <button type="button" class="btn primary" id="as-save-btn" disabled><i data-lucide="save" size="13"></i> Save edit</button>
        </div>
      </footer>
    `;
    document.body.append(dlg);

    dlg.querySelector('#as-close-btn').addEventListener('click', close);
    dlg.querySelector('#as-refresh-btn').addEventListener('click', () => {
      state.clipsByBank = {};
      loadCatalog(true);
    });
    dlg.querySelector('#as-import-subs-btn').addEventListener('click', () => {
      dlg.querySelector('#as-import-subs-input').click();
    });
    dlg.querySelector('#as-import-subs-input').addEventListener('change', e => {
      const f = e.target.files?.[0];
      e.target.value = '';
      if (f) handleSubtitleImport(f);
    });
    dlg.querySelector('#as-search-input').addEventListener('input', e => {
      state.query = e.target.value;
      renderBrowser();
    });
    dlg.querySelector('#as-cats').addEventListener('click', e => {
      const btn = e.target.closest('.as-cat-pill');
      if (!btn) return;
      state.category = btn.dataset.cat || 'all';
      dlg.querySelectorAll('.as-cat-pill').forEach(b => b.setAttribute('aria-pressed', String(b === btn)));
      renderBrowser();
    });
    dlg.querySelector('#as-save-btn').addEventListener('click', saveCurrentClip);
    dlg.querySelector('#as-reset-btn').addEventListener('click', resetCurrentClip);

    dlg.addEventListener('cancel', e => {
      e.preventDefault();
      close();
    });
    dlg.addEventListener('click', e => {
      if (e.target === dlg) close();
    });
    dlg.addEventListener('keydown', e => {
      if (e.code === 'Space' && !e.ctrlKey && !e.metaKey && !e.altKey) {
        const t = e.target;
        if (!(t instanceof HTMLElement && t.closest('input, textarea, select, button, summary'))) {
          e.preventDefault();
          togglePlay();
        }
      }
    });
    window.addEventListener('resize', () => {
      if (dlg?.open) drawWaveform();
    });
    if (window.lucide) window.lucide.createIcons({ nodes: [dlg] });
    return dlg;
  }

  function updateToolBadge() {
    if (!dlg || !state.catalog) return;
    const tools = state.catalog.tools || {};
    const label = dlg.querySelector('#as-tool-label');
    const pill = dlg.querySelector('#as-tool-pill');
    if (tools.has_vgmstream && tools.has_wav2wem) {
      label.textContent = 'Vorbis & preview ready';
      pill.title = 'Full Wwise Vorbis encoding and compressed audio preview are active automatically.';
    } else if (tools.has_wav2wem) {
      label.textContent = 'Vorbis encoder ready';
      pill.title = 'Zero-setup Wwise Vorbis encoding is active; PCM clips preview directly.';
    } else {
      label.textContent = 'Built-in PCM · Ready';
      pill.title = 'Zero-setup built-in Wwise PCM engine active — drop any WAV, MP3, OGG or FLAC file.';
    }
    const edBtn = dlg.querySelector('#as-cat-edited');
    if (edBtn) {
      const n = state.catalog.edited_count || 0;
      edBtn.textContent = n ? `Edited (${n})` : 'Edited';
    }
  }

  function renderClipRow(clip, isSelected) {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'as-clip-row';
    btn.setAttribute('aria-selected', String(isSelected));
    const top = document.createElement('span');
    top.className = 'as-clip-row-top';
    if (clip.edited) {
      const dot = document.createElement('span');
      dot.className = 'as-edited-dot';
      dot.title = 'Edited in this project';
      top.append(dot);
    }
    const title = document.createElement('span');
    title.className = 'as-clip-title' + (clip.subtitle ? ' is-quote' : '');
    title.textContent = clip.subtitle
      ? `“${clip.subtitle}”`
      : (clip.label || `Clip #${clip.media_id}`);
    top.append(title);

    const sub = document.createElement('span');
    sub.className = 'as-clip-sub';
    const metaBits = [`#${clip.media_id}`];
    if (clip.duration) metaBits.push(`${Number(clip.duration).toFixed(2)}s`);
    if (clip.codec && clip.codec !== 'Unknown') metaBits.push(clip.codec);
    else if (clip.bank_stem) metaBits.push(clip.bank_stem);
    sub.textContent = metaBits.join(' · ');

    btn.append(top, sub);
    btn.addEventListener('click', () => selectClip(clip.game_rel));
    return btn;
  }

  function renderBrowser() {
    if (!dlg) return;
    const list = dlg.querySelector('#as-browser-list');
    list.replaceChildren();

    if (state.loadingCatalog && !state.catalog) {
      const loading = document.createElement('div');
      loading.className = 'as-browser-empty';
      loading.textContent = 'Scanning game SoundBanks & subtitles…';
      list.append(loading);
      return;
    }

    if (!state.catalog) {
      const empty = document.createElement('div');
      empty.className = 'as-browser-empty';
      empty.textContent = 'Set your game Paks folder in Settings to browse audio banks.';
      list.append(empty);
      return;
    }

    // Edited-only view shows all saved project audio edits immediately without opening banks.
    if (state.category === 'edited') {
      const edited = filterClips(state.catalog.edited_items || [], state.query);
      if (!edited.length) {
        const empty = document.createElement('div');
        empty.className = 'as-browser-empty';
        empty.textContent = state.query
          ? 'No edited clips match your search.'
          : 'No edited audio clips in this project yet. Pick any SoundBank to get started.';
        list.append(empty);
        return;
      }
      const head = document.createElement('div');
      head.className = 'as-group-label';
      head.textContent = `Edited in project (${edited.length})`;
      list.append(head);
      for (const item of edited) {
        list.append(renderClipRow({ ...item, edited: true }, item.game_rel === state.selectedGameRel));
      }
      return;
    }

    const banks = filterBanks(state.catalog.banks || [], state.query, state.category, state.clipsByBank);
    const streams = (state.catalog.streams || []).filter(s => {
      if (state.category !== 'all' && s.category !== state.category) return false;
      if (!state.query.trim()) return true;
      const hay = `${s.media_id} ${s.group_label} ${s.pak_entry}`.toLowerCase();
      return state.query.trim().toLowerCase().split(/\s+/).every(t => hay.includes(t));
    });

    if (!banks.length && !streams.length) {
      const empty = document.createElement('div');
      empty.className = 'as-browser-empty';
      empty.textContent = state.catalog.banks?.length
        ? 'No SoundBanks or loaded subtitles match your filter.'
        : 'No Wwise SoundBanks (.bnk) were found in your configured Paks folder.';
      list.append(empty);
      return;
    }

    const editedSet = new Set(state.catalog.edited_rels || []);
    if (banks.length) {
      const head = document.createElement('div');
      head.className = 'as-group-label';
      head.textContent = `SoundBanks (${banks.length})`;
      list.append(head);
    }

    for (const bank of banks.slice(0, 120)) {
      const isOpen = state.openBanks.has(bank.bank_rel);
      const card = document.createElement('div');
      card.className = 'as-bank' + (isOpen ? ' is-open' : '');

      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'as-bank-btn';
      btn.setAttribute('aria-expanded', String(isOpen));
      btn.innerHTML = `
        <span class="as-bank-title">
          <span class="as-bank-name"></span>
          <span class="as-bank-meta"></span>
        </span>
        <i data-lucide="chevron-down" size="14" class="as-bank-chev"></i>
      `;
      btn.querySelector('.as-bank-name').textContent = bank.group_label || bank.stem;
      const clips = state.clipsByBank[bank.bank_rel];
      btn.querySelector('.as-bank-meta').textContent =
        `${bank.stem} · ${clips ? `${clips.length} clips` : formatSize(bank.size)}`;
      btn.addEventListener('click', () => {
        if (state.openBanks.has(bank.bank_rel)) {
          state.openBanks.delete(bank.bank_rel);
          renderBrowser();
        } else {
          state.openBanks.add(bank.bank_rel);
          loadBankClips(bank.bank_rel);
        }
      });
      card.append(btn);

      if (isOpen) {
        const body = document.createElement('div');
        body.className = 'as-bank-clips';
        if (state.loadingBanks.has(bank.bank_rel) && !clips) {
          const msg = document.createElement('div');
          msg.className = 'as-clip-sub';
          msg.style.padding = '6px 8px';
          msg.textContent = 'Reading SoundBank clips…';
          body.append(msg);
        } else {
          const visibleClips = filterClips(clips || [], state.query);
          if (!visibleClips.length) {
            const msg = document.createElement('div');
            msg.className = 'as-clip-sub';
            msg.style.padding = '6px 8px';
            msg.textContent = clips?.length ? 'No clips match this search.' : 'No embedded clips in this bank.';
            body.append(msg);
          } else {
            for (const clip of visibleClips.slice(0, 150)) {
              body.append(renderClipRow(
                { ...clip, edited: clip.edited || editedSet.has(clip.game_rel) },
                clip.game_rel === state.selectedGameRel,
              ));
            }
          }
        }
        card.append(body);
      }
      list.append(card);
    }

    if (streams.length) {
      const head = document.createElement('div');
      head.className = 'as-group-label';
      head.textContent = `Streamed audio (${streams.length})`;
      list.append(head);
      for (const s of streams.slice(0, 80)) {
        list.append(renderClipRow(
          {
            game_rel: s.game_rel,
            media_id: s.media_id,
            label: `${s.group_label} · #${s.media_id}`,
            edited: editedSet.has(s.game_rel),
          },
          s.game_rel === state.selectedGameRel,
        ));
      }
    }

    if (window.lucide) window.lucide.createIcons({ nodes: [list] });
  }

  function renderSubtitleSearchResults() {
    const host = dlg?.querySelector('#as-sub-search-results');
    if (!host) return;
    host.replaceChildren();
    if (state.subSearchLoading) {
      const p = document.createElement('div');
      p.className = 'as-clip-sub';
      p.textContent = 'Searching game subtitles…';
      host.append(p);
      return;
    }
    if (!state.subSearchHits.length) {
      const p = document.createElement('div');
      p.className = 'as-clip-sub';
      p.textContent = 'No matching game subtitles found. You can also import a JSON/CSV subtitle sheet from the header.';
      host.append(p);
      return;
    }
    for (const hit of state.subSearchHits.slice(0, 40)) {
      const row = document.createElement('div');
      row.className = 'as-sub-hit';
      const copy = document.createElement('div');
      copy.className = 'as-sub-hit-text';
      copy.textContent = hit.text;
      const key = document.createElement('span');
      key.className = 'as-sub-hit-key';
      key.textContent = hit.key;
      copy.append(key);

      const linkBtn = document.createElement('button');
      linkBtn.type = 'button';
      linkBtn.className = 'btn';
      linkBtn.textContent = 'Link';
      linkBtn.addEventListener('click', () => {
        saveSubtitleNote(hit.text, state.clip?.label || '');
      });
      row.append(copy, linkBtn);
      host.append(row);
    }
  }

  function renderFooterButtons() {
    if (!dlg) return;
    const saveBtn = dlg.querySelector('#as-save-btn');
    const resetBtn = dlg.querySelector('#as-reset-btn');
    const canSave = !!(state.clip && !state.saving && (state.pendingWavBytes || state.clip.edited));
    if (saveBtn) saveBtn.disabled = !canSave;
    if (resetBtn) {
      resetBtn.hidden = !(state.clip && state.clip.edited);
      resetBtn.disabled = state.saving;
    }
  }

  function renderStage() {
    if (!dlg) return;
    const stage = dlg.querySelector('#as-stage');
    stage.replaceChildren();
    renderFooterButtons();

    if (state.loadingClip) {
      const box = document.createElement('div');
      box.className = 'as-empty-stage';
      box.innerHTML = '<span class="spinner" aria-hidden="true"></span><p>Loading clip waveform and subtitle…</p>';
      stage.append(box);
      return;
    }

    if (!state.clip) {
      const box = document.createElement('div');
      box.className = 'as-empty-stage';
      box.innerHTML = `
        <i data-lucide="folder-audio" size="40"></i>
        <h3>Choose a voice line or sound clip</h3>
        <p>Open any SoundBank on the left to inspect its clips and associated subtitle lines. Drop any <strong>WAV, MP3, OGG or FLAC</strong> file to replace a clip — Atelier automatically matches in-game loudness and packs it cleanly into your mod.</p>
      `;
      stage.append(box);
      if (window.lucide) window.lucide.createIcons({ nodes: [box] });
      return;
    }

    const clip = state.clip;
    const hasEdited = !!(clip.edited || state.pendingWavBytes);
    const wem = clip.wem || {};
    const origLufs = clip.original_wave?.lufs;
    const editLufs = clip.edited_wave?.lufs;

    // 1. Clip Header + Original/Edited A/B Toggle
    const head = document.createElement('div');
    head.className = 'as-clip-head';
    head.innerHTML = `
      <div>
        <div class="as-clip-crumb"></div>
        <h3 class="as-clip-heading"></h3>
        <div class="as-specs"></div>
      </div>
      <div class="as-ab-segment" role="group" aria-label="Preview version">
        <button type="button" id="as-ver-orig" aria-pressed="${state.version === 'original'}">Original</button>
        <button type="button" id="as-ver-edit" aria-pressed="${state.version === 'edited'}" ${hasEdited ? '' : 'disabled'}>Edited</button>
      </div>
    `;
    head.querySelector('.as-clip-crumb').textContent =
      [clip.group_label, clip.bank_stem || 'Stream', `#${clip.media_id}`].filter(Boolean).join(' · ');
    head.querySelector('.as-clip-heading').textContent =
      clip.label || (clip.subtitle ? clip.subtitle.slice(0, 48) : `Clip #${clip.media_id}`);
    const specs = head.querySelector('.as-specs');
    const specList = [
      wem.codec || 'WEM',
      wem.sample_rate ? `${Math.round(wem.sample_rate / 1000)} kHz` : '',
      wem.channels === 1 ? 'Mono' : wem.channels ? `${wem.channels} ch` : '',
      wem.duration ? `${Number(wem.duration).toFixed(2)}s` : '',
    ].filter(Boolean);
    for (const text of specList) {
      const chip = document.createElement('span');
      chip.className = 'as-spec-chip';
      chip.textContent = text;
      specs.append(chip);
    }
    head.querySelector('#as-ver-orig').addEventListener('click', () => {
      if (state.version === 'original') return;
      stopPlayback();
      state.version = 'original';
      renderStage();
    });
    head.querySelector('#as-ver-edit').addEventListener('click', () => {
      if (!hasEdited || state.version === 'edited') return;
      stopPlayback();
      state.version = 'edited';
      renderStage();
    });
    stage.append(head);

    // 2. Associated Subtitle Card
    const subCard = document.createElement('section');
    subCard.className = 'as-subtitle-card';
    subCard.setAttribute('aria-label', 'Associated subtitle');
    const srcLabel = clip.subtitle_source === 'soundbanks_info' || clip.subtitle_source === 'locres'
      ? 'From game subtitles'
      : clip.subtitle_source === 'custom'
        ? 'Custom note'
        : clip.subtitle ? 'Linked' : 'Not linked yet';

    subCard.innerHTML = `
      <div class="as-subtitle-top">
        <span class="as-subtitle-eyebrow">Associated subtitle <span class="as-sub-source"></span></span>
        <div class="as-subtitle-actions">
          <button type="button" class="btn" id="as-find-sub-btn"><i data-lucide="search" size="13"></i> Find hero subtitle</button>
          <button type="button" class="btn" id="as-edit-sub-btn"><i data-lucide="pencil" size="13"></i> Edit note</button>
        </div>
      </div>
      <p class="as-subtitle-quote ${clip.subtitle ? '' : 'is-empty'}"></p>
    `;
    subCard.querySelector('.as-sub-source').textContent = srcLabel;
    subCard.querySelector('.as-subtitle-quote').textContent = clip.subtitle
      ? `“${clip.subtitle}”`
      : 'No subtitle line linked to this clip yet — search hero subtitles or add your own label.';

    subCard.querySelector('#as-edit-sub-btn').addEventListener('click', () => {
      state.subEditorOpen = !state.subEditorOpen;
      renderStage();
    });
    subCard.querySelector('#as-find-sub-btn').addEventListener('click', () => {
      state.subSearchOpen = !state.subSearchOpen;
      renderStage();
      if (state.subSearchOpen) searchHeroSubtitles(state.subSearchQuery);
    });

    if (state.subEditorOpen) {
      const ed = document.createElement('div');
      ed.className = 'as-subtitle-editor';
      ed.innerHTML = `
        <div class="as-subtitle-fields">
          <label class="as-field">Friendly label<input type="text" id="as-label-input" placeholder="e.g. Ultimate activation"></label>
          <label class="as-field">Subtitle line<input type="text" id="as-subtitle-input" placeholder="Spoken dialogue line…"></label>
        </div>
        <div class="as-subtitle-actions">
          <button type="button" class="btn primary" id="as-save-sub-btn"><i data-lucide="check" size="13"></i> Save note</button>
          <button type="button" class="btn" id="as-cancel-sub-btn">Cancel</button>
        </div>
      `;
      ed.querySelector('#as-label-input').value = clip.label || '';
      ed.querySelector('#as-subtitle-input').value = clip.subtitle || '';
      ed.querySelector('#as-save-sub-btn').addEventListener('click', () => {
        saveSubtitleNote(
          ed.querySelector('#as-subtitle-input').value.trim(),
          ed.querySelector('#as-label-input').value.trim(),
        );
      });
      ed.querySelector('#as-cancel-sub-btn').addEventListener('click', () => {
        state.subEditorOpen = false;
        renderStage();
      });
      subCard.append(ed);
    }

    if (state.subSearchOpen) {
      const drawer = document.createElement('div');
      drawer.className = 'as-sub-search-drawer';
      drawer.innerHTML = `
        <div class="as-search-wrap">
          <i data-lucide="search" size="14"></i>
          <input type="search" id="as-sub-search-input" placeholder="Search hero dialogue lines from game .locres…" autocomplete="off">
        </div>
        <div class="as-sub-search-results" id="as-sub-search-results"></div>
      `;
      const input = drawer.querySelector('#as-sub-search-input');
      input.value = state.subSearchQuery;
      let timer = 0;
      input.addEventListener('input', () => {
        clearTimeout(timer);
        timer = setTimeout(() => searchHeroSubtitles(input.value), 180);
      });
      subCard.append(drawer);
    }
    stage.append(subCard);

    // 3. Waveform Stage & Transport
    const waveCard = document.createElement('section');
    waveCard.className = 'as-wave-card';
    waveCard.setAttribute('aria-label', 'Audio waveform preview');
    waveCard.innerHTML = `
      <div class="as-wave-canvas-wrap" id="as-wave-wrap" title="Click anywhere on the waveform to seek">
        <canvas id="as-wave-canvas"></canvas>
      </div>
      ${state.version === 'original' && clip.original_error ? `<div class="as-wave-notice"></div>` : ''}
      <div class="as-transport">
        <div class="as-transport-left">
          <button type="button" class="as-play-btn" id="as-play-btn">${PLAY_SVG}<span>Play</span></button>
          <button type="button" class="btn" id="as-loop-btn" aria-pressed="${state.loop}" title="Loop playback"><i data-lucide="refresh-cw" size="13"></i> Loop</button>
          <span class="as-time" id="as-time">0:00.00 / 0:00.00</span>
        </div>
        <span class="as-lufs-readout" id="as-lufs-readout"></span>
      </div>
    `;
    const noticeEl = waveCard.querySelector('.as-wave-notice');
    if (noticeEl) {
      noticeEl.textContent = `${clip.original_error} You can still drop and audition your replacement clip below.`;
    }
    const lufsParts = [];
    if (typeof origLufs === 'number') lufsParts.push(`Original: ${origLufs.toFixed(1)} LUFS`);
    if (state.version === 'edited' && typeof editLufs === 'number') {
      lufsParts.push(`Edited: ${editLufs.toFixed(1)} LUFS`);
    } else if (state.dsp.match_lufs && typeof origLufs === 'number') {
      lufsParts.push('Auto-match ON');
    }
    waveCard.querySelector('#as-lufs-readout').textContent = lufsParts.join(' · ');

    waveCard.querySelector('#as-play-btn').addEventListener('click', togglePlay);
    waveCard.querySelector('#as-loop-btn').addEventListener('click', e => {
      state.loop = !state.loop;
      e.currentTarget.setAttribute('aria-pressed', String(state.loop));
      if (audioEl) audioEl.loop = state.loop;
    });
    const wrap = waveCard.querySelector('#as-wave-wrap');
    wrap.addEventListener('click', e => {
      const r = wrap.getBoundingClientRect();
      seekToFraction((e.clientX - r.left) / Math.max(1, r.width));
    });
    stage.append(waveCard);

    // 4. Universal Dropzone (WAV / MP3 / OGG / FLAC / M4A)
    const drop = document.createElement('div');
    drop.className = 'as-dropzone';
    drop.setAttribute('role', 'button');
    drop.setAttribute('tabindex', '0');
    drop.innerHTML = `
      <div class="as-drop-copy">
        <span class="as-drop-title"></span>
        <span class="as-drop-hint">Accepts WAV, MP3, OGG, FLAC or M4A — converted automatically, no FFmpeg or Wwise setup needed.</span>
      </div>
      <span class="btn"><i data-lucide="arrow-up-from-line" size="13"></i> Choose file…</span>
      <input type="file" id="as-file-input" accept="audio/*,.wav,.mp3,.ogg,.flac,.m4a" hidden>
    `;
    drop.querySelector('.as-drop-title').textContent = state.pendingFileName
      ? `Replacement ready: ${state.pendingFileName} (drop another to swap)`
      : 'Drop a replacement audio file here, or click to browse';
    const fileInput = drop.querySelector('#as-file-input');
    drop.addEventListener('click', () => fileInput.click());
    drop.addEventListener('keydown', e => {
      if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); fileInput.click(); }
    });
    fileInput.addEventListener('change', e => {
      const f = e.target.files?.[0];
      e.target.value = '';
      if (f) handleDroppedFile(f);
    });
    drop.addEventListener('dragover', e => { e.preventDefault(); drop.classList.add('is-dragover'); });
    drop.addEventListener('dragleave', () => drop.classList.remove('is-dragover'));
    drop.addEventListener('drop', e => {
      e.preventDefault();
      drop.classList.remove('is-dragover');
      const f = e.dataTransfer?.files?.[0];
      if (f) handleDroppedFile(f);
    });
    stage.append(drop);

    // 5. Beginner-Friendly Mix & Polish Card
    const mix = document.createElement('section');
    mix.className = 'as-mix-card';
    mix.setAttribute('aria-label', 'Loudness and trim controls');
    mix.innerHTML = `
      <label class="as-switch-row">
        <span class="as-switch-copy">
          <strong>Match original loudness (LUFS)</strong>
          <span>Normalises your replacement to match in-game volume with true-peak clipping protection.</span>
        </span>
        <input type="checkbox" class="switch" id="as-match-lufs">
      </label>
      <details class="as-advanced">
        <summary>Fine-tune gain, trim &amp; fades</summary>
        <div class="as-advanced-grid">
          <label class="as-gain-row">
            <span class="as-gain-head"><span>Extra gain</span><output id="as-gain-out"></output></span>
            <input type="range" id="as-gain" min="-12" max="12" step="0.5">
          </label>
          <label class="as-field">Trim start (seconds)<input type="number" id="as-trim-start" min="0" step="0.05"></label>
          <label class="as-field">Trim end (seconds)<input type="number" id="as-trim-end" min="0" step="0.05"></label>
          <label class="as-field">Fade in (ms)<input type="number" id="as-fade-in" min="0" max="5000" step="10"></label>
          <label class="as-field">Fade out (ms)<input type="number" id="as-fade-out" min="0" max="5000" step="10"></label>
        </div>
      </details>
    `;
    const lufsChk = mix.querySelector('#as-match-lufs');
    const gainInput = mix.querySelector('#as-gain');
    const gainOut = mix.querySelector('#as-gain-out');
    const trimStart = mix.querySelector('#as-trim-start');
    const trimEnd = mix.querySelector('#as-trim-end');
    const fadeIn = mix.querySelector('#as-fade-in');
    const fadeOut = mix.querySelector('#as-fade-out');

    lufsChk.checked = !!state.dsp.match_lufs;
    gainInput.value = String(state.dsp.gain_db ?? 0);
    gainOut.textContent = `${Number(state.dsp.gain_db || 0) >= 0 ? '+' : ''}${Number(state.dsp.gain_db || 0).toFixed(1)} dB`;
    trimStart.value = String(state.dsp.trim_start ?? 0);
    trimEnd.value = String(state.dsp.trim_end ?? 0);
    fadeIn.value = String(state.dsp.fade_in_ms ?? 0);
    fadeOut.value = String(state.dsp.fade_out_ms ?? 15);

    lufsChk.addEventListener('change', () => { state.dsp.match_lufs = lufsChk.checked; });
    gainInput.addEventListener('input', () => {
      state.dsp.gain_db = parseFloat(gainInput.value) || 0;
      gainOut.textContent = `${state.dsp.gain_db >= 0 ? '+' : ''}${state.dsp.gain_db.toFixed(1)} dB`;
    });
    const syncOverlay = () => {
      state.dsp.trim_start = Math.max(0, parseFloat(trimStart.value) || 0);
      state.dsp.trim_end = Math.max(0, parseFloat(trimEnd.value) || 0);
      state.dsp.fade_in_ms = Math.max(0, parseFloat(fadeIn.value) || 0);
      state.dsp.fade_out_ms = Math.max(0, parseFloat(fadeOut.value) || 0);
      drawWaveform();
    };
    trimStart.addEventListener('input', syncOverlay);
    trimEnd.addEventListener('input', syncOverlay);
    fadeIn.addEventListener('input', syncOverlay);
    fadeOut.addEventListener('input', syncOverlay);
    stage.append(mix);

    if (window.lucide) window.lucide.createIcons({ nodes: [stage] });
    if (state.subSearchOpen) renderSubtitleSearchResults();
    updateTransportReadout();
    requestAnimationFrame(drawWaveform);
  }

  // ── Public lifecycle ───────────────────────────────────────────────────────
  async function open() {
    const dialog = ensureDialog();
    if (!dialog.open) dialog.showModal();
    renderStage();
    await loadCatalog(!state.catalog);
  }

  async function openClip(gameRel) {
    const dialog = ensureDialog();
    if (!dialog.open) dialog.showModal();
    await loadCatalog(!state.catalog);
    const parts = String(gameRel || '').replace(/\\/g, '/').split('/');
    if (parts.length >= 4 && parts[0].toLowerCase() === 'audio' && parts[1].toLowerCase() === 'banks') {
      const bankStem = parts[2].toLowerCase();
      const bank = (state.catalog?.banks || []).find(b => (b.stem || '').toLowerCase() === bankStem);
      if (bank) {
        state.openBanks.add(bank.bank_rel);
        await loadBankClips(bank.bank_rel);
      }
    }
    await selectClip(gameRel);
  }

  function close() {
    stopPlayback();
    revokePendingUrl();
    if (dlg?.open) dlg.close();
  }

  window.AtelierAudioStudio = Object.freeze({
    open,
    openClip,
    close,
    encodePcm16Wav,
    peaksFromChannels,
    uint8ToBase64,
    formatTime,
    filterClips,
    filterBanks,
  });
})();

// Short, event-driven Krackle formations for the everyday editing workflow.
// Presentation only: callers commit navigation/selection/imports before playing.
(() => {
  'use strict';
  const active = new Map();
  const durations = {hero: 500, navigation: 480, editor: 520, arrival: 560};
  const clamp = value => Math.max(0, Math.min(1, value));
  const easeOut = value => 1 - (1 - clamp(value)) ** 3;
  const mode = () => window.AtelierMotionPolicy?.mode() || 'off';

  function stop() { for (const dispose of [...active.values()]) dispose(); }
  function visibleBounds(host) {
    if (!host?.isConnected || !host.getClientRects().length) return null;
    const box = host.getBoundingClientRect();
    let left = Math.max(0, box.left), top = Math.max(0, box.top);
    let right = Math.min(innerWidth, box.right), bottom = Math.min(innerHeight, box.bottom);
    for (let parent = host.parentElement; parent && parent !== document.body; parent = parent.parentElement) {
      const css = getComputedStyle(parent), rect = parent.getBoundingClientRect();
      if (/(auto|scroll|hidden|clip)/.test(css.overflowX)) { left = Math.max(left, rect.left); right = Math.min(right, rect.right); }
      if (/(auto|scroll|hidden|clip)/.test(css.overflowY)) { top = Math.max(top, rect.top); bottom = Math.min(bottom, rect.bottom); }
    }
    return right - left > 4 && bottom - top > 4 ? {left, top, width: right - left, height: bottom - top} : null;
  }
  function permitted(host) {
    if (document.hidden || mode() === 'off') return false;
    // Effects in the workspace never float over a modal the user is working in.
    const overlays = [...document.querySelectorAll('.overlay.active, dialog[open]')];
    return overlays.every(overlay => overlay.contains(host));
  }
  function run(kind, host, direction) {
    if (!durations[kind] || !host || !permitted(host)) return false;
    const rect = visibleBounds(host);
    if (!rect) return false;
    active.get(host)?.();
    while (active.size >= 3) active.values().next().value();
    const ink = getComputedStyle(host).getPropertyValue('--krackle-charge').trim() || '#2a9fd6';

    if (mode() === 'calm') {
      if (typeof host.animate !== 'function') return false;
      const resting = getComputedStyle(host).boxShadow;
      const animation = host.animate([
        {boxShadow: resting}, {boxShadow: `inset 0 -2px 0 ${ink}`, offset: .35}, {boxShadow: resting},
      ], {duration: 180, easing: 'ease-out'});
      let disposed = false;
      const dispose = () => { if (disposed) return; disposed = true; animation.cancel(); active.delete(host); clearTimeout(timer); };
      const timer = setTimeout(dispose, 220);
      active.set(host, dispose);
      animation.finished.then(dispose, dispose);
      return true;
    }

    // Wide arrivals share the existing large-moment owner with import/export stages.
    const canvas = document.createElement('canvas');
    canvas.className = 'k-workflow-canvas'; canvas.dataset.workflowKind = kind;
    canvas.setAttribute('aria-hidden', 'true'); canvas.inert = true;
    const pad = 12, width = rect.width + pad * 2;
    const height = (kind === 'navigation' || kind === 'editor' ? 24 : rect.height) + pad * 2;
    const left = rect.left - pad;
    const top = (kind === 'navigation' || kind === 'editor' ? rect.top + rect.height - 16 : rect.top) - pad;
    Object.assign(canvas.style, {left: left + 'px', top: top + 'px', width: width + 'px', height: height + 'px'});
    const scale = Math.min(devicePixelRatio || 1, 2);
    canvas.width = Math.ceil(width * scale); canvas.height = Math.ceil(height * scale);
    let ctx;
    try { ctx = canvas.getContext('2d'); } catch (_) {}
    if (!ctx) return false;
    ctx.scale(scale, scale);
    const release = kind === 'navigation' || kind === 'editor'
      ? window.AtelierMotion?.moment?.claim('workflow-' + kind, 2) : () => {};
    if (!release) return false;
    let frame = 0, start = null, disposed = false, timer;
    const dispose = () => {
      if (disposed) return;
      disposed = true; cancelAnimationFrame(frame); clearTimeout(timer); canvas.remove();
      active.delete(host); release();
    };
    active.set(host, dispose);
    document.body.append(canvas);

    // One energy ink, crisp punched holes and a few Paper glints, as in the stage.
    const paper = getComputedStyle(host).getPropertyValue('--krackle-glint').trim() || '#eee5cf';
    function dot(x, y, radius, opacity, bubble = false) {
      if (radius < .2 || opacity <= 0) return;
      ctx.globalAlpha = opacity; ctx.fillStyle = ink;
      ctx.beginPath(); ctx.arc(x, y, radius, 0, Math.PI * 2); ctx.fill();
      if (bubble && radius > 3) {
        ctx.globalCompositeOperation = 'destination-out';
        ctx.beginPath(); ctx.arc(x + radius * .27, y + radius * .25, radius * .3, 0, Math.PI * 2); ctx.fill();
        ctx.globalCompositeOperation = 'source-over';
        ctx.fillStyle = paper; ctx.beginPath(); ctx.arc(x - radius * .34, y - radius * .35, radius * .1, 0, Math.PI * 2); ctx.fill();
      }
    }
    function draw(t) {
      ctx.clearRect(0, 0, width, height);
      const fade = 1 - clamp((t - .62) / .38), w = rect.width, h = rect.height;
      if (kind === 'navigation' || kind === 'editor') {
        const back = direction === 'back', travel = easeOut(t), y = height / 2;
        for (let i = 0; i < 22; i++) {
          const lag = i / 30, p = clamp((travel - lag) / (1 - lag));
          if (travel < lag) continue;
          const x = pad + (back ? 1 - p : p) * w;
          const r = (i < 5 ? 5.6 - i * .65 : 1.4 + (i % 3) * .65) * Math.sin(Math.PI * clamp(p * .94 + .03));
          dot(x, y + Math.sin(i * 2.4 + p * 5) * (i < 5 ? 3 : 7), r, fade * (1 - i / 32), i < 5);
          if (kind === 'editor') dot(width - x, y - 3, r * .72, fade * .75, i < 3);
        }
      } else if (kind === 'hero') {
        // The mass gathers along the selected portrait's lower edge, leaving its face clear.
        const swell = Math.sin(Math.PI * clamp(t / .85));
        for (let i = 0; i < 15; i++) {
          const p = i / 14, x = pad + w * (.08 + .84 * p);
          const y = pad + h - 3 - Math.sin(p * Math.PI) * (5 + 9 * easeOut(t));
          const r = (i > 8 ? 3.8 + i % 3 : 1.5 + i % 2) * Math.max(0, swell);
          dot(x, y, r, fade * .95, i > 8);
        }
      } else {
        // A small ink catch closes around the real imported/saved thumbnail.
        const settle = easeOut(t), cx = width / 2, cy = height / 2;
        for (let i = 0; i < 12; i++) {
          const angle = i / 12 * Math.PI * 2, radius = (1 - settle) * 16;
          const x = cx + Math.cos(angle) * (w * .48 + radius);
          const y = cy + Math.sin(angle) * (h * .44 + radius) - Math.sin(t * Math.PI) * 4;
          dot(x, y, (i < 4 ? 5.8 - i * .6 : 2 + i % 3 * .4) * Math.sin(Math.PI * clamp(t * 1.1 + .03)), fade, i < 4);
        }
      }
      ctx.globalAlpha = 1;
    }
    function tick(now) {
      const current = visibleBounds(host);
      if (!permitted(host) || !current || mode() !== 'full' || Math.abs(current.width - rect.width) > 1 || Math.abs(current.height - rect.height) > 1) { dispose(); return; }
      // Editors can recenter when their parameters arrive; follow their real edge.
      canvas.style.left = (current.left - pad) + 'px';
      canvas.style.top = ((kind === 'navigation' || kind === 'editor' ? current.top + current.height - 16 : current.top) - pad) + 'px';
      if (start === null) start = now;
      const t = clamp((now - start) / durations[kind]);
      try { draw(t); } catch (_) { dispose(); return; }
      if (t < 1) frame = requestAnimationFrame(tick); else dispose();
    }
    frame = requestAnimationFrame(tick);
    timer = setTimeout(dispose, durations[kind] + 200);
    return true;
  }
  const present = (kind, host, direction) => { try { return run(kind, host, direction); } catch (_) { active.get(host)?.(); return false; } };
  window.AtelierMotion ||= {};
  window.AtelierMotion.workflow = Object.freeze({
    hero: host => present('hero', host),
    navigation: (host, direction) => present('navigation', host, direction),
    editor: host => present('editor', host),
    arrival: host => present('arrival', host),
    stop,
  });
  window.AtelierMotionPolicy?.query().addEventListener('change', stop);
  window.addEventListener('atelier:inks', stop);
  window.addEventListener('resize', stop);
  document.addEventListener('scroll', stop, {capture: true, passive: true});
  document.addEventListener('visibilitychange', () => { if (document.hidden) stop(); });
  window.addEventListener('pagehide', stop);
})();

// Reassemble updated texture previews. Image loading and project writes stay with the app.
// Krackle: the new pixels arrive through a 45° halftone screen, each dot swelling from
// nothing until the dots overlap into the finished image (one deliberate print pass).
// A wipe swap sends the same swelling dots across the old preview from left to right.
(() => {
  'use strict';
  const records = new WeakMap(), live = new Set();
  const motionQuery=window.AtelierMotionPolicy?.query()||window.matchMedia('(prefers-reduced-motion: reduce)');
  const reduced={get matches(){return motionQuery.matches||window.AtelierMotionPolicy?.allows(2)===false;},addEventListener:(...args)=>motionQuery.addEventListener(...args)};
  const MAX_CANVASES = 4;

  function dispose(record) {
    if (!record || !live.delete(record)) return;
    clearTimeout(record.timeout);
    cancelAnimationFrame(record.frame);
    record.img.removeEventListener('load', record.loaded);
    record.img.removeEventListener('error', record.failed);
    record.canvas?.remove();
    record.host?.classList.remove('texture-reconstructing');
    if (records.get(record.img) === record) records.delete(record.img);
  }

  function disposeWithin(container) {
    for (const record of live) if (container.contains(record.img)) dispose(record);
  }

  function clear() { for (const record of live) dispose(record); }

  function current(record) {
    return records.get(record.img) === record && record.img.isConnected &&
      (record.project === undefined || window.atelierProject?.() === record.project);
  }

  function visible(host) {
    const rect = host.getBoundingClientRect();
    return rect.width >= 24 && rect.height >= 24 && rect.bottom > 0 && rect.right > 0 &&
      rect.top < window.innerHeight && rect.left < window.innerWidth && host.checkVisibility?.() !== false;
  }

  function assemble(record) {
    const {img} = record, host = img.closest('.card-thumb, .sb-thumb');
    if (!current(record) || !host || document.hidden || reduced.matches || !visible(host) ||
        [...live].filter(item => item.canvas).length >= MAX_CANVASES) {
      dispose(record); return;
    }
    const width = host.clientWidth, height = host.clientHeight;
    const ratio = Math.min(window.devicePixelRatio || 1, 2);
    const source = document.createElement('canvas'), canvas = document.createElement('canvas');
    source.width = canvas.width = Math.ceil(width * ratio);
    source.height = canvas.height = Math.ceil(height * ratio);
    const sourceContext = source.getContext('2d'), context = canvas.getContext('2d');
    if (!sourceContext || !context) { dispose(record); return; }
    // Match the previews' contain fit, retaining non-square maps and their alpha channel.
    const scale = Math.min(source.width / img.naturalWidth, source.height / img.naturalHeight);
    const imageWidth = img.naturalWidth * scale, imageHeight = img.naturalHeight * scale;
    sourceContext.drawImage(img, (source.width - imageWidth) / 2, (source.height - imageHeight) / 2,
      imageWidth, imageHeight);
    canvas.className = 'texture-reconstruction';
    canvas.setAttribute('aria-hidden', 'true');
    record.canvas = canvas; record.host = host;
    host.classList.add('texture-reconstructing');
    host.appendChild(canvas);

    const duration = record.mode === 'wipe' ? 320 : width >= 90 ? 460 : 330;
    const spread = record.mode === 'wipe' ? 0 : width >= 90 ? 180 : 100;
    canvas.dataset.swapMode = record.mode;
    // Comic-sized screen: about 14 dots across a tile, 8 in the compact sidebar.
    const pitch = canvas.width / (width >= 90 ? 14 : 8), reach = pitch * 0.76;
    const cx = canvas.width / 2, cy = canvas.height / 2;
    const dots = [];
    const c = Math.SQRT1_2, span = Math.ceil(Math.hypot(canvas.width, canvas.height) / pitch) + 2;
    for (let i = -span; i <= span; i++) for (let j = -span; j <= span; j++) {
      const x = cx + (i - j) * pitch * c, y = cy + (i + j) * pitch * c;
      if (x < -reach || y < -reach || x > canvas.width + reach || y > canvas.height + reach) continue;
      // Ordered diagonal rows read as a fresh proof coming off the press.
      // The mask alone moves; sampled artwork never receives a tint or a distortion.
      dots.push({x, y, delay: Math.max(0, Math.min(1, (x + y * .35) / (canvas.width + canvas.height * .35))) * spread});
    }
    const started = performance.now();
    const draw = now => {
      record.frame = null;
      if (!current(record) || document.hidden || reduced.matches || !visible(host) ||
          host.clientWidth !== width || host.clientHeight !== height || now - started >= duration + spread) {
        dispose(record); return;
      }
      try {
        context.clearRect(0, 0, canvas.width, canvas.height);
        const elapsed = now - started;
        if (record.mode === 'wipe' && record.previous) context.drawImage(record.previous, 0, 0, canvas.width, canvas.height);
        const front = (1 - Math.pow(1 - Math.min(1, elapsed / duration), 3)) * canvas.width * 1.35;
        context.save();
        context.beginPath();
        for (const dot of dots) {
          let grow;
          if (record.mode === 'wipe') grow = Math.max(0, Math.min(1, (front - dot.x) / (canvas.width * 0.35)));
          else {
            const progress = Math.max(0, Math.min(1, (elapsed - dot.delay) / duration));
            grow = 1 - Math.pow(1 - progress, 3);
          }
          if (grow <= 0) continue;
          const r = reach * grow;
          context.moveTo(dot.x + r, dot.y);
          context.arc(dot.x, dot.y, r, 0, Math.PI * 2);
        }
        context.clip();
        if (record.mode === 'wipe') context.clearRect(0, 0, canvas.width, canvas.height);
        context.drawImage(source, 0, 0);
        context.restore();
        record.frame = requestAnimationFrame(draw);
      } catch (_) { dispose(record); }
    };
    record.frame = requestAnimationFrame(draw);
  }

  function refresh(img, src, {project, mode = 'blocks'} = {}) {
    dispose(records.get(img));
    const record = {img, project, mode, canvas: null, frame: null, previous:null};
    if (mode === 'wipe' && img.complete && img.naturalWidth && !reduced.matches && !document.hidden) {
      const host=img.closest('.card-thumb,.sb-thumb');
      if (host && visible(host)) {
        const previous=document.createElement('canvas'), ratio=Math.min(devicePixelRatio||1,2);
        previous.width=Math.ceil(host.clientWidth*ratio);previous.height=Math.ceil(host.clientHeight*ratio);
        try {
          const context=previous.getContext('2d'), scale=Math.min(previous.width/img.naturalWidth,previous.height/img.naturalHeight);
          context.drawImage(img,(previous.width-img.naturalWidth*scale)/2,(previous.height-img.naturalHeight*scale)/2,img.naturalWidth*scale,img.naturalHeight*scale);
          record.previous=previous;
        } catch (_) { /* The final loaded image remains the fallback. */ }
      }
    }
    record.failed = () => dispose(record);
    record.loaded = () => {
      if (!current(record) || !img.naturalWidth || !img.naturalHeight) { dispose(record); return; }
      img.style.opacity = ''; // A successful replacement also clears a previous sidebar error pose.
      img.removeEventListener('load', record.loaded);
      img.removeEventListener('error', record.failed);
      try { assemble(record); } catch (_) { dispose(record); }
    };
    records.set(img, record); live.add(record);
    img.addEventListener('load', record.loaded);
    img.addEventListener('error', record.failed);
    record.timeout = setTimeout(() => dispose(record), 30000);
    img.src = src;
  }

  document.addEventListener('visibilitychange', () => { if (document.hidden) clear(); });
  reduced.addEventListener?.('change', () => { if (reduced.matches) clear(); });
  window.addEventListener('pagehide', clear);
  window.AtelierTextureReconstruction = Object.freeze({refresh, disposeWithin, clear});
})();

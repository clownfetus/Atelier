// Reassemble updated texture previews. Image loading and project writes stay with the app.
(() => {
  'use strict';
  const records = new WeakMap(), live = new Set();
  const reduced = (window.AtelierMotionPolicy?.query() || window.matchMedia('(prefers-reduced-motion: reduce)'));
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

    const columns = width >= 90 ? 8 : 4, rows = columns;
    const blockWidth = canvas.width / columns, blockHeight = canvas.height / rows;
    const duration = record.mode === 'wipe' ? 320 : width >= 90 ? 460 : 330;
    const spread = record.mode === 'wipe' ? 0 : width >= 90 ? 180 : 100;
    canvas.dataset.swapMode = record.mode;
    const blocks = Array.from({length: columns * rows}, (_, index) => ({
      x: (index % columns) * blockWidth, y: Math.floor(index / columns) * blockHeight,
      delay: ((index * 37) % (columns * rows)) / (columns * rows) * spread,
      dx: Math.sin(index * 12.9898 + 1) * canvas.width * .22,
      dy: Math.cos(index * 7.233 + 2) * canvas.height * .22,
      rotation: Math.sin(index * 3.17) * .22,
    }));
    const started = performance.now();
    const draw = now => {
      record.frame = null;
      if (!current(record) || document.hidden || reduced.matches || !visible(host) ||
          host.clientWidth !== width || host.clientHeight !== height || now - started >= duration + spread) {
        dispose(record); return;
      }
      try {
        context.clearRect(0, 0, canvas.width, canvas.height);
        if (record.mode === 'wipe') {
          const progress = Math.min(1, (now-started)/duration), eased = 1-Math.pow(1-progress,3);
          if (record.previous) context.drawImage(record.previous,0,0,canvas.width,canvas.height);
          context.save(); context.beginPath(); context.rect(0,0,canvas.width*eased,canvas.height); context.clip();
          context.clearRect(0,0,canvas.width,canvas.height); context.drawImage(source,0,0); context.restore();
          record.frame=requestAnimationFrame(draw); return;
        }
        for (const block of blocks) {
          const progress = Math.max(0, Math.min(1, (now - started - block.delay) / duration));
          if (!progress) continue;
          const eased = 1 - Math.pow(1 - progress, 3), remaining = 1 - eased;
          context.save();
          context.globalAlpha = Math.min(1, progress * 3);
          context.translate(block.x + blockWidth / 2 + block.dx * remaining,
            block.y + blockHeight / 2 + block.dy * remaining);
          context.rotate(block.rotation * remaining);
          context.scale(.55 + eased * .45, .55 + eased * .45);
          context.drawImage(source, block.x, block.y, blockWidth, blockHeight,
            -blockWidth / 2, -blockHeight / 2, blockWidth + .5, blockHeight + .5);
          context.restore();
        }
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

// Per-grid thumbnail delivery. Cached images load immediately; polling recovers missed SSE.
(() => {
  // Paint at the display's pixel density so a large catalogue image does not alias
  // when the browser scales it into a card. Keep the source image for loading and fallback.
  function resizePortraits(entries) {
    const pixelRatio = window.devicePixelRatio;
    for (const {target: img, contentRect} of entries) {
      const width = Math.round(contentRect.width * pixelRatio);
      const height = Math.round(contentRect.height * pixelRatio);
      if (!width || !height || !img.naturalWidth || !img.naturalHeight) continue;

      const canvas = img.nextElementSibling || document.createElement('canvas');
      if (canvas.isConnected && canvas.width === width && canvas.height === height) continue;
      const context = canvas.getContext('2d');
      if (!context) continue;
      canvas.width = width;
      canvas.height = height;
      context.imageSmoothingQuality = 'high';

      // Match object-fit: cover and object-position: center bottom on the source image.
      const scale = Math.max(width / img.naturalWidth, height / img.naturalHeight);
      const sourceWidth = width / scale;
      const sourceHeight = height / scale;
      context.drawImage(img, (img.naturalWidth - sourceWidth) / 2, img.naturalHeight - sourceHeight,
        sourceWidth, sourceHeight, 0, 0, width, height);
      if (!canvas.isConnected) {
        canvas.setAttribute('aria-hidden', 'true');
        img.after(canvas);
      }
    }
  }

  function create({project, request, makeFallback}) {
    const entries = new Map(), requests = new Set(), requeued = new Set();
    const portraitSizes = new ResizeObserver(resizePortraits);
    const portraitBox = 'devicePixelContentBoxSize' in ResizeObserverEntry.prototype
      ? 'device-pixel-content-box' : 'content-box';
    let destroyed = false, timer = null, checking = false, deadline = 0;
    const usesArtwork = entry => entry.card.thumbnail && !entry.card.imported;
    const remaining = () => [...entries.values()].filter(e => !usesArtwork(e) && !e.loaded && !e.failed);

    function fail(entry, message = 'Preview unavailable — right-click to retry') {
      if (destroyed || entry.loaded) return;
      clearTimeout(entry.imageTimer);
      entry.reading = false;
      entry.failed = true;
      entry.img.style.display = 'none';
      entry.thumb.dataset.previewState = 'error';
      entry.thumb.title = message;
      if (!entry.fallback) {
        entry.fallback = makeFallback(entry.card);
        entry.thumb.appendChild(entry.fallback);
      }
      entry.fallback.hidden = false;
    }

    function load(entry, fresh = false) {
      // Repeated cached snapshots must not restart a slow, valid image response.
      if (destroyed || (entry.reading && entry.cacheAttempt && fresh)) return;
      entry.failed = false;
      entry.reading = true;
      entry.cacheAttempt = fresh;
      clearTimeout(entry.imageTimer);
      entry.imageTimer = setTimeout(() => fail(entry, 'Preview timed out — right-click to retry'), 30000);
      if (!entry.loaded) entry.thumb.dataset.previewState = 'loading';
      if (usesArtwork(entry)) {
        entry.img.src = entry.card.thumbnail;
      } else {
        const query = new URLSearchParams({game_rel: entry.card.game_rel, _project: project});
        if (fresh) query.set('_t', String(Date.now()));
        entry.img.src = `/api/thumb?${query}`;
      }
    }

    function attach(card, img, thumb) {
      const entry = {card, img, thumb, loaded: false, failed: false,
        reading: false, cacheAttempt: false, imageTimer: null, fallback: null};
      entries.set(card.game_rel, entry);
      thumb.dataset.previewState = 'loading';
      img.style.display = 'none';
      img.onload = () => {
        if (destroyed) return;
        clearTimeout(entry.imageTimer); entry.reading = false;
        entry.loaded = true; entry.failed = false;
        img.style.display = '';
        entry.fallback?.remove(); entry.fallback = null;
        thumb.dataset.previewState = 'ready';
        thumb.removeAttribute('title');
        // It opens downwards out of its top edge over the plate; no fade, no travel (P4b.7).
        window.AtelierPolish?.play(img,[{clipPath:'inset(0 0 100% 0)'},{clipPath:'inset(0)'}],AtelierMotion.unfoldMs||280,AtelierMotion.ease.unfold);
        if (!remaining().length) clearTimeout(timer);
      };
      img.onerror = () => {
        if (destroyed) return;
        clearTimeout(entry.imageTimer); entry.reading = false;
        entry.loaded = false;
        if (usesArtwork(entry) || entry.cacheAttempt || entry.failed) fail(entry);
        // A cache miss while queued is recovered by ready/status, not treated as failure yet.
      };
      load(entry);
    }

    async function post(path, payload) {
      const controller = new AbortController();
      requests.add(controller);
      const timeout = setTimeout(() => controller.abort(), 15000);
      try {
        return await request(path, {method: 'POST', signal: controller.signal,
          headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload)});
      } finally { clearTimeout(timeout); requests.delete(controller); }
    }

    function apply(status) {
      for (const gr of status.cached || []) {
        const entry = entries.get(gr);
        if (entry && !entry.loaded) {
          load(entry, true);
        }
      }
      for (const gr of status.failed || []) {
        const entry = entries.get(gr);
        if (entry) fail(entry, status.errors?.[gr] || undefined);
      }
    }

    function schedule() {
      clearTimeout(timer);
      if (!destroyed && remaining().length) timer = setTimeout(check, 2000);
    }

    async function check() {
      if (destroyed || checking || !remaining().length) return;
      if (deadline && Date.now() >= deadline) {
        remaining().forEach(e => fail(e, 'Preview timed out — right-click to retry'));
        return;
      }
      checking = true;
      try {
        const status = await post('/api/thumb_status', {game_rels: remaining().map(e => e.card.game_rel)});
        if (destroyed) return;
        if (!status?.ok) throw Error('Thumbnail status unavailable');
        apply(status);
        // A backend restart loses queued jobs, but the visible grid can enqueue them once again.
        const missing = (status.missing || []).filter(gr => entries.has(gr));
        const retry = missing.filter(gr => !requeued.has(gr));
        missing.filter(gr => requeued.has(gr)).forEach(gr => fail(entries.get(gr)));
        if (retry.length) {
          retry.forEach(gr => requeued.add(gr));
          const resumed = await post('/api/prefetch_thumbs', {game_rels: retry});
          if (!destroyed && resumed?.ok) apply(resumed);
        }
      } catch (_) {
        if (!destroyed) {
          // Includes older backends without a status endpoint: one final cache read,
          // then a truthful fallback instead of an unbounded spinner.
          remaining().forEach(e => load(e, true));
        }
      } finally { checking = false; schedule(); }
    }

    async function start(retry = false) {
      if (destroyed || !remaining().length) return;
      deadline = Date.now() + 180000;
      try {
        const status = await post('/api/prefetch_thumbs', {
          game_rels: remaining().map(e => e.card.game_rel), ...(retry ? {retry: true} : {})});
        if (destroyed) return;
        if (!status?.ok) throw Error('Thumbnail request unavailable');
        apply(status);
      } catch (_) {
        if (!destroyed) remaining().forEach(e => load(e, true));
      }
      schedule();
    }

    function handleEvent(data) {
      if (destroyed) return;
      const entry = entries.get(data.game_rel);
      if (!entry || usesArtwork(entry)) return;
      if (data.thumb_ready) {
        load(entry, true);
      } else if (data.thumb_failed) fail(entry, data.error || undefined);
    }

    function observePortrait(img) {
      if (!destroyed) portraitSizes.observe(img, {box: portraitBox});
    }

    function destroy() {
      destroyed = true;
      portraitSizes.disconnect();
      clearTimeout(timer);
      requests.forEach(controller => controller.abort());
      entries.forEach(entry => {
        clearTimeout(entry.imageTimer);
        entry.img.onload = null; entry.img.onerror = null;
      });
      entries.clear();
    }
    return {attach, observePortrait, start, handleEvent, reconcile: check, destroy};
  }
  window.AtelierThumbnails = Object.freeze({create});
})();

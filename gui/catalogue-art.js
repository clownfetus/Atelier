// Optional identity artwork. A missing image always falls back without blocking the UI.
(() => {
  'use strict';
  function heroId(value) {
    if (value && typeof value === 'object') {
      const path = heroId(value.game_rel || value.path || '');
      return path || (/^10\d{2}$/.test(value.char_id || '') ? value.char_id :
        /^10\d{5}$/.test(value.skin_id || '') ? value.skin_id.slice(0,4) : null);
    }
    if (typeof value !== 'string') return null;
    const match = /^(?:Characters|VFX\/Materials\/Characters)\/(10\d{2})(?:\/(\d{7}))?(?:\/|$)/i.exec(value);
    return match && (!match[2] || match[2].startsWith(match[1])) ? match[1] : /^10\d{2}$/.test(value) ? value : null;
  }
  function load(image, sources) {
    const urls = [...new Set(sources.filter(Boolean))];
    image.onerror = () => { if (urls.length) image.src = urls.shift(); else image.remove(); };
    image.onerror(); return image;
  }
  function heroChip(value) {
    const id = heroId(value); if (!id) return null;
    const image = document.createElement('img'); image.className = 'hero-chip-art'; image.alt = '';
    image.dataset.heroChipId = id;
    image.decoding = 'async';
    return load(image, ['/api/catalogue/hero/'+id+'/lord', '/api/catalogue/hero/'+id+'/avatar', '/api/catalogue/thumbnail/'+id]);
  }
  window.addEventListener('atelier:catalogue-updated', () => {
    for (const image of document.querySelectorAll('.hero-chip-art[data-hero-chip-id]')) {
      const id = image.dataset.heroChipId;
      if (heroId(id)) load(image, ['/api/catalogue/hero/'+id+'/lord', '/api/catalogue/hero/'+id+'/avatar', '/api/catalogue/thumbnail/'+id]);
    }
  });
  function bannerUrl(url) {
    return url && url.startsWith('/api/catalogue/banner/') ?
      url + (url.includes('?') ? '&' : '?') + 'sharp=1' : url;
  }
  const banners = new WeakMap();
  function watchBanner(image) {
    const source = image.getAttribute('src');
    if (!source || banners.get(image)?.source === source) return;
    const url = new URL(source, location.href);
    if (url.origin !== location.origin || url.searchParams.has('upscale') ||
        !/^\/api\/catalogue\/(?:hero\/\d{4}\/story|banner\/\d{4}(?:\d{3})?)$/.test(url.pathname)) return;
    if (url.pathname.includes('/banner/') && url.searchParams.get('sharp') !== '1') return;
    const state = {source}; banners.set(image, state);
    const current = () => banners.get(image) === state && image.isConnected &&
      image.getAttribute('src') === source && image.getClientRects().length;
    async function check(attempt = 0) {
      if (!current()) return;
      try {
        const response = await fetch(url, {method:'HEAD', cache:'no-store', signal:AbortSignal.timeout(10000)});
        if (!current() || !response.ok) return;
        const status = response.headers.get('X-Atelier-Upscale');
        if (status === 'ready') {
          // Decode the replacement first; the original stays visible until it is ready.
          url.searchParams.set('upscale', '4');
          const sharp = new Image();
          sharp.onload = () => { if (current()) image.src = url.pathname + url.search; };
          sharp.src = url.href;
          return;
        }
        if (status !== 'pending') return;
      } catch (_) { /* Keep the original through a temporary local connection failure. */ }
      if (attempt < 80 && current()) setTimeout(() => check(attempt + 1), 2500);
    }
    // Run after the image's own load handler has made it visible.
    setTimeout(check, 0);
  }
  document.addEventListener('load', event => {
    if (event.target instanceof HTMLImageElement && event.target.matches('.library-hero-art, #viewport-skin-card img'))
      watchBanner(event.target);
  }, true);
  function tray(items) {
    const host = document.getElementById('mod-tray-heroes'); if (!host) return;
    const heroes = new Map();
    for (const item of items) {
      const id = heroId(item); if (item.selected !== false && id && !heroes.has(id)) heroes.set(id, item.char_name || id);
    }
    const signature = JSON.stringify([...heroes]); if (host.dataset.heroes === signature) return;
    host.dataset.heroes = signature; host.replaceChildren(); host.hidden = !heroes.size;
    for (const [id,name] of heroes) {
      const chip = document.createElement('span'); chip.className = 'tray-hero-chip';
      const art = heroChip(id), label = document.createElement('span'); label.textContent = name;
      if (art) chip.append(art); chip.append(label); host.append(chip);
    }
  }
  window.AtelierCatalogueArt = Object.freeze({heroId, heroChip, load, bannerUrl, tray});
})();

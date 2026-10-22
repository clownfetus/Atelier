// Optional identity artwork. A missing image always falls back without blocking the UI.
(() => {
  'use strict';
  let identities = {};
  function resolveIds(value, leafOnly = false) {
    if (typeof value !== 'string' || !value) return null;
    const path = value.replaceAll('\\', '/').replace(/^\/Game\/Marvel\//, '');
    if (path.startsWith('/') || /[:?#\x00-\x1f\x7f]/.test(path)) return null;
    const parts = path.replace(/\/+$/, '').split('/');
    if (parts.some(part => ['', '.', '..'].includes(part)) ||
        leafOnly && !/^\d{4}(?:\d{3})?$/.test(parts.at(-1))) return null;
    let cid = null, sid = null, heroPath = null, skinPath = null;
    for (const [index, part] of parts.entries()) {
      const tokens = /^\d{4}(?:\d{3})?$/.test(part) ? [part] : index === parts.length - 1 && !leafOnly ?
        [...part.matchAll(/(?<!\d)(\d{7}|\d{4})(?!\d)/g)].map(match => match[1]) : [];
      for (const key of tokens) {
        const entry = identities[key], owner = key.slice(0, 4);
        const conventional = index > 0 && parts[index - 1].toLowerCase() === 'characters' && key.length === 4;
        if (key === part && key.length === 7 && heroPath && owner !== cid) return null;
        if (!entry && !conventional && (key !== part || key.length !== 7 || !identities[owner] && owner !== cid)) continue;
        if (entry && (entry.kind || (key.length === 4 ? 'hero' : 'skin')) !== (key.length === 4 ? 'hero' : 'skin')) continue;
        if (entry && key.length === 7 && entry.hero && entry.hero !== owner) return null;
        if ((cid && cid !== owner) || (sid && key.length === 7 && sid !== key)) return null;
        cid = owner;
        if (key.length === 4) heroPath = parts.slice(0, index + 1).join('/');
        else { sid = key; skinPath = parts.slice(0, index + 1).join('/'); }
      }
    }
    return cid ? {char_id: cid, skin_id: sid, hero_path: heroPath, skin_path: skinPath} : null;
  }
  function entryFor(id) {
    if (!id) return null;
    const entry = identities[id], hero = identities[id.slice(0, 4)];
    if (!entry && !hero) return null;
    const skin = id.length === 7;
    return {...(entry || {}), id, unlisted: !entry,
      path: 'Characters/' + (skin ? id.slice(0, 4) + '/' + id : id),
      name: entry?.name || (skin ? 'Skin ' + id.slice(-3) : id),
      hero_fallback: entry?.hero_fallback ?? (!entry && skin),
      thumbnail: entry?.thumbnail || hero?.thumbnail,
      ...(!skin ? {avatar:'/api/catalogue/hero/'+id+'/avatar', logo:'/api/catalogue/hero/'+id+'/logo'} : {}),
      ...(skin && entry && !entry.hero_fallback && entry.thumbnail ? {icon:'/api/catalogue/icon/'+id} : {})};
  }
  function describe(path) {
    const ids = resolveIds(path);
    if (!ids) return null;
    const hero = entryFor(ids.char_id), skin = entryFor(ids.skin_id);
    return hero || skin ? {...ids, hero, skin} : null;
  }
  function pathLabel(path) {
    if (typeof path !== 'string') return '';
    const identity = describe(path);
    if (!identity) return path;
    let namedHero = false;
    return path.split('/').map(part => {
      if (part === identity.char_id && identity.hero) { namedHero = true; return identity.hero.name; }
      if (part === identity.skin_id && identity.skin) return [!namedHero && identity.hero?.name,
        identity.skin.name].filter(Boolean).join(' — ');
      return part;
    }).join('/');
  }
  function setIdentities(result) {
    if (result.identities && typeof result.identities === 'object') identities = {...result.identities};
    else {
      identities = {};
      for (const hero of result.heroes || []) {
        const cid = hero.path?.split('/').at(-1);
        if (!/^\d{4}$/.test(cid || '')) continue;
        identities[cid] = {...hero, id:cid, kind:'hero', hero:cid};
        for (const skin of hero.skins || []) {
          const sid = skin.path?.split('/').at(-1);
          if (/^\d{7}$/.test(sid || '') && sid.startsWith(cid))
            identities[sid] = {...skin, id:sid, kind:'skin', hero:cid};
        }
      }
    }
    window.dispatchEvent(new CustomEvent('atelier:identities-updated'));
  }
  function heroId(value) {
    if (value && typeof value === 'object') {
      const path = heroId(value.game_rel || value.path || '');
      return path || (/^10\d{2}$/.test(value.char_id || '') ? value.char_id :
        /^10\d{5}$/.test(value.skin_id || '') ? value.skin_id.slice(0,4) : null);
    }
    if (typeof value !== 'string') return null;
    const resolved = resolveIds(value);
    if (resolved) return /^10\d{2}$/.test(resolved.char_id) ? resolved.char_id : null;
    if (/^10\d{2}$/.test(value)) return value;
    if (Object.keys(identities).length) return null;
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
  function identityChip(value) {
    const path = typeof value === 'string' ? value : value?.game_rel || value?.rel_path || value?.path || '';
    const identity = describe(path), skin = identity?.skin;
    if (!skin || skin.hero_fallback || !skin.thumbnail) return heroChip(value);
    const image = document.createElement('img'); image.className = 'hero-chip-art skin-chip-art';
    image.alt = ''; image.decoding = 'async';
    return load(image, [skin.icon, skin.badge, skin.thumbnail, identity.hero?.avatar, identity.hero?.thumbnail]);
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
  let cornerGeneration = 0;
  function corner(path) {
    const host = document.getElementById('library-corner-art'); if (!host) return;
    const generation = ++cornerGeneration, identity = describe(path), ids = resolveIds(path), cid = heroId(path);
    host.replaceChildren(); host.hidden = true; delete host.dataset.kind;
    if (!cid) return;
    const image = new Image(); image.alt = ''; image.decoding = 'async'; image.draggable = false;
    const spray = identity?.skin?.spray || (ids?.skin_id && '/api/catalogue/spray/'+ids.skin_id);
    const sources = [spray, '/api/catalogue/hero/'+cid+'/prestige'].filter(Boolean);
    const current = () => generation === cornerGeneration;
    const next = () => {
      if (!current()) return;
      host.hidden = true;
      if (sources.length) image.src = sources.shift(); else image.remove();
    };
    image.onerror = next;
    image.onload = () => {
      if (!current()) return;
      host.dataset.kind = image.getAttribute('src').includes('/spray/') ? 'spray' : 'prestige';
      host.hidden = false;
    };
    host.append(image); next();
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
  window.AtelierCatalogueArt = Object.freeze({heroId, heroChip, identityChip, resolveIds, describe,
    pathLabel, setIdentities, load, bannerUrl, corner, tray});
})();

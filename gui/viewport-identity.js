// Model Studio's skin identity: the costume icon beside the title, the skin's nameplate (or the
// hero's own nameplate, then story art) above the material list, and the skin's main colour. That colour is decoration
// only (the icon ring, a line under the header, a glow behind the card), so controls keep the
// user's theme. Artwork is optional catalogue data; anything that fails to load is simply left out.
(() => {
  'use strict';
  let token = 0;
  const $ = id => document.getElementById(id);
  function load(img, sources, stamp, done) {
    if (stamp !== token) return;
    const [src, ...rest] = sources.filter(Boolean);
    if (!src) { img.hidden = true; img.removeAttribute('src'); done?.(null); return; }
    img.onload = () => { if (stamp !== token) return; img.hidden = false; done?.(src); };
    img.onerror = () => { if (stamp === token) load(img, rest, stamp, done); };
    img.src = src;
  }
  function element(id, tag, parent, where) {
    let node = $(id);
    if (!node && parent) { node = document.createElement(tag); node.id = id; parent[where](node); }
    return node;
  }
  function show(skinId, heroId) {
    const box = $('viewport-box'), stamp = ++token;
    if (!box) return;
    const skin = /^\d{7}$/.test(skinId || '') ? skinId : '';
    const hero = skin ? skin.slice(0, 4) : (/^\d{4}$/.test(heroId || '') ? heroId : '');
    box.classList.remove('has-skin-colour'); box.style.removeProperty('--vp-skin-colour');
    const icon = element('viewport-skin-icon', 'img', $('viewport-title')?.parentElement, 'prepend');
    const card = element('viewport-skin-card', 'figure', $('viewport-materials'), 'prepend');
    if (!icon || !card) return;
    icon.alt = ''; card.setAttribute('aria-hidden', 'true');
    const art = card.querySelector('img') || card.appendChild(document.createElement('img'));
    art.alt = ''; card.hidden = true; card.className = '';
    icon.hidden = true; art.hidden = true;
    let iconColour = null, artReady = false;
    const accent = image => {
      if (stamp !== token) return;
      let colour = null;
      try { colour = window.AtelierPolish?.accent(image); } catch (_) { /* Artwork is optional. */ }
      if (/^#[0-9a-f]{6}$/i.test(colour || '')) {
        box.style.setProperty('--vp-skin-colour', colour); box.classList.add('has-skin-colour');
        return colour;
      }
      return null;
    };
    const enc = encodeURIComponent;
    load(icon, [skin && '/api/catalogue/icon/' + enc(skin), skin && '/api/catalogue/badge/' + enc(skin),
      hero && '/api/catalogue/hero/' + enc(hero) + '/avatar'], stamp, src => {
      if (stamp !== token) return;
      iconColour = src && accent(icon);
      if (!iconColour && artReady) accent(art);
    });
    // The library already knows which skins have a nameplate; otherwise ask, then fall back.
    const known = skin && window.AtelierRoster?.describe(`Characters/${hero}/${skin}`)?.skin;
    const nameplate = window.AtelierCatalogueArt?.bannerUrl(skin && (known && !known.unlisted ? known.banner : '/api/catalogue/banner/' + enc(skin)));
    const heroNameplate = hero && window.AtelierCatalogueArt?.bannerUrl('/api/catalogue/banner/' + enc(hero));
    const story = hero && '/api/catalogue/hero/' + enc(hero) + '/story';
    load(art, [nameplate, heroNameplate, story], stamp, src => {
      if (stamp !== token) return;
      card.hidden = !src;
      card.className = src && (src === nameplate || src === heroNameplate) ? 'is-nameplate' : 'is-story';
      artReady = !!src; if (artReady && !iconColour) accent(art);
    });
  }
  function clear() {
    token++;
    for (const id of ['viewport-skin-icon', 'viewport-skin-card']) {
      const node = $(id);
      if (node) {
        node.hidden = true;
        for (const image of node.tagName === 'IMG' ? [node] : node.querySelectorAll('img')) {
          image.onload = image.onerror = null; image.removeAttribute('src');
        }
      }
    }
    $('viewport-box')?.classList.remove('has-skin-colour');
    $('viewport-box')?.style.removeProperty('--vp-skin-colour');
  }
  window.AtelierViewportIdentity = Object.freeze({show, clear});
})();

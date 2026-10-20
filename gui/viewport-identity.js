// Model Studio's skin identity: the costume icon beside the title, the skin's nameplate (or the
// hero's story art) above the material list, and the skin's main colour. That colour is decoration
// only (the icon ring, a line under the header, a glow behind the card), so controls keep the
// user's theme. Artwork is optional catalogue data; anything that fails to load is simply left out.
(() => {
  'use strict';
  let token = 0;
  const $ = id => document.getElementById(id);
  function load(img, sources, done) {
    const [src, ...rest] = sources.filter(Boolean);
    if (!src) { img.hidden = true; img.removeAttribute('src'); done?.(null); return; }
    img.onload = () => { img.hidden = false; done?.(src); };
    img.onerror = () => load(img, rest, done);
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
    const enc = encodeURIComponent;
    load(icon, [skin && '/api/catalogue/icon/' + enc(skin), hero && '/api/catalogue/hero/' + enc(hero) + '/avatar'], src => {
      if (stamp !== token || !src) return;
      const colour = window.AtelierPolish?.accent(icon);
      if (colour) { box.style.setProperty('--vp-skin-colour', colour); box.classList.add('has-skin-colour'); }
    });
    // The library already knows which skins have a nameplate; otherwise ask, then fall back.
    const known = skin && window.AtelierRoster?.describe(`Characters/${hero}/${skin}`)?.skin;
    const nameplate = skin && (known ? known.banner : '/api/catalogue/banner/' + enc(skin));
    const story = hero && '/api/catalogue/hero/' + enc(hero) + '/story';
    load(art, [nameplate, story], src => {
      if (stamp !== token) return;
      card.hidden = !src;
      card.className = src && src === nameplate ? 'is-nameplate' : 'is-story';
    });
  }
  window.AtelierViewportIdentity = Object.freeze({show});
})();

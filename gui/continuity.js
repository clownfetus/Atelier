// Presentation only: navigation, shared elements and optional editor transitions.
(() => {
  'use strict';
  const reduced = (window.AtelierMotionPolicy?.query() || matchMedia('(prefers-reduced-motion: reduce)'));
  let active = null;
  let bannerArgs = null;
  const origins = new WeakMap();
  const cardFor = path => [...document.querySelectorAll('#grid-area .card')]
    .find(card => card.dataset.libraryPath === path);
  const visible = el => el?.isConnected && el.getClientRects().length;
  function animate(el, frames, duration = 160) {
    if (!el || reduced.matches) return;
    if (window.AtelierMotion?.polish) {
      const motion = window.AtelierMotion.polish.mount(el,{frames,duration,state:'playing'});
      motion.finished.catch(() => {}).finally(() => motion.destroy()); return motion;
    }
    try { return el.animate(frames, {duration, easing: window.AtelierMotion?.ease?.standard || 'cubic-bezier(.2,0,0,1)'}); } catch (_) {}
  }
  async function transition(update, before, after, fallback) {
    if (active) {
      active.skipTransition();
      await active.finished.catch(() => {});
    }
    if (!document.startViewTransition || reduced.matches || document.hidden) {
      update(); fallback?.(); return;
    }
    const cleanup = [];
    const name = (el, value) => {
      if (!visible(el)) return;
      const previous = el.style.viewTransitionName;
      el.style.viewTransitionName = value;
      cleanup.push(() => { el.style.viewTransitionName = previous; });
    };
    let updated = false;
    const commit = () => { if (!updated) { updated = true; const ready=update(); after?.(name); return ready; } };
    let current, deferred = false;
    const release = () => {
      // Last named, first restored: an element named before and after the update (the banner)
      // must end with its original name, not the one the second call recorded.
      cleanup.splice(0).reverse().forEach(fn => fn());
      if (active === current) active = null;
    };
    try {
      before?.(name);
      current = document.startViewTransition(commit);
      active = current;
      // Skipped/unsupported snapshots still run the update exactly once.
      current.ready.catch(() => {});
      await current.updateCallbackDone;
      deferred = true;
      current.finished.catch(() => {}).finally(release);
    } catch (_) { commit(); }
    finally {
      if (!deferred) release();
    }
  }

  function banner(path, labels = {}, artwork = {}) {
    window.AtelierCatalogueArt?.corner(path);
    const args=[path,labels,artwork];bannerArgs=args;
    const host = document.getElementById('library-hero');
    if(!host)return;
    const current=()=>bannerArgs===args&&host.isConnected&&!host.hidden;
    const context = window.AtelierRoster?.describe(path);
    const identity = window.AtelierCatalogueArt?.describe(path);
    const match = identity?.hero ? [null, identity.hero.path, identity.skin ? '/' + identity.skin.id : null] :
      /^(Characters\/\d{4})(\/\d{7})?(?:\/|$)/i.exec(path);
    const story = match ? '/api/catalogue/hero/' + match[1].split('/')[1] + '/story' : null;
    // Prefer the costume's verified nameplate, then the hero's own named nameplate.
    const skinKey = identity?.skin_path || (match?.[2] ? match[1] + match[2] : null);
    const heroKey = identity?.hero_path || match?.[1];
    const nameplate = window.AtelierCatalogueArt?.bannerUrl(skinKey && (artwork[skinKey]?.banner || context?.skin?.banner) || null);
    const heroNameplate = match && window.AtelierCatalogueArt?.bannerUrl(
      artwork[heroKey]?.banner || context?.hero?.banner || '/api/catalogue/banner/'+match[1].split('/')[1]);
    const plates = [...new Set([nameplate, heroNameplate].filter(Boolean))];
    const bannerSources = [...plates, story].filter(Boolean);
    const src = bannerSources[0];
    const preloaded = src && [...document.querySelectorAll('#library-hero img,.hero-portrait.loaded')].some(img=>img.complete && img.naturalWidth && img.getAttribute('src')===src);
    host.replaceChildren(); host.hidden = !match;
    host.classList.remove('has-art','has-art-colour','has-nameplate');host.style.removeProperty('--library-art-colour');
    window.dispatchEvent(new CustomEvent('atelier:artwork', {detail:{accent:null,colors:[]}}));
    if (!match) return;
    const heroPath = match[1], skinPath = match[2] ? heroPath + match[2] : null;
    const skin={...context?.skin,...artwork[skinKey]},hero={...context?.hero,...artwork[heroKey]};
    // Use the same costume icon / hero avatar as Home and Continue. Clear the old tint while
    // loading, and bind every fallback to this render (including an A → B → A navigation).
    const sources=[...new Set([
      ...(skinPath&&!(skin.heroFallback??skin.hero_fallback) ? [skin.icon||'/api/catalogue/icon/'+match[2].slice(1),
        skin.thumbnail||'/api/catalogue/thumbnail/'+match[2].slice(1),nameplate] : []),
      hero.avatar||'/api/catalogue/hero/'+match[1].split('/')[1]+'/avatar',
      hero.thumbnail||'/api/catalogue/thumbnail/'+match[1].split('/')[1],story,
    ].filter(Boolean))];
    let identityColoured = false;
    const tint=(index=0)=>{
      if(!current()||index>=sources.length)return;
      const source=new Image();
      source.onload=()=>{
        if(!current())return;
        const colour=window.AtelierPolish?.accent(source);
        if(colour){
          host.style.setProperty('--library-art-colour',colour);host.classList.add('has-art-colour');
          identityColoured = true; window.AtelierPolish?.artwork(source);
        }
        else tint(index+1);
      };
      source.onerror=()=>tint(index+1);source.src=sources[index];
    };
    tint();
    const label = key => (labels[key] || (key===heroPath ? context?.hero?.name : context?.skin?.name) || key.split('/').at(-1)).replace(/^\d+\s*[—–-]\s*/, '');
    const image = document.createElement('img');
    image.alt = ''; image.className = 'library-hero-art';
    const showNameplate = on => { image.classList.toggle('nameplate', on); host.classList.toggle('has-nameplate', on); };
    let sourceIndex = 0;
    const nextSource = () => { showNameplate(sourceIndex < plates.length); image.src = bannerSources[sourceIndex++]; };
    image.onload = () => { if(current()&&image.isConnected){
      host.classList.add('has-art');
      if (!identityColoured) window.AtelierPolish?.artwork(image);
    } };
    image.onerror = () => {
      if(!current())return;
      if (sourceIndex < bannerSources.length) { nextSource(); return; }
      host.classList.remove('has-art'); image.remove();
    };
    host.classList.remove('has-art');
    if (preloaded) host.classList.add('has-art');
    const text = document.createElement('div'); text.className = 'library-hero-copy';
    const eyebrow = document.createElement('span'); eyebrow.textContent = /^Characters\//i.test(path) ? 'CHARACTER LIBRARY' : 'CHARACTER ASSETS';
    const title = document.createElement('h2'); title.textContent = label(heroPath);
    const logo=document.createElement('img'); logo.className='hero-emblem'; logo.alt='';
    logo.src='/api/catalogue/hero/'+match[1].split('/')[1]+'/logo'; logo.onerror=()=>logo.remove();
    title.prepend(logo);
    const signature = document.createElement('img'); signature.className = 'library-hero-signature';
    signature.alt = ''; signature.setAttribute('aria-hidden', 'true'); signature.draggable = false;
    signature.decoding = 'async';
    signature.onload = () => { if (current() && signature.isConnected) signature.classList.add('loaded'); };
    signature.onerror = () => signature.remove();
    signature.src = '/api/catalogue/hero/'+match[1].split('/')[1]+'/signature';
    const detail = document.createElement('p');
    detail.textContent = [skinPath && label(skinPath), path.slice((identity?.skin_path || identity?.hero_path || skinPath || heroPath).length + 1).split('/').join(' / '),
      ].filter(Boolean).join(' · ') || 'Explore costumes, materials and textures';
    text.append(eyebrow, title, signature, detail); host.append(image, text);
    nextSource();
    // Shared-element snapshots wait only for decoding an image already on screen.
    if (preloaded && image.decode) return image.decode().catch(()=>{});
  }
  window.addEventListener('atelier:catalogue-updated',()=>{if(bannerArgs)banner(...bannerArgs);});
  window.addEventListener('atelier:identities-updated',()=>{if(bannerArgs)banner(...bannerArgs);});

  function library(from, to, direction, update) {
    const source = cardFor(to);
    const sourceLabel = source?.querySelector('.card-name');
    const banner = document.getElementById('library-hero');
    document.documentElement.dataset.libraryDirection = direction;
    // The banner enters and leaves on its own. Morphing the square card portrait into the wide
    // story art zoomed and stretched two different pictures into each other.
    return transition(update, name => {
      name(document.querySelector('#grid-area > .grid'), 'atelier-grid');
      name(direction === 'back' ? document.querySelector('#breadcrumbs > :last-child') : sourceLabel, 'atelier-folder-name');
      name(banner, 'atelier-banner');
    }, name => {
      name(document.querySelector('#grid-area > .grid'), 'atelier-grid');
      name(direction === 'back' ? cardFor(from)?.querySelector('.card-name') : sourceLabel && document.querySelector('#breadcrumbs > :last-child'), 'atelier-folder-name');
      name(banner, 'atelier-banner');
    }, () => {
      const grid = document.querySelector('#grid-area > .grid');
      animate(grid, [{opacity: 0, transform: `translateX(${direction === 'back' ? -8 : 8}px)`}, {opacity: 1, transform: 'none'}]);
    });
  }

  // The material, curve and VFX editors are dialogs: they unfold out of their centre line and fold back like
  // every other (continuity.css, P4b.7). The old card-to-panel morph cross-faded the card into the panel, a fade.
  // The editor remembers its card so closing hands focus back to it.
  function openEditor(overlay, path) {
    origins.set(overlay, {path});
    overlay.classList.add('active');
    return Promise.resolve();
  }
  function closeEditor(overlay) {
    const card = cardFor(origins.get(overlay)?.path);
    overlay.classList.remove('active');
    if (visible(card)) card.focus({preventScroll:true});
  }
  // A menu unfolds out of the edge at its pointer or button: downwards, or upwards when it had to flip above.
  function menu(el, x, y) {
    const edge = el.getBoundingClientRect().top < y - 1 ? 'bottom' : 'top';
    el.dataset.unfoldEdge = edge;
    window.AtelierMotion?.unfold?.(el, edge);
  }
  reduced.addEventListener('change', () => { if (reduced.matches) active?.skipTransition(); });
  window.AtelierContinuity = Object.freeze({banner, library, openEditor, closeEditor, menu});
})();

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
    try { return el.animate(frames, {duration, easing: 'cubic-bezier(.2,0,0,1)'}); } catch (_) {}
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

  function banner(path, labels, artwork) {
    bannerArgs=[path,labels,artwork];
    const host = document.getElementById('library-hero');
    const match = /^(Characters\/\d{4})(\/\d{7})?(?:\/|$)/i.exec(path);
    const context = window.AtelierRoster?.describe(path);
    const story = match ? '/api/catalogue/hero/' + match[1].split('/')[1] + '/story' : null;
    // A skin whose bundle has a nameplate of the same name shows it; every other folder keeps the
    // hero's story art, which is also the fallback if the nameplate can't be loaded.
    const skinKey = match?.[2] ? match[1] + match[2] : null;
    const nameplate = skinKey && (artwork[skinKey]?.banner || context?.skin?.banner) || null;
    const src = nameplate || story;
    const preloaded = src && [...document.querySelectorAll('#library-hero img,.hero-portrait.loaded')].some(img=>img.complete && img.naturalWidth && img.getAttribute('src')===src);
    host.replaceChildren(); host.hidden = !match;
    window.dispatchEvent(new CustomEvent('atelier:artwork', {detail:{accent:null}}));
    if (!match) { host.classList.remove('has-art-colour'); host.style.removeProperty('--library-art-colour'); return; }
    const heroPath = match[1], skinPath = match[2] ? heroPath + match[2] : null;
    // A decorative edge in the skin's colour (its costume icon), else the hero art's. The previous
    // colour stays until the new one is known, so moving between a hero and its skins doesn't flash.
    const tint = source => { const colour = bannerArgs?.[0] === path && window.AtelierPolish?.accent(source);
      if (colour) { host.style.setProperty('--library-art-colour', colour); host.classList.add('has-art-colour'); } };
    if (skinPath) {
      const icon = new Image(); icon.onload = () => tint(icon);
      icon.onerror = () => image.complete && image.naturalWidth ? tint(image) : image.addEventListener('load', () => tint(image), {once: true});
      icon.src = '/api/catalogue/icon/' + match[2].slice(1);
    }
    const label = key => (labels[key] || (key===heroPath ? context?.hero?.name : context?.skin?.name) || key.split('/').at(-1)).replace(/^\d+\s*[—–-]\s*/, '');
    const image = document.createElement('img');
    image.alt = ''; image.className = 'library-hero-art';
    const showNameplate = on => { image.classList.toggle('nameplate', on); host.classList.toggle('has-nameplate', on); };
    showNameplate(!!nameplate);
    image.src = src;
    image.onload = () => { if(image.isConnected){host.classList.add('has-art'); window.AtelierPolish?.artwork(image); if(!skinPath) tint(image);} };
    image.onerror = () => {
      if (nameplate && image.getAttribute('src') === nameplate) { showNameplate(false); image.src = story; return; }
      host.classList.remove('has-art'); image.remove();
    };
    host.classList.remove('has-art');
    if (preloaded) host.classList.add('has-art');
    const text = document.createElement('div'); text.className = 'library-hero-copy';
    const eyebrow = document.createElement('span'); eyebrow.textContent = 'CHARACTER LIBRARY';
    const title = document.createElement('h2'); title.textContent = label(heroPath);
    const logo=document.createElement('img'); logo.className='hero-emblem'; logo.alt='';
    logo.src='/api/catalogue/hero/'+match[1].split('/')[1]+'/logo'; logo.onerror=()=>logo.remove();
    title.prepend(logo);
    const detail = document.createElement('p');
    detail.textContent = [skinPath && label(skinPath), path.slice((skinPath || heroPath).length + 1).split('/').join(' / '),
      ].filter(Boolean).join(' · ') || 'Explore costumes, materials and textures';
    text.append(eyebrow, title, detail); host.append(image, text);
    // Shared-element snapshots wait only for decoding an image already on screen.
    if (preloaded && image.decode) return image.decode().catch(()=>{});
  }
  window.addEventListener('atelier:catalogue-updated',()=>{if(bannerArgs)banner(...bannerArgs);});

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

  function openEditor(overlay, path) {
    const card = cardFor(path), panel = overlay.firstElementChild;
    const box = visible(card) ? card.getBoundingClientRect() : null;
    origins.set(overlay, {path, card, box});
    if (!box) { overlay.classList.add('active'); return Promise.resolve(); }
    return transition(() => overlay.classList.add('active'),
      name => name(card, 'atelier-editor'), name => name(panel, 'atelier-editor'), () => {
        if (!box) return;
        const rect = panel.getBoundingClientRect();
        animate(panel, [{opacity: .3, transformOrigin: 'top left', transform: `translate(${box.x - rect.x}px,${box.y - rect.y}px) scale(${box.width / rect.width},${box.height / rect.height})`},
          {opacity: 1, transformOrigin: 'top left', transform: 'none'}], 200);
      });
  }
  function closeEditor(overlay) {
    const origin = origins.get(overlay), card = cardFor(origin?.path), panel = overlay.firstElementChild;
    // Close logical state immediately; a disposable snapshot carries the visual return.
    let ghost, rect;
    if (visible(card) && visible(panel) && !reduced.matches) {
      rect = panel.getBoundingClientRect(); ghost = panel.cloneNode(true);
      ghost.removeAttribute('id'); ghost.querySelectorAll('[id]').forEach(el => el.removeAttribute('id'));
      ghost.inert = true; ghost.setAttribute('aria-hidden', 'true');
      Object.assign(ghost.style, {position:'fixed',left:rect.x+'px',top:rect.y+'px',width:rect.width+'px',height:rect.height+'px',
        margin:'0',maxWidth:'none',maxHeight:'none',pointerEvents:'none',zIndex:250});
      document.body.appendChild(ghost);
    }
    overlay.classList.remove('active');
    if (visible(card)) card.focus({preventScroll:true});
    if (ghost) {
      const target = card.getBoundingClientRect();
      const motion = animate(ghost, [{opacity:1,transformOrigin:'top left',transform:'none'},
        {opacity:0,transformOrigin:'top left',transform:`translate(${target.x-rect.x}px,${target.y-rect.y}px) scale(${target.width/rect.width},${target.height/rect.height})`}], 160);
      if (motion) motion.finished.catch(() => {}).finally(() => ghost.remove()); else ghost.remove();
    }
  }
  function menu(el, x, y) {
    const bounds = el.getBoundingClientRect();
    el.style.transformOrigin = `${Math.max(0, Math.min(bounds.width, x - bounds.x))}px ${Math.max(0, Math.min(bounds.height, y - bounds.y))}px`;
    animate(el, [{opacity: 0, transform: 'scale(.96)'}, {opacity: 1, transform: 'scale(1)'}], 120);
  }
  reduced.addEventListener('change', () => { if (reduced.matches) active?.skipTransition(); });
  window.AtelierContinuity = Object.freeze({banner, library, openEditor, closeEditor, menu});
})();

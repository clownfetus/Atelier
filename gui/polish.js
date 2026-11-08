// Truthful, optional presentation. Every transient effect owns a disposable mount.
(() => {
  'use strict';
  const reduced = () => (window.AtelierMotionPolicy?.query() || matchMedia('(prefers-reduced-motion: reduce)')).matches;
  const mounts = new Map();
  const drains = new Set();
  const clearDrains = () => { for (const dispose of [...drains]) dispose(); };
  function mount(host, {frames = [], duration = 160, state = 'idle', easing = window.AtelierMotion.ease.standard} = {}) {
    mounts.get(host)?.destroy(); let animation = null, destroyed = false;
    const instance = {
      get finished() { return animation?.finished || Promise.resolve(); },
      setState(value) {
        if (destroyed) return;
        state = value; host.dataset.polishState = value; animation?.cancel();
        if (frames.length && !reduced() && !document.hidden) {
          try { animation = host.animate(frames, {duration, easing}); } catch (_) {}
        }
      },
      destroy() { if (destroyed) return; destroyed = true; animation?.cancel(); mounts.delete(host); delete host.dataset.polishState; },
    };
    mounts.set(host, instance); instance.setState(state); return instance;
  }
  const removals = new MutationObserver(() => {
    for (const [host, instance] of mounts) if (!host.isConnected) instance.destroy();
  });
  removals.observe(document.documentElement, {childList:true, subtree:true});
  const play = (host, frames, duration = 160, easing = window.AtelierMotion.ease.standard) => {
    const instance = mount(host, {frames,duration,easing,state:'playing'});
    setTimeout(() => instance.destroy(), duration + 20); return instance;
  };
  window.AtelierMotion ||= {}; window.AtelierMotion.polish = Object.freeze({mount});
  window.AtelierMotionPolicy?.query().addEventListener('change', () => { if (reduced()) for (const instance of mounts.values()) instance.destroy(); });
  window.AtelierMotionPolicy?.query().addEventListener('change', () => { if (!window.AtelierMotionPolicy.allows(1)) clearDrains(); });
  document.addEventListener('visibilitychange',()=>{if(document.hidden){clearDrains();for(const instance of mounts.values())instance.destroy();}});
  window.addEventListener('pagehide',()=>{clearDrains();});
  window.addEventListener('pagehide', () => { removals.disconnect(); for (const instance of mounts.values()) instance.destroy(); });

  function count(host, value) {
    if (!host) return;
    const text = String(value), previous = host.textContent;
    if (text === previous) return;
    host.replaceChildren(); host.classList.add('rolling-count');
    [...text].forEach((digit,index) => {
      if (!/\d/.test(digit)) { host.append(document.createTextNode(digit)); return; }
      const slot = document.createElement('span'); slot.className = 'rolling-digit'; slot.textContent = digit;
      if (previous && previous[index] !== digit && /\d/.test(previous[index] || '')) {
        slot.dataset.previous = previous[index]; slot.classList.add('rolling-change');
        setTimeout(() => { delete slot.dataset.previous; slot.classList.remove('rolling-change'); }, 180);
      }
      host.append(slot);
    });
  }
  function samplePalette(image) {
    if (!image?.complete || !image.naturalWidth) return [];
    try {
      const canvas = document.createElement('canvas'); canvas.width = canvas.height = 16;
      const ctx = canvas.getContext('2d', {willReadFrequently:true}); ctx.drawImage(image,0,0,16,16);
      const data = ctx.getImageData(0,0,16,16).data, buckets = new Map();
      for (let i=0;i<data.length;i+=4) {
        if (data[i+3]<128 || Math.max(...data.slice(i,i+3))<35 || Math.min(...data.slice(i,i+3))>235) continue;
        const key = [data[i],data[i+1],data[i+2]].map(n=>Math.round(n/32)*32).map(n=>Math.min(255,n));
        const color = '#'+key.map(n=>n.toString(16).padStart(2,'0')).join(''); buckets.set(color,(buckets.get(color)||0)+1);
      }
      return [...buckets].sort((a,b)=>b[1]-a[1]).map(([color])=>color).slice(0,8);
    } catch (_) { return []; }
  }
  function sample(image) { return samplePalette(image)[0] || null; }
  // The colour a costume or hero reads as: the hue with the most strong colour in it, rather than the
  // most common pixel (often skin, hair or a grey suit). Falls back to sample() for grey artwork.
  function accent(image) {
    if (!image?.complete || !image.naturalWidth) return null;
    try {
      const size = 24, canvas = document.createElement('canvas'); canvas.width = canvas.height = size;
      const ctx = canvas.getContext('2d', {willReadFrequently:true}); ctx.drawImage(image,0,0,size,size);
      const data = ctx.getImageData(0,0,size,size).data, bins = Array.from({length:12}, () => [0,0,0,0]);
      for (let i=0;i<data.length;i+=4) {
        if (data[i+3]<128) continue;
        const [r,g,b] = [data[i],data[i+1],data[i+2]].map(n=>n/255), max = Math.max(r,g,b), min = Math.min(r,g,b), d = max-min, l = (max+min)/2;
        if (!d || l<.12 || l>.9) continue;
        const hue = (max===r ? ((g-b)/d+6)%6 : max===g ? (b-r)/d+2 : (r-g)/d+4)*60, chroma = 1-Math.abs(2*l-1);
        // Saturation alone overvalues dark blonde hair and skin. Chroma gives stronger costume
        // colours enough weight to survive a larger, muted area without favouring a fixed hue.
        const weight = (d/chroma)**2*d*d, bin = bins[Math.floor(((hue+15)%360)/30)];  // Reds sit in one bin.
        bin[0]+=weight; bin[1]+=data[i]*weight; bin[2]+=data[i+1]*weight; bin[3]+=data[i+2]*weight;
      }
      const best = bins.reduce((a,b)=>b[0]>a[0]?b:a);
      if (best[0]<.15) return sample(image);
      return '#'+best.slice(1).map(n=>Math.round(n/best[0]).toString(16).padStart(2,'0')).join('');
    } catch (_) { return null; }
  }
  function artwork(image) {
    const colors=samplePalette(image), pigment=accent(image) || colors[0] || null;
    window.dispatchEvent(new CustomEvent('atelier:artwork', {detail:{accent:pigment,colors}}));
    let loader = pigment || '#accbff';
    const rgb = loader.slice(1).match(/../g).map(n=>parseInt(n,16));
    const luminance = values => values.map(n=>n/255).map(n=>n<=.04045?n/12.92:((n+.055)/1.055)**2.4).reduce((n,v,i)=>n+v*[.2126,.7152,.0722][i],0);
    for (let step=0;step<=100;step++) {
      const values=rgb.map(n=>Math.round(n+(255-n)*step/100));
      if ((luminance(values)+.05)/(luminance([20,22,27])+.05)>=4.5) {loader='#'+values.map(n=>n.toString(16).padStart(2,'0')).join('');break;}
    }
    document.documentElement.style.setProperty('--skin-loader-accent', loader);
  }
  // Tokens of the rows the last tray render added, so a confirmed save can tell a new piece from a re-save.
  let freshRows = new Set();
  const seating = new Map();
  // A row arriving in the Mod tray clicks in like a glyph piece (P4b.6, SPEC 4.3's click): its slot opens while
  // the thumbnail travels in from the library's side (340 ms), comes in (110 ms), snaps 3 px past its well (80 ms),
  // recoils (110 ms) and rests (130 ms); at the impact the thumbnail squashes and the name, tick and delete wipe in.
  // A row saved over in place only re-seats: the snap, recoil and rest. Calm drops the squash; Off shows the row
  // at once. Nothing fades. Called only once a save or import has really succeeded.
  function seat(row, fresh) {
    seating.get(row)?.();
    const curves = window.AtelierMotion?.assembly?.curves, thumb = row.querySelector('.sb-thumb');
    if (!curves || !thumb || typeof row.animate !== 'function') return;
    const squash = window.AtelierMotionPolicy?.allows(3) !== false;
    const lead = fresh ? 450 : 0, T = lead + 320 + (squash ? 60 : 0), at = ms => ms / T;
    const run = (el, frames) => el.animate(frames, {duration: T, fill: 'backwards'});
    // The library sits to one side of the tray; the piece travels from it.
    const grid = document.getElementById('grid-area')?.getBoundingClientRect(), box = row.getBoundingClientRect();
    const s = grid && grid.width && grid.left > box.left ? -1 : 1;
    const x = v => v ? `translateX(${v}px)` : 'none';
    const travel = [
      ...(fresh ? [{offset: 0, transform: x(-s * 120), easing: curves.move},
        {offset: at(340), transform: x(-s * 12), easing: curves.out}] : []),
      {offset: at(lead), transform: 'none', easing: curves.snap},
      {offset: at(lead + 80), transform: x(s * 3), easing: curves.recoil},
      {offset: at(lead + 190), transform: x(s), easing: curves.rest},
      {offset: at(lead + 320), transform: 'none'}, ...(T > lead + 320 ? [{offset: 1, transform: 'none'}] : [])];
    const animations = [run(thumb, travel)];
    if (squash) {
      const art = thumb.firstElementChild || thumb, hit = at(lead + 80);
      animations.push(art.animate([{offset: 0, transform: 'none'}, {offset: hit, transform: 'none'},
        {offset: hit, transform: 'scale(.88,1.12)', easing: curves.punchBack}, {offset: Math.min(1, at(lead + 380)), transform: 'none'},
        ...(at(lead + 380) < 1 ? [{offset: 1, transform: 'none'}] : [])], {duration: T}));
    }
    if (fresh) {
      const cs = getComputedStyle(row), h = box.height + 'px';
      // The opening slot carries the rows below down itself, so their slide from sidebarAfter would double it.
      for (const other of row.closest('#sidebar-list')?.querySelectorAll('.sb-item') || []) {
        if (row.compareDocumentPosition(other) & Node.DOCUMENT_POSITION_FOLLOWING) mounts.get(other)?.destroy();
      }
      row.style.overflow = 'hidden';
      animations.push(run(row, [{offset: 0, height: '0px', paddingTop: '0px', paddingBottom: '0px', easing: curves.move},
        {offset: at(340), height: h, paddingTop: cs.paddingTop, paddingBottom: cs.paddingBottom}, {offset: 1, height: h, paddingTop: cs.paddingTop, paddingBottom: cs.paddingBottom}]));
      // A wipe, not a fade: the text is revealed from the impact by a clip.
      for (const part of row.querySelectorAll(':scope > .sb-info, :scope > .sb-check, :scope > .sb-clear')) {
        animations.push(run(part, [{offset: 0, clipPath: 'inset(0 100% 0 0)'}, {offset: at(530), clipPath: 'inset(0 100% 0 0)', easing: curves.out},
          {offset: Math.min(1, at(770)), clipPath: 'inset(0 0 0 0)'}, ...(at(770) < 1 ? [{offset: 1, clipPath: 'inset(0 0 0 0)'}] : [])]));
      }
    }
    let done = false;
    const dispose = () => {
      if (done) return; done = true;
      for (const animation of animations) animation.cancel();
      row.style.overflow = ''; seating.delete(row); drains.delete(dispose);
    };
    seating.set(row, dispose); drains.add(dispose);
    Promise.all(animations.map(a => a.finished)).then(dispose, dispose);
  }
  function fly(path) {
    requestAnimationFrame(() => {
      if (document.hidden || reduced()) return;
      const row = [...document.querySelectorAll('.sb-item')].find(node=>node.dataset.gameRel===path);
      if (row?.getClientRects().length) seat(row, freshRows.has(row.dataset.token));
    });
  }
  // A changed texture fades in over the old one, so what's on screen is always the artwork itself.
  function swapImage(image, src) {
    const parent = image.parentElement;
    if (reduced() || document.hidden || !parent || !image.naturalWidth || window.AtelierMotionPolicy?.allows(1) === false) { image.src = src; return; }
    parent.querySelector(':scope > .image-swap')?.remove();
    const old = image.cloneNode(false);
    old.removeAttribute('id');
    for (const name of [...old.attributes]) if (name.name.startsWith('data-')) old.removeAttribute(name.name);
    old.classList.add('image-swap'); old.alt = ''; old.setAttribute('aria-hidden', 'true');
    Object.assign(old.style, {position:'absolute', left:image.offsetLeft+'px', top:image.offsetTop+'px', width:image.offsetWidth+'px', height:image.offsetHeight+'px', pointerEvents:'none'});
    parent.append(old);
    const done = () => { image.removeEventListener('load', fade); image.removeEventListener('error', done); clearTimeout(timer); old.remove(); };
    const fade = () => {
      clearTimeout(timer); image.removeEventListener('error', done);
      if (!old.isConnected) return;
      try { old.animate([{opacity:1},{opacity:0}],{duration:200,easing:window.AtelierMotion?.ease?.standard||'linear'}).finished.catch(()=>{}).finally(()=>old.remove()); }
      catch (_) { old.remove(); }
    };
    const timer = setTimeout(done, 8000);
    image.addEventListener('load', fade, {once:true});
    image.addEventListener('error', done, {once:true});
    image.src = src;
  }
  function sidebarBefore(list) {
    return [...list.querySelectorAll('.sb-item')].map(row=>({token:row.dataset.token,rect:row.getBoundingClientRect(),row}));
  }
  function sidebarAfter(previous, list) {
    const known = new Set((previous || []).map(entry => entry.token));
    freshRows = new Set([...list.querySelectorAll('.sb-item')].map(row => row.dataset.token).filter(token => !known.has(token)));
    if (reduced() || document.hidden || !list.getClientRects().length) return;
    for (const entry of previous || []) {
      const next = [...list.querySelectorAll('.sb-item')].find(row=>row.dataset.token===entry.token);
      if (next) {
        const dy = entry.rect.y-next.getBoundingClientRect().y;
        if (dy) play(next,[{transform:`translateY(${dy}px)`},{transform:'none'}],120);
      } else {
        if (window.AtelierMotionPolicy?.allows(1) === false) continue;
        const copy = entry.row.cloneNode(true); copy.classList.add('polish-ghost'); copy.inert=true; copy.setAttribute('aria-hidden','true');
        copy.removeAttribute('id');copy.querySelectorAll('[id],[name]').forEach(node=>{node.removeAttribute('id');node.removeAttribute('name');});
        copy.querySelectorAll('.swatch-wipe').forEach(node=>node.remove());
        for (const node of [copy,...copy.querySelectorAll('[data-token],[data-game-rel],[data-library-path]')]) {
          for (const name of ['data-token','data-game-rel','data-library-path']) node.removeAttribute(name);
        }
        Object.assign(copy.style,{left:entry.rect.x+'px',top:entry.rect.y+'px',width:entry.rect.width+'px',height:entry.rect.height+'px',margin:'0',overflow:'hidden',opacity:'0'});
        document.body.append(copy);
        // A removed row fades where it stood, for 200 ms.
        const rowAnimation=play(copy,[{opacity:1},{opacity:0}],200);
        const dispose=()=>{clearTimeout(timer);rowAnimation?.destroy();copy.remove();drains.delete(dispose);};
        const timer=setTimeout(dispose,220);drains.add(dispose);
      }
    }
  }
  // A dismissed toast leaves its slot at once, so the live region, collation and the stack stay truthful,
  // while the same element fades 4 px down for 220 ms (accelerating) in an inert layer. Off removes it outright.
  function leave(el, done) {
    if (!el?.isConnected || reduced() || document.hidden || typeof el.animate !== 'function') { done(); return; }
    if (el.parentElement?.id==='toast-exit-layer') return; // Already leaving; the first exit removes it.
    let finished=false; const finish=()=>{ if (finished) return; finished=true; done(); };
    try {
      const rect=el.getBoundingClientRect(), area=document.getElementById('toast-area');
      let layer=document.getElementById('toast-exit-layer');
      if (!layer) {
        layer=document.createElement('div'); layer.id='toast-exit-layer'; layer.setAttribute('aria-hidden','true'); layer.inert=true;
        layer.style.cssText='position:fixed;inset:0;pointer-events:none;z-index:300';
        if (area) area.before(layer); else document.body.append(layer);
      }
      // Keep the caption ink while dropping the hooks that identify a live toast.
      el.style.borderLeftColor=getComputedStyle(el).borderLeftColor;
      el.classList.remove('toast-timed'); el.removeAttribute('role'); el.removeAttribute('aria-live'); delete el.dataset.operationState;
      Object.assign(el.style,{position:'fixed',left:rect.left+'px',top:rect.top+'px',width:rect.width+'px',margin:'0',animation:'none',pointerEvents:'none'});
      layer.append(el);
      const exitMs=AtelierMotion.toastExitMs||220;
      el.animate([{opacity:1,transform:'none'},{opacity:0,transform:'translateY(4px)'}],
        {duration:exitMs,easing:AtelierMotion.ease.exit,fill:'forwards'}).finished.then(finish,finish);
      setTimeout(finish,exitMs+80);
    } catch (_) { finish(); }
  }
  function swatchesBefore() { return new Map([...document.querySelectorAll('#mat-body input[type=color]')].map(node=>[node.id,node.value])); }
  function swatchesAfter(previous, colors=[]) {
    for (const node of document.querySelectorAll('#mat-body input[type=color]')) {
      const index=Number(node.id.replace('matsw','')), value=colors[index];
      const parent=node.parentElement;
      if (value) {
        parent.style.setProperty('--swatch-color',node.value); parent.style.setProperty('--swatch-alpha',value.rgba[3] ?? 1);
        node.style.boxShadow='none';
        parent.querySelector('.hdr-ring')?.remove();
        if(value.inten>1){
          const ring=document.createElement('span');ring.className='hdr-ring';ring.setAttribute('aria-hidden','true');
          parent.style.setProperty('--hdr-radius',Math.min(7,2+Math.log2(value.inten)*1.5)+'px');
          const count=Math.min(5,Math.ceil(Math.log2(value.inten))+1);
          for(let i=0;i<count;i++){const bubble=document.createElement('i'),angle=(i/count)*Math.PI*2; bubble.style.left=(50+50*Math.cos(angle))+'%';bubble.style.top=(50+50*Math.sin(angle))+'%';ring.append(bubble);}parent.append(ring);
        }
        node.style.opacity = String(Math.max(0, Math.min(1,value.rgba[3] ?? 1)));
        node.title=`${value.name} · intensity ${+(value.inten||1).toFixed(2)} · alpha ${+(value.rgba[3]??1).toFixed(2)}`;
      }
      const old=previous?.get(node.id); if (!old || old===node.value || reduced()) continue;
      const wipe=document.createElement('span'); wipe.className='swatch-wipe'; wipe.style.background=old; parent.append(wipe);
      play(wipe,[{clipPath:'inset(0 0 0 0)'},{clipPath:'inset(0 0 0 100%)'}],120); setTimeout(()=>wipe.remove(),140);
    }
  }
  function empty(host, title, description='') {
    host.classList.add('polish-empty');
    const art=document.createElementNS('http://www.w3.org/2000/svg','svg'); art.setAttribute('viewBox','0 0 96 64'); art.setAttribute('aria-hidden','true');
    art.innerHTML='<path d="M12 18h23l9 8h40v28H12Z M12 42h72 M25 18V9h44v17 M34 18h26 M42 32h12 M48 26v12" fill="none" stroke="currentColor" stroke-width="1.5"/>';
    const text=document.createElement('strong'); text.textContent=title;
    const detail=document.createElement('span'); detail.textContent=description;
    host.replaceChildren(art,text,detail);
    // The still glyph stands in for the outline drawing, which stays as the fallback.
    window.AtelierEmptyGlyph?.mount(host);
  }
  function importStart(items) {
    const host=document.getElementById('import-segments'); if (!host) return;
    host.replaceChildren(); host.setAttribute('aria-label',`${items.length} assets to import`);
    items.forEach(item=>{const segment=document.createElement('span'); segment.title=item.name; segment.dataset.path=item.game_rel; segment.dataset.state='pending'; host.append(segment);});
  }
  function importProgress(data) {
    const host=document.getElementById('import-segments'); if (!host) return;
    if (data.game_rel) {
      const segment=[...host.children].find(node=>node.dataset.path===data.game_rel);
      if (segment) segment.dataset.state=data.ok===false?'failed':'done';
    }
    if (data.done && Array.isArray(data.results)) {
      const success=new Set(data.results.map(item=>item.game_rel));
      for (const segment of host.children) if (success.has(segment.dataset.path)) segment.dataset.state='done'; else if (segment.dataset.state!=='done') segment.dataset.state='failed';
    }
  }
  let startupTimer, startupEnded=false;
  async function startup() {
    if (startupEnded) return;
    try {
      const data=await fetch('/api/startup_progress').then(r=>r.json());
      const label=document.getElementById('startup-label'), progress=document.getElementById('startup-progress');
      if (label) label.textContent=data.total ? `Reading container ${data.current} / ${data.total}` : data.stage==='ready'?'Library ready':'Opening your library…';
      if (progress) { if(data.total) {progress.max=data.total;progress.value=data.current;} else progress.removeAttribute('value'); }
      window.AtelierSurfaces?.startupProgress(data);
    } catch (_) { /* Startup errors remain visible in the normal library error state. */ }
    if (!startupEnded) startupTimer=setTimeout(startup,300);
  }
  function startupDone() { startupEnded=true; clearTimeout(startupTimer);window.AtelierSurfaces?.startupDone(); document.getElementById('startup-splash')?.remove(); }
  window.addEventListener('pagehide',()=>{startupEnded=true;clearTimeout(startupTimer);});
  window.AtelierPolish=Object.freeze({count,sample,samplePalette,accent,artwork,fly,swapImage,sidebarBefore,sidebarAfter,swatchesBefore,swatchesAfter,empty,importStart,importProgress,startup,startupDone,play,leave});
})();

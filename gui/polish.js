// Truthful, optional presentation. Every transient effect owns a disposable mount.
(() => {
  'use strict';
  const reduced = () => (window.AtelierMotionPolicy?.query() || matchMedia('(prefers-reduced-motion: reduce)')).matches;
  const mounts = new Map();
  function mount(host, {frames = [], duration = 160, state = 'idle', easing = window.AtelierMotion.ease.standard} = {}) {
    mounts.get(host)?.destroy(); let animation = null, destroyed = false;
    const instance = {
      get finished() { return animation?.finished || Promise.resolve(); },
      setState(value) {
        if (destroyed) return;
        state = value; host.dataset.polishState = value; animation?.cancel();
        if (frames.length && !reduced()) {
          try { animation = host.animate(frames, {duration, easing}); } catch (_) {}
        }
      },
      destroy() { if (destroyed) return; destroyed = true; animation?.cancel(); mounts.delete(host); delete host.dataset.polishState; },
    };
    mounts.set(host, instance); instance.setState(state); return instance;
  }
  // Container -> the empty state it shows. Typing that keeps a view empty rebuilds it with the same key,
  // so the art stays settled; any other content in between (cards, a loading pose) forgets the key.
  const emptyKeys = new Map();
  const removals = new MutationObserver(() => {
    for (const [host, instance] of mounts) if (!host.isConnected) instance.destroy();
    for (const container of emptyKeys.keys()) if (!container.isConnected || !container.querySelector(':scope > .polish-empty')) emptyKeys.delete(container);
  });
  removals.observe(document.documentElement, {childList:true, subtree:true});
  const play = (host, frames, duration = 160, easing = window.AtelierMotion.ease.standard) => {
    const instance = mount(host, {frames,duration,easing,state:'playing'});
    setTimeout(() => instance.destroy(), duration + 20); return instance;
  };
  window.AtelierMotion ||= {}; window.AtelierMotion.polish = Object.freeze({mount});
  window.AtelierMotionPolicy?.query().addEventListener('change', () => { if (reduced()) for (const instance of mounts.values()) instance.destroy(); });
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
  function artwork(image) {
    const colors=samplePalette(image),accent=colors[0]||null;
    window.dispatchEvent(new CustomEvent('atelier:artwork', {detail:{accent,colors}}));
    let loader = accent || '#accbff';
    const rgb = loader.slice(1).match(/../g).map(n=>parseInt(n,16));
    const luminance = values => values.map(n=>n/255).map(n=>n<=.04045?n/12.92:((n+.055)/1.055)**2.4).reduce((n,v,i)=>n+v*[.2126,.7152,.0722][i],0);
    for (let step=0;step<=100;step++) {
      const values=rgb.map(n=>Math.round(n+(255-n)*step/100));
      if ((luminance(values)+.05)/(luminance([20,22,27])+.05)>=4.5) {loader='#'+values.map(n=>n.toString(16).padStart(2,'0')).join('');break;}
    }
    document.documentElement.style.setProperty('--skin-loader-accent', loader);
  }
  function ghost(source) {
    const rect = source.getBoundingClientRect(), copy = source.cloneNode(true);
    copy.removeAttribute('id'); copy.querySelectorAll('[id]').forEach(node=>node.removeAttribute('id'));
    copy.querySelectorAll('.texture-reconstruction,.swatch-wipe').forEach(node=>node.remove());
    for (const node of [copy,...copy.querySelectorAll('.texture-reconstructing')]) node.classList.remove('texture-reconstructing');
    copy.querySelectorAll('[name]').forEach(node=>node.removeAttribute('name'));
    for (const node of [copy,...copy.querySelectorAll('[data-token],[data-game-rel],[data-library-path]')]) {
      for (const name of ['data-token','data-game-rel','data-library-path']) node.removeAttribute(name);
    }
    copy.inert = true; copy.setAttribute('aria-hidden','true'); copy.classList.add('polish-ghost');
    Object.assign(copy.style,{left:rect.x+'px',top:rect.y+'px',width:rect.width+'px',height:rect.height+'px',margin:'0'});
    document.body.append(copy); return {copy,rect};
  }
  function fly(path) {
    requestAnimationFrame(() => {
      const source = [...document.querySelectorAll('#grid-area .card')].find(node=>node.dataset.libraryPath===path)?.querySelector('.card-thumb');
      const destination = [...document.querySelectorAll('.sb-item')].find(node=>node.dataset.gameRel===path)?.querySelector('.sb-thumb');
      if (!destination) return;
      play(destination,[{boxShadow:'0 0 0 0 var(--acc)'},{boxShadow:'0 0 0 3px transparent'}],220);
      if (!source || reduced()) return;
      const {copy,rect} = ghost(source), end = destination.getBoundingClientRect();
      play(copy,[{opacity:.85,transformOrigin:'top left',transform:'none'},
        {opacity:.65,offset:.6,transformOrigin:'top left',transform:`translate(${(end.x-rect.x)*.55}px,${end.y-rect.y-55}px) scale(.6)`},
        {opacity:0,transformOrigin:'top left',transform:`translate(${end.x-rect.x}px,${end.y-rect.y}px) scale(${end.width/rect.width},${end.height/rect.height})`}],320);
      setTimeout(()=>copy.remove(),340);
    });
  }
  function sidebarBefore(list) {
    return [...list.querySelectorAll('.sb-item')].map(row=>({token:row.dataset.token,rect:row.getBoundingClientRect(),row}));
  }
  function sidebarAfter(previous, list) {
    if (reduced() || !list.getClientRects().length) return;
    for (const entry of previous || []) {
      const next = [...list.querySelectorAll('.sb-item')].find(row=>row.dataset.token===entry.token);
      if (next) {
        const dy = entry.rect.y-next.getBoundingClientRect().y;
        if (dy) play(next,[{transform:`translateY(${dy}px)`},{transform:'none'}],120);
      } else {
        const copy = entry.row.cloneNode(true); copy.classList.add('polish-ghost'); copy.inert=true; copy.setAttribute('aria-hidden','true');
        copy.querySelectorAll('.texture-reconstruction,.swatch-wipe').forEach(node=>node.remove());
        for (const node of [copy,...copy.querySelectorAll('.texture-reconstructing')]) node.classList.remove('texture-reconstructing');
        for (const node of [copy,...copy.querySelectorAll('[data-token],[data-game-rel],[data-library-path]')]) {
          for (const name of ['data-token','data-game-rel','data-library-path']) node.removeAttribute(name);
        }
        Object.assign(copy.style,{left:entry.rect.x+'px',top:entry.rect.y+'px',width:entry.rect.width+'px',height:entry.rect.height+'px',margin:'0',overflow:'hidden'});
        document.body.append(copy);
        play(copy,[{opacity:1,clipPath:'inset(0 0 0 0)'},{opacity:0,clipPath:'inset(100% 0 0 0)'}],300,AtelierMotion.ease.fall);
        const bubbles=document.createElement('span'); bubbles.className='trash-drain'; bubbles.setAttribute('aria-hidden','true'); bubbles.inert=true;
        Object.assign(bubbles.style,{left:(entry.rect.x+8)+'px',top:(entry.rect.y+2)+'px'});
        for(let i=0;i<6;i++) {
          const dot=document.createElement('i'); dot.style.left=(6+i%3*13)+'px'; dot.style.top=(3+Math.floor(i/3)*14)+'px'; bubbles.append(dot);
          play(dot,[{transform:'translateY(0) scale(1)',opacity:1},{transform:`translateY(${12+i*2}px) scale(.6)`,opacity:0}],300,AtelierMotion.ease.fall);
        }
        document.body.append(bubbles);
        setTimeout(()=>{copy.remove();bubbles.remove();},320);
      }
    }
  }
  function packing() {
    if (reduced()) return;
    const tray = document.querySelector('#install-btn .am-export-feedback-slot'); if (!tray) return;
    const target = tray.getBoundingClientRect();
    [...document.querySelectorAll('.sb-item.selected')].slice(0,6).forEach((source,index)=>{
      const {copy,rect}=ghost(source);
      play(copy,[{opacity:.6,transformOrigin:'left center',transform:'none'},
        {opacity:0,transformOrigin:'left center',transform:`translate(${target.x-rect.x}px,${target.y-rect.y}px) scale(.06,.15)`}],220+index*12);
      setTimeout(()=>copy.remove(),320);
    });
  }
  let burstQueued=false;
  function exported() {
    if(!window.AtelierMotionPolicy?.allows(3)||document.hidden)return;
    try { if (localStorage.getItem('atelier.firstExportCelebrated')) return; } catch (_) {}
    const colors = [...new Set([...document.querySelectorAll('.sb-item.selected img')].map(sample).concat(
      [...document.querySelectorAll('.sb-item.selected [data-swatch-color]')].map(node=>node.dataset.swatchColor)).filter(Boolean))].slice(0,6);
    if (!colors.length) return;
    // The export review's stage owns the moment while the dialog is open, so the burst waits for it to
    // close and leaves the then-visible button. The overlay's 120 ms exit and the stage's release follow.
    const overlay=document.getElementById('export-review-overlay');
    if (overlay?.classList.contains('active')) {
      if (burstQueued) return;
      burstQueued=true;
      const closed=()=>{
        if (overlay.classList.contains('active')) return;
        document.removeEventListener('atelier:export-review',closed); burstQueued=false;
        let tries=0; const attempt=()=>{ if(!burst(colors)&&++tries<5) setTimeout(attempt,150); };
        setTimeout(attempt,140);
      };
      document.addEventListener('atelier:export-review',closed);
      return;
    }
    burst(colors);
  }
  // Returns false only when the moment was refused, so a deferred burst can retry.
  function burst(colors) {
    if(!window.AtelierMotionPolicy?.allows(3)||document.hidden)return true;
    try { if (localStorage.getItem('atelier.firstExportCelebrated')) return true; } catch (_) {}
    const release=window.AtelierMotion?.moment?.claim('first-export',3);if(!release)return false;
    try{localStorage.setItem('atelier.firstExportCelebrated','1');}catch(_){}
    const button=document.getElementById('install-btn'), rect=button.getBoundingClientRect();
    colors.forEach((color,index)=>{
      const dot=document.createElement('span'); dot.className='export-color-moment'; dot.style.background=color; dot.setAttribute('aria-hidden','true');
      dot.style.left=(rect.x+rect.width/2)+'px'; dot.style.top=(rect.y+rect.height/2)+'px'; document.body.append(dot);
      if (!reduced()) play(dot,[{opacity:1,transform:'translate(0,0) scale(.6)'},{opacity:0,transform:`translate(${(index-(colors.length-1)/2)*30}px,${-60-index%2*15}px) scale(1)`}],460);
      else dot.style.transform=`translate(${index*10}px,-12px)`;
      setTimeout(()=>dot.remove(),reduced()?1800:480);
    });
    setTimeout(release,500);
    return true;
  }
  // A dismissed toast leaves its slot at once, so the live region, collation and the stack stay truthful,
  // while the same element fades 4 px down for 120 ms (accelerating) in an inert layer. Off removes it outright.
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
      el.animate([{opacity:1,transform:'none'},{opacity:0,transform:'translateY(4px)'}],
        {duration:AtelierMotion.exitMs,easing:AtelierMotion.ease.exit,fill:'forwards'}).finished.then(finish,finish);
      setTimeout(finish,AtelierMotion.exitMs+80);
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
  function empty(host, title, description='', kind='empty') {
    host.classList.add('polish-empty');
    const art=document.createElementNS('http://www.w3.org/2000/svg','svg'); art.setAttribute('viewBox','0 0 96 64'); art.setAttribute('aria-hidden','true');
    art.innerHTML='<path d="M12 18h23l9 8h40v28H12Z M12 42h72 M25 18V9h44v17 M34 18h26 M42 32h12 M48 26v12" fill="none" stroke="currentColor" stroke-width="1.5"/>';
    const text=document.createElement('strong'); text.textContent=title;
    const detail=document.createElement('span'); detail.textContent=description;
    host.replaceChildren(art,text,detail);
    // Krackle art replaces the outline drawing when available; the outline stays as the fallback.
    if (!window.AtelierMotion?.emptyState) return;
    const container=host.parentElement, key=kind+'|'+title, settled=!!container&&emptyKeys.get(container)===key;
    if (container) emptyKeys.set(container,key);
    const krackle=document.createElement('span'); krackle.className='am-empty-state-host k-screen';
    try { host.prepend(krackle); window.AtelierMotion.emptyState.mount(krackle,{kind,reducedMotion:settled?'reduce':'system'}); art.remove(); }
    catch (_) { krackle.remove(); }
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
  window.AtelierPolish=Object.freeze({count,sample,samplePalette,artwork,fly,sidebarBefore,sidebarAfter,packing,exported,swatchesBefore,swatchesAfter,empty,importStart,importProgress,startup,startupDone,play,leave});
})();

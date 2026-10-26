// Truthful, optional presentation. Every transient effect owns a disposable mount.
(() => {
  'use strict';
  const reduced = () => (window.AtelierMotionPolicy?.query() || matchMedia('(prefers-reduced-motion: reduce)')).matches;
  const mounts = new Map();
  const drains = new Set();
  const clearDrains = () => { for (const dispose of [...drains]) dispose(); };
  const receipts = new Set();
  const clearReceipts = () => { for (const dispose of [...receipts]) dispose(); };
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
  window.AtelierMotionPolicy?.query().addEventListener('change', () => { if (!window.AtelierMotionPolicy.allows(2)) clearDrains(); });
  window.AtelierMotionPolicy?.query().addEventListener('change', () => { if (!window.AtelierMotionPolicy.allows(3)) clearReceipts(); });
  document.addEventListener('visibilitychange',()=>{if(document.hidden){clearDrains();clearReceipts();for(const instance of mounts.values())instance.destroy();}});
  window.addEventListener('pagehide',()=>{clearDrains();clearReceipts();});
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
  function fly(path) {
    requestAnimationFrame(() => {
      if (document.hidden || reduced()) return;
      // The asset frame has a clear ink lane even when its image fills the thumbnail.
      const source = [...document.querySelectorAll('#grid-area .card')].find(node=>node.dataset.libraryPath===path);
      const destination = [...document.querySelectorAll('.sb-item')].find(node=>node.dataset.gameRel===path);
      if (!destination) return;
      if (window.AtelierMotion?.workflow?.transfer?.(source,destination,'arrival')) return;
      if (!window.AtelierMotion?.workflow?.arrival(destination))
        play(destination,[{boxShadow:'0 0 0 0 var(--acc)'},{boxShadow:'0 0 0 3px transparent'}],220);
    });
  }
  function sidebarBefore(list) {
    return [...list.querySelectorAll('.sb-item')].map(row=>({token:row.dataset.token,rect:row.getBoundingClientRect(),row}));
  }
  function sidebarAfter(previous, list) {
    if (reduced() || document.hidden || !list.getClientRects().length) return;
    for (const entry of previous || []) {
      const next = [...list.querySelectorAll('.sb-item')].find(row=>row.dataset.token===entry.token);
      if (next) {
        const dy = entry.rect.y-next.getBoundingClientRect().y;
        if (dy) play(next,[{transform:`translateY(${dy}px)`},{transform:'none'}],120);
      } else {
        if (window.AtelierMotionPolicy?.allows(2) === false) continue;
        const copy = entry.row.cloneNode(true); copy.classList.add('polish-ghost'); copy.inert=true; copy.setAttribute('aria-hidden','true');
        copy.removeAttribute('id');copy.querySelectorAll('[id],[name]').forEach(node=>{node.removeAttribute('id');node.removeAttribute('name');});
        copy.querySelectorAll('.texture-reconstruction,.swatch-wipe').forEach(node=>node.remove());
        for (const node of [copy,...copy.querySelectorAll('.texture-reconstructing')]) node.classList.remove('texture-reconstructing');
        for (const node of [copy,...copy.querySelectorAll('[data-token],[data-game-rel],[data-library-path]')]) {
          for (const name of ['data-token','data-game-rel','data-library-path']) node.removeAttribute(name);
        }
        Object.assign(copy.style,{left:entry.rect.x+'px',top:entry.rect.y+'px',width:entry.rect.width+'px',height:entry.rect.height+'px',margin:'0',overflow:'hidden',opacity:'0'});
        document.body.append(copy);
        const rowAnimation=play(copy,[{opacity:1,clipPath:'inset(0 0 0 0)',transform:'none'},{opacity:.8,clipPath:'inset(56% 0 0 0)',transform:'translateY(3px)'},{opacity:0,clipPath:'inset(100% 0 0 0)',transform:'translateY(5px)'}],300,AtelierMotion.ease.fall);
        const bubbles=document.createElement('span'); bubbles.className='trash-drain'; bubbles.setAttribute('aria-hidden','true'); bubbles.inert=true;
        Object.assign(bubbles.style,{left:(entry.rect.x+12)+'px',top:(entry.rect.bottom-14)+'px'});
        const energy=window.AtelierMotion?.energy?.resolve(list);
        if(energy)bubbles.style.setProperty('--krackle-energy',energy.charge);
        const animations=[rowAnimation];
        // Three connected lobes merge into the removed thumbnail's baseline.
        for(let i=0;i<3;i++) {
          const dot=document.createElement('i'); dot.style.left=(i*8)+'px'; dot.style.top='0'; dot.style.opacity='0'; bubbles.append(dot);
          animations.push(play(dot,[{transform:'translateY(-4px) scale(.6,1.1)',opacity:0},{transform:'translateY(0) scale(1.25,.7)',opacity:1,offset:.45},{transform:`translate(${(1-i)*8}px,4px) scale(.2)`,opacity:0}],300,AtelierMotion.ease.fall));
        }
        document.body.append(bubbles);
        const dispose=()=>{clearTimeout(timer);for(const animation of animations)animation.destroy();copy.remove();bubbles.remove();drains.delete(dispose);};
        const timer=setTimeout(dispose,320);drains.add(dispose);
      }
    }
  }
  function packing() {
    if (reduced() || document.hidden || window.AtelierMotionPolicy?.allows(2) === false) return;
    const tray = document.getElementById('install-btn'); if (!tray) return;
    const source = [...document.querySelectorAll('.sb-item.selected')].find(node=>{
      const rect=node.getBoundingClientRect();return rect.width>0&&rect.height>0&&rect.bottom>0&&rect.top<innerHeight;
    });
    // One continuous handoff connects the selected work to its actual export receiver.
    if (source) window.AtelierMotion?.workflow?.transfer?.(source,tray,'action');
  }
  let burstQueued=false;
  function exported() {
    if(!window.AtelierMotionPolicy?.allows(3)||document.hidden)return;
    try { if (localStorage.getItem('atelier.firstExportCelebrated')) return; } catch (_) {}
    const colors = [...new Set([...document.querySelectorAll('.sb-item.selected img')].map(sample).concat(
      [...document.querySelectorAll('.sb-item.selected [data-swatch-color]')].map(node=>node.dataset.swatchColor)).filter(Boolean))].slice(0,6);
    if (!colors.length) return;
    // The export review owns the moment while open. The seal waits for its actual
    // receiver to be visible after the overlay's exit and stage release.
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
    const button=document.getElementById('install-btn');
    if(!button?.isConnected||!button.getClientRects().length){release();return true;}
    // Keep the exported hues readable even when one matches the button's paint.
    colors=colors.map(color=>window.AtelierMotion?.energy?.fit?.(color,button)||color);
    const rect=button.getBoundingClientRect(),slot=button.querySelector('.am-export-feedback-slot')?.getBoundingClientRect();
    const w=rect.width,h=rect.height,seam=h-4.5;
    const sourceX=slot?.width?slot.x-rect.x+slot.width/2:7;
    const sourceY=slot?.height?Math.min(seam,slot.y-rect.y+slot.height*.72):seam;
    const sealWidth=Math.min(64,w*.28),sealX=Math.max(sourceX+8,w/2-sealWidth*.22),sealEnd=Math.min(w-8,sealX+sealWidth);
    const elbow=Math.min(6,Math.max(0,seam-sourceY),Math.max(0,sealX-sourceX));
    const ns='http://www.w3.org/2000/svg',id='export-receipt-'+Math.round(performance.now()*1000);
    const node=(tag,attrs={})=>{const element=document.createElementNS(ns,tag);for(const [key,value] of Object.entries(attrs))element.setAttribute(key,String(value));return element;};
    const svg=node('svg',{class:'export-color-moment',viewBox:`0 0 ${w} ${h}`,width:w,height:h,'aria-hidden':'true',focusable:'false'});
    svg.inert=true;Object.assign(svg.style,{left:rect.left+'px',top:rect.top+'px',width:w+'px',height:h+'px',borderRadius:getComputedStyle(button).borderRadius});
    const defs=node('defs'),gradient=node('linearGradient',{id:id+'-ink',gradientUnits:'userSpaceOnUse',x1:sourceX,y1:seam,x2:sealEnd,y2:seam});
    // Hard stops keep each sampled ink flat while sharing one continuous silhouette.
    colors.forEach((color,index)=>{
      gradient.append(node('stop',{offset:index/colors.length,'stop-color':color}),node('stop',{offset:(index+1)/colors.length,'stop-color':color}));
    });
    const mask=node('mask',{id:id+'-content',maskUnits:'userSpaceOnUse',x:0,y:0,width:w,height:h});
    mask.append(node('rect',{x:0,y:0,width:w,height:h,fill:'white'}));
    // Protect the actual label rectangles, including localized or wrapping labels.
    const walker=document.createTreeWalker(button,NodeFilter.SHOW_TEXT);
    while(walker.nextNode()){
      const text=walker.currentNode;if(!text.textContent.trim()||text.parentElement?.closest('.am-export-feedback-slot'))continue;
      const range=document.createRange();range.selectNodeContents(text);
      for(const box of range.getClientRects())mask.append(node('rect',{class:'export-receipt-content-cutout',x:box.left-rect.left-1,y:box.top-rect.top-1,width:box.width+2,height:box.height+2,fill:'black'}));
    }
    defs.append(gradient,mask);svg.append(defs);
    const ink='url(#'+id+'-ink)',body=node('g',{mask:'url(#'+id+'-content)'});
    const source=node('g',{class:'export-receipt-source'});
    source.append(node('path',{d:`M${sourceX-4} ${sourceY}a4 4 0 1 0 8 0a4 4 0 1 0 -8 0M${sourceX+.1} ${sourceY+.7}a1.3 1.3 0 1 0 2.6 0a1.3 1.3 0 1 0 -2.6 0`,fill:colors[0],'fill-rule':'evenodd'}));
    const flow=node('path',{class:'export-receipt-flow',d:`M${sourceX} ${sourceY}V${seam-elbow}Q${sourceX} ${seam} ${sourceX+elbow} ${seam}H${sealX+4}`,fill:'none',stroke:ink,'stroke-width':5,'stroke-linecap':'round','stroke-linejoin':'round',pathLength:1,'stroke-dasharray':'1 1','stroke-dashoffset':1});
    // A single connected seal, with a cluster of holes cut through its right lobe.
    let sealPath=`M${sealX+4} ${seam-3}H${sealEnd-5}Q${sealEnd+1} ${seam-3} ${sealEnd} ${seam}Q${sealEnd+1} ${seam+3} ${sealEnd-5} ${seam+3}H${sealX+4}Q${sealX-2} ${seam+3} ${sealX} ${seam}Q${sealX-2} ${seam-3} ${sealX+4} ${seam-3}Z`;
    for(const [offset,y,r] of [[8,-.7,1.15],[12,1,1],[16,-.6,.75]]){const x=sealEnd-offset;sealPath+=`M${x-r} ${seam+y}a${r} ${r} 0 1 0 ${r*2} 0a${r} ${r} 0 1 0 ${-r*2} 0Z`;}
    const seal=node('path',{class:'export-receipt-seal',d:sealPath,fill:ink,'fill-rule':'evenodd'});
    body.append(flow,source,seal);svg.append(body);document.body.append(svg);
    const clamp=value=>Math.max(0,Math.min(1,value)),ease=value=>{const t=clamp(value);return t*t*(3-2*t);};
    let frame=null,timer=null,started=null,disposed=false;
    const dispose=()=>{if(disposed)return;disposed=true;clearTimeout(timer);cancelAnimationFrame(frame);svg.remove();release();receipts.delete(dispose);};
    receipts.add(dispose);
    function draw(now){
      if(disposed)return;
      const current=button.getBoundingClientRect();
      if(document.hidden||!button.isConnected||!window.AtelierMotionPolicy?.allows(3)||Math.abs(current.left-rect.left)>1||Math.abs(current.top-rect.top)>1||Math.abs(current.width-w)>1||Math.abs(current.height-h)>1){dispose();return;}
      if(started===null)started=now;const time=now-started;
      if(time>=980){dispose();return;}
      // Charge, pour, receive, compress, rebound, then absorb into the seam.
      const charge=ease(time/130),travel=ease((time-130)/420),arrival=clamp((time-550)/270),fade=1-ease((time-830)/150);
      source.setAttribute('opacity',clamp(time/45)*(1-ease((time-250)/270)));
      const size=.35+charge*.9-travel*.4;
      source.setAttribute('transform',`translate(${sourceX} ${sourceY}) scale(${size} ${size*(1+travel*.25)}) translate(${-sourceX} ${-sourceY})`);
      flow.setAttribute('stroke-dashoffset',1-travel);flow.setAttribute('opacity',clamp((time-120)/60)*fade);
      flow.setAttribute('stroke-width',5+Math.sin(Math.PI*travel)*1.4);
      seal.setAttribute('opacity',clamp((time-550)/45)*fade);
      let sx,sy;
      if(arrival<.42){const t=ease(arrival/.42);sx=.12+t*1.03;sy=1.4-t*.72;}
      else if(arrival<.76){const t=ease((arrival-.42)/.34);sx=1.15-t*.19;sy=.68+t*.46;}
      else{const t=ease((arrival-.76)/.24);sx=.96+t*.04;sy=1.14-t*.14;}
      seal.setAttribute('transform',`translate(${sealX} ${seam}) scale(${sx} ${sy}) translate(${-sealX} ${-seam})`);
      frame=requestAnimationFrame(draw);
    }
    source.setAttribute('opacity',0);seal.setAttribute('opacity',0);flow.setAttribute('opacity',0);
    frame=requestAnimationFrame(draw);timer=setTimeout(dispose,1100);
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
  window.AtelierPolish=Object.freeze({count,sample,samplePalette,accent,artwork,fly,sidebarBefore,sidebarAfter,packing,exported,swatchesBefore,swatchesAfter,empty,importStart,importProgress,startup,startupDone,play,leave});
})();

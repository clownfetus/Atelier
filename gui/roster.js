// Metadata-only catalogue view; opening it never imports assets or refreshes artwork.
(() => {
  'use strict';
  let data = null, pending = null, navigate, requested = false, selected = '';
  let carouselCleanups = [];
  const colourCache = new Map();
  const host = () => document.getElementById('hero-roster');
  const reduced = () => (window.AtelierMotionPolicy?.query() || matchMedia('(prefers-reduced-motion: reduce)')).matches;
  function cleanup() { for (const dispose of carouselCleanups) dispose(); carouselCleanups = []; }
  function carousel(track, label) {
    const wrap=document.createElement('div');wrap.className='roster-carousel';
    const buttons=[-1,1].map(direction=>{
      const button=document.createElement('button');button.type='button';button.className='roster-scroll';
      button.setAttribute('aria-label',`${direction<0?'Previous':'Next'} ${label}`);
      button.innerHTML=`<i data-lucide="chevron-${direction<0?'left':'right'}" size="20"></i>`;
      button.addEventListener('click',()=>track.scrollBy({left:direction*Math.max(100,track.clientWidth*.8),behavior:reduced()?'instant':'smooth'}));
      return button;
    });
    wrap.append(buttons[0],track,buttons[1]);window.AtelierIcons?.createIcons({nodes:[wrap]});
    const update=()=>{
      const max=Math.max(0,track.scrollWidth-track.clientWidth);
      buttons[0].disabled=track.scrollLeft<=1;buttons[1].disabled=track.scrollLeft>=max-1;
    };
    track.addEventListener('scroll',update,{passive:true});
    const observer=new ResizeObserver(update);observer.observe(track);
    carouselCleanups.push(()=>{observer.disconnect();track.removeEventListener('scroll',update);});
    requestAnimationFrame(update);document.fonts?.ready.then(update);
    return {wrap,update};
  }
  function rgb(value) {
    const hex=/^#([a-f\d]{6})$/i.exec(value.trim());
    if(hex)return hex[1].match(/../g).map(value=>parseInt(value,16));
    const match=/^rgb\(\s*(\d+)[, ]+\s*(\d+)[, ]+\s*(\d+)/.exec(value);
    return match ? match.slice(1).map(Number) : null;
  }
  const hex=values=>'#'+values.map(value=>Math.round(value).toString(16).padStart(2,'0')).join('');
  const luminance=values=>values.map(value=>value/255).map(value=>value<=.04045?value/12.92:((value+.055)/1.055)**2.4).reduce((sum,value,index)=>sum+value*[.2126,.7152,.0722][index],0);
  const contrast=(a,b)=>(Math.max(luminance(a),luminance(b))+.05)/(Math.min(luminance(a),luminance(b))+.05);
  function paintSkin(tile) {
    const accent=rgb(tile.dataset.artworkColour || '');if(!accent)return;
    const style=getComputedStyle(tile),base=rgb(style.getPropertyValue('--bg2')),text=rgb(style.getPropertyValue('--text'));
    if(!base || !text)return;
    const background=base.map((value,index)=>value*.65+accent[index]*.35);
    const foreground=contrast(text,background)>=4.5?text:contrast([0,0,0],background)>contrast([255,255,255],background)?[0,0,0]:[255,255,255];
    tile.style.setProperty('--roster-skin-background',hex(background));tile.style.setProperty('--roster-skin-foreground',hex(foreground));
    tile.style.setProperty('--roster-skin-border',hex(base.map((value,index)=>value*.35+accent[index]*.65)));
  }
  function skinColour(url) {
    if(!colourCache.has(url))colourCache.set(url,new Promise(resolve=>{
      const image=new Image();image.decoding='async';
      image.onload=()=>resolve(window.AtelierPolish?.sample(image) || null);
      image.onerror=()=>{colourCache.delete(url);resolve(null);};image.src=url;
    }));
    return colourCache.get(url);
  }
  function tintSkin(tile, skin) {
    if(!skin.thumbnail)return;
    skinColour(skin.thumbnail).then(colour=>{if(colour&&tile.isConnected){tile.dataset.artworkColour=colour;paintSkin(tile);}});
  }
  const themeObserver=new MutationObserver(()=>{for(const tile of host()?.querySelectorAll('.roster-skin[data-artwork-colour]') || [])paintSkin(tile);});
  themeObserver.observe(document.documentElement,{attributes:true,attributeFilter:['data-theme','data-palette','style']});
  window.addEventListener('pagehide',()=>{cleanup();themeObserver.disconnect();});
  function image(item) {
    const img = document.createElement('img'); img.alt=''; img.loading='lazy'; img.decoding='async'; img.src=item.avatar;
    img.addEventListener('error',()=>{img.hidden=true;}); return img;
  }
  function render() {
    const root=host(); if (!root || !requested || !data) return;
    cleanup();root.replaceChildren(); root.hidden=false;
    if (!data.heroes?.length) { window.AtelierPolish?.empty(root,'Catalogue unavailable','Browse the library folders below. Saved artwork will return when available.'); return; }
    const details=document.createElement('details'); details.open=true;
    const summary=document.createElement('summary'); summary.textContent='Character roster'; details.append(summary);
    const heroes=document.createElement('div'); heroes.className='roster-strip'; heroes.setAttribute('role','group'); heroes.setAttribute('aria-label','Heroes');
    const skins=document.createElement('div'); skins.className='roster-skins'; skins.setAttribute('role','group'); skins.setAttribute('aria-label','Selected hero costumes');
    const heroCarousel=carousel(heroes,'heroes'),skinCarousel=carousel(skins,'skins');
    function choose(hero, button) {
      selected = hero.path;
      heroes.querySelectorAll('button').forEach(node=>node.setAttribute('aria-pressed',String(node===button)));
      skins.replaceChildren();
      const open=document.createElement('button'); open.className='roster-open'; open.textContent='Open '+hero.name; open.addEventListener('click',()=>navigate?.(hero.path)); skins.append(open);
      for (const skin of hero.skins || []) {
        const tile=document.createElement('button'); tile.className='roster-skin'; tile.title=skin.name; tile.setAttribute('aria-label',skin.name);
        const label=document.createElement('span'); label.textContent=skin.name; tile.append(label);
        tile.addEventListener('click',()=>navigate?.(skin.path)); skins.append(tile);
        tintSkin(tile,skin);
      }
      skins.scrollLeft=0;requestAnimationFrame(skinCarousel.update);
    }
    for (const hero of data.heroes) {
      const button=document.createElement('button'); button.className='roster-portrait'; button.setAttribute('aria-pressed','false');
      button.title=hero.name; button.append(image(hero)); const label=document.createElement('span'); label.textContent=hero.name; button.append(label);
      button.addEventListener('click',()=>choose(hero,button)); heroes.append(button);
    }
    details.append(heroCarousel.wrap,skinCarousel.wrap); root.append(details);
    const index = Math.max(0,data.heroes.findIndex(hero=>hero.path===selected));
    choose(data.heroes[index],heroes.children[index]);
    heroes.children[index]?.scrollIntoView({block:'nearest',inline:'nearest'});requestAnimationFrame(heroCarousel.update);
  }
  window.addEventListener('atelier:catalogue-updated', () => {
    if (pending) return;
    pending=fetch('/api/catalogue/library').then(response=>{if(!response.ok)throw Error();return response.json();})
      .then(result=>{data=result;host()?.replaceChildren();render();}).catch(()=>{}).finally(()=>{pending=null;});
  });
  function show(home, onNavigate) {
    requested=home; navigate=onNavigate; const root=host(); if (!root) return;
    if (!home) {root.hidden=true;return;}
    if (data) {if(!root.childNodes.length) render();else root.hidden=false;return;}
    if (!pending) pending=fetch('/api/catalogue/library').then(response=>{if(!response.ok)throw Error();return response.json();})
      .then(result=>{data=result;render();}).catch(()=>{data={heroes:[]};render();}).finally(()=>{pending=null;});
  }
  function describe(path) {
    const parts=path.split('/'), hero=data?.heroes?.find(item=>item.path==='Characters/'+parts[1]);
    return hero ? {hero,skin:hero.skins?.find(item=>item.path==='Characters/'+parts[1]+'/'+parts[2])} : null;
  }
  window.AtelierRoster=Object.freeze({show,describe});
})();

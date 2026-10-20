// Metadata-only catalogue view; opening it never imports assets or refreshes artwork.
(() => {
  'use strict';
  let data = null, pending = null, navigate, requested = false, selected = '';
  let carouselCleanups = [];
  let edits=[],project='',filter='all',options={},signature='',recent=[];
  const storageKey=()=> 'atelier.roster.'+project+'.v1';
  const read=()=>{try{return JSON.parse(localStorage.getItem(storageKey()))||{};}catch(_){return {};}};
  const write=value=>{try{localStorage.setItem(storageKey(),JSON.stringify(value));}catch(_){}};
  function rememberEditor(gameRel,kind,inProject=project) {
    try {const key='atelier.editors.'+inProject+'.v1',saved=JSON.parse(localStorage.getItem(key)||'{}');saved[gameRel]=kind;localStorage.setItem(key,JSON.stringify(saved));}catch(_){}
  }
  function editorFor(item) {try{return JSON.parse(localStorage.getItem('atelier.editors.'+project+'.v1')||'{}')[item.game_rel]||item.file_type;}catch(_){return item.file_type;}}
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
      image.onload=()=>resolve(window.AtelierPolish?.accent(image) || null);
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
    const img = document.createElement('img'); img.alt=''; img.loading='lazy'; img.decoding='async'; img.src=item.avatar||item.thumbnail||'';
    img.addEventListener('load',()=>{const colour=window.AtelierPolish?.accent(img);if(colour)img.parentElement?.style.setProperty('--roster-accent',colour);});
    img.addEventListener('error',()=>{img.hidden=true;}); return img;
  }
  function render() {
    const root=host(); if (!root || !requested || !data) return;
    renderContinue();
    cleanup();root.replaceChildren(); root.hidden=false;
    if (!data.heroes?.length) { window.AtelierPolish?.empty(root,'Catalogue unavailable','Browse the library folders below. Saved artwork will return when available.'); return; }
    // A plain section: the label shares the filter row, and the hero grid fills the free height.
    const details=document.createElement('div'); details.className='roster-section';
    const filters=document.createElement('div');filters.className='roster-filters';filters.setAttribute('role','group');filters.setAttribute('aria-label','Filter heroes');
    const heading=document.createElement('h2'); heading.className='roster-heading'; heading.textContent='Heroes'; filters.append(heading);
    for(const [value,label] of [['all','All'],['edited','Edited'],['recent','Recently opened']]) {
      const button=document.createElement('button');button.className='btn';button.textContent=label;button.setAttribute('aria-pressed',String(value===filter));button.addEventListener('click',()=>{filter=value;render();});filters.append(button);
    }
    details.append(filters);
    const heroes=document.createElement('div'); heroes.className='roster-strip'; heroes.setAttribute('role','group'); heroes.setAttribute('aria-label','Heroes');
    const skins=document.createElement('div'); skins.className='roster-skins'; skins.setAttribute('role','group'); skins.setAttribute('aria-label','Selected hero costumes');
    const skinCarousel=carousel(skins,'skins');
    function choose(hero, button,record=false) {
      selected = hero.path;
      if(record){recent=[hero.path,...recent.filter(path=>path!==hero.path)].slice(0,30);write({recent});}
      heroes.querySelectorAll('button').forEach(node=>node.setAttribute('aria-pressed',String(node===button)));
      skins.replaceChildren();
      const open=document.createElement('button'); open.className='roster-open'; open.textContent='Open '+hero.name; open.addEventListener('click',()=>navigate?.(hero.path)); skins.append(open);
      for (const skin of hero.skins || []) {
        const tile=document.createElement('button'); tile.className='roster-skin'; tile.title=skin.name; tile.setAttribute('aria-label',skin.name);
        if(skin.icon){const icon=document.createElement('img');icon.className='roster-skin-icon';icon.alt='';icon.loading='lazy';icon.decoding='async';icon.src=skin.icon;icon.addEventListener('error',()=>icon.remove());tile.append(icon);}
        const label=document.createElement('span'); label.textContent=skin.name; tile.append(label);
        tile.addEventListener('click',()=>options.openSkin?options.openSkin(skin):navigate?.(skin.path)); skins.append(tile);
        tintSkin(tile,skin);
      }
      skins.scrollLeft=0;requestAnimationFrame(skinCarousel.update);
    }
    const editCount=hero=>edits.filter(item=>item.char_id===hero.path.split('/')[1]||item.game_rel.startsWith(hero.path+'/')).length;
    const shown=data.heroes.filter(hero=>filter==='all'||(filter==='edited'?editCount(hero)>0:recent.includes(hero.path)));
    if(filter==='recent')shown.sort((a,b)=>recent.indexOf(a.path)-recent.indexOf(b.path));
    for (const hero of shown) {
      const button=document.createElement('button'); button.className='roster-portrait'; button.setAttribute('aria-pressed','false');
      const count=editCount(hero);button.classList.toggle('has-edits',count>0);
      button.title=hero.name;button.setAttribute('aria-label',hero.name);
      const artwork=document.createElement('div');artwork.className='roster-art';artwork.append(image(hero));button.append(artwork);
      const label=document.createElement('strong');label.className='roster-hero-name';label.textContent=hero.name;
      const costumes=hero.skins?.length||0;
      const counts=document.createElement('span');counts.className='roster-counts';counts.textContent=`${costumes} costume${costumes===1?'':'s'} · ${count} edit${count===1?'':'s'}`;button.append(label,counts);
      button.addEventListener('click',()=>choose(hero,button,true)); heroes.append(button);
    }
    heroes.classList.add('k-screen');
    heroes.addEventListener('keydown',event=>{
      if(!['ArrowLeft','ArrowRight','ArrowUp','ArrowDown','Home','End'].includes(event.key))return;
      const buttons=[...heroes.children],index=buttons.indexOf(document.activeElement);if(index<0)return;
      const columns=Math.max(1,Math.round(heroes.clientWidth/buttons[0].offsetWidth));
      const delta={ArrowLeft:-1,ArrowRight:1,ArrowUp:-columns,ArrowDown:columns};
      const next=event.key==='Home'?0:event.key==='End'?buttons.length-1:Math.min(buttons.length-1,Math.max(0,index+delta[event.key]));event.preventDefault();buttons[next].focus();
    });
    details.append(heroes,skinCarousel.wrap);root.append(details);
    if(shown.length){const index=Math.max(0,shown.findIndex(hero=>hero.path===selected));choose(shown[index],heroes.children[index]);}
    else {const empty=document.createElement('p');empty.className='roster-filter-empty';empty.textContent=filter==='edited'?'No heroes have edits in this project.':'Open a hero to see it here.';heroes.append(empty);}
    renderContinue();
  }
  window.addEventListener('atelier:catalogue-updated', () => {
    if (pending) return;
    pending=fetch('/api/catalogue/library').then(response=>{if(!response.ok)throw Error();return response.json();})
      .then(result=>{data=result;host()?.replaceChildren();render();}).catch(()=>{}).finally(()=>{pending=null;});
  });
  function show(home, onNavigate,opts={}) {
    requested=home; navigate=onNavigate;options=opts;const root=host(); if (!root) return;
    renderContinue();
    if (!home) {root.hidden=true;return;}
    if (data) {if(!root.childNodes.length) render();else root.hidden=false;return;}
    if (!pending) pending=fetch('/api/catalogue/library').then(response=>{if(!response.ok)throw Error();return response.json();})
      .then(result=>{data=result;render();}).catch(()=>{data={heroes:[]};render();}).finally(()=>{pending=null;});
  }
  function update(items,inProject) {
    const next=JSON.stringify([inProject,items.map(item=>[item.game_rel,item.modified||item.mtime,item.file_type])]);
    if(next===signature)return;signature=next;edits=items;
    if(project!==inProject){project=inProject;filter='all';const stored=read();recent=Array.isArray(stored.recent)?stored.recent.filter(path=>typeof path==='string'):[];}
    render();
  }
  function renderContinue() {
    const root=document.getElementById('continue-ribbon');if(!root)return;
    const item=[...edits].sort((a,b)=>(b.modified||b.mtime||0)-(a.modified||a.mtime||0))[0];root.replaceChildren();root.hidden=!requested||!item;
    root.classList.remove('has-skin-colour');root.style.removeProperty('--continue-colour');
    if(!item)return;
    if(item.file_type==='texture'||item.skin_id){const img=document.createElement('img');img.alt='';img.src=item.file_type==='texture'?`/api/preview?game_rel=${encodeURIComponent(item.game_rel)}&_project=${encodeURIComponent(project)}`:'/api/catalogue/thumbnail/'+item.skin_id;img.onerror=()=>img.remove();root.append(img);}
    // The skin's colour edges the ribbon (decoration only; its button keeps the theme's primary ink).
    if(item.skin_id)skinColour('/api/catalogue/thumbnail/'+item.skin_id).then(colour=>{if(colour&&root.contains(copy)){root.style.setProperty('--continue-colour',colour);root.classList.add('has-skin-colour');}});
    const copy=document.createElement('div'),title=document.createElement('strong');title.textContent='Pick up where you left off';
    const detail=document.createElement('p'),seconds=Math.max(0,Date.now()/1000-(item.modified||item.mtime||0));
    const ago=seconds<60?'just now':seconds<3600?Math.floor(seconds/60)+' min ago':seconds<86400?Math.floor(seconds/3600)+' h ago':Math.floor(seconds/86400)+' d ago';
    detail.textContent=[item.char_name,item.skin_name,item.name].filter(Boolean).join(' · ')+', edited '+ago;copy.append(title,detail);root.append(copy);
    const button=document.createElement('button');button.className='btn primary';button.textContent='Continue editing';button.addEventListener('click',()=>options.continue?.(item,editorFor(item)));root.append(button);
  }
  function describe(path) {
    const parts=path.split('/'), hero=data?.heroes?.find(item=>item.path==='Characters/'+parts[1]);
    return hero ? {hero,skin:hero.skins?.find(item=>item.path==='Characters/'+parts[1]+'/'+parts[2])} : null;
  }
  window.AtelierRoster=Object.freeze({show,describe,update,rememberEditor});
})();

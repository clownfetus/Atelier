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
  const homeHeroesKey='atelier.homeHeroesOpen';
  const openByDefault=()=>{try{return localStorage.getItem(homeHeroesKey)!=='0';}catch(_){return true;}};
  let heroesOpen=openByDefault();
  function expandHeroes(open) {
    heroesOpen=open;
    const root=host(),content=root?.querySelector('.roster-content'),toggle=root?.querySelector('.roster-toggle');
    root?.classList.toggle('roster-collapsed',!open);
    if(content)content.hidden=!open;
    toggle?.setAttribute('aria-expanded',String(open));
  }
  document.addEventListener('DOMContentLoaded',()=>{
    const control=document.getElementById('settings-home-heroes');if(!control)return;
    control.checked=openByDefault();
    control.addEventListener('change',()=>{
      try{localStorage.setItem(homeHeroesKey,control.checked?'1':'0');}catch(_){}
      expandHeroes(control.checked);
    });
  });
  window.addEventListener('storage',event=>{
    if(event.key!==homeHeroesKey&&event.key!==null)return;
    const open=openByDefault(),control=document.getElementById('settings-home-heroes');
    if(control)control.checked=open;expandHeroes(open);
  });
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
  function skinColour(url) {
    if(!colourCache.has(url)) {
      const pending=new Promise(resolve=>{
        const image=new Image();image.decoding='async';
        image.onload=()=>resolve(window.AtelierPolish?.accent(image) || null);
        image.onerror=()=>resolve(null);image.src=url;
      });
      colourCache.set(url,pending);
      // Failed or unsampleable art can become available after a catalogue refresh or retry.
      pending.then(colour=>{if(!colour&&colourCache.get(url)===pending)colourCache.delete(url);});
    }
    return colourCache.get(url);
  }
  async function identityColour(path, skin, hero) {
    const match=/^Characters\/(\d{4})(?:\/(\d{7}))?(?:\/|$)/i.exec(path || '');
    const sources=[
      ...(match?.[2]&&!skin?.hero_fallback ? [skin?.icon || '/api/catalogue/icon/'+match[2],
        skin?.thumbnail || '/api/catalogue/thumbnail/'+match[2],skin?.banner] : []),
      hero?.avatar || (match&&'/api/catalogue/hero/'+match[1]+'/avatar'),
      hero?.thumbnail || (match&&'/api/catalogue/thumbnail/'+match[1]),
      match&&'/api/catalogue/hero/'+match[1]+'/story',
    ];
    for(const src of new Set(sources.filter(Boolean))) {
      const colour=await skinColour(src);if(colour)return colour;
    }
    return null;
  }
  function tintSkin(tile, skin, hero) {
    identityColour(skin.path,skin,hero).then(colour=>{
      if(colour&&tile.isConnected){tile.dataset.artworkColour=colour;tile.style.setProperty('--roster-skin-accent',colour);}
    });
  }
  window.addEventListener('pagehide',cleanup);
  function image(item) {
    const img = document.createElement('img'); img.alt=''; img.loading='lazy'; img.decoding='async';
    const sources=[...new Set([item.avatar,item.thumbnail].filter(Boolean))];
    const next=()=>{if(sources.length)img.src=sources.shift();else img.hidden=true;};
    img.addEventListener('load',()=>{const colour=window.AtelierPolish?.accent(img);if(colour&&img.isConnected)img.parentElement?.style.setProperty('--roster-accent',colour);});
    img.addEventListener('error',next);next();return img;
  }
  function render() {
    const root=host(); if (!root || !requested || !data) return;
    renderContinue();
    cleanup();root.replaceChildren(); root.hidden=false;
    const details=document.createElement('div'); details.className='roster-section';
    const heading=document.createElement('h2');heading.className='roster-heading';
    const toggle=document.createElement('button');toggle.type='button';toggle.className='roster-toggle';toggle.setAttribute('aria-controls','home-heroes-content');
    toggle.innerHTML='<span class="roster-disclosure" aria-hidden="true">▸</span> Heroes';
    toggle.addEventListener('click',()=>expandHeroes(!heroesOpen));heading.append(toggle);
    const content=document.createElement('div');content.className='roster-content';content.id='home-heroes-content';
    details.append(heading,content);root.append(details);expandHeroes(heroesOpen);
    if (!data.heroes?.length) { window.AtelierPolish?.empty(content,'Catalogue unavailable','Browse the library folders below. Saved artwork will return when available.'); return; }
    const filters=document.createElement('div');filters.className='roster-filters';filters.setAttribute('role','group');filters.setAttribute('aria-label','Filter heroes');
    for(const [value,label] of [['all','All'],['edited','Edited'],['recent','Recently opened']]) {
      const button=document.createElement('button');button.className='btn';button.textContent=label;button.setAttribute('aria-pressed',String(value===filter));button.addEventListener('click',()=>{filter=value;render();});filters.append(button);
    }
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
        if(skin.icon||skin.badge){const icon=document.createElement('img');icon.className='roster-skin-icon';icon.alt='';icon.loading='lazy';icon.decoding='async';
          window.AtelierCatalogueArt.load(icon,[skin.icon,skin.badge]);tile.append(icon);}
        const label=document.createElement('span'); label.textContent=skin.name; tile.append(label);
        tile.addEventListener('click',()=>options.openSkin?options.openSkin(skin):navigate?.(skin.path)); skins.append(tile);
        tintSkin(tile,skin,hero);
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
      button.addEventListener('click',()=>choose(hero,button,true));
      button.addEventListener('dblclick',()=>navigate?.(hero.path));
      heroes.append(button);
    }
    heroes.classList.add('k-screen');
    heroes.addEventListener('keydown',event=>{
      if(!['ArrowLeft','ArrowRight','ArrowUp','ArrowDown','Home','End'].includes(event.key))return;
      const buttons=[...heroes.children],index=buttons.indexOf(document.activeElement);if(index<0)return;
      const columns=Math.max(1,Math.round(heroes.clientWidth/buttons[0].offsetWidth));
      const delta={ArrowLeft:-1,ArrowRight:1,ArrowUp:-columns,ArrowDown:columns};
      const next=event.key==='Home'?0:event.key==='End'?buttons.length-1:Math.min(buttons.length-1,Math.max(0,index+delta[event.key]));event.preventDefault();buttons[next].focus();
    });
    content.append(filters,heroes,skinCarousel.wrap);
    if(shown.length){const index=Math.max(0,shown.findIndex(hero=>hero.path===selected));choose(shown[index],heroes.children[index]);}
    else {const empty=document.createElement('p');empty.className='roster-filter-empty';empty.textContent=filter==='edited'?'No heroes have edits in this project.':'Open a hero to see it here.';heroes.append(empty);}
    renderContinue();
  }
  window.addEventListener('atelier:catalogue-updated', () => {
    colourCache.clear();
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
    if(!requested||!item)return;
    const inProject=project;
    if(item.file_type==='texture'||item.skin_id){const img=document.createElement('img');img.alt='';
      const sources=item.file_type==='texture'?[`/api/preview?game_rel=${encodeURIComponent(item.game_rel)}&_project=${encodeURIComponent(project)}`]:
        ['/api/catalogue/badge/'+item.skin_id,'/api/catalogue/icon/'+item.skin_id,'/api/catalogue/thumbnail/'+item.skin_id];
      window.AtelierCatalogueArt.load(img,sources);root.append(img);}
    const copy=document.createElement('div'),title=document.createElement('strong');title.textContent='Pick up where you left off';
    const detail=document.createElement('p'),seconds=Math.max(0,Date.now()/1000-(item.modified||item.mtime||0));
    const ago=seconds<60?'just now':seconds<3600?Math.floor(seconds/60)+' min ago':seconds<86400?Math.floor(seconds/3600)+' h ago':Math.floor(seconds/86400)+' d ago';
    detail.textContent=[item.char_name,item.skin_name,item.name].filter(Boolean).join(' · ')+', edited '+ago;
    const heroChip=window.AtelierCatalogueArt?.heroChip(item);if(heroChip)detail.prepend(heroChip);
    copy.append(title,detail);root.append(copy);
    const button=document.createElement('button');button.className='btn primary';button.textContent='Continue editing';button.addEventListener('click',()=>options.continue?.(item,editorFor(item)));root.append(button);
    // Match the library/roster identity art; an asset path also works when sidebar IDs are absent.
    const path=/^Characters\//i.test(item.game_rel) ? item.game_rel : ['Characters',item.char_id||item.skin_id?.slice(0,4),item.skin_id].filter(Boolean).join('/');
    const context=describe(path);
    identityColour(path,context?.skin,context?.hero).then(colour=>{
      if(colour&&requested&&project===inProject&&root.contains(copy)){
        root.style.setProperty('--continue-colour',colour);root.classList.add('has-skin-colour');
      }
    });
  }
  function describe(path) {
    const parts=path.split('/'), hero=data?.heroes?.find(item=>item.path==='Characters/'+parts[1]);
    return hero ? {hero,skin:hero.skins?.find(item=>item.path==='Characters/'+parts[1]+'/'+parts[2])} : null;
  }
  window.AtelierRoster=Object.freeze({show,describe,update,rememberEditor});
})();

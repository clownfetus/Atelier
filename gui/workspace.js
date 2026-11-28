(() => {
  const $ = id => document.getElementById(id);
  let catalogue, loading, creating=false, choosing=false, busy=false, session=0, selectedHero='', heroArtToken=0;
  function decorateChoiceHeading(hero) {
    const heading = document.querySelector('#workspace-choice .workspace-choice-heading');
    if (!heading) return;
    const token = ++heroArtToken;
    heading.classList.remove('has-hero-art');
    heading.style.removeProperty('--ws-hero-art');
    let ornament = heading.querySelector('.workspace-hero-ornament');
    if (ornament) ornament.replaceChildren();
    const cid = hero?.path?.split('/').pop();
    if (!/^\d{4}$/.test(cid || '')) { ornament?.remove(); return; }
    if (!ornament) {
      ornament = document.createElement('div');
      ornament.className = 'workspace-hero-ornament';
      ornament.setAttribute('aria-hidden', 'true');
      const searchInput = $('workspace-search');
      if (searchInput && searchInput.parentElement === heading) searchInput.before(ornament);
      else heading.append(ornament);
    }
    const enc = encodeURIComponent;
    const logo = document.createElement('img');
    logo.className = 'workspace-hero-logo'; logo.alt = ''; logo.decoding = 'async'; logo.hidden = true;
    logo.onload = () => { if (token === heroArtToken) logo.hidden = false; };
    logo.onerror = () => logo.remove();
    logo.src = '/api/catalogue/hero/' + enc(cid) + '/logo';
    const sig = document.createElement('img');
    sig.className = 'workspace-hero-signature'; sig.alt = ''; sig.decoding = 'async'; sig.hidden = true;
    sig.onload = () => { if (token === heroArtToken) sig.hidden = false; };
    sig.onerror = () => sig.remove();
    sig.src = '/api/catalogue/hero/' + enc(cid) + '/signature';
    ornament.append(logo, sig);
    const sources = [
      '/api/catalogue/hero/' + enc(cid) + '/story',
      window.AtelierCatalogueArt?.bannerUrl('/api/catalogue/banner/' + enc(cid)),
    ].filter(Boolean);
    const probe = new Image(); probe.decoding = 'async';
    const next = () => {
      if (token !== heroArtToken) return;
      if (!sources.length) return;
      probe.src = sources.shift();
    };
    probe.onload = () => {
      if (token !== heroArtToken) return;
      const loaded = probe.getAttribute('src');
      if (loaded) {
        heading.style.setProperty('--ws-hero-art', `url("${loaded}")`);
        heading.classList.add('has-hero-art');
      }
    };
    probe.onerror = next;
    next();
  }
  function opening(state=null) {
    $('workspace-opening').hidden=!state;
    if(state==='loading')$('workspace').setAttribute('aria-busy','true');
    else $('workspace').removeAttribute('aria-busy');
    document.querySelector('.workspace-steps').hidden=!!state;
    if(!state)return;
    $('workspace-stage').hidden=$('workspace-choice').hidden=$('workspace-choose').hidden=true;
    $('workspace-retry').hidden=state!=='error';
    $('workspace-opening-status').textContent=state==='error'
      ? 'Could not open your saved workspace. Try again, or return to Library.'
      : 'Opening your saved workspace…';
    $('workspace-help').textContent=state==='error'
      ? 'Your saved edits are still in this project.' : 'Loading the costume you last worked on.';
  }
  function page(name) {
    window.AtelierRoster?.hideHoverCard?.();
    document.body.dataset.page=name;
    $('workspace').hidden=name!=='workspace'; $('body').hidden=name!=='library';
    for(const item of ['library','workspace']) $('page-'+item).setAttribute('aria-current',item===name?'page':'false');
    $('page-library').disabled=!window.atelierProject?.();
    $('workspace-title').textContent=creating?'Start a recolour':window.atelierProject?.() || 'Your next creation';
    $('workspace-advanced').hidden=!window.atelierProject?.();
    $('workspace-step-choose').toggleAttribute('aria-current',choosing);
    $('workspace-step-edit').toggleAttribute('aria-current',!choosing);
    if(choosing)$('workspace-step-choose').setAttribute('aria-current','step');
    else $('workspace-step-edit').setAttribute('aria-current','step');
    $('workspace-help').hidden=choosing;
    $('workspace-help').textContent='Click a part on the model or in the list. Pick a colour, then save your changes.';
  }
  function present() {
    opening();
    creating=false; choosing=false; page('workspace');
    $('project-overlay').classList.remove('active');
    $('workspace-choice').hidden=true; $('workspace-stage').hidden=false; $('workspace-choose').hidden=false;
    window.AtelierViewport.mount($('workspace-stage'));
  }
  async function library({closed=false}={}) {
    if(!window.atelierProject?.())return false;
    if(!closed && await window.AtelierViewport?.close({navigate:false})===false)return false;
    session++; choosing=false; creating=false;
    opening();
    window.AtelierViewport?.mount(null);
    $('project-overlay').classList.remove('active'); page('library');
    $('search-input').focus();
    return true;
  }
  async function resume() {
    const project=window.atelierProject?.(), ticket=++session;
    if(!project)return start();
    creating=false; choosing=false; page('workspace'); opening('loading');
    try {
      const response=await window.atelierFetch('/api/project/workspace',{},project);
      if(!response.ok)throw Error('Workspace could not be loaded.');
      const data=await response.json();
      if(data.ok===false)throw Error('Workspace could not be loaded.');
      if(ticket!==session || project!==window.atelierProject?.())return;
      const state=data.workspace || {};
      if(!state.skin_id)return choose();
      present();
      await window.AtelierViewport.open(state.skin_id,state.title,state.model || null,state.material_set || null);
    } catch(error) {
      if(ticket===session && project===window.atelierProject?.())opening('error');
    }
  }
  function loadCatalogue() {
    loading ||= fetch('/api/catalogue/library').then(response=>{
      if(!response.ok)throw Error('Could not load heroes.');
      return response.json();
    }).finally(()=>loading=null);
    return loading;
  }

  async function choose(fresh=false) {
    if(await window.AtelierViewport?.close({navigate:false})===false)return;
    opening();
    const ticket=++session; creating=fresh; choosing=true; page('workspace');
    $('project-overlay').classList.remove('active');
    $('workspace-stage').hidden=true; $('workspace-choice').hidden=false; $('workspace-choose').hidden=true;
    $('workspace-search').value=''; $('workspace-heroes').replaceChildren(); $('workspace-costumes').replaceChildren();
    $('workspace-choice-status').textContent='Loading heroes…';
    try {
      const data=catalogue || await loadCatalogue();
      if(ticket!==session)return;
      catalogue=data;
      render(); $('workspace-search').focus({preventScroll:true});
    } catch(error) {
      if(ticket!==session)return;
      $('workspace-choice-status').textContent='Heroes could not be loaded. Try again in a moment.';
      const retry=document.createElement('button');retry.className='at-btn';retry.textContent='Try again';retry.onclick=()=>choose(fresh);$('workspace-choice-status').append(' ',retry);
    }
  }
  function render() {
    const search=$('workspace-search'), heroList=$('workspace-heroes'), costumeList=$('workspace-costumes');
    const focused=document.activeElement;
    const focusList=[heroList,costumeList].find(list=>list.contains(focused));
    const focusPath=focused?.dataset.path;
    const heroScroll=heroList.scrollLeft;
    const query=search.value.trim().toLowerCase();
    const heroes=(catalogue?.heroes || []).filter(h=>h.name.toLowerCase().includes(query)||(h.skins||[]).some(s=>s.name.toLowerCase().includes(query)));
    const hero=heroes.find(h=>h.path===selectedHero) || heroes[0];
    selectedHero=hero?.path || '';
    decorateChoiceHeading(hero);
    heroList.replaceChildren(); costumeList.replaceChildren();
    $('workspace-choice-status').textContent=heroes.length?(hero.skins?.length?'':'No costumes are available for this hero yet.'):query?'No heroes or costumes match. Try another name.':'The costume library is not ready yet. Try again after indexing.';
    if(!heroes.length&&!query) {
      const retry=document.createElement('button');retry.className='at-btn';retry.textContent='Try again';retry.onclick=()=>{catalogue=null;choose(creating);};$('workspace-choice-status').append(' ',retry);
    }
    for(const item of heroes) {
      const button=document.createElement('button');button.className='workspace-hero';button.type='button';button.setAttribute('aria-pressed',String(item===hero));
      const image=document.createElement('img');image.alt='';image.loading='lazy';image.src=item.avatar || item.thumbnail || '/api/catalogue/hero/'+encodeURIComponent(item.path.split('/').pop())+'/avatar';
      image.onerror=()=>image.hidden=true;button.append(image,document.createTextNode(item.name));
      button.dataset.path=item.path;
      button.onclick=()=>{window.AtelierRoster?.hideHoverCard?.();selectedHero=item.path;render();};heroList.append(button);
      const cid=item.path?.split('/').pop()||'';
      const costumeCount=item.skins?.length||0;
      window.AtelierRoster?.attachHoverCard?.(button,()=>({
        title:item.name,
        subtitle:`${costumeCount} costume${costumeCount===1?'':'s'}`,
        charId:/^\d{4}$/.test(cid)?cid:'',
        skinId:'',
        avatar:item.avatar||item.thumbnail||'',
      }));
    }
    for(const skin of hero?.skins || []) {
      if(query&&!hero.name.toLowerCase().includes(query)&&!skin.name.toLowerCase().includes(query))continue;
      const button=document.createElement('button');button.className='workspace-costume';button.type='button';button.disabled=busy;
      if(skin.icon||skin.badge){const image=document.createElement('img');image.alt='';image.loading='lazy';image.src=skin.icon||skin.badge;image.onerror=()=>image.hidden=true;button.append(image);}
      button.dataset.path=skin.path;
      button.append(document.createTextNode(skin.name));
      button.onclick=()=>{window.AtelierRoster?.hideHoverCard?.();select(hero,skin);};costumeList.append(button);
      const skinMatch=/^Characters\/(\d{4})(?:\/(\d{7}))?/i.exec(skin.path||'');
      window.AtelierRoster?.attachHoverCard?.(button,()=>({
        title:skin.name,
        subtitle:hero.name,
        charId:skinMatch?.[1]||hero.path?.split('/').pop()||'',
        skinId:skin.hero_fallback?'':(skinMatch?.[2]||''),
        icon:skin.icon||skin.badge||'',
        thumbnail:skin.thumbnail||'',
        avatar:hero.avatar||hero.thumbnail||'',
      }));
    }
    heroList.scrollLeft=heroScroll;
    if(focusList) {
      const replacement=[...focusList.children].find(button=>button.dataset.path===focusPath&&!button.disabled);
      const selected=focusList===heroList?heroList.querySelector('[aria-pressed="true"]'):null;
      (replacement || selected || search).focus({preventScroll:true});
    }
  }
  async function select(hero,skin) {
    if(busy)return;busy=true;render();
    const ticket=session, state={skin_id:skin.path.split('/').pop(),title:`${hero.name} / ${skin.name}`};
    try {
      if(creating) {
        const base=`${hero.name} — ${skin.name}`.replace(/[/\\:*?"<>|]/g,'').slice(0,70);
        const data=await api('/api/projects');let index=1,name=base;
        if(ticket!==session)return;
        while((data.projects||[]).some(p=>p.name.toLowerCase()===name.toLowerCase()))name=`${base} ${++index}`;
        const result=await api('/api/project/create',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name})});
        if(!result.ok)throw Error(result.error || 'Could not create project.');
        if(ticket!==session)return;
        await _selectProject(name,state);
      } else {
        if(ticket!==session)return;
        present(); await window.AtelierViewport.open(state.skin_id,state.title);
      }
    } catch(error) {toast(error.message,'warning');}
    finally {busy=false;if(choosing)render();}
  }
  function remember(state) {
    if(!$('viewport-overlay').classList.contains('mounted'))return;
    const project=window.atelierProject?.();
    window.atelierFetch('/api/project/workspace',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(state)},project)
      .then(r=>{if(!r.ok)throw Error();}).catch(()=>{if(project===window.atelierProject?.())toast('Could not remember this costume. Your saved edits are safe.','warning');});
  }
  function start() {return choose(true);}
  window.addEventListener('atelier:catalogue-updated',async()=>{
    if(!choosing){catalogue=null;return;}
    const ticket=session;
    try {
      const data=await loadCatalogue();
      if(ticket!==session || !choosing)return;
      catalogue=data;
      if(!busy)render();
    } catch (_) { /* Keep the usable chooser if the refresh fails. */ }
  });
  $('page-library').onclick=()=>library();
  $('workspace-advanced').onclick=()=>library();
  $('workspace-retry').onclick=resume;
  $('page-workspace').onclick=()=>document.body.dataset.page==='workspace'?null:resume();
  $('workspace-choose').onclick=()=>choose(); $('workspace-search').oninput=render;
  window.AtelierWorkspace={start,resume,present,library,remember};
  page('library');
})();

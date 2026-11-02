(() => {
  const $ = id => document.getElementById(id);
  let catalogue, loading, creating=false, choosing=false, busy=false, session=0, selectedHero='';
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
    $('workspace-help').textContent=choosing?'Choose a hero below, then pick the costume you want to change.':'Click a part on the model or in the list. Pick a colour, then save your changes.';
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
  async function choose(fresh=false) {
    if(await window.AtelierViewport?.close({navigate:false})===false)return;
    opening();
    const ticket=++session; creating=fresh; choosing=true; page('workspace');
    $('project-overlay').classList.remove('active');
    $('workspace-stage').hidden=true; $('workspace-choice').hidden=false; $('workspace-choose').hidden=true;
    $('workspace-search').value=''; $('workspace-heroes').replaceChildren(); $('workspace-costumes').replaceChildren();
    $('workspace-choice-status').textContent='Loading heroes…';
    try {
      if(!catalogue) {
        loading ||= fetch('/api/catalogue/library').then(r=>{if(!r.ok)throw Error('Could not load heroes.');return r.json();}).finally(()=>loading=null);
        catalogue=await loading;
      }
      if(ticket!==session)return;
      render(); $('workspace-search').focus({preventScroll:true});
    } catch(error) {
      if(ticket!==session)return;
      $('workspace-choice-status').textContent='Heroes could not be loaded. Try again in a moment.';
      const retry=document.createElement('button');retry.className='at-btn';retry.textContent='Try again';retry.onclick=()=>choose(fresh);$('workspace-choice-status').append(' ',retry);
    }
  }
  function render() {
    const query=$('workspace-search').value.trim().toLowerCase();
    const heroes=(catalogue?.heroes || []).filter(h=>h.name.toLowerCase().includes(query)||(h.skins||[]).some(s=>s.name.toLowerCase().includes(query)));
    const hero=heroes.find(h=>h.path===selectedHero) || heroes[0];
    selectedHero=hero?.path || '';
    $('workspace-heroes').replaceChildren(); $('workspace-costumes').replaceChildren();
    $('workspace-choice-status').textContent=heroes.length?(hero.skins?.length?'':'No costumes are available for this hero yet.'):query?'No heroes or costumes match. Try another name.':'The costume library is not ready yet. Try again after indexing.';
    if(!heroes.length&&!query) {
      const retry=document.createElement('button');retry.className='at-btn';retry.textContent='Try again';retry.onclick=()=>{catalogue=null;choose(creating);};$('workspace-choice-status').append(' ',retry);
    }
    for(const item of heroes) {
      const button=document.createElement('button');button.className='workspace-hero';button.type='button';button.setAttribute('aria-pressed',String(item===hero));
      const image=document.createElement('img');image.alt='';image.loading='lazy';image.src=item.avatar || item.thumbnail || '/api/catalogue/hero/'+encodeURIComponent(item.path.split('/').pop())+'/avatar';
      image.onerror=()=>image.hidden=true;button.append(image,document.createTextNode(item.name));
      button.onclick=()=>{selectedHero=item.path;render();};$('workspace-heroes').append(button);
    }
    for(const skin of hero?.skins || []) {
      if(query&&!hero.name.toLowerCase().includes(query)&&!skin.name.toLowerCase().includes(query))continue;
      const button=document.createElement('button');button.className='workspace-costume';button.type='button';button.disabled=busy;
      if(skin.icon||skin.badge){const image=document.createElement('img');image.alt='';image.loading='lazy';image.src=skin.icon||skin.badge;image.onerror=()=>image.hidden=true;button.append(image);}
      button.append(document.createTextNode(skin.name));const hint=document.createElement('span');hint.textContent='Choose costume';button.append(hint);
      button.onclick=()=>select(hero,skin);$('workspace-costumes').append(button);
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
  window.addEventListener('atelier:catalogue-updated',()=>{catalogue=null;if(choosing&&!busy)choose(creating);});
  $('page-library').onclick=()=>library();
  $('workspace-advanced').onclick=()=>library();
  $('workspace-retry').onclick=resume;
  $('page-workspace').onclick=()=>document.body.dataset.page==='workspace'?null:resume();
  $('workspace-choose').onclick=()=>choose(); $('workspace-search').oninput=render;
  window.AtelierWorkspace={start,resume,present,library,remember};
  page('library');
})();

// Everywhere is a grouped index lookup; This folder retains the existing local filter.
(() => {
  'use strict';
  let scope='everywhere', generation=0, timer, controller, callbacks={}, active=-1;
  const $=id=>document.getElementById(id);
  // Stops a lookup in flight. Typing does only this, so the open panel refreshes in place instead of closing.
  function cancel() {generation++;clearTimeout(timer);controller?.abort();active=-1;$('search-input')?.removeAttribute('aria-activedescendant');}
  const open=panel=>!panel.hidden&&!panel.dataset.folding;
  // Closing: the panel folds back up under the search box (P4b.7); its logical state closes at once.
  function reset() {
    cancel();$('search-input')?.setAttribute('aria-expanded','false');
    const panel=$('search-results');if(!panel||!open(panel))return;
    panel.dataset.folding='1';
    const gone=()=>{if(!panel.dataset.folding)return;delete panel.dataset.folding;panel.hidden=true;};
    if(window.AtelierMotion?.fold)AtelierMotion.fold(panel,'top',gone);else gone();
  }
  function reveal(panel) {
    const was=open(panel);
    if(panel.dataset.folding){window.AtelierMotion?.unfoldStop?.(panel);delete panel.dataset.folding;}
    panel.hidden=false;if(!was)window.AtelierMotion?.unfold?.(panel,'top');
  }
  function rows() {return [...$('search-results').querySelectorAll('[role=option]')];}
  function select(index) {
    const items=rows();active=(index+items.length)%items.length;
    items.forEach((row,i)=>row.classList.toggle('search-active',i===active));
    if(items[active]){$('search-input').setAttribute('aria-activedescendant',items[active].id);items[active].scrollIntoView({block:'nearest'});}
  }
  async function lookup() {
    const q=$('search-input').value.trim();cancel();if(scope!=='everywhere'||!q){reset();return;}
    const gen=generation, project=window.atelierProject();controller=new AbortController();
    const panel=$('search-results');panel.replaceChildren();reveal(panel);panel.textContent='Searching…';panel.setAttribute('aria-busy','true');$('search-input').setAttribute('aria-expanded','true');
    try {
      const response=await window.atelierFetch('/api/search?q='+encodeURIComponent(q)+'&limit=50',{signal:controller.signal});
      if(!response.ok)throw Error('Search could not be loaded. Try again.');
      const data=await response.json();if(gen!==generation||project!==window.atelierProject())return;
      panel.replaceChildren();active=-1;$('search-input').removeAttribute('aria-activedescendant');
      if(data.building){panel.textContent='The game index is still loading…';timer=setTimeout(lookup,300);return;}
      for(const [group,label] of [['heroes','Heroes'],['skins','Costumes'],['folders','Folders'],['assets','Assets']]) {
        if(!data[group]?.length)continue;
        const section=document.createElement('div');section.setAttribute('role','group');section.setAttribute('aria-label',label);
        const heading=document.createElement('p');heading.className='search-group';heading.textContent=label+' · '+data.totals[group];section.append(heading);
        for(const item of data[group]) {
          const row=document.createElement('button');row.type='button';row.className='search-result';row.setAttribute('role','option');row.tabIndex=-1;row.id='search-result-'+gen+'-'+group+'-'+section.children.length;
          const name=document.createElement('strong');name.textContent=item.display_name || item.name;
          const art=window.AtelierCatalogueArt?.identityChip(item);if(art)name.prepend(art);
          const raw=item.game_rel||item.path;row.title=raw;
          const friendly=window.AtelierCatalogueArt?.pathLabel(raw)||raw;
          const path=document.createElement('span');path.textContent=friendly===raw&&item.identity_label ? item.identity_label+' · '+raw : friendly;
          row.append(name,path);row.addEventListener('click',()=>{reset();$('search-input').blur();callbacks.open?.(group,item);});section.append(row);
        }
        panel.append(section);
      }
      if(!panel.childNodes.length){const text=document.createElement('p');text.textContent='No results';panel.append(text);const bubbles=document.createElement('span');bubbles.className='search-no-results';bubbles.setAttribute('aria-hidden','true');bubbles.textContent='● ● ●';panel.append(bubbles);}
    } catch(error) {if(gen===generation&&error.name!=='AbortError')panel.textContent=error.message;}
    finally {if(gen===generation)panel.removeAttribute('aria-busy');}
  }
  function init(options) {
    callbacks=options;const input=$('search-input'),chip=$('search-scope');
    // The full hint fits the wide box only; the scope chip beside it already says where.
    const wide=matchMedia('(min-width: 1101px)'),hint=input.placeholder,fit=()=>{input.placeholder=wide.matches?hint:'Search…';};
    wide.addEventListener('change',fit);fit();
    chip.addEventListener('click',()=>{scope=scope==='everywhere'?'folder':'everywhere';chip.textContent=scope==='folder'?'This folder':'Everywhere';chip.setAttribute('aria-label','Search scope: '+chip.textContent);reset();callbacks.changed?.();if(scope==='everywhere')lookup();input.focus();});
    input.setAttribute('role','combobox');input.setAttribute('aria-autocomplete','list');input.setAttribute('aria-controls','search-results');input.setAttribute('aria-expanded','false');
    input.addEventListener('input',()=>{cancel();if(scope==='everywhere'&&input.value.trim())timer=setTimeout(lookup,150);else reset();});
    input.addEventListener('keydown',event=>{
      if(scope!=='everywhere'||!open($('search-results')))return;
      if(event.key==='Escape'){event.preventDefault();event.stopImmediatePropagation();reset();input.focus();}
      else if(['ArrowDown','ArrowUp'].includes(event.key)&&rows().length){event.preventDefault();select(active<0?(event.key==='ArrowDown'?0:rows().length-1):active+(event.key==='ArrowDown'?1:-1));}
      else if(event.key==='Enter'&&active>=0){event.preventDefault();rows()[active]?.click();}
    });
    document.addEventListener('pointerdown',event=>{if(!event.target.closest('#searchbar'))reset();});
    window.addEventListener('pagehide',reset);
  }
  window.AtelierSearch=Object.freeze({init,reset,scope:()=>scope,query:()=>scope==='folder'?$('search-input').value.trim():''});
})();

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
    items.forEach((row,i)=>{
      const selected=i===active;
      row.classList.toggle('search-active',selected);
      row.setAttribute('aria-selected',String(selected));
    });
    if(items[active]){$('search-input').setAttribute('aria-activedescendant',items[active].id);items[active].scrollIntoView({block:'nearest'});}
  }
  function fallbackEmblemClass(group, item) {
    const type = String(item.type || item.file_type || '').toLowerCase();
    const raw = String(item.game_rel || item.path || item.name || '').toLowerCase();
    if (group === 'heroes' || group === 'skins') return 'char-icon';
    if (type === 'texture' || /\btextures?\b/.test(raw)) return 'texture-folder-icon';
    if (type === 'material' || /\bmaterials?\b/.test(raw)) return 'material-folder-icon';
    if (type === 'mesh' || /\bmesh(?:es)?\b/.test(raw)) return 'mesh-folder-icon';
    if (type === 'vfx' || type === 'curve' || /\bvfx\b/.test(raw)) return 'vfx-folder-icon';
    if (type === 'text' || type === 'config' || /\b(?:string|text|loc)\b/.test(raw)) return 'text-folder-icon';
    if (type === 'world' || /\bmaps?\b/.test(raw)) return 'map-folder-icon';
    if (/\bui\b/.test(raw)) return 'ui-folder-icon';
    if (/\bcharacters?\b/.test(raw)) return 'char-icon';
    if (/\bweapons?\b/.test(raw)) return 'weapon-folder-icon';
    if (/\babilities?\b/.test(raw)) return 'ability-folder-icon';
    if (/\benvironment\b/.test(raw)) return 'environment-folder-icon';
    return 'folder-icon';
  }
  function makeEmblemSvg(cls) {
    const emblems = window.AtelierFolderEmblems;
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('viewBox', '0 0 24 24');
    svg.setAttribute('aria-hidden', 'true');
    svg.classList.add('search-thumb-emblem');
    const role = emblems?.roles?.[cls] || 'neutral';
    svg.style.color = `var(--studio-emblem-${role})`;
    svg.innerHTML = emblems?.markup?.(cls, 18) || '<rect x="4" y="6" width="16" height="12" rx="2"/>';
    return svg;
  }
  function makeSearchThumb(group, item) {
    const slot = document.createElement('span');
    slot.className = 'search-thumb';
    slot.setAttribute('aria-hidden', 'true');
    const fallback = () => {
      if (slot.querySelector('.search-thumb-emblem')) return;
      slot.replaceChildren(makeEmblemSvg(fallbackEmblemClass(group, item)));
    };
    const art = window.AtelierCatalogueArt?.identityChip(item);
    if (art) {
      art.classList.add('search-thumb-art');
      const prevOnError = art.onerror;
      art.onerror = () => {
        prevOnError?.();
        if (!art.isConnected) fallback();
      };
      slot.append(art);
    } else {
      fallback();
    }
    return slot;
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
          row.setAttribute('aria-selected','false');
          const thumb=makeSearchThumb(group,item);
          const copy=document.createElement('div');copy.className='search-copy';
          const name=document.createElement('strong');name.textContent=item.display_name || item.name;
          const raw=item.game_rel||item.path;row.title=raw;
          const friendly=window.AtelierCatalogueArt?.pathLabel(raw)||raw;
          const path=document.createElement('span');path.textContent=friendly===raw&&item.identity_label ? item.identity_label+' · '+raw : friendly;
          copy.append(name,path);row.append(thumb,copy);row.addEventListener('click',()=>{reset();$('search-input').blur();callbacks.open?.(group,item);});section.append(row);
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
    const bar=$('searchbar');
    bar.addEventListener('focusout',event=>{if(!bar.contains(event.relatedTarget))reset();});
    document.addEventListener('pointerdown',event=>{if(!event.target.closest('#searchbar'))reset();});
    window.addEventListener('pagehide',reset);
  }
  window.AtelierSearch=Object.freeze({init,reset,scope:()=>scope,query:()=>scope==='folder'?$('search-input').value.trim():''});
})();

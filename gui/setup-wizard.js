// Reparent the original settings controls: one set of IDs, validators and save payloads.
(() => {
  'use strict';
  const $=id=>document.getElementById(id);
  let initialized=false, settings=true, step=0, pages=[], original=[], valid={}, detected='', glyphs=[];
  let back,next,nav,dial,advanced;
  const titles=['Find the game','Unlock the paks','Make it yours'];
  function init() {
    if(initialized)return; initialized=true;
    const body=document.querySelector('#setup-overlay .setup-body');
    original=[...body.children].map(node=>{const marker=document.createComment('settings position');node.before(marker);return {node,marker};});
    pages=titles.map((title,index)=>{
      const page=document.createElement('section');page.className='setup-step';page.id='setup-step-'+(index+1);page.hidden=true;
      const count=document.createElement('p');count.className='setup-step-count';count.textContent=`Step ${index+1} of 3`;
      const heading=document.createElement('h3');heading.tabIndex=-1;heading.textContent=title;
      const glyph=document.createElement('span');glyph.className='setup-step-glyph';glyph.setAttribute('aria-hidden','true');heading.append(glyph);
      const status=document.createElement('p');status.className='setup-step-status';status.setAttribute('role','status');
      page.append(count,heading,status);body.append(page);return {page,heading,status,glyph};
    });
    const help=document.createElement('p');help.className='setup-note';help.textContent='Choose the MarvelRivals folder. In Steam: Manage → Browse local files.';pages[0].page.append(help);
    for(const kind of ['aes','usmap']) {
      const status=document.createElement('p');status.id='setup-'+kind+'-retrieval';status.className='setup-note';status.setAttribute('role','status');pages[1].page.append(status);
    }
    nav=document.createElement('span');nav.className='setup-step-nav';
    back=document.createElement('button');back.id='setup-back';back.className='btn';back.textContent='Back';
    next=document.createElement('button');next.id='setup-next';next.className='btn primary';next.textContent='Next';
    back.addEventListener('click',()=>{step=Math.max(0,step-1);render(true);});
    next.addEventListener('click',async()=>{await window.validateSetup();if(step===0?valid.pakOk:valid.pakOk&&valid.usmapOk&&valid.keyOk){step=Math.min(2,step+1);render(true);}});
    nav.append(back,next);$('setup-save').before(nav);
    const label=document.createElement('label');label.className='setup-label';label.textContent='Motion';label.htmlFor='setup-motion-dial';
    dial=document.createElement('select');dial.id='setup-motion-dial';dial.className='setup-input';
    for(const [value,text] of [['full','Full'],['calm','Calm'],['off','Off']]) {const option=document.createElement('option');option.value=value;option.textContent=text;dial.append(option);}
    dial.value=$('settings-motion').value==='reduce'?'off':'full';
    dial.addEventListener('change',()=>{
      const control=$('settings-motion');
      control.value=[...control.options].some(o=>o.value==='full')?dial.value:(dial.value==='full'?'system':'reduce');
      control.dispatchEvent(new Event('change',{bubbles:true}));
    });
    const field=document.createElement('div');field.className='setup-field';field.append(label,dial);pages[2].page.append(field);
    advanced=document.createElement('details');advanced.className='setup-advanced';
    const summary=document.createElement('summary');summary.textContent='More appearance options';advanced.append(summary);pages[2].page.append(advanced);
    document.querySelector('[data-theme-preset="custom"]').addEventListener('click',()=>{if(!settings)advanced.open=true;},true);
  }
  function mode(isSettings) {
    init(); settings=isSettings;step=0;
    glyphs.forEach(g=>g?.destroy());glyphs=[];
    for(const {node,marker} of original)marker.after(node);
    if(!settings) {
      const appearanceEnd=original.findIndex(({node})=>node.classList.contains('setup-section')&&node.textContent==='Paths');
      const behavior=original.findIndex(({node})=>node.classList.contains('setup-section')&&node.textContent==='Behavior');
      for(let i=0;i<original.length;i++) {
        const node=original[i].node;
        if(node.contains($('setup-path')))pages[0].page.append(node);
        else if(node.contains($('setup-usmap'))||node.contains($('setup-aes')))pages[1].page.append(node);
        else if(i<appearanceEnd||i>=behavior) {
          (node.contains($('settings-theme'))||node.querySelector('.theme-palettes')?pages[2].page:advanced).append(node);
        }
        else node.hidden=true;
      }
      $('settings-motion').closest('.setup-field').hidden=true;
      // Keep the Full/Calm/Off dial beside the presets; Wave 4 replaces the legacy mapping.
      pages[2].page.append(dial.closest('.setup-field'));
      pages[2].page.append(advanced);
    } else {
      for(const {node} of original)node.hidden=false;
      $('settings-motion').closest('.setup-field').hidden=false;
    }
    render();
  }
  function render(focus=false) {
    pages.forEach(({page},index)=>page.hidden=settings||index!==step);
    nav.hidden=settings;back.hidden=step===0;next.hidden=step===2;
    next.disabled=step===0?!valid.pakOk:!(valid.pakOk&&valid.usmapOk&&valid.keyOk);
    $('setup-save').hidden=!settings&&step!==2;
    $('setup-save-label').textContent=settings?'Save':'Open Atelier';
    if(focus&&!settings)pages[step].heading.focus();
  }
  function validation(state) {
    valid=state;if(!initialized)return;
    const ready=[state.pakOk,state.pakOk&&state.usmapOk&&state.keyOk,false];
    pages[0].status.textContent=state.pakOk?($('setup-path').value===detected?'Found in your Steam library':'Game folder ready'):'Choose a valid game folder to continue.';
    pages[1].status.textContent=ready[1]?'Key and mapping ready':'A valid key and USMAP mapping are required.';
    ready.forEach((done,index)=>{
      if(done&&!glyphs[index]) {try{glyphs[index]=AtelierMotion.krackleGlyph.mount(pages[index].glyph,{state:'success'});}catch(_) {}}
      if(!done&&glyphs[index]){glyphs[index].destroy();glyphs[index]=null;}
    });render();
  }
  function retrieval(kind, state) {
    init();$('setup-'+kind+'-retrieval').textContent=state==='pending'?(kind==='aes'?'Retrieving the current AES key…':'Downloading the latest USMAP mapping…'):
      state==='ready'?(kind==='aes'?'AES key retrieved automatically.':'Latest USMAP mapping downloaded.'):
      (kind==='aes'?'The key service could not be reached. Paste your key below.':'The mapping download failed. Browse to a USMAP file below.');
  }
  window.AtelierSetup=Object.freeze({mode,validation,retrieval,detected:path=>detected=path});
})();

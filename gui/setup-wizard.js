// The launch check and first-run setup page. It reparents the original Settings controls into the
// page's rows: one set of IDs, validators and save payloads. app.js owns every request and outcome;
// this file only presents them, and Settings keeps its dialog unchanged.
(() => {
  'use strict';
  const $=id=>document.getElementById(id);
  const NAMES=['key','map','game'];   // the page's order, and the drop's path
  const ROWS={
    game:{input:'setup-path',help:'https://github.com/clownfetus/Atelier#get-marvelrivals-path'},
    key:{input:'setup-aes',help:'https://discord.com/channels/1419106202511609958/1485413590310584374/1485417747834863616'},
    map:{input:'setup-usmap',help:'https://spacedepot.github.io/SpaceHost/'},
  };
  const DONE={
    game:{prefill:'Found on this PC',user:'Game folder chosen'},
    key:{prefill:'Saved key found',fetched:'Current key retrieved',user:'Key entered'},
    map:{prefill:'Mapping file found',fetched:'Latest mapping downloaded',user:'Mapping file chosen'},
  };
  const NOUN={game:'the game folder',key:'the key',map:'the mapping file'};
  const GLYPH={pending:'busy',done:'success',missing:'warning'};
  const FOUND={key:'key',map:'file',game:'folder'};   // each row's found glyph: the ink key, the code file, the folder
  let initialized=false, settings=true, page='checking', outcome='busy', error='';
  let valid={}, validated=false, editing={}, prefill={}, fetched={}, retrieval={}, awaiting={};
  let overlay, modal, hero, pageEl, line=null, lineHost=null, moved=[], glyphs={};
  let drop=null, dropFrame=0;

  const join=items=>items.length<2?items.join(''):items.slice(0,-1).join(', ')+' and '+items[items.length-1];
  const capital=text=>text.charAt(0).toUpperCase()+text.slice(1);
  const value=name=>($(ROWS[name].input)?.value||'').trim();
  const full=()=>window.AtelierMotionPolicy?window.AtelierMotionPolicy.allows(3):true;

  function init() {
    if(initialized)return; initialized=true;
    overlay=$('setup-overlay');modal=overlay.querySelector('.setup-modal');hero=$('setup-hero');pageEl=$('setup-page');
    for(const name of NAMES) {
      const row=ROWS[name], el=pageEl.querySelector(`[data-row="${name}"]`);
      Object.assign(row,{el,glyph:el.querySelector('.at-setup-glyph'),what:el.querySelector('.at-setup-what'),
        where:el.querySelector('.at-setup-where'),field:el.querySelector('.at-setup-field'),change:el.querySelector('.at-setup-change'),
        controls:$(row.input).closest('.setup-row')});
      row.change.addEventListener('click',()=>{editing[name]=true;render();$(row.input).focus();});
    }
    new MutationObserver(syncLine).observe(overlay,{attributes:true,attributeFilter:['class']});
    window.addEventListener('atelier:preferences',()=>{for(const glyph of Object.values(glyphs))glyph?.setReducedMotion(full()?'system':'reduce');});
  }
  function move(node,into) {
    if(!node)return;
    if(!moved.some(entry=>entry.node===node)){const marker=document.createComment('settings position');node.before(marker);moved.push({node,marker});}
    into.append(node);
  }
  function mode(isSettings) {
    init();settings=isSettings;
    if(settings) {
      for(const {node,marker} of moved)marker.after(node);
      overlay.classList.remove('at-identity');modal.classList.remove('at-projects');delete overlay.dataset.setupPage;
      hero.hidden=pageEl.hidden=true;
      destroyLine();destroyDrop();
    } else {
      for(const name of NAMES)move(ROWS[name].controls,ROWS[name].field);
      move($('setup-save'),pageEl.querySelector('.at-setup-save-slot'));
      overlay.classList.add('at-identity');modal.classList.add('at-projects');
      hero.hidden=pageEl.hidden=false;
    }
    render();
  }

  // ── What the check found, row by row ──
  function rowState(name) {
    if(page!=='first-run')return 'waiting';
    const ok=name==='game'?valid.pakOk:name==='key'?valid.keyOk:valid.usmapOk;
    if(validated&&ok)return 'done';
    if(retrieval[name]==='pending'||awaiting[name])return 'pending';
    return validated?'missing':'waiting';
  }
  function origin(name) {
    const v=value(name);
    if(v&&fetched[name]&&v===fetched[name])return 'fetched';
    return v&&v===prefill[name]?'prefill':'user';
  }
  function where(name) {
    const v=value(name);
    if(name==='key')return v.length>16?v.slice(0,10)+'…'+v.slice(-4):v;
    return name==='map'?v.split(/[\\/]/).pop():v;
  }
  function instruction(name) {
    if(name==='game')return valid.pakBad?"That folder isn't a Marvel Rivals install. Choose the MarvelRivals folder; in Steam: Manage → Browse local files.":
      'Choose your MarvelRivals folder. In Steam: Manage → Browse local files.';
    if(name==='key')return valid.keyBad?"That isn't a valid key. Keys start with 0x followed by 64 characters.":
      retrieval.key==='failed'?"The key service couldn't be reached. Paste the current key.":'Paste the current key.';
    return valid.usmapBad?"That file isn't a usable .usmap mapping. Choose another.":
      retrieval.map==='failed'?'The mapping download failed. Choose a .usmap file.':'Choose a .usmap mapping file.';
  }
  function reason(name) {
    if(name==='game')return valid.pakBad?"the folder chosen isn't the game":"it couldn't find the game on its own";
    if(name==='key')return valid.keyBad?"the key isn't valid":retrieval.key==='failed'?"the key service didn't answer":'the key is missing';
    return valid.usmapBad?"the mapping file can't be read":retrieval.map==='failed'?'the mapping download failed':'the mapping file is missing';
  }
  function summary(states) {
    if(page==='checking')return ['Checking your setup','Looking for Marvel Rivals, its unlock key and its mapping file.',''];
    if(page==='failed')return ["Couldn't check your setup","Atelier's background service couldn't finish the check. Checking changes nothing, so your projects and files are as you left them.",''];
    const missing=NAMES.filter(n=>states[n]==='missing'), pending=NAMES.filter(n=>states[n]==='pending'), later=' Appearance and motion are in Settings.';
    if(missing.length)return [`Atelier needs ${['one thing','two things','three things'][missing.length-1]} from you`,
      capital(join(missing.map(reason)))+'.',`Ready once ${join(missing.map(n=>NOUN[n]))} ${missing.length>1?'are':'is'} in.`+later];
    if(pending.length)return [states.game==='done'?'Found Marvel Rivals':'Checking your setup',
      `Atelier is fetching ${join(pending.map(n=>n==='key'?'the key that unlocks the game files':'the latest mapping file'))}. You don't need to do anything.`,
      `Ready when ${join(pending.map(n=>NOUN[n]))} ${pending.length>1?'arrive':'arrives'}.`+later];
    if(states.game==='waiting')return ['Checking your setup','Looking for Marvel Rivals, its unlock key and its mapping file.',''];
    return ['Ready to open Atelier',NAMES.every(n=>origin(n)!=='user')?'Found the game, its unlock key and its mapping file.':'Everything Atelier needs is in place.',later.trim()];
  }
  function setText(el,text){if(el.textContent!==text)el.textContent=text;}
  function setGlyph(name,state) {
    const row=ROWS[name], kind=GLYPH[state];
    if(!kind){glyphs[name]?.destroy();glyphs[name]=null;row.glyph.replaceChildren();return;}
    if(glyphs[name]){glyphs[name].setState(kind);return;}
    try{glyphs[name]=window.AtelierMotion.krackleGlyph.mount(row.glyph,{state:kind,found:FOUND[name],reducedMotion:full()?'system':'reduce'});}
    catch(_){glyphs[name]=null;row.glyph.replaceChildren();}
  }
  function render() {
    if(!initialized||settings)return;
    overlay.dataset.setupPage=page;
    const states=Object.fromEntries(NAMES.map(n=>[n,rowState(n)]));
    for(const name of NAMES) {
      const row=ROWS[name], state=states[name], open=state==='missing'||(state!=='waiting'&&editing[name]);
      row.el.dataset.state=state;row.el.classList.toggle('is-editing',open);
      setGlyph(name,state);
      row.what.replaceChildren();
      if(state==='done')row.what.textContent=DONE[name][origin(name)]||DONE[name].user;
      else if(state==='pending')row.what.textContent=name==='key'?'Retrieving the current key…':'Downloading the latest mapping…';
      else if(state==='missing') {
        const help=document.createElement('a');help.href=ROWS[name].help;help.target='_blank';help.rel='noopener';
        help.textContent=name==='game'?'Where do I find this?':'Where do I find it?';
        row.what.append(instruction(name)+' ',help);
      }
      setText(row.where,state==='done'?where(name):'');row.where.title=state==='done'&&name!=='key'?value(name):'';
      row.field.hidden=!open;row.change.hidden=state!=='done'||open;
    }
    const [title,lede,note]=summary(states);
    setText($('setup-page-title'),title);setText($('setup-page-lede'),lede);setText($('setup-page-note'),note);
    $('setup-rows').hidden=page==='failed';$('setup-failure').hidden=page!=='failed';$('setup-page-foot').hidden=page!=='first-run';
    setText($('setup-page-error'),error);
    syncDrop(states);
  }
  function arrive() {
    // A result moves focus to its heading unless the person is already working in the page.
    if(!overlay.classList.contains('active')||pageEl.contains(document.activeElement))return;
    $('setup-page-title').focus({preventScroll:true});
  }

  // ── The ink-well Open Atelier is labelled on: one drop runs down the rows that are valid ──
  function destroyDrop() {
    cancelAnimationFrame(dropFrame);dropFrame=0;drop?.destroy();drop=null;
  }
  function syncDrop(states) {
    if(page!=='first-run'){destroyDrop();return;}
    let reached=0;while(reached<NAMES.length&&states[NAMES[reached]]==='done')reached++;
    const waiting=states[NAMES[reached]]==='pending'?'busy':'still';
    // The page may become visible in the same task; the line is measured once it is laid out.
    cancelAnimationFrame(dropFrame);
    dropFrame=requestAnimationFrame(()=>{
      dropFrame=0;
      if(!drop){
        try{drop=window.AtelierMotion.setupDrop.mount($('setup-well-art'),{layer:pageEl,size:240});}
        catch(_){drop=null;return;}
      }
      drop.setProgress(reached,{rows:NAMES.map(n=>ROWS[n].el),glyphs:NAMES.map(n=>ROWS[n].glyph),waiting});
    });
  }

  // ── The line the page stands on ──
  function destroyLine() {
    line?.destroy();line=null;lineHost?.remove();lineHost=null;hero?.classList.remove('at-has-line');
  }
  function syncLine() {
    if(settings||!overlay.classList.contains('active')){destroyLine();return;}
    const state=page==='checking'?'busy':outcome;
    if(line){line.setState(state);return;}
    lineHost=document.createElement('span');hero.append(lineHost);
    try{line=window.AtelierMotion.setupCheck.mount(lineHost,{state,play:true});hero.classList.add('at-has-line');}
    catch(_){destroyLine();}
  }

  // ── Requests, as app.js reports them ──
  function checking() {
    init();page='checking';outcome='busy';error='';valid={};validated=false;editing={};prefill={};fetched={};retrieval={};awaiting={};
    render();syncLine();
  }
  function found(result) {
    init();page='first-run';outcome=result?.outcome||'warning';prefill=result?.prefill||{};
    render();syncLine();arrive();
  }
  function failed(message) {
    init();page='failed';outcome='error';error=String(message||'No answer from the service.');
    render();syncLine();arrive();
  }
  function validation(state) {
    valid=state||{};validated=true;awaiting={};render();
  }
  function retrieval_(kind,state,fetchedValue) {
    init();const name=kind==='aes'?'key':'map';
    retrieval[name]=state;
    if(state==='ready'){fetched[name]=String(fetchedValue||'').trim();awaiting[name]=true;}
    render();
  }
  // Release the launch animation as the Library or first project picker opens.
  function handover() {
    init();
    destroyLine();
  }
  window.AtelierSetup=Object.freeze({mode,checking,found,failed,validation,retrieval:retrieval_,handover});
})();

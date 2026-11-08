// The launch check and first-run setup page. It reparents the original Settings controls into the
// page's rows: one set of IDs, validators and save payloads. app.js owns every request and outcome;
// this file only presents them, and Settings keeps its dialog unchanged.
(() => {
  'use strict';
  const $=id=>document.getElementById(id);
  const NAMES=['key','map','game'];   // the page's order
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
  const GLYPH={pending:'busy',missing:'warning'};   // a passed row has its block and its sentence, and no glyph
  const BLOCK={key:'texture',map:'mesh',game:'material'};   // one block to a stage, in the mark's order: tile, mesh, disc
  let initialized=false, settings=true, page='checking', error='';
  let valid={}, validated=false, editing={}, prefill={}, fetched={}, retrieval={}, awaiting={};
  let overlay, modal, hero, pageEl, check=null, checkHost=null, moved=[], glyphs={};
  let nextBlock=0;

  const join=items=>items.length<2?items.join(''):items.slice(0,-1).join(', ')+' and '+items[items.length-1];
  const capital=text=>text.charAt(0).toUpperCase()+text.slice(1);
  const value=name=>($(ROWS[name].input)?.value||'').trim();
  const full=()=>window.AtelierMotionPolicy?window.AtelierMotionPolicy.allows(3):true;

  function init() {
    if(initialized)return; initialized=true;
    overlay=$('setup-overlay');modal=overlay.querySelector('.setup-modal');hero=$('setup-hero');pageEl=$('setup-page');
    for(const name of NAMES) {
      const row=ROWS[name], el=pageEl.querySelector(`[data-row="${name}"]`);
      Object.assign(row,{el,block:el.querySelector('.at-setup-block'),glyph:el.querySelector('.at-setup-glyph'),what:el.querySelector('.at-setup-what'),
        where:el.querySelector('.at-setup-where'),field:el.querySelector('.at-setup-field'),change:el.querySelector('.at-setup-change'),
        controls:$(row.input).closest('.setup-row')});
      row.change.addEventListener('click',()=>{editing[name]=true;render();$(row.input).focus();});
      row.block.dataset.piece=BLOCK[name];
    }
    new MutationObserver(syncCheck).observe(overlay,{attributes:true,attributeFilter:['class']});
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
      destroyCheck();resetBlocks();
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
    if(glyphs[name]){glyphs[name].set(kind);return;}
    try{glyphs[name]=window.AtelierMotion.glyph.mount(row.glyph,{state:kind});}
    catch(_){glyphs[name]=null;row.glyph.replaceChildren();}
  }
  function render() {
    if(!initialized||settings)return;
    overlay.dataset.setupPage=page;
    const states=Object.fromEntries(NAMES.map(n=>[n,rowState(n)]));
    for(const name of NAMES) {
      const row=ROWS[name], state=states[name], open=state==='missing'||(state!=='waiting'&&!!editing[name]);
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
    for(const name of NAMES){ROWS[name].wanted=states[name]==='done';syncBlock(ROWS[name]);}
    syncCheck();
  }
  function arrive() {
    // A result moves focus to its heading unless the person is already working in the page.
    if(!overlay.classList.contains('active')||pageEl.contains(document.activeElement))return;
    $('setup-page-title').focus({preventScroll:true});
  }

  // ── A block comes into existence when its row's check really passes ──
  // Specks of the piece gather from nothing and it swells out of where they met. It's solid
  // throughout: a clip and a scale reveal it, never opacity. Blocks settling together take turns.
  const SPECKS=[[-.53,-.28],[.42,-.47],[.58,.14],[-.19,.56],[-.61,.22],[.25,-.61],[.5,.47],[-.42,-.56]];
  const FORM=620, TURN=260, GATHER=340, SWELL_AT=250;
  // The glyph's own curves (SPEC 4.9, pieces.js loads after this file, so they're read when a block lands):
  // the swell travels on `move`; specks gather on `heavy`, accelerating into the block.
  const curve=(name,fallback)=>window.AtelierMotion?.assembly?.curves?.[name]||fallback;
  const CLOSED='circle(0% at 50% 50%)', OPEN='circle(72% at 50% 50%)';
  function drawBlock(row) {
    const svg=document.createElementNS('http://www.w3.org/2000/svg','svg');
    svg.setAttribute('viewBox','0 0 24 24');
    svg.innerHTML=window.AtelierFolderEmblems.markup(row.block.dataset.piece+'-folder-icon',48);
    row.block.replaceChildren(svg);row.block.dataset.shown='true';row.drawn=true;
    return svg;
  }
  function landed(row,running,after) {
    row.running=running;row.moving=true;
    Promise.allSettled(running.map(a=>a.finished)).then(()=>{
      if(row.running!==running)return;   // reset while it played
      after?.();running.forEach(a=>a.cancel());
      row.running=null;row.moving=false;syncBlock(row);
    });
  }
  function condense(row) {
    const svg=drawBlock(row), size=row.block.offsetWidth, specks=[], EASE=curve('move','cubic-bezier(.65,0,.35,1)');
    const running=[
      svg.animate([{clipPath:CLOSED},{clipPath:OPEN}],{delay:SWELL_AT,duration:FORM-SWELL_AT,easing:EASE,fill:'both'}),
      svg.animate([{transform:'scale(.82)',offset:0},{transform:'scale(1.04)',offset:.72},{transform:'scale(1)',offset:1}],{delay:SWELL_AT,duration:FORM-SWELL_AT,easing:EASE,fill:'both'}),
    ];
    SPECKS.forEach(([x,y],i)=>{
      const speck=document.createElement('span'), from=`translate(${(x*size).toFixed(1)}px,${(y*size).toFixed(1)}px)`;
      speck.className='at-setup-speck';row.block.append(speck);specks.push(speck);
      running.push(speck.animate([{transform:from+' scale(0)',offset:0},{transform:from+' scale(1)',offset:.3},{transform:'translate(0,0) scale(.5)',offset:.98},{transform:'translate(0,0) scale(0)',offset:1}],
        {delay:i*14,duration:GATHER,easing:curve('heavy','cubic-bezier(.6,0,.95,.55)'),fill:'both'}));
    });
    landed(row,running,()=>specks.forEach(s=>s.remove()));
  }
  function arriveBlock(row) {
    if(document.hidden||!row.block.animate){drawBlock(row);return;}
    const motion=window.AtelierMotionPolicy?window.AtelierMotionPolicy.mode():'full';
    if(motion==='full'){condense(row);return;}
    const svg=drawBlock(row);
    // Calm keeps the swell. Off and reduced motion take the one fade the system allows (SPEC §5).
    landed(row,[motion==='calm'?svg.animate([{clipPath:CLOSED},{clipPath:OPEN}],{duration:240,easing:curve('move','cubic-bezier(.65,0,.35,1)'),fill:'both'})
      :svg.animate([{opacity:0},{opacity:1}],{duration:150,fill:'both'})]);
  }
  function syncBlock(row) {
    // A move in flight finishes first; a block still waiting for its turn just doesn't start.
    if(row.moving||row.wanted===!!row.drawn)return;
    if(!row.wanted){row.drawn=false;row.block.replaceChildren();delete row.block.dataset.shown;return;}
    if(!full()){arriveBlock(row);return;}
    const now=performance.now(), wait=Math.max(0,nextBlock-now);
    nextBlock=now+wait+FORM+TURN;
    row.moving=true;
    row.timer=setTimeout(()=>{row.timer=0;row.moving=false;
      if(row.wanted)arriveBlock(row);else syncBlock(row);},wait);
  }
  function resetBlocks() {
    nextBlock=0;
    for(const name of NAMES) {
      const row=ROWS[name], running=row.running;
      clearTimeout(row.timer);row.timer=0;row.running=null;row.moving=false;row.drawn=false;row.wanted=false;
      running?.forEach(a=>a.cancel());
      row.block.replaceChildren();delete row.block.dataset.shown;
    }
  }

  // ── The page's one glyph stands in for the logo's mark: working while checks run, the mark itself
  // once every row is valid, ! or X otherwise ──
  function destroyCheck() {
    check?.destroy();check=null;checkHost?.remove();checkHost=null;
  }
  function checkState() {
    if(page==='checking')return 'busy';
    if(page==='failed')return 'error';
    const states=NAMES.map(rowState);
    return states.every(state=>state==='done')?'success':states.includes('missing')?'warning':'busy';
  }
  function syncCheck() {
    if(settings||!overlay.classList.contains('active')){destroyCheck();return;}
    const state=checkState();
    if(check){check.set(state);return;}
    checkHost=document.createElement('span');checkHost.className='at-setup-check';hero.querySelector('.at-proj-lockup').append(checkHost);
    try{check=window.AtelierMotion.glyph.mount(checkHost,{state});}
    catch(_){destroyCheck();}
  }

  // ── Requests, as app.js reports them ──
  function checking() {
    init();page='checking';error='';valid={};validated=false;editing={};prefill={};fetched={};retrieval={};awaiting={};
    render();
  }
  function found(result) {
    init();page='first-run';prefill=result?.prefill||{};
    render();arrive();
  }
  function failed(message) {
    init();page='failed';error=String(message||'No answer from the service.');
    render();arrive();
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
    destroyCheck();
  }
  window.AtelierSetup=Object.freeze({mode,checking,found,failed,validation,retrieval:retrieval_,handover});
})();

// Presentation hooks reuse real jobs and existing application actions.
(() => {
  'use strict';
  const api=window.AtelierSurfaces||={},transients=new Set(),emptyGlyphs=new Map();
  function syncVisibility(){document.documentElement.toggleAttribute('data-krackle-hidden',document.hidden);}
  syncVisibility();
  document.addEventListener('visibilitychange',syncVisibility);
  const disposals=new MutationObserver(()=>{for(const [host,glyph] of emptyGlyphs)if(!host.isConnected){glyph.destroy();emptyGlyphs.delete(host);}});
  disposals.observe(document.documentElement,{childList:true,subtree:true});
  let startupStage=null,startupHost=null,launchAttempted=false;
  api.startupProgress=data=>{
    const splash=document.getElementById('startup-splash');if(!splash||!Number(data.total)||!AtelierMotionPolicy.allows(2))return;
    if(!startupHost){
      startupHost=document.createElement('div');startupHost.className='k-startup-stage';splash.prepend(startupHost);
      try{
        let mask=null;
        const image=document.querySelector('.studio-brand > img');
        if(!launchAttempted&&image?.complete&&image.naturalWidth){
          launchAttempted=true;const canvas=document.createElement('canvas');canvas.width=canvas.height=128;
          const ctx=canvas.getContext('2d');ctx.drawImage(image,0,0,128,128);mask=ctx.getImageData(0,0,128,128);
        }
        startupStage=AtelierMotion.krackleStage.mount(startupHost,{state:'busy',size:mask?224:156,kind:mask?'launch':'index-load',tier:mask?3:2,mask});
        if(mask&&startupHost.dataset.amMicro!=='true') {
          splash.dataset.launch='true';
          if(AtelierMotionPolicy.allows(3)&&!document.hidden)window.AtelierLogoEntranceUI?.holdStartup();
        }
      }catch(_){startupHost.remove();startupHost=null;}
    }
    if(startupHost)startupHost.setAttribute('aria-label',`Container ${data.current} of ${data.total}`);
    startupStage?.setProgress(Number(data.current)/Number(data.total));
  };
  api.startupDone=()=>{startupStage?.destroy();startupStage=null;startupHost?.remove();startupHost=null;window.AtelierLogoEntranceUI?.startupDone();};
  api.indexFailure=notice=>{
    const host=document.createElement('div');host.className='k-index-failure';notice.prepend(host);
    let stage;try{stage=AtelierMotion.krackleStage.mount(host,{state:'error',size:112,kind:'index-load'});}catch(_){host.remove();}
    const remove=notice.remove.bind(notice);notice.remove=()=>{stage?.destroy();remove();};
  };
  api.emptyProjects=host=>{
    const old=host.querySelector('.am-empty-state-host');old?.remove();
    const button=document.createElement('button');button.type='button';button.className='k-project-drop';button.title='New Project';button.setAttribute('aria-label','New Project');
    const glyphHost=document.createElement('span');button.append(glyphHost);host.prepend(button);
    try{emptyGlyphs.set(glyphHost,AtelierMotion.krackleGlyph.mount(glyphHost,{state:'info',reducedMotion:'reduce'}));}catch(_){button.textContent='New Project';}
    button.addEventListener('click',()=>document.getElementById('proj-new-btn').click());
  };
  api.newProjectMoment=()=>{
    const drop=document.querySelector('.k-project-drop');if(!drop||!AtelierMotionPolicy.allows(2)||document.hidden)return;
    const release=AtelierMotion.moment.claim('new-project',2);if(!release)return;
    const rect=drop.getBoundingClientRect(),copy=drop.cloneNode(true);copy.removeAttribute('title');copy.removeAttribute('aria-label');copy.setAttribute('aria-hidden','true');copy.inert=true;
    const energy=window.AtelierMotion?.energy?.resolve(drop);
    if(energy){copy.style.setProperty('--krackle-energy',energy.charge);copy.style.setProperty('--krackle-energy-rift',energy.rift);}
    copy.classList.add('k-project-fall');copy.style.left=rect.x+'px';copy.style.top=rect.y+'px';document.body.append(copy);
    let animation;const dispose=()=>{animation?.cancel();copy.remove();release();transients.delete(dispose);};transients.add(dispose);
    // A single drop presses into its own slot before the project dialog takes over.
    try{animation=copy.animate([{transform:'translateY(-3px) scale(.9,1.08)',opacity:1},{transform:'translateY(5px) scale(1.18,.7)',opacity:1,offset:.55},{transform:'translateY(7px) scale(.85,.18)',opacity:0}],{duration:300,easing:'cubic-bezier(.4,0,.6,1)'});animation.finished.then(dispose,dispose);}catch(_){dispose();}
    setTimeout(dispose,340);
  };
  const drops=new Map();
  document.addEventListener('click',event=>{
    const button=event.target.closest?.('.btn.primary:not(:disabled)');if(!button||!AtelierMotionPolicy.allows(2)||document.hidden)return;
    window.AtelierMotion?.workflow?.action?.(button);
  },true);
  api.updateDrop=(kind,open)=>{
    drops.get(kind)?.remove();
    const button=document.createElement('button');button.className='k-update-drop';button.type='button';button.title=kind==='usmap'?'Mapping update available':'Atelier update available';button.setAttribute('aria-label',button.title);
    const host=document.createElement('span');button.append(host);document.body.append(button);
    let glyph;try{glyph=AtelierMotion.krackleGlyph.mount(host,{state:'info',reducedMotion:'reduce'});}catch(_){button.textContent='Update';}
    const remove=button.remove.bind(button);button.remove=()=>{glyph?.destroy();button.getAnimations().forEach(a=>a.cancel());remove();if(drops.get(kind)===button)drops.delete(kind);};
    drops.set(kind,button);
    button.addEventListener('click',()=>{button.remove();open();});
    if(AtelierMotionPolicy.allows(1)&&!document.hidden)try{button.animate([{transform:'translateY(-10px)',opacity:.5},{transform:'translateY(2px)',opacity:1,offset:.7},{transform:'none',opacity:1}],{duration:260,easing:'cubic-bezier(.2,0,0,1)'});}catch(_){}
  };
  document.addEventListener('visibilitychange',()=>{if(document.hidden)for(const button of drops.values())button.getAnimations().forEach(a=>a.cancel());});
  function stopTransients(){for(const dispose of [...transients])dispose();}
  document.addEventListener('visibilitychange',()=>{if(document.hidden)stopTransients();});
  AtelierMotionPolicy.query().addEventListener('change',()=>{if(!AtelierMotionPolicy.allows(2))stopTransients();if(!AtelierMotionPolicy.allows(1))for(const button of drops.values())button.getAnimations().forEach(a=>a.cancel());});
  window.addEventListener('pagehide',()=>{stopTransients();api.startupDone();for(const button of drops.values())button.remove();for(const glyph of emptyGlyphs.values())glyph.destroy();emptyGlyphs.clear();disposals.disconnect();});
})();

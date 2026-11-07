// Presentation hooks reuse real jobs and existing application actions.
(() => {
  'use strict';
  const api=window.AtelierSurfaces||={},transients=new Set(),emptyGlyphs=new Map();
  const disposals=new MutationObserver(()=>{for(const [host,glyph] of emptyGlyphs)if(!host.isConnected){glyph.destroy();emptyGlyphs.delete(host);}});
  disposals.observe(document.documentElement,{childList:true,subtree:true});
  // Startup: the working glyph at Stage beside the counted bar, in Full only. The A never forms here;
  // the logo entrance follows once the library opens (D8). Calm and Off keep the still logo and the bar.
  let startupGlyph=null,startupHost=null;
  api.startupProgress=data=>{
    const splash=document.getElementById('startup-splash');if(!splash||!Number(data.total)||!AtelierMotionPolicy.allows(2)||startupHost)return;
    startupHost=document.createElement('span');startupHost.className='startup-glyph';startupHost.setAttribute('aria-hidden','true');splash.prepend(startupHost);
    try{startupGlyph=AtelierMotion.glyph.mount(startupHost,{state:'busy'});}catch(_){startupGlyph=null;startupHost.remove();startupHost=null;return;}
    splash.dataset.launch='true';
    if(AtelierMotionPolicy.allows(3)&&!document.hidden)window.AtelierLogoEntranceUI?.holdStartup();
  };
  api.startupDone=()=>{try{startupGlyph?.destroy();}catch(_){}startupGlyph=null;startupHost?.remove();startupHost=null;window.AtelierLogoEntranceUI?.startupDone();};
  // Containers that couldn't be read: the X, still, at Stage, in place of the notice's own small glyph. The text is unchanged.
  api.indexFailure=notice=>{
    const host=document.createElement('span');host.className='index-failure-glyph';host.setAttribute('aria-hidden','true');notice.prepend(host);
    let glyph;try{glyph=AtelierMotion.glyph.mount(host,{state:'error',still:true});}catch(_){host.remove();return;}
    notice.classList.add('index-failure');
    const remove=notice.remove.bind(notice);notice.remove=()=>{try{glyph.destroy();}catch(_){}remove();};
  };
  // Projects: the picker's empty drop and new-project ink live in app.js and project-ink.js.
  const drops=new Map();
  api.updateDrop=(kind,open)=>{
    drops.get(kind)?.remove();
    const button=document.createElement('button');button.className='update-drop';button.type='button';button.title=kind==='usmap'?'Mapping update available':'Atelier update available';button.setAttribute('aria-label',button.title);
    const host=document.createElement('span');button.append(host);
    const topbar=document.getElementById('topbar');
    if(topbar)topbar.insertBefore(button,document.getElementById('job-activity')||document.getElementById('menu-btn'));else document.body.append(button);
    let glyph;try{glyph=AtelierMotion.glyph.mount(host,{state:'info',reducedMotion:'reduce'});}catch(_){button.textContent='Update';}
    const remove=button.remove.bind(button);button.remove=()=>{glyph?.destroy();button.getAnimations().forEach(a=>a.cancel());remove();if(drops.get(kind)===button)drops.delete(kind);};
    drops.set(kind,button);
    button.addEventListener('click',()=>{button.remove();open();});
    if(AtelierMotionPolicy.allows(1)&&!document.hidden)try{button.animate([{transform:'translateY(-10px)',opacity:.5},{transform:'none',opacity:1}],{duration:AtelierMotion.springMs?.snappy||340,easing:AtelierMotion.ease?.snappy||'cubic-bezier(.22,.8,.32,1.12)'});}catch(_){}
  };
  document.addEventListener('visibilitychange',()=>{if(document.hidden)for(const button of drops.values())button.getAnimations().forEach(a=>a.cancel());});
  function stopTransients(){for(const dispose of [...transients])dispose();}
  document.addEventListener('visibilitychange',()=>{if(document.hidden)stopTransients();});
  AtelierMotionPolicy.query().addEventListener('change',()=>{if(!AtelierMotionPolicy.allows(2))stopTransients();if(!AtelierMotionPolicy.allows(1))for(const button of drops.values())button.getAnimations().forEach(a=>a.cancel());});
  window.addEventListener('pagehide',()=>{stopTransients();api.startupDone();for(const button of drops.values())button.remove();for(const glyph of emptyGlyphs.values())glyph.destroy();emptyGlyphs.clear();disposals.disconnect();});
})();

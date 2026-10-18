// Presentation hooks reuse real jobs and existing application actions.
(() => {
  'use strict';
  const api=window.AtelierSurfaces||={};
  const drops=new Map();
  api.updateDrop=(kind,open)=>{
    drops.get(kind)?.remove();
    const button=document.createElement('button');button.className='k-update-drop';button.type='button';button.title=kind==='usmap'?'Mapping update available':'Atelier update available';button.setAttribute('aria-label',button.title);
    const host=document.createElement('span');button.append(host);document.body.append(button);
    let glyph;try{glyph=AtelierMotion.krackleGlyph.mount(host,{state:'info',reducedMotion:'reduce'});}catch(_){button.textContent='Update';}
    const remove=button.remove.bind(button);button.remove=()=>{glyph?.destroy();button.getAnimations().forEach(a=>a.cancel());remove();if(drops.get(kind)===button)drops.delete(kind);};
    drops.set(kind,button);
    button.addEventListener('click',()=>{button.remove();open();});
    if(AtelierMotionPolicy.allows(1)&&!document.hidden)try{button.animate([{transform:'translateY(-16px) scale(.4)'},{transform:'none'}],{duration:260,easing:'cubic-bezier(.2,0,0,1)'});}catch(_){}
  };
  document.addEventListener('visibilitychange',()=>{if(document.hidden)for(const button of drops.values())button.getAnimations().forEach(a=>a.cancel());});
})();

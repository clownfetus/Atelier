// Presentation hooks reuse real jobs and existing application actions.
(() => {
  'use strict';
  const api=window.AtelierSurfaces||={};
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
        if(mask&&startupHost.dataset.amMicro!=='true')splash.dataset.launch='true';
      }catch(_){startupHost.remove();startupHost=null;}
    }
    if(startupHost)startupHost.setAttribute('aria-label',`Container ${data.current} of ${data.total}`);
    startupStage?.setProgress(Number(data.current)/Number(data.total));
  };
  api.startupDone=()=>{startupStage?.destroy();startupStage=null;startupHost?.remove();startupHost=null;};
  api.indexFailure=notice=>{
    const host=document.createElement('div');host.className='k-index-failure';notice.prepend(host);
    let stage;try{stage=AtelierMotion.krackleStage.mount(host,{state:'error',size:112,kind:'index-load'});}catch(_){host.remove();}
    const remove=notice.remove.bind(notice);notice.remove=()=>{stage?.destroy();remove();};
  };
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

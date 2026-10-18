// Optional, client-only export artwork. Never enters a project or mod payload.
(() => {
  'use strict';
  const blob=canvas=>new Promise((resolve,reject)=>canvas.toBlob(value=>value?resolve(value):reject(Error('Image encoding unavailable')),'image/png'));
  function mount(parent,snapshot,result,{reveal,builtAt=new Date().toISOString()}={}) {
    const context=window.AtelierModCardData.context(snapshot);if(!(result.ok||result.built)||!context)return ()=>{};
    let disposed=false,image=null,stamp=null,objectUrl=null;
    const controller=new AbortController();
    (async()=>{
      let picture=window.AtelierViewport?.captureModPoster(context),source='Showcase capture';
      if(!picture){
        source='Catalogue artwork';image=new Image();image.src='/api/catalogue/thumbnail/'+(context.skin||context.hero);
        await image.decode();if(disposed)return;picture=image;
      }
      const version=await fetch('/api/app_info',{signal:controller.signal}).then(r=>r.json());
      await document.fonts.load('650 58px "Bricolage Grotesque"');if(disposed)return;
      const canvas=document.createElement('canvas');canvas.width=1000;canvas.height=1240;canvas.className='mod-card-preview';canvas.setAttribute('role','img');canvas.setAttribute('aria-label',snapshot.modName+' mod card');
      const ctx=canvas.getContext('2d');if(!ctx)return;
      const colors=picture instanceof HTMLImageElement?window.AtelierPolish?.samplePalette(picture):[];
      AtelierShowcaseArt.draw(ctx,1000,1000,AtelierShowcaseArt.palette(colors));
      const w=picture.naturalWidth||picture.width,h=picture.naturalHeight||picture.height,scale=Math.min(1000/w,1000/h);
      ctx.drawImage(picture,(1000-w*scale)/2,(1000-h*scale)/2,w*scale,h*scale);
      const heroes=new Set((snapshot.included||[]).map(item=>window.AtelierCatalogueArt?.heroId(item)).filter(Boolean));
      if(heroes.size===1&&heroes.has(context.hero)){
        stamp=new Image();stamp.src='/api/catalogue/hero/'+context.hero+'/kill';
        try{await stamp.decode();if(disposed)return;ctx.drawImage(stamp,876,20,104,104);canvas.dataset.heroBadge=context.hero;}catch(_){}
      }
      ctx.fillStyle='#eee5cf';ctx.fillRect(0,1000,1000,240);ctx.fillStyle='#121216';ctx.font='650 58px "Bricolage Grotesque",Roboto,sans-serif';ctx.fillText(snapshot.modName,34,1070,930);
      const singular={textures:'texture',materials:'material',meshes:'mesh',curves:'curve',texts:'text',levels:'level',collections:'collection',configs:'config'};
      const count=AtelierModCardData.counts(result.applied),details=Object.entries(count.types).map(([type,n])=>`${n} ${n===1?singular[type]||type:type}`);
      const countLabel=`${count.total} asset${count.total===1?'':'s'}${details.length?' · '+details.join(' · '):''}`;
      ctx.font='400 24px Roboto,sans-serif';ctx.fillText(countLabel,34,1120,930);
      const skipped=(result.skipped||[]).length,warning=!result.ok||!!skipped||!!snapshot.skipped;
      if(warning){
        ctx.save();ctx.translate(54,1160);ctx.fillStyle='#9a6b00';ctx.beginPath();ctx.arc(0,-2,16,.7,Math.PI*2-.4);ctx.arc(0,-2,10,Math.PI*2-.4,.7,true);ctx.closePath();ctx.fill();ctx.beginPath();ctx.arc(14,13,5,0,Math.PI*2);ctx.fill();ctx.restore();
        ctx.fillStyle='#121216';ctx.fillText(`${skipped} skipped${snapshot.skipped?' · '+snapshot.skipped+' excluded':''}${!result.ok?' · Copy incomplete':''}`,84,1168,870);
      }else ctx.fillText(source,34,1168,930);
      ctx.font='400 20px Roboto,sans-serif';ctx.fillText(`Built with Atelier ${version.version} · ${builtAt.slice(0,10)}`,34,1212,930);
      if(disposed)return;
      const card=document.createElement('details');card.className='mod-card';card.dataset.warning=String(warning);const summary=document.createElement('summary');summary.textContent='Mod card';card.append(summary,canvas);
      const stats=document.createElement('p');stats.className='mod-card-stats';stats.textContent=countLabel+(warning?` · ${skipped} skipped`:'');card.append(stats);
      const provenance=document.createElement('p');provenance.textContent=source+(source==='Catalogue artwork'?' · representative artwork; your applied edits are counted above.':'');card.append(provenance);
      const actions=document.createElement('div');actions.className='mod-card-actions';
      const button=(label,action)=>{const control=document.createElement('button');control.type='button';control.className='btn';control.textContent=label;control.addEventListener('click',async()=>{try{await action();}catch(error){window.toast?.(error.message,'warning');}});actions.append(control);};
      button('Copy image',async()=>{if(!navigator.clipboard?.write||!window.ClipboardItem)throw Error('Image copying is unavailable. Save PNG instead.');await navigator.clipboard.write([new ClipboardItem({'image/png':await blob(canvas)})]);window.toast?.('Mod card copied','success');});
      button('Save PNG',async()=>{if(objectUrl)URL.revokeObjectURL(objectUrl);objectUrl=URL.createObjectURL(await blob(canvas));const anchor=document.createElement('a');anchor.href=objectUrl;anchor.download=snapshot.modName.replace(/[<>:"/\\|?*\x00-\x1f]/g,'_')+'-Atelier.png';anchor.click();});
      button('Open export folder',()=>reveal?.());card.append(actions);parent.append(card);
    })().catch(()=>{/* A missing capture/artwork skips the optional card. Export remains complete. */});
    return ()=>{disposed=true;controller.abort();if(image)image.src='';if(stamp)stamp.src='';if(objectUrl)URL.revokeObjectURL(objectUrl);};
  }
  window.AtelierModCards=Object.freeze({mount});
})();

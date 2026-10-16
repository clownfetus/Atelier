// Model replacements use the game's skeleton and the same export list as other edits.
(() => {
  'use strict';
  let overlay,panel,title,description,status,choose,cancel,preview,input,item,busy=false,opener;
  const importControls={};
  const el=(...args)=>AtelierJobDialogs.el(...args);
  function hide(){if(busy){overlay.classList.remove('active');return;}overlay.classList.remove('active');if(opener?.isConnected)opener.focus();}
  function init(){
    overlay=el('div',undefined,'overlay mesh-edit-overlay');overlay.id='mesh-edit-overlay';
    panel=el('section',undefined,'modal mesh-edit-modal');panel.tabIndex=-1;panel.setAttribute('role','dialog');panel.setAttribute('aria-modal','true');panel.setAttribute('aria-labelledby','mesh-edit-title');
    title=el('h2','Model replacement');title.id='mesh-edit-title';
    description=el('p');description.className='mesh-edit-path';
    const help=el('p','Choose a Blender, FBX, GLB, PSK or cooked Unreal mesh. Choose what to retain below. Existing material slots are preserved.');
    const options=el('fieldset',undefined,'mesh-import-options');options.append(el('legend','Import options'));
    for(const [key,label,help] of [
      ['keep_skeleton','Keep original skeleton','Uses the game’s rig. Turn off only for an embedded armature with matching bone names and hierarchy.'],
      ['keep_weights','Preserve compatible weights','Keeps existing weights; missing weights transfer automatically. Turn off to transfer all weights from the original.'],
      ['keep_morphs','Keep facial and corrective morph targets','Preserves original morph names and transfers their movements to replacement geometry at each detail level.']]){
      const row=el('label',undefined,'mesh-import-option'),control=el('input');control.type='checkbox';control.checked=true;control.id='mesh-import-'+key;control.name=key;importControls[key]=control;
      const copy=el('span');copy.append(el('strong',label),el('small',help));row.append(control,copy);options.append(row);
    }
    const companions=el('p','For cooked Unreal files, select the .uasset and its matching .uexp together, plus .ubulk when present. Available LODs are rebuilt and checked before saving. Missing vertex colours and secondary UVs are transferred from the original.');
    status=el('p','Choose a replacement model.');status.id='mesh-edit-status';status.setAttribute('role','status');
    input=el('input');input.type='file';input.multiple=true;input.accept='.blend,.fbx,.glb,.psk,.pskx,.uasset,.uexp,.ubulk';input.hidden=true;
    choose=el('button','Choose replacement…','btn primary');choose.id='mesh-replace-choose';choose.addEventListener('click',()=>input.click());
    input.addEventListener('change',()=>{if(input.files.length)replace([...input.files]);});
    const close=el('button','Close','btn');close.addEventListener('click',hide);
    cancel=el('button','Cancel replacement','btn');cancel.hidden=true;cancel.addEventListener('click',()=>AtelierJobs.cancelCurrent('mesh-replace'));
    preview=el('button','View in 3D','btn');preview.addEventListener('click',()=>{hide();AtelierViewport.openMesh(item.game_rel,item.name);});
    const actions=el('div',undefined,'mesh-edit-actions');actions.append(close,cancel,preview,choose);
    panel.append(title,description,help,options,companions,input,status,actions);overlay.append(panel);document.body.append(overlay);
    AtelierJobDialogs.trap(overlay,panel,hide);
    window.addEventListener('atelier-job',event=>{const job=event.detail;if(busy&&job.kind==='mesh-replace')status.textContent=job.stage;});
  }
  function open(target){
    if(!overlay)init();
    if(busy){overlay.classList.add('active');panel.focus();return;}
    if(AtelierViewport?.hasPendingEdits()){AtelierViewport.focusPendingEdits();toast('Save or revert the current recolours before replacing a model.','warning');return;}
    AtelierViewport?.close();
    if(document.querySelector('#viewport-overlay.active'))return;
    opener=document.activeElement;item=target;title.textContent='Replace '+(target.name||'model');description.textContent=target.game_rel;
    for(const control of Object.values(importControls))control.checked=true;
    status.textContent='Import options start enabled. The replacement uses this asset’s export destination.';input.value='';overlay.classList.add('active');panel.focus();
  }
  async function add(target){
    if(!target?.game_rel)return;
    const project=atelierProject();
    try{
      const result=await atelierFetch('/api/mesh_add',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({game_rel:target.game_rel})}).then(r=>r.json());
      if(!result.ok)throw Error(result.error||'Could not add the model');
      if(project!==atelierProject())return;
      refreshSidebarEntry(target.game_rel,target.name,'');renderGrid();open(target);
    }catch(error){toast(error.message,'warning');}
  }
  async function replace(files){
    if(busy)return;
    const project=atelierProject(),target={...item},form=new FormData();form.append('game_rel',target.game_rel);for(const file of files)form.append('files',file,file.name);
    form.append('options',JSON.stringify(Object.fromEntries(Object.entries(importControls).map(([key,control])=>[key,control.checked]))));
    busy=true;choose.disabled=preview.disabled=true;for(const control of Object.values(importControls))control.disabled=true;cancel.hidden=false;status.textContent='Uploading replacement files…';
    try{
      const result=await AtelierJobs.run('/api/mesh_replace',{method:'POST',body:form,project});
      if(!result.ok)throw Error(result.error||(result.cancelled?'Replacement cancelled; existing edits were kept.':'Replacement failed'));
      const info=result.validation;status.textContent=`Model saved · ${info.lods} LODs checked · ${info.retained_weight_vertices} vertices kept their weights · ${info.transferred_weight_vertices} received transferred weights.${info.morph_targets ? ' '+info.morph_targets+' original morph targets retained.' : ''}${info.warnings?.length ? ' '+info.warnings.join('. ')+'.' : ''}`;
      if(project===atelierProject()){refreshSidebarEntry(target.game_rel,target.name,'');renderGrid();}
    }catch(error){status.textContent=error.message;}
    finally{busy=false;choose.disabled=preview.disabled=false;for(const control of Object.values(importControls))control.disabled=false;cancel.hidden=true;input.value='';}
  }
  window.AtelierMeshEdit=Object.freeze({add,open,replace});
})();

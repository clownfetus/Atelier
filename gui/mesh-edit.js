// Model replacements use the game's skeleton and the same export list as other edits.
(() => {
  'use strict';
  let overlay,panel,title,description,status,choose,cancel,preview,input,item,busy=false,opener;
  let targets,bodyList,weaponList,weaponStatus,fitRow,targetGeneration=0,targetRequest;
  const skinOf=path=>/^Characters\/\d{4}\/(\d{7})(?:\/|$)/i.exec(path||'')?.[1];
  const importControls={};
  const el=(...args)=>AtelierJobDialogs.el(...args);
  function hide(){targetGeneration++;targetRequest?.abort();if(busy){overlay.classList.remove('active');return;}overlay.classList.remove('active');if(opener?.isConnected)opener.focus();}
  function selectTarget(target){
    if(busy)return;
    item={...target};title.textContent='Replace '+(target.name||'model');description.textContent=target.game_rel;
    choose.textContent=target.kind==='weapon'?'Choose weapon replacement…':'Choose replacement…';input.value='';
    if(importControls.fit_weapon){importControls.fit_weapon.checked=target.kind==='weapon';fitRow.hidden=target.kind!=='weapon';}
    status.textContent='Choose a replacement for '+(target.name||'this model')+'.';
    for(const button of targets.querySelectorAll('button[data-mesh]'))button.setAttribute('aria-pressed',String(button.dataset.mesh===target.game_rel));
  }
  function targetButton(target){
    const button=el('button',target.name||target.game_rel.split('/').at(-1),'btn mesh-edit-target');button.type='button';button.dataset.mesh=target.game_rel;
    button.setAttribute('aria-pressed',String(target.game_rel===item.game_rel));button.title=target.game_rel;button.disabled=busy;
    button.addEventListener('click',()=>selectTarget(target));return button;
  }
  async function loadTargets(target){
    const generation=++targetGeneration,project=atelierProject(),skin=skinOf(target.game_rel);
    targetRequest?.abort();targetRequest=new AbortController();
    bodyList.replaceChildren();weaponList.replaceChildren();weaponStatus.textContent=skin?'Finding this skin’s weapons…':'Weapon discovery is available for character skins.';
    (target.kind==='weapon'?weaponList:bodyList).append(targetButton(target));
    if(!skin)return;
    try{
      const response=await atelierFetch('/api/skin_meshes?skin_id='+encodeURIComponent(skin),{signal:targetRequest.signal,project});
      if(!response.ok)throw Error('Could not load weapons');
      const meshes=await response.json();if(!Array.isArray(meshes))throw Error('Could not load weapons');
      if(generation!==targetGeneration||project!==atelierProject()||!overlay.classList.contains('active'))return;
      const seen=new Set(),rows=[target,...meshes].filter(row=>row?.game_rel&&skinOf(row.game_rel)===skin&&!seen.has(row.game_rel)&&seen.add(row.game_rel));
      bodyList.replaceChildren();weaponList.replaceChildren();
      for(const row of rows){const entry={...row,kind:/\/Weapons\//i.test(row.game_rel)?'weapon':'body'};(entry.kind==='weapon'?weaponList:bodyList).append(targetButton(entry));}
      weaponStatus.textContent=weaponList.childElementCount?'Select a weapon to replace it separately. Each replacement keeps that weapon’s material slots and export destination.':'No separate weapon meshes were found for this skin.';
    }catch(error){if(error.name!=='AbortError'&&generation===targetGeneration&&project===atelierProject())weaponStatus.textContent='Weapons could not be loaded. Reopen the replacer to try again.';}
  }
  function init(){
    overlay=el('div',undefined,'overlay mesh-edit-overlay');overlay.id='mesh-edit-overlay';
    panel=el('section',undefined,'modal mesh-edit-modal');panel.tabIndex=-1;panel.setAttribute('role','dialog');panel.setAttribute('aria-modal','true');panel.setAttribute('aria-labelledby','mesh-edit-title');
    title=el('h2','Model replacement');title.id='mesh-edit-title';
    description=el('p');description.className='mesh-edit-path';
    const help=el('p','Choose a model ZIP, Blender, FBX, GLB, PSK or cooked Unreal mesh. A ZIP can contain the model, material JSON and PNG textures, or you can select those files together. Existing game material slots are preserved. PSK files contain no texture images; assign those in the material editor.');
    targets=el('div',undefined,'mesh-edit-targets');
    const bodySection=el('section'),bodyHeading=el('h3','Body parts');bodyHeading.id='mesh-edit-body-heading';bodyList=el('div',undefined,'mesh-edit-target-list');bodyList.setAttribute('role','group');bodyList.setAttribute('aria-labelledby',bodyHeading.id);bodySection.append(bodyHeading,bodyList);
    const weaponSection=el('section'),weaponHeading=el('h3','Weapons');weaponHeading.id='mesh-edit-weapons-heading';weaponList=el('div',undefined,'mesh-edit-target-list');weaponList.id='mesh-edit-weapons';weaponList.setAttribute('role','group');weaponList.setAttribute('aria-labelledby',weaponHeading.id);
    weaponStatus=el('p',undefined,'mesh-edit-weapon-status');weaponStatus.setAttribute('role','status');weaponSection.append(weaponHeading,weaponList,weaponStatus);targets.append(bodySection,weaponSection);
    const rigHelp=el('p','Replacements use the game’s existing rig, attachments and physics settings. A different shape can need weight adjustments. New bones and custom physics are not created.','mesh-edit-rig-help');
    const options=el('fieldset',undefined,'mesh-import-options');options.append(el('legend','Import options'));
    for(const [key,label,help] of [
      ['keep_skeleton','Keep original skeleton','Uses the game’s rig. Turn off only for an embedded armature with matching bone names and hierarchy.'],
      ['keep_weights','Preserve compatible weights','Keeps existing weights; missing weights transfer automatically. Turn off to transfer all weights from the original.'],
      ['keep_morphs','Keep facial and corrective morph targets','Preserves original morph names and transfers their movements to replacement geometry at each detail level.']]){
      const row=el('label',undefined,'mesh-import-option'),control=el('input');control.type='checkbox';control.checked=true;control.id='mesh-import-'+key;control.name=key;importControls[key]=control;
      const copy=el('span');copy.append(el('strong',label),el('small',help));row.append(control,copy);options.append(row);
    }
    const coverage=el('label',undefined,'mesh-import-option mesh-import-coverage'),keepParts=el('input');keepParts.type='checkbox';keepParts.checked=true;keepParts.id='mesh-import-keep_parts';importControls.keep_parts=keepParts;
    const coverageCopy=el('span');coverageCopy.append(el('strong','Keep untouched parts'),el('small','Keeps original material sections missing from your upload. Turn off when every original part must be supplied by the replacement.'));coverage.append(keepParts,coverageCopy);
    const repairRow=el('label',undefined,'mesh-import-option'),repair=el('input');repair.type='checkbox';repair.checked=true;repair.id='mesh-import-repair_weights';importControls.repair_weights=repair;
    const repairCopy=el('span');repairCopy.append(el('strong','Repair incompatible weights'),el('small','Fits unsupported weights to the original body or weapon section. Turn off to require your exact weights.'));repairRow.append(repair,repairCopy);
    const unitsRow=el('label',undefined,'mesh-import-option'),units=el('select');units.id='mesh-import-source_units';units.setAttribute('aria-label','PSK source units');
    for(const [value,label] of [['auto','Automatic'],['centimetres','Centimetres'],['metres','Metres']])units.append(new Option(label,value));importControls.source_units=units;
    const unitsCopy=el('span');unitsCopy.append(el('strong','PSK source units'),el('small','Automatic checks matching bones to detect metres or centimetres. Choose a unit if the imported size is wrong.'));unitsRow.append(units,unitsCopy);
    const placement=el('details',undefined,'mesh-import-details');placement.append(el('summary','Size and placement'));
    fitRow=el('label',undefined,'mesh-import-option');const fit=el('input');fit.type='checkbox';fit.id='mesh-import-fit_weapon';importControls.fit_weapon=fit;
    const fitCopy=el('span');fitCopy.append(el('strong','Fit to original weapon'),el('small','Matches the original weapon’s size, centre and main axis. Review the grip and barrel direction in 3D; use rotation and offsets to adjust them.'));fitRow.append(fit,fitCopy);placement.append(fitRow);
    const transformGrid=el('div',undefined,'mesh-import-transform');
    for(const [key,label,value,min,max,step] of [
      ['scale','Scale',1,.001,1000,.001],['rotate_x','Rotate X (°)',0,-360,360,1],['rotate_y','Rotate Y (°)',0,-360,360,1],['rotate_z','Rotate Z (°)',0,-360,360,1],
      ['offset_x','Move X (cm)',0,-10000,10000,.1],['offset_y','Move Y (cm)',0,-10000,10000,.1],['offset_z','Move Z (cm)',0,-10000,10000,.1]]){
      const row=el('label',label),control=el('input');control.type='number';control.value=value;control.defaultValue=value;control.min=min;control.max=max;control.step=step;control.id='mesh-import-'+key;control.setAttribute('aria-label',label);importControls[key]=control;row.append(control);transformGrid.append(row);
    }
    placement.append(transformGrid);
    const textures=el('details',undefined,'mesh-import-details');textures.append(el('summary','Texture bundle options'));
    textures.append(el('p','For one-material models, the JSON names the textures to connect. Packed masks use the channel choices below. Original maps are kept for inspection. Texture changes also affect any other mesh using that exact material asset. Restore the model and its materials separately with their Restore controls.'));
    for(const [key,label,choices] of [
      ['normal_encoding','Normal map',[['auto','Automatic'],['unity_ag','Unity packed A/G'],['opengl','OpenGL RGB'],['directx','DirectX RGB']]],
      ['pbr_layout','PBR channels',[['rough_r_metal_g','R roughness · G metallic'],['metal_r_rough_g','R metallic · G roughness'],['metal_r_smooth_a','R metallic · A smoothness'],['orm','R AO · G roughness · B metallic']]],
      ['ao_channel','AO channel',[['a','Alpha'],['r','Red'],['g','Green'],['b','Blue'],['none','Neutral']]]]){
      const row=el('label',label,'mesh-import-select'),control=el('select');control.id='mesh-import-'+key;control.setAttribute('aria-label',label);for(const [value,text] of choices)control.append(new Option(text,value));control.dataset.default=choices[0][0];importControls[key]=control;row.append(control);textures.append(row);
    }
    const invertRow=el('label','Invert AO','mesh-import-option'),invert=el('input');invert.type='checkbox';invert.id='mesh-import-ao_invert';importControls.ao_invert=invert;invertRow.prepend(invert);textures.append(invertRow);
    const companions=el('p','PSK files contain geometry and material names; their texture images are separate. For cooked Unreal files, select the .uasset and its matching .uexp together, plus .ubulk when present. All available detail levels are rebuilt and checked before saving. Missing vertex colours and secondary UVs are transferred from the original.');
    status=el('p','Choose a replacement model.');status.id='mesh-edit-status';status.setAttribute('role','status');
    input=el('input');input.type='file';input.multiple=true;input.accept='.zip,.blend,.fbx,.glb,.psk,.pskx,.uasset,.uexp,.ubulk,.json,.png';input.hidden=true;
    choose=el('button','Choose replacement…','btn primary');choose.id='mesh-replace-choose';choose.addEventListener('click',()=>input.click());
    input.addEventListener('change',()=>{if(input.files.length)replace([...input.files]);});
    const close=el('button','Close','btn');close.addEventListener('click',hide);
    cancel=el('button','Cancel replacement','btn');cancel.hidden=true;cancel.addEventListener('click',()=>AtelierJobs.cancelCurrent('mesh-replace'));
    preview=el('button','View in 3D','btn');preview.addEventListener('click',()=>{hide();AtelierViewport.openMesh(item.game_rel,item.name);});
    const actions=el('div',undefined,'mesh-edit-actions');actions.append(close,cancel,preview,choose);
    const content=el('div',undefined,'mesh-edit-content');content.append(targets,help,rigHelp,coverage,repairRow,unitsRow,options,placement,textures,companions);
    const footer=el('div',undefined,'mesh-edit-footer');footer.append(status,actions);
    panel.append(title,description,content,input,footer);overlay.append(panel);document.body.append(overlay);
    AtelierJobDialogs.trap(overlay,panel,hide);
    window.addEventListener('atelier-job',event=>{const job=event.detail;if(busy&&job.kind==='mesh-replace')status.textContent=job.stage;});
  }
  async function open(target){
    if(!overlay)init();
    if(busy){overlay.classList.add('active');panel.focus();return;}
    if(AtelierViewport?.hasPendingEdits()){AtelierViewport.focusPendingEdits();toast('Save or revert the current recolours before replacing a model.','warning');return;}
    await AtelierViewport?.close();
    if(document.querySelector('#viewport-overlay.active'))return;
    if(!target?.game_rel)return;
    opener=document.activeElement;selectTarget({...target,kind:/\/Weapons\//i.test(target.game_rel)?'weapon':'body'});
    for(const [key,control] of Object.entries(importControls)){
      if(control.tagName==='SELECT')control.value=control.dataset.default||'auto';
      else if(control.type==='number')control.value=control.defaultValue;
      else control.checked=key==='fit_weapon'?item.kind==='weapon':key!=='ao_invert';
    }
    overlay.classList.add('active');panel.focus();panel.querySelector('.mesh-edit-content').scrollTop=0;loadTargets(item);
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
    for(const control of Object.values(importControls))if(!control.checkValidity()){control.reportValidity();return;}
    const project=atelierProject(),target={...item},form=new FormData();form.append('game_rel',target.game_rel);for(const file of files)form.append('files',file,file.name);
    form.append('options',JSON.stringify(Object.fromEntries(Object.entries(importControls).map(([key,control])=>[key,control.tagName==='SELECT'?control.value:control.type==='number'?control.valueAsNumber:control.checked]))));
    busy=true;choose.disabled=preview.disabled=true;for(const control of [...Object.values(importControls),...targets.querySelectorAll('button')])control.disabled=true;cancel.hidden=false;status.textContent='Uploading replacement files…';
    try{
      const result=await AtelierJobs.run('/api/mesh_replace',{method:'POST',body:form,project});
      if(!result.ok)throw Error(result.error||(result.cancelled?'Replacement cancelled; existing edits were kept.':'Replacement failed'));
      const info=result.validation;status.textContent=`Model saved · ${info.lods} LODs checked · ${info.retained_weight_vertices} vertices kept their weights · ${info.transferred_weight_vertices} received transferred weights.${info.repaired_weight_vertices ? ' Incompatible weights were fitted to their original game sections.' : ''}${info.preserved_parts?.length ? ' Kept '+info.preserved_parts.length+' untouched part(s).' : ''}${info.morph_targets ? ' '+info.morph_targets+' original morph targets retained.' : ''}${info.material_bundle ? ' '+info.material_bundle.textures+' textures connected. '+info.material_bundle.notes.join(' ') : ''}${info.warnings?.length ? ' '+info.warnings.join('. ')+'.' : ''}`;
      if(project===atelierProject()){refreshSidebarEntry(target.game_rel,target.name,'');renderGrid();}
    }catch(error){status.textContent=error.message;}
    finally{busy=false;choose.disabled=preview.disabled=false;for(const control of [...Object.values(importControls),...targets.querySelectorAll('button')])control.disabled=false;cancel.hidden=true;input.value='';}
  }
  window.AtelierMeshEdit=Object.freeze({add,open,replace});
})();

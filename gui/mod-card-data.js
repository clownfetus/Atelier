// Counts come from completed applied entries, never the reviewed selection.
(() => {
  'use strict';
  const aliases={tex:'textures',texture:'textures','dye-off':'textures',mat:'materials',material:'materials',mesh:'meshes',curve:'curves',vfx:'VFX',text:'texts',world:'levels',mpc:'collections',config:'configs'};
  function counts(applied=[]) {
    const types={};let total=0;
    for(const entry of applied){
      const match=/^(tex|texture|dye-off|mat|material|mesh|curve|vfx|text|world|mpc|config)\s+\S/i.exec(String(entry));if(!match)continue;
      const type=aliases[match[1].toLowerCase()];types[type]=(types[type]||0)+1;total++;
      const extra=/\(\+(\d+) custom textures?\)/i.exec(String(entry));if(extra){types.textures=(types.textures||0)+Number(extra[1]);total+=Number(extra[1]);}
    }
    return {total,types};
  }
  function context(snapshot){
    for(const item of snapshot.included||[]){const skin=/^\d{7}$/.test(item.skin_id||'')?item.skin_id:/^Characters\/\d{4}\/(\d{7})(?:\/|$)/i.exec(item.game_rel||'')?.[1];if(skin)return {project:snapshot.project,skin,hero:skin.slice(0,4)};}
    const hero=(snapshot.included||[]).map(item=>/^\d{4}$/.test(item.char_id||'')?item.char_id:/^Characters\/(\d{4})(?:\/|$)/i.exec(item.game_rel||'')?.[1]).find(Boolean);
    return hero?{project:snapshot.project,hero,skin:null}:null;
  }
  const api=Object.freeze({counts,context});if(typeof module!=='undefined'&&module.exports)module.exports=api;else window.AtelierModCardData=api;
})();

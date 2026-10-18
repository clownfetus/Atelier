const assert=require('node:assert/strict'),data=require('../gui/mod-card-data.js');
assert.deepEqual(data.counts(['tex T_A','mat MI_Body','vfx NS_Fire','combined 3 containers into one pak','packaging done']),{total:3,types:{textures:1,materials:1,VFX:1}});
assert.deepEqual(data.counts(['mat MI_Body (+2 custom textures)','dye-off MI_Mask','config DA_Skin (hero 1029)']),{total:5,types:{materials:1,textures:3,configs:1}});
assert.deepEqual(data.context({project:'A',included:[{game_rel:'Characters/1029/1029001/Textures/T_A'}]}),{project:'A',skin:'1029001',hero:'1029'});
assert.deepEqual(data.context({project:'A',included:[{char_id:'1029',game_rel:'Global/T_A'}]}),{project:'A',skin:null,hero:'1029'});
assert.equal(data.context({project:'A',included:[{game_rel:'Global/T_A'}]}),null);
assert.deepEqual(data.counts([]),{total:0,types:{}});
console.log('Mod card applied counts and context passed');

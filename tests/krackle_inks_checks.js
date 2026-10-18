const assert=require('node:assert/strict');
const K=require('../gui/motion/krackle-inks.js');
const skins=[['pink','#ff5c9a','#8a6cff'],['gold','#ffd700','#8a6cff'],['amber','#ffbf00','#8a6cff'],
  ['orange','#ff6a00','#8a6cff'],['coral','#ff7f50','#8a6cff'],['red','#e92929','#8a6cff'],
  ['deep red','#a20d0d','#8a6cff'],['pink and blue','#f062a4','#2a9fd6']];
let cases=0;
for(const surface of ['#202329','#f5f6f8'])for(const [name,charge,rift] of skins) {
  const result=K.guard(charge,rift,surface),outcomes=K.defaults(surface);
  assert.equal(result.clash,false,name+' resolved');
  for(const color of [result.charge,result.rift]) {
    assert.ok(K.contrast(color,surface)>=3,name+' contrast');
    for(const ink of [outcomes.success,outcomes.warn,outcomes.fault])assert.ok(K.deltaE(color,ink)>=25,name+' outcome distance');
  }
  assert.ok(K.deltaE(result.charge,result.rift)>=25,name+' Charge/Rift distance');
  assert.ok(K.hueDistance(result.charge,result.rift)>=35,name+' Charge/Rift hue');
  if(['pink','gold','amber','pink and blue'].includes(name)) {
    assert.equal(result.shifted,true,name+' marked shifted');
    assert.ok(K.hueDistance(K.fit(charge,surface),result.charge)<=45,name+' small hue nudge');
  } else {
    assert.equal(result.charge,K.fit(charge,surface),name+' retains its fitted colour');
    assert.equal(result.shifted,false,name+' remains unshifted');
  }
  cases++;
}
for(const surface of ['#000000','#ffffff','#777777'])for(const color of ['#000000','#ffffff','#123456','#ffcc00'])assert.ok(K.contrast(K.fit(color,surface),surface)>=3);
const manual=K.guard('#e0407a','#8a6cff','#202329',{handPicked:true});
assert.equal(manual.charge,'#e0407a');assert.equal(manual.clash,true);assert.equal(manual.shifted,false);
const pair=K.guard('#8a6cff','#8a6cff','#202329');assert.ok(K.hueDistance(pair.charge,pair.rift)>=35);
const white=K.lab('#ffffff');assert.ok(Math.abs(white[0]-100)<.001&&Math.abs(white[1])<.001&&Math.abs(white[2])<.001);
assert.ok(Math.abs(K.deltaE('#000000','#ffffff')-100)<.001);
assert.deepEqual(K.defaults('#ffffff'),{charge:'#2693c6',rift:'#8a6cff',success:'#121216',warn:'#9a6b00',fault:'#c8336a',hole:'#121216',successHole:'#eee5cf'});
console.log('PASS '+cases+' skin/surface pairs, colour fitting, fixed outcomes and hand-picked clashes');

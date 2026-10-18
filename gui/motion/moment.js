// One owner for a large formation/event. Refused work keeps its ordinary controls and micro art.
(() => {
  'use strict';
  let owner=null;const seen=new Set();
  function claim(kind,tier=2) {
    if(!window.AtelierMotionPolicy?.allows(tier))return null;
    if(tier<=1)return ()=>{};
    if(owner||tier>=3&&seen.has(kind))return null;
    const token={kind,tier};owner=token;if(tier>=3)seen.add(kind);
    let released=false;
    return ()=>{if(released)return;released=true;if(owner===token)owner=null;};
  }
  window.AtelierMotion ||= {};
  window.AtelierMotion.moment=Object.freeze({claim});
  window.AtelierMotionPolicy?.query().addEventListener('change',()=>{if(owner&&!AtelierMotionPolicy.allows(owner.tier))owner=null;});
  window.addEventListener('pagehide',()=>{owner=null;});
})();

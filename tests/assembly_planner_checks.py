"""The route planner on the production modules, against the prototype's baseline.

Replays 400 seeded cycles in the order the engine really runs them: straight between Head and Ramp,
coming apart to and from Bench, and assembling into the A, ! and X. A move only counts as clear if it
keeps every piece a halo's gap from the others, so even a slight graze counts against it. Complete and
the opening out of an outcome aren't planned, so here they only set the pose for what follows.
"""
from glyph_fixture import open_glyph_page

# Fully clear moves in the prototype on 7 November 2026. These must never drop.
BASELINE = {'straight': 108, 'open': 3, 'spread': 236, 'slots': 217, 'regroup': 176}
TOTALS = {'straight': 108, 'open': 3, 'spread': 236, 'slots': 236, 'regroup': 244}

REPLAY = """()=>{
  let seed=12345; Math.random=()=>(seed=(seed*1664525+1013904223)%4294967296)/4294967296;
  const A={...AtelierMotion.assembly.pieces,...AtelierMotion.assembly.planner}, ATT=A.fits(), M=A.POSES.master;
  const ER=A.clone(A.POSES.error); ER.blue.rot-=6; ER.teal.rot+=6;
  const OUTS=[['A',{...A.OUT.master,contact:A.standOff(M),fixed:['teal']}],['!',{...A.OUT.warning,contact:A.POSES.warning}],['X',{...A.OUT.error,contact:ER}]];
  let cur=A.clone(M), last=-1, apart=true; const res={straight:[0,0],open:[0,0],spread:[0,0],slots:[0,0],regroup:[0,0]};
  const plan=(f,t,o,k)=>{ const st=A.planSequence(f,t,o,true); res[k][1]++; if(st.over<1) res[k][0]++; };
  const asm=(a,target)=>{ const open=A.seated(cur);
    if(open){ const s=A.standOff(cur); plan(cur,s,['teal'],'open'); cur=s }
    const sp=A.spreadFor(a,cur,open); if(A.simulClear(cur,sp)){res.spread[0]++;res.spread[1]++} else plan(cur,sp,['blue','teal','disc'],'spread');
    cur=sp; const sl=A.slotsFor(a,cur); plan(cur,sl,a.order.slice(1),'slots'); cur=sl; plan(cur,target,a.order,'regroup'); cur=A.clone(target); };
  for(let it=0;it<400;it++){
    if(Math.random()<.12){ const k=it%4;
      if(k===3) cur=A.clone(M);
      else { const [n,a]=OUTS[k]; asm(a,a.contact); if(n==='A'){ plan(cur,M,['teal'],'regroup'); cur=A.clone(M) } }
      apart=true; continue }
    let i; do{i=Math.floor(Math.random()*ATT.length)}while(i===last); const prev=ATT[last]; last=i; const a=ATT[i];
    if(apart) apart=false;
    else if(!A.STRAIGHT.has(a.name)||!A.STRAIGHT.has(prev.name)) asm(a,a.approach);
    else plan(cur,a.approach,a.order,'straight');
    cur=A.clone(a.contact);
  }
  return res;}"""

LIVE = """async()=>{const L=AtelierMotion.assembly.planner;
  const longs=[];new PerformanceObserver(l=>{for(const e of l.getEntries())longs.push(e.duration)}).observe({type:'longtask',buffered:false});
  L.clearRoutes();L.stats.longestSlice=0;L.stats.overBudget=0;let n=0;
  for(const [from,to,prefer] of L.commonRoutes()){const steps=await L.planLive(from,to,prefer);if(!steps.length&&JSON.stringify(from)!==JSON.stringify(to))return {empty:true};n++}
  await new Promise(r=>setTimeout(r,100));
  return {n,longest:L.stats.longestSlice,over:L.stats.overBudget,longs}}"""


def run_assembly_planner_checks(context, url, report, checks):
    tab, errors = open_glyph_page(context, url)
    result = tab.evaluate(REPLAY)
    for kind, least in BASELINE.items():
        clear, total = result[kind]
        assert total == TOTALS[kind], (kind, result)
        assert clear >= least, (kind, result)
    # The idle pass and a live plan work in short slices, so the page never stalls.
    tab.wait_for_function("AtelierMotion.assembly.planner.idleDone()", timeout=60000)
    live = tab.evaluate(LIVE)
    assert not live.get('empty') and live['n'] > 0, live
    assert live['longest'] < 50, live
    assert not errors, errors
    tab.close()
    summary = ', '.join(f"{kind} {result[kind][0]}/{result[kind][1]}" for kind in BASELINE)
    checks.append(f"Glyph: planner keeps the baseline ({summary})")
    checks.append(f"Glyph: {live['n']} live plans, longest slice {live['longest']:.1f} ms against the 50 ms limit, {len(live['longs'])} long tasks seen on the page")

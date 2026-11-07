"""Planner baseline check for the assembly motion engine.

Replays 400 seeded cycles through the planner exposed on window.__atelier, in the
order the engine really runs them: straight between Head and Ramp, coming apart to
and from Bench, and assembling into the A, ! and X. Reports how many moves keep every
piece one halo-gap (14u) clear of the others.

Complete and the opening out of an outcome aren't planned: each runs all three pieces
together in one brisk move (SPEC invariant 4), so here they only set the pose for
whatever follows.

Usage:  python planner_check.py <path-to-page.html> [--chrome <exe>]
Baseline (prototype, 7 Nov 2026): straight 108/108, open 3/3, spread 236/236,
slots 217/236, regroup 176/244, slowest plan 146 ms. A move counts as not clear for
even a slight graze. These don't compare with figures for the earlier pieces.
Port this to the production module in Phase 2; it must never get worse.
"""
import sys, argparse
from pathlib import Path
from playwright.sync_api import sync_playwright
ap=argparse.ArgumentParser(); ap.add_argument('page'); ap.add_argument('--chrome',default=None); args=ap.parse_args()
URL=Path(args.page).resolve().as_uri()
with sync_playwright() as p:
    b=p.chromium.launch(executable_path=args.chrome) if args.chrome else p.chromium.launch()
    pg=b.new_page(viewport={"width":1180,"height":900}); errs=[]; pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.goto(URL); pg.wait_for_timeout(500)
    r=pg.evaluate("""()=>{
      let seed=12345; Math.random=()=>(seed=(seed*1664525+1013904223)%4294967296)/4294967296;
      const A=window.__atelier, ATT=A.ATT, M=A.POSES.master;
      const ER=A.clone(A.POSES.error); ER.blue.rot-=6; ER.teal.rot+=6;
      const OUTS=[['A',{...A.OUT.master,contact:A.standOff(M),fixed:['teal']}],['!',{...A.OUT.warning,contact:A.POSES.warning}],['X',{...A.OUT.error,contact:ER}]];
      let cur=A.clone(M), last=-1, apart=true; const res={straight:[0,0],open:[0,0],spread:[0,0],slots:[0,0],regroup:[0,0]}; const bads={}; let tmax=0;
      const plan=(f,t,o,k,name)=>{ const t0=performance.now(); const st=A.planSequence(f,t,o,true); tmax=Math.max(tmax,performance.now()-t0); res[k][1]++; if(st.over<1) res[k][0]++; else bads[name]=(bads[name]||0)+1; };
      const asm=(a,target,name)=>{ const open=A.seated(cur);
        if(open){ const s=A.standOff(cur); plan(cur,s,['teal'],'open','open>'+name); cur=s }
        const sp=A.spreadFor(a,cur,open); if(A.simulClear(cur,sp)){res.spread[0]++;res.spread[1]++} else plan(cur,sp,['blue','teal','disc'],'spread','out>'+name);
        cur=sp; const sl=A.slotsFor(a,cur); plan(cur,sl,a.order.slice(1),'slots','side>'+name); cur=sl; plan(cur,target,a.order,'regroup','in>'+name); cur=A.clone(target); };
      for(let it=0;it<400;it++){
        if(Math.random()<.12){ const k=it%4;
          if(k===3) cur=A.clone(M);                                                     // Complete
          else { const [n,a]=OUTS[k]; asm(a,a.contact,n); if(n==='A'){ plan(cur,M,['teal'],'regroup','close>A'); cur=A.clone(M) } }
          apart=true; continue }
        let i; do{i=Math.floor(Math.random()*ATT.length)}while(i===last); const prev=ATT[last]; last=i; const a=ATT[i];
        if(apart) apart=false;                                                          // the opening is one brisk move, not planned
        else if(!A.STRAIGHT.has(a.name)||!A.STRAIGHT.has(prev.name)) asm(a,a.approach,a.name);
        else plan(cur,a.approach,a.order,'straight',a.name);
        cur=A.clone(a.contact);
      }
      const f=k=>res[k][0]+'/'+res[k][1];
      return {straight:f('straight'), open:f('open'), spread:f('spread'), slots:f('slots'), regroup:f('regroup'), bads, planMsMax:tmax.toFixed(0)};}""")
    print(r, errs); b.close()

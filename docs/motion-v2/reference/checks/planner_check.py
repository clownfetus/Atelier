"""Planner baseline check for the assembly motion engine.

Replays 400 random cycles (wrong fits plus moves into A, ! and X) through the
planner exposed on window.__atelier, and reports how many moves keep every
piece one halo-gap (14u) clear of the others.

Usage:  python planner_check.py <path-to-page.html> [--chrome <exe>]
Baseline (prototype, Nov 2026): spread 400/400, slots ~385/400, regroup ~350/400.
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
      const A=window.__atelier, ATT=A.ATT; const pre=A.nudge(A.POSES.master,6,6);
      const ER=A.clone(A.POSES.error); ER.blue.rot-=6; ER.teal.rot+=6;
      const OUTS=[['A',{...A.OUT.master,contact:pre}],['!',{...A.OUT.warning,contact:A.POSES.warning}],['X',{...A.OUT.error,contact:ER}]];
      let cur=A.clone(A.POSES.master), last=-1; const res={spread:[0,0],slots:[0,0],regroup:[0,0]}; const bads={}; let tmax=0;
      const run=(f,t,o,k,name)=>{ const t0=performance.now(); const st=A.planSequence(f,t,o,true); tmax=Math.max(tmax,performance.now()-t0); res[k][1]++; if(st.over<1) res[k][0]++; else bads[name]=(bads[name]||0)+1; };
      const asm=(a,target,name)=>{ const d=a.order.slice(1), oo=[...d].sort((x,y)=>x==='disc'?-1:y==='disc'?1:0);
        const sp=A.spreadFor(a,cur); if(A.simulClear(cur,sp)){res.spread[0]++;res.spread[1]++} else run(cur,sp,['disc','teal','blue'],'spread','out>'+name); cur=sp; const sl=A.slotsFor(a,cur); run(cur,sl,a.order.slice(1),'slots','side>'+name); cur=sl; run(cur,target,a.order,'regroup','in>'+name); cur=A.clone(target); };
      for(let it=0;it<400;it++){
        if(Math.random()<.12){ const [n,a]=OUTS[it%3]; asm(a,a.contact,n); continue }
        let i; do{i=Math.floor(Math.random()*ATT.length)}while(i===last); last=i; const a=ATT[i];
        asm(a,a.approach,a.name); cur=A.clone(a.contact);
      }
      return {spread:res.spread[0]+'/'+res.spread[1], regroup:res.regroup[0]+'/'+res.regroup[1], slots:res.slots[0]+'/'+res.slots[1], bads, planMsMax:tmax.toFixed(0)};}""")
    print(r, errs); b.close()

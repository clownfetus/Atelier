"""True clearance between the pieces, on the outlines actually drawn.

Measures every designed pose, then steps a fixed timeline of every state on a
fake clock at 25 fps with seeded randomness, so runs are repeatable. Gaps are
computed here from the drawn outlines, not by the engine's own gap(), so the
check doesn't share the planner's assumptions.

Usage:  python clearance_check.py <path-to-page.html> [--chrome <exe>]
Exits 1 if a resting pose breaks its minimum:
  - master: every pair at least 13.9u
  - warning: tile to mesh and mesh to disc at least 13.9u
  - each wrong fit, at contact, tap and approach: every pair at least 14u
  - the at-rest row, and with the mesh or tile raised: every pair at least 14u
The X crosses on purpose, so its overlap isn't a failure. The texture loader's bands
move inside the pose, up to 14u sideways, so they aren't measured here; the row's 30u
gaps leave them 16u clear.

Baseline (prototype, 7 Nov 2026), frames with a pair under 13.8u, of 1515:
  tile-mesh 57 (closest -1.27u), tile-disc 162, mesh-disc 168.
Most of the last two are the X and leaving it, where the disc is pinned on the
crossing. The rest are the two brisk moves, Complete and the opening out of an
outcome, where all three move together (SPEC invariant 4). No piece overlaps another
once Working or a loader has opened. Wrong-fit contact gaps are all 16u.
Port this to the production module in Phase 2; it must never get worse.
"""
import argparse
import json
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

CLOCK = """
(() => {
  let now = 0, id = 1, seed = 12345;
  const timers = [], frames = [];
  const realTimeout = window.setTimeout.bind(window);
  performance.now = () => now;
  window.requestAnimationFrame = fn => { frames.push(fn); return id++; };
  window.setTimeout = (fn, ms = 0) => { timers.push({at: now + ms, fn}); return id++; };
  Math.random = () => (seed = (seed * 1664525 + 1013904223) % 4294967296) / 4294967296;
  const settle = () => new Promise(r => realTimeout(r, 0));
  window.__clear = () => { timers.length = 0; };
  window.__step = async dt => {
    now += dt;
    for (const t of timers.filter(t => t.at <= now)) { timers.splice(timers.indexOf(t), 1); t.fn(); }
    await settle();
    const fs = frames.splice(0);
    fs.forEach(f => f(now));
    await settle();
  };
})();
"""

# brandRing and plainRing are the page's own outline samplers: this measures what is drawn.
HELPERS = """
window.__clearance = (() => {
  const arc = (p, v, q, k, n) => {
    const a=[p[0]-v[0],p[1]-v[1]],b=[q[0]-v[0],q[1]-v[1]],la=Math.hypot(...a),lb=Math.hypot(...b);
    const ua=[a[0]/la,a[1]/la],ub=[b[0]/lb,b[1]/lb],ang=Math.acos(Math.max(-1,Math.min(1,ua[0]*ub[0]+ua[1]*ub[1])));
    const t=Math.min(k/Math.tan(ang/2),la/2,lb/2),r=t*Math.tan(ang/2);
    const s=[v[0]+ua[0]*t,v[1]+ua[1]*t],e=[v[0]+ub[0]*t,v[1]+ub[1]*t],m=[ua[0]+ub[0],ua[1]+ub[1]],ml=Math.hypot(...m)||1,d=r/Math.sin(ang/2);
    const c=[v[0]+m[0]/ml*d,v[1]+m[1]/ml*d];let a0=Math.atan2(s[1]-c[1],s[0]-c[0]),a1=Math.atan2(e[1]-c[1],e[0]-c[0]);
    while(a1-a0>Math.PI)a1-=2*Math.PI;while(a1-a0<-Math.PI)a1+=2*Math.PI;
    const out=[];for(let i=0;i<=n;i++){const u=i/n;out.push([c[0]+r*Math.cos(a0+(a1-a0)*u),c[1]+r*Math.sin(a0+(a1-a0)*u)])}return out;
  };
  const quad = (id, o) => { const w=o.w,h=o.h; if(id==='blue'){const t=o.taper; return [[-w/2,-h/2],[w/2,-h/2],[w/2-t,h/2],[-w/2,h/2]]}
    const dx=o.dx; return [[-w/2-dx/2,-h/2],[w/2-dx/2,-h/2],[w/2+dx/2,h/2],[-w/2+dx/2,h/2]] };
  const rounded = (id, o) => { const q=quad(id,o); let r=[]; for(let i=0;i<4;i++) r=r.concat(arc(q[(i+3)%4],q[i],q[(i+1)%4],o.k,8)); return r };
  const local = (id, o) => {
    const m = o.m ?? 0;
    if (m <= .001) return rounded(id, o);
    const B = brandRing(id, o);
    if (m >= .999) return B;
    const Q = plainRing(id, o);
    return B.map((p, i) => [Q[i][0] + (p[0] - Q[i][0]) * m, Q[i][1] + (p[1] - Q[i][1]) * m]);
  };
  const place = (id, o) => { const c=Math.cos(o.rot*Math.PI/180),s=Math.sin(o.rot*Math.PI/180),sc=o.s||1;
    return local(id,o).map(([x,y])=>[o.x+(x*c-y*s)*sc,o.y+(x*s+y*c)*sc]) };
  const inside = (p, poly) => { let c=false; for(let i=0,j=poly.length-1;i<poly.length;j=i++){const a=poly[i],b=poly[j]; if((a[1]>p[1])!==(b[1]>p[1])&&p[0]<(b[0]-a[0])*(p[1]-a[1])/(b[1]-a[1])+a[0]) c=!c} return c };
  const sd = (p, a, b) => { const dx=b[0]-a[0],dy=b[1]-a[1],l=dx*dx+dy*dy; let t=l?((p[0]-a[0])*dx+(p[1]-a[1])*dy)/l:0; t=Math.max(0,Math.min(1,t)); return Math.hypot(p[0]-a[0]-t*dx,p[1]-a[1]-t*dy) };
  const ringDist = (A, B) => { let m=1e9; for(const [P,Q] of [[A,B],[B,A]]) for(const p of P) for(let i=0;i<Q.length;i++){const d=sd(p,Q[i],Q[(i+1)%Q.length]); if(d<m)m=d} return m };
  // positive: clear by that much. negative: overlapping, by roughly that depth.
  const pair = (A, B) => { const d=ringDist(A,B), over=A.some(p=>inside(p,B))||B.some(p=>inside(p,A)); return over?-d:d };
  const disc = (d, R) => { const c=[d.x,d.y], r=d.r*(d.s||1); let m=1e9; for(let i=0;i<R.length;i++){const v=sd(c,R[i],R[(i+1)%R.length]); if(v<m)m=v} return inside(c,R)?-(m+r):m-r };
  const gaps = pose => { const T=place('blue',pose.blue), M=place('teal',pose.teal);
    return {tm:+pair(T,M).toFixed(2), td:+disc(pose.disc,T).toFixed(2), md:+disc(pose.disc,M).toFixed(2)} };
  return {gaps};
})();
"""

POSES = """
() => {
  const A = window.__atelier, g = window.__clearance.gaps, out = {};
  out.master = g(A.POSES.master);
  out.warning = g(A.POSES.warning);
  out.error = g(A.POSES.error);
  out['at rest'] = g(A.REST);
  for (const id of ['blue', 'teal']) { const q = A.clone(A.REST); q[id].y -= A.RISE; out['raised ' + id] = g(q); }
  for (const a of A.ATT) for (const k of ['contact', 'tap', 'approach', 'apart']) out[a.name + ' ' + k] = g(a[k]);
  return out;
}
"""

FPS = 25
TIMELINE = [('working', 5.5), ('success', 7.0), ('working', 4.6), ('warning', 7.0), ('working', 4.6), ('error', 7.0), ('idle', 6.0),
            ('mesh', 5.0), ('success', 4.0), ('texture', 5.0), ('material', 5.0)]
PAIRS = (('tm', 'tile-mesh'), ('td', 'tile-disc'), ('md', 'mesh-disc'))

ap = argparse.ArgumentParser()
ap.add_argument('page')
ap.add_argument('--chrome', default=None)
args = ap.parse_args()

with sync_playwright() as p:
    b = p.chromium.launch(executable_path=args.chrome) if args.chrome else p.chromium.launch()
    pg = b.new_page(viewport={'width': 1400, 'height': 1000})
    errs = []
    pg.on('pageerror', lambda e: errs.append(str(e)))
    pg.add_init_script(CLOCK)
    pg.route('**/*', lambda r: r.continue_() if r.request.url.startswith('file:') else r.abort())
    pg.goto(Path(args.page).resolve().as_uri())
    pg.wait_for_function('!!window.__atelier')
    pg.evaluate('window.__clear()')
    pg.add_script_tag(content=HELPERS)
    poses = pg.evaluate(POSES)

    failures = []
    print('DESIGNED POSES (tile-mesh, tile-disc, mesh-disc)')
    for name, g in poses.items():
        print(f"  {name:18} {g['tm']:8} {g['td']:8} {g['md']:8}")
        if name == 'master' and min(g.values()) < 13.9:
            failures.append(name)
        if name == 'warning' and min(g['tm'], g['md']) < 13.9:
            failures.append(name)
        if (name == 'at rest' or name.startswith('raised')) and min(g.values()) < 14:
            failures.append(name)
        if name.split()[-1] in ('contact', 'tap', 'approach') and min(g.values()) < 14:
            failures.append(name)

    frames, n = [], 0
    for state, secs in TIMELINE:
        pg.evaluate(f'void window.__atelier.run({json.dumps(state)})')
        for _ in range(int(secs * FPS)):
            pg.evaluate(f'window.__step({1000 / FPS})')
            g = pg.evaluate('window.__clearance.gaps(window.__atelier.state().cur)')
            frames.append(dict(n=n, state=state, **g))
            n += 1
    b.close()

print(f'FRAMES ({len(frames)})')
for key, label in PAIRS:
    under = [f for f in frames if f[key] < 13.8]
    print(f"  {label}: under 13.8u {len(under)}; closest {min(f[key] for f in frames)}")
    runs, cur = [], None
    for f in under:
        if cur and cur['state'] == f['state'] and cur['to'] == f['n'] - 1:
            cur['to'] = f['n']
            cur['min'] = min(cur['min'], f[key])
        else:
            cur = dict(state=f['state'], frm=f['n'], to=f['n'], min=f[key])
            runs.append(cur)
    for r in runs:
        print(f"    {r['state']:8} frames {r['frm']}-{r['to']}, closest {r['min']}")
print('page errors:', errs)
if failures or errs:
    print('FAILED:', ', '.join(failures) or 'page errors')
    sys.exit(1)
print('passed')

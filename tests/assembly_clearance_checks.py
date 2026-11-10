"""True clearance between the pieces, on the outlines actually drawn.

Gaps are measured here from the drawn outlines, not by the engine's own gap(), so the check doesn't
share the planner's assumptions. The designed poses each have a minimum. A fixed timeline of every
state then runs on a stepped clock with seeded randomness, so a run is repeatable, and it must not
get worse than the prototype's baseline. The X crosses on purpose, so its overlap isn't a failure.
"""
import importlib.util
import json
from pathlib import Path

from glyph_fixture import open_glyph_page

FPS = 25
TIMELINE = [('working', 5.5), ('success', 7.0), ('working', 4.6), ('warning', 7.0), ('working', 4.6), ('error', 7.0), ('idle', 6.0),
            ('mesh', 5.0), ('success', 4.0), ('texture', 5.0), ('material', 5.0)]
# Frames with a pair under 13.8u, of 1515, in the prototype on 7 November 2026. Most of the last two are the
# X and leaving it, where the disc is pinned on the crossing. The rest are the two brisk moves, Complete and
# the opening out of an outcome, where all three move together (SPEC invariant 4).
# Tile-mesh re-measured on 10 November 2026 for the D20 drawing (it was 57; the same engine with the D14
# outlines gives 45). The A now holds the tile and mesh one halo apart instead of 31u, so the moves that
# start or end in it spend more frames near that line: Complete's move in and the opening out of it add
# one to three frames each (closest new frame 11.1u), and the X forming adds a run. Tile-disc and
# mesh-disc came down (150 and 144), and keep the prototype's ceilings.
BASELINE = {'tm': 63, 'td': 162, 'md': 168}
OPENED = int(.48 * FPS)  # The opening takes 420 ms; after it, Working and the loaders never overlap.

# brandRing and plainRing are the engine's own outline samplers: this measures what is drawn.
HELPERS = """
window.__atelier = {...AtelierMotion.assembly.pieces, ...AtelierMotion.assembly.planner};
window.__clearance = (() => {
  const {brandRing, plainRing} = window.__atelier;
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
0;
"""

POSES = """()=>{
  const A=window.__atelier, g=window.__clearance.gaps, out={}, R=A.rest();
  out.master=g(A.POSES.master);
  out.warning=g(A.POSES.warning);
  out.error=g(A.POSES.error);
  out['at rest']=g(R);
  for(const id of ['blue','teal']){const q=A.clone(R);q[id].y-=A.RISE;out['raised '+id]=g(q)}
  for(const a of A.fits())for(const k of ['contact','tap','approach'])out[a.name+' '+k]=g(a[k]);
  const m=A.micro();for(const k of ['info','success','warning'])out['micro '+k]=g(m[k]);
  return out}"""

FILM = """async([timeline,fps])=>{
  const P=AtelierMotion.assembly.pieces,g=__mount(128,{state:'info'}),e=g.engine,dt=1000/fps,frames=[];
  e.fresh=false;e.cur=P.clone(P.POSES.master);
  const play={working:()=>e.run('busy'),idle:()=>e.run('brand'),mesh:()=>e.run('busy','mesh'),texture:()=>e.run('busy','texture'),material:()=>e.run('busy','material')};
  for(const [state,secs] of timeline){
    void (play[state]||(()=>e.run(state)))();
    for(let i=0,n=Math.floor(secs*fps);i<n;i++){await __step(dt);frames.push({state,i,...__clearance.gaps(e.cur)})}
  }
  g.destroy();return frames}"""

ENTRANCE = """async dt=>{
  const host=document.createElement('div');document.getElementById('root').append(host);let done=false,least={tm:1e9,td:1e9,md:1e9},t=0;
  const g=AtelierMotion.glyph.entrance(host,{size:32,preview:true,onDone:()=>{done=true}});
  while(!done&&t<4000){await __step(dt);t+=dt;const q=__clearance.gaps(g.engine.cur);for(const k in q)least[k]=Math.min(least[k],q[k])}
  g.destroy();return {least,done,t}}"""


def _brand_mark():
    path = Path(__file__).resolve().parent.parent / 'scripts' / 'brand_mark.py'
    spec = importlib.util.spec_from_file_location('atelier_brand_mark', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _close(a, b):
    """The embedded outlines and their generator agree, to the two decimals they're written in."""
    if isinstance(a, (list, tuple)):
        return len(a) == len(b) and all(_close(x, y) for x, y in zip(a, b))
    return abs(a - b) < .006


def run_assembly_clearance_checks(context, url, report, checks):
    tab, errors = open_glyph_page(context, url, clock=True)
    tab.evaluate(HELPERS)

    # The engine draws the mark's own outlines, so they stay in step with the script that generates it.
    brand = _brand_mark()
    embedded = tab.evaluate("()=>{const P=AtelierMotion.assembly.pieces;return [P.BRAND,P.BRAND_SMALL]}")
    for name, master, drawn in (('master', brand.MASTER, embedded[0]), ('small', brand.SMALL, embedded[1])):
        made = json.loads(json.dumps(brand.pieces(master)))
        assert set(made) == set(drawn), (name, set(made) ^ set(drawn))
        for key, value in made.items():
            assert _close(value, drawn[key]), (name, key)

    poses = tab.evaluate(POSES)
    for name, gap in poses.items():
        if name in ('master', 'micro success'):
            assert min(gap.values()) >= 13.9, (name, gap)
        elif name == 'warning':
            assert min(gap['tm'], gap['md']) >= 13.9, (name, gap)
        elif name == 'error':
            continue  # crosses on purpose
        else:
            assert min(gap.values()) >= 14, (name, gap)

    frames = tab.evaluate(FILM, [TIMELINE, FPS])
    assert len(frames) == 1515, len(frames)
    under = {key: sum(1 for frame in frames if frame[key] < 13.8) for key in BASELINE}
    for key, most in BASELINE.items():
        assert under[key] <= most, (key, under)
    busy = [f for f in frames if f['state'] in ('working', 'mesh', 'texture', 'material') and f['i'] >= OPENED]
    overlap = [f for f in busy if min(f['tm'], f['td'], f['md']) < 0]
    assert not overlap, overlap[:5]

    # The logo's entrance keeps the planner's tolerance of the halo's gap the whole way in.
    entrance = tab.evaluate(ENTRANCE, 1000 / FPS)
    assert entrance['done'] and min(entrance['least'].values()) >= 13, entrance

    assert not errors, errors
    tab.close()
    checks.append('Glyph: engine outlines match scripts/brand_mark.py, and every designed pose keeps its minimum gap')
    checks.append(f"Glyph: {len(frames)} frames no worse than the baseline (under 13.8u: tile-mesh {under['tm']}, tile-disc {under['td']}, mesh-disc {under['md']}), and no overlap in Working or a loader once open")
    checks.append(f"Glyph: logo entrance stays clear, closest {min(entrance['least'].values()):.2f}u")

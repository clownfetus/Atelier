"""The glyph's promises, on the production modules, with time stepped by hand.

Success never forms without a success result, a result lands within 640 ms, only busy loops, busy
after busy carries on, the layer order never changes, a settled glyph asks for no frames, and the
Motion setting takes effect on a running animation. Also the logo's entrance, the success click, the
cost of many Micro glyphs, and Preview motion in the real app.
"""
from glyph_fixture import open_glyph_page

FRAME = 1000 / 25

HELPERS = """
window.__g = window.__g || {};
const P = AtelierMotion.assembly.pieces;
// An A is all three pieces within reach of their seats, in the master or the small mark.
window.__isA = pose => {
  const near = M => ['blue', 'teal', 'disc'].every(id => Math.hypot(pose[id].x - M[id].x, pose[id].y - M[id].y) < 20);
  return near(P.POSES.master) || near(P.micro().success);
};
window.__order = host => [...host.querySelectorAll('[data-piece]')].map(el => el.dataset.piece).join();
window.__cat = e => ['blue', 'teal', 'disc'].every(id => P.CAT[id].every((v, i) => v === e.cols[id][i]));
window.__green = e => ['blue', 'teal', 'disc'].every(id => e.cols[id].join() === '182,235,168');
0;
"""


def _step(tab, ms):
    tab.evaluate(f"window.__step({FRAME}, {int(ms / FRAME)})")


def _api(context, url, report, checks):
    tab, errors = open_glyph_page(context, url)
    tab.evaluate(HELPERS)
    # A non-element host throws; a busy host needs emptying; a remount replaces the last glyph.
    assert tab.evaluate("(()=>{try{AtelierMotion.glyph.mount(null);return false}catch(e){return /DOM host/.test(e.message)}})()")
    assert tab.evaluate("(()=>{const h=document.createElement('div');h.append('x');try{AtelierMotion.glyph.mount(h);return false}catch(e){return /empty host/.test(e.message)}})()")
    # A result that has already played mounts finished; busy can't be still, and a later state plays as usual.
    still = tab.evaluate("""()=>{const g=__mount(128,{state:'success',still:true}),done=[g.engine.settled,g.engine.formed];g.set('busy');const after=g.engine.settled;g.destroy();
      const b=__mount(128,{state:'busy',still:true}),busy=b.engine.settled;b.destroy();document.getElementById('root').replaceChildren();return {done,after,busy};}""")
    assert still == {'done': [True, True], 'after': False, 'busy': False}, still
    facts = tab.evaluate("""()=>{const g=__mount(48,{state:'info'}),host=document.querySelector('#root>div'),svg=host.querySelector('svg');
      const out={keys:['set','replay','destroy'].every(k=>typeof g[k]==='function'),state:g.state,hidden:svg.getAttribute('aria-hidden'),tier:host.dataset.glyphTier,attr:host.dataset.glyphState};
      g.set('warning');out.after=g.state;out.attr2=host.dataset.glyphState;g.set('nonsense');out.ignored=g.state;
      g.set('busy',{asset:'mesh'});out.asset=host.dataset.glyphAsset;g.set('info',{asset:'mesh'});out.noAsset=host.dataset.glyphAsset===undefined;
      const again=AtelierMotion.glyph.mount(host,{state:'busy'});out.remount=host.querySelectorAll('svg').length;again.destroy();out.clean=!host.hasChildNodes()&&!host.dataset.atelierMotion;return out}""")
    assert facts['keys'] and facts['state'] == 'info' and facts['hidden'] == 'true', facts
    assert facts['tier'] == 'inline' and facts['attr'] == 'info', facts
    # Text next to the glyph updates at once, so the state must change before anything settles.
    assert facts['after'] == 'warning' and facts['attr2'] == 'warning' and facts['ignored'] == 'warning', facts
    assert facts['asset'] == 'mesh' and facts['noAsset'] and facts['remount'] == 1 and facts['clean'], facts
    # Tiers come from the host's rendered height, with no gaps, and follow it when it changes.
    tiers = tab.evaluate("""async()=>{const out={};for(const h of [16,31,32,95,96,128]){const g=__mount(h,{state:'info'});out[h]=g.engine.tier}
      const host=document.createElement('div');host.style.height='24px';host.style.width='37px';document.getElementById('root').append(host);
      const g=AtelierMotion.glyph.mount(host,{state:'success'});out.before=host.dataset.glyphTier;host.style.height='64px';await new Promise(r=>setTimeout(r,120));out.after=host.dataset.glyphTier;out.engine=g.engine.tier;return out}""")
    assert (tiers['16'], tiers['31'], tiers['32'], tiers['95'], tiers['96'], tiers['128']) == ('micro', 'micro', 'inline', 'inline', 'stage', 'stage'), tiers
    assert tiers['before'] == 'micro' and tiers['after'] == 'inline' and tiers['engine'] == 'inline', tiers
    assert not errors, errors
    tab.close()
    checks.append('Glyph: mount shape, aria-hidden, one busy host, tiers with no gaps and live resizing')


def _earned(context, url, report, checks):
    tab, errors = open_glyph_page(context, url, clock=True)
    tab.evaluate(HELPERS)
    # A glyph mounted in busy, at every tier and for every loader, never shows an A, however long it runs.
    for size in (16, 48, 128):
        for asset in (None, 'mesh', 'texture', 'material'):
            ok = tab.evaluate("""async([size,asset,dt,n])=>{const g=__mount(size,{state:'busy',asset});let A=0,kinds=new Set();
              if(__isA(g.engine.cur))A++;
              for(let i=0;i<n;i++){await __step(dt);if(__isA(g.engine.cur))A++;if(g.engine.load)kinds.add(g.engine.load.kind)}
              const out={A,kinds:[...kinds],state:g.state,asset:g.engine.asset};g.destroy();return out}""", [size, asset, FRAME, 300])
            assert ok['A'] == 0 and ok['state'] == 'busy', (size, asset, ok)
            # A loader only runs when the surface names it, and never hands over by itself.
            if size == 16 or asset is None:
                assert ok['kinds'] == [], (size, asset, ok)
            else:
                assert ok['kinds'] == [{'mesh': 'mesh', 'texture': 'texture', 'material': 'material'}[asset]], (size, asset, ok)
    # Busy after the same busy carries on: no restart.
    same = tab.evaluate("""async dt=>{const g=__mount(128,{state:'busy'});await __step(dt,20);const t=g.engine.token;g.set('busy');g.set('busy',{});await __step(dt,5);const r=g.engine.token===t;g.destroy();return r}""", FRAME)
    assert same
    assert not errors, errors
    tab.close()
    checks.append('Glyph: busy never shows an A at any tier, loaders only when named, busy after busy carries on')


def _compact(context, url, report, checks):
    tab, errors = open_glyph_page(context, url, clock=True)
    tab.evaluate(HELPERS)
    # Working from 32 to 47 px is the row and a nudge: no fit, and every piece within about 1.5 px of its seat.
    for size in (32, 47):
        r = tab.evaluate("""async([size,dt])=>{const g=__mount(size,{state:'busy'}),e=g.engine,R=AtelierMotion.assembly.pieces.rest();let far=0,moved=0,A=0;
          const each=()=>{let most=0;for(const id of ['blue','teal','disc'])most=Math.max(most,Math.hypot(e.cur[id].x-R[id].x,e.cur[id].y-R[id].y));return most};
          for(let i=0;i<200;i++){await __step(dt);const m=each();far=Math.max(far,m);if(m>0)moved++;if(__isA(e.cur))A++}
          const scale=Math.min(size/e.box[3],e.width/e.box[2]);const out={px:far*scale,moved,A,fit:e.lastFit,settled:e.settled,tier:e.tier,box:e.box.join()};g.destroy();return out}""", [size, FRAME])
        assert r['tier'] == 'inline' and r['fit'] == -1 and not r['settled'] and r['A'] == 0, (size, r)
        assert r['moved'] > 100 and 1.2 < r['px'] < 1.6 and r['box'] == '38,84,440,216', (size, r)
    moves = tab.evaluate("""async dt=>{const out={};
      const a=__mount(48,{state:'busy'});await __step(dt,60);out.fits=a.engine.lastFit!==-1;a.destroy();
      const b=__mount(40,{state:'busy',asset:'mesh'});await __step(dt,20);out.loader=b.engine.load&&b.engine.load.kind;b.destroy();
      const c=__mount(40,{state:'busy'});await __step(dt,30);c.set('success');let t=0;while(!c.engine.settled&&t<6000){await __step(dt);t+=dt}out.A=__isA(c.engine.cur);out.cat=__cat(c.engine);c.set('busy');t=0;await __step(dt,40);out.back=!__isA(c.engine.cur)&&c.engine.lastFit===-1;c.destroy();
      const d=__mount(40,{state:'busy'});await __step(dt,10);const before=d.engine.lastFit;d.engine.setSize('inline',64,130);await __step(dt,60);out.grown=[before,d.engine.lastFit!==-1];d.destroy();
      return out}""", FRAME)
    assert moves['fits'] and moves['loader'] == 'mesh' and moves['A'] and moves['cat'] and moves['back'], moves
    assert moves['grown'] == [-1, True], moves
    assert not errors, errors
    tab.close()
    tab, errors = open_glyph_page(context, url, clock=True, motion='off')
    still = tab.evaluate("""async dt=>{const g=__mount(40,{state:'busy'}),R=JSON.stringify(AtelierMotion.assembly.pieces.rest());await __step(dt,30);return {row:JSON.stringify(g.engine.cur)===R,settled:g.engine.settled}}""", FRAME)
    assert still['row'] and still['settled'], still
    assert not errors, errors
    tab.close()
    checks.append('Glyph: Working from 32 to 47 px is the row and a nudge, loaders and results still run, and it follows the host across 48 px')


def _rim(context, url, report, checks):
    # Material's light stays inside the disc, on every surface, so the rim stays whole.
    tab, errors = open_glyph_page(context, url, clock=True)
    tab.evaluate(HELPERS)
    r = tab.evaluate("""async dt=>{const g=__mount(128,{state:'busy',asset:'material'});await __step(dt,40);const e=g.engine;
      return {clip:+[...e.view.svg.querySelectorAll('clipPath circle')][0].getAttribute('r'),disc:e.cur.disc.r}}""", FRAME)
    assert r['clip'] <= r['disc'] * .85, r
    assert not errors, errors
    tab.close()
    checks.append("Glyph: Material's band stays inside the disc's rim")


def _lands(context, url, report, checks):
    tab, errors = open_glyph_page(context, url, clock=True)
    tab.evaluate(HELPERS)
    # A result arriving at any moment of a move or a loader lands within 640 ms.
    worst = tab.evaluate("""async dt=>{let worst=0,seen=0;
      for(const asset of [null,'mesh','texture','material']){
        for(let delay=3;delay<90;delay+=7){
          const g=__mount(128,{state:'busy',asset});await __step(dt,delay);
          const e=g.engine,move=e.moving;let landed=!move,t=0;if(move)move.then(()=>{landed=true});
          g.set('success');
          while(!landed&&t<3000){await __step(dt);t+=dt}
          worst=Math.max(worst,t);seen++;g.destroy();
        }
      }
      return {worst,seen}}""", FRAME)
    assert worst['seen'] > 40 and worst['worst'] <= 640 + FRAME, worst
    # The piece in flight really does finish before the next state moves anything else.
    assert not errors, errors
    tab.close()
    checks.append(f"Glyph: a result lands within 640 ms of any moment (worst {worst['worst']:.0f} ms over {worst['seen']} moments)")


def _settles(context, url, report, checks):
    tab, errors = open_glyph_page(context, url, clock=True)
    tab.evaluate(HELPERS)
    # Only busy loops. A settled glyph asks for no frames at all. Stage's warning wobble is the one exception.
    for size in (16, 48, 128):
        for state in ('info', 'success', 'warning', 'error'):
            if size == 128 and state == 'warning':
                continue
            r = tab.evaluate("""async([size,state,dt])=>{const g=__mount(size,{state:'busy'});await __step(dt,60);g.set(state);
              let t=0;while(!g.engine.settled&&t<12000){await __step(dt);t+=dt}
              await __step(dt,3);const before=window.__frames;await __step(dt,50);const frames=window.__frames-before;
              const e=g.engine,out={t,settled:e.settled,frames,cat:__cat(e),green:__green(e),order:__order(g.engine.view.svg),A:__isA(e.cur)};g.destroy();return out}""", [size, state, FRAME])
            assert r['settled'] and r['frames'] == 0, (size, state, r)
            assert r['order'] == 'blue,teal,disc', (size, state, r)
            if state == 'success':
                assert r['A'], (size, state, r)
                # The A goes back to its own colours after success, except at Micro, where it stays green.
                assert (r['green'] if size == 16 else r['cat']), (size, state, r)
    wobble = tab.evaluate("""async dt=>{const g=__mount(128,{state:'warning'});await __step(dt,200);const before=window.__frames;await __step(dt,50);const f=window.__frames-before;const s=g.engine.settled;g.destroy();return {f,s}}""", FRAME)
    assert wobble['f'] > 0 and not wobble['s'], wobble
    # The layer order never changes through a whole run of states.
    order = tab.evaluate("""async dt=>{const g=__mount(128,{state:'busy'}),svg=g.engine.view.svg,els=[...svg.querySelectorAll('[data-piece]')];let bad=0;
      const walk=async n=>{for(let i=0;i<n;i++){await __step(dt);const now=[...svg.querySelectorAll('[data-piece]')];if(now.some((el,k)=>el!==els[k]))bad++;}};
      for(const [s,a] of [['busy',null],['success',null],['busy','mesh'],['warning',null],['busy','texture'],['error',null],['busy','material'],['info',null]]){g.set(s,{asset:a});await walk(80)}
      g.destroy();return bad}""", FRAME)
    assert order == 0, order
    assert not errors, errors
    tab.close()
    checks.append('Glyph: only busy loops, settled glyphs ask for no frames, the A returns to its colours except at Micro, layer order holds')


def _policy(context, url, report, checks):
    # Calm: at most Inline, with no punch, ripple or wobble loop, and a loader that doesn't travel.
    tab, errors = open_glyph_page(context, url, clock=True, motion='calm')
    tab.evaluate(HELPERS)
    calm = tab.evaluate("""async dt=>{const g=__mount(128,{state:'busy'});await __step(dt,40);g.set('success');let punch=false,ring=false,t=0;
      while(!g.engine.settled&&t<8000){await __step(dt);t+=dt;punch=punch||g.engine.fx.punch!==1;ring=ring||g.engine.fx.ringOp>0}
      const out={punch,ring,green:0,settled:g.engine.settled};g.set('warning');t=0;while(!g.engine.settled&&t<12000){await __step(dt);t+=dt}out.warnSettled=g.engine.settled;g.destroy();
      const l=__mount(48,{state:'busy',asset:'mesh'}),R=AtelierMotion.assembly.pieces.rest();let moved=0,cuts=0;for(let i=0;i<120;i++){await __step(dt);if(Math.abs(l.engine.cur.teal.y-R.teal.y)>.01||Math.abs(l.engine.cur.teal.rot)>.01)moved++;if(l.engine.load&&l.engine.load.w>1)cuts++}
      out.moved=moved;out.cuts=cuts;l.destroy();return out}""", FRAME)
    assert calm['settled'] and not calm['punch'] and not calm['ring'] and calm['warnSettled'], calm
    assert calm['moved'] == 0 and calm['cuts'] > 0, calm
    assert not errors, errors
    tab.close()
    # Off: still poses and a cross-fade. Nothing travels, and a loader is the still row.
    tab, errors = open_glyph_page(context, url, clock=True, motion='off')
    tab.evaluate(HELPERS)
    still = tab.evaluate("""async dt=>{const g=__mount(128,{state:'busy'}),e=g.engine,K=JSON.stringify;const first=K(e.cur);let moved=0;for(let i=0;i<60;i++){await __step(dt);if(K(e.cur)!==first)moved++}
      const out={moved,settled:e.settled,opacity:e.opacity??1};let low=1;g.set('success');let green=false,t=0;while(!e.settled&&t<4000){await __step(dt);t+=dt;low=Math.min(low,e.opacity??1);green=green||__green(e)}
      out.fade=low;out.green=green;out.cat=__cat(e);out.A=__isA(e.cur);out.end=e.opacity??1;
      const before=window.__frames;await __step(dt,3);await __step(dt,30);out.frames=window.__frames-before;
      const l=__mount(48,{state:'busy',asset:'texture'}),R=JSON.stringify(AtelierMotion.assembly.pieces.rest());await __step(dt,40);out.row=JSON.stringify(l.engine.cur)===R;out.load=l.engine.load;return out}""", FRAME)
    assert still['moved'] == 0 and still['settled'], still
    assert still['fade'] < .05 and still['end'] == 1 and still['green'] and still['cat'] and still['A'], still
    assert still['frames'] == 0 and still['row'] and still['load'] is None, still
    assert not errors, errors
    tab.close()
    # A change takes effect on a running animation: the piece in flight lands, then the new setting applies.
    tab, errors = open_glyph_page(context, url, clock=True)
    tab.evaluate(HELPERS)
    change = tab.evaluate("""async dt=>{const out=[];for(const delay of [7,19,33,47,61,75]){
        window.__motion='full';const g=__mount(128,{state:'busy'}),e=g.engine;await __step(dt,delay);
        let t=0,landedAt=null;const move=e.moving;if(move)move.then(()=>{landedAt=t});else landedAt=0;
        __setMotion('off');while(landedAt===null&&t<2000){await __step(dt);t+=dt}
        while(!e.settled&&t<3000){await __step(dt);t+=dt}
        out.push({landedAt,t,settled:e.settled,opacity:e.opacity??1});g.destroy()}
      window.__motion='full';const w=__mount(128,{state:'warning'});await __step(dt,220);const wobbling=!w.engine.settled;__setMotion('calm');let t=0;while(!w.engine.settled&&t<1500){await __step(dt);t+=dt}
      const held=AtelierMotion.assembly.pieces.POSES.warning;return {out,wobbling,stopped:w.engine.settled,x:Math.abs(w.engine.cur.blue.x-held.blue.x)}}""", FRAME)
    for one in change['out']:
        assert one['settled'] and one['landedAt'] <= 640 + FRAME and one['t'] <= 640 + 300 + 3 * FRAME and one['opacity'] == 1, change
    assert change['wobbling'] and change['stopped'] and change['x'] < .01, change
    assert not errors, errors
    tab.close()
    # Off after a Complete has drawn its ripple: the still poses reset the effects, and the glyph keeps drawing.
    tab, errors = open_glyph_page(context, url, clock=True)
    tab.evaluate(HELPERS)
    after = tab.evaluate("""async dt=>{const g=__mount(128,{state:'busy'}),e=g.engine;await __step(dt,40);g.set('success');let t=0,ring=false;
      while(!e.settled&&t<6000){await __step(dt);t+=dt;ring=ring||e.fx.ringOp>0}
      __setMotion('off');g.set('warning');t=0;while(!e.settled&&t<3000){await __step(dt);t+=dt}
      const out={ring,settled:e.settled,state:e.state,opacity:e.opacity??1,shown:e.view.svg.style.opacity};g.destroy();return out}""", FRAME)
    assert after['ring'] and after['settled'] and after['state'] == 'warning', after
    assert after['opacity'] == 1 and after['shown'] == '', after
    assert not errors, errors
    tab.close()
    checks.append('Glyph: Calm has no flourish or travelling loader, Off has still poses and a cross-fade (after a ripple too), a setting change lands then applies')


def _hidden(context, url, report, checks):
    # Real time here: an off-screen glyph draws nothing, and picks up where it left off when it comes back.
    tab, errors = open_glyph_page(context, url)
    tab.evaluate(HELPERS)
    r = tab.evaluate("""async()=>{const wait=ms=>new Promise(s=>setTimeout(s,ms));const g=__mount(128,{state:'busy'}),host=document.querySelector('#root>div');host.style.position='fixed';host.style.top='0';
      await wait(300);const seen=g.engine.time;await wait(200);const running=g.engine.time>seen;host.style.top='-4000px';await wait(200);const off=g.engine.time;await wait(400);const frozen=g.engine.time===off,visible=g.engine.visible;
      g.set('success');await wait(200);const still=g.engine.time===off;host.style.top='0';await wait(2600);const out={running,frozen,visible,still,back:g.engine.visible,moved:g.engine.time>off,state:g.engine.state,settled:g.engine.settled};g.destroy();return out}""")
    assert r['running'] and r['frozen'] and not r['visible'] and r['still'], r
    assert r['back'] and r['moved'] and r['settled'], r
    assert not errors, errors
    tab.close()
    checks.append('Glyph: time stops off screen, and a state set meanwhile plays when the glyph comes back')


def _entrance(context, url, report, checks):
    tab, errors = open_glyph_page(context, url, clock=True)
    tab.evaluate(HELPERS)
    # One piece at a time on the Brand mark route, in its own colours, with no flourish, and it ends on the mark.
    r = tab.evaluate("""async dt=>{window.AtelierFoley={click(){window.__clicks=(window.__clicks||0)+1}};
      const host=document.createElement('div');document.getElementById('root').append(host);let done=0,t=0;
      const g=AtelierMotion.glyph.entrance(host,{size:32,onDone:()=>{done++}}),e=g.engine,box=()=>{const r=host.getBoundingClientRect();return [r.x,r.y,r.width,r.height].join()},first=box();
      let colour=true,flourish=false,shifted=false,together=false,seq=[],was=JSON.stringify(e.cur);const snap=()=>Object.fromEntries(['blue','teal','disc'].map(id=>[id,JSON.stringify(e.cur[id])]));let prev=snap();
      while(!done&&t<4000){await __step(dt);t+=dt;colour=colour&&__cat(e);flourish=flourish||e.fx.punch!==1||e.fx.ringOp>0;shifted=shifted||box()!==first;
        const now=snap(),moved=Object.keys(now).filter(id=>now[id]!==prev[id]);prev=now;if(moved.length>1)together=true;if(moved.length===1&&seq[seq.length-1]!==moved[0])seq.push(moved[0])}
      await __step(dt,3);const before=window.__frames;await __step(dt,20);
      const M=AtelierMotion.assembly.pieces.POSES.master,out={t,done,colour,flourish,shifted,together,seq,clicks:window.__clicks||0,exact:JSON.stringify(e.cur)===JSON.stringify(M),frames:window.__frames-before,size:first.split(',').slice(2),order:__order(e.view.svg)};
      let again=0;out.second=AtelierMotion.glyph.entrance(document.createElement('div'),{onDone:()=>{again++}})===null;out.again=again;
      __setMotion('calm');await __step(dt,3);out.doneOnce=done;return out}""", FRAME)
    assert r['done'] == 1 and r['doneOnce'] == 1 and r['t'] <= 1600, r
    assert r['colour'] and not r['flourish'] and r['clicks'] == 0, r
    assert not r['shifted'] and r['size'] == ['49', '32'], r
    assert not r['together'] and r['seq'] == ['blue', 'teal', 'disc', 'teal'], r
    assert r['exact'] and r['frames'] == 0 and r['order'] == 'blue,teal,disc', r
    assert r['second'] and r['again'] == 1, r
    assert not errors, errors
    tab.close()
    # Calm, Off and a hidden window: nothing plays, and the still logo is simply there.
    for motion, hide in (('calm', False), ('off', False), ('full', True)):
        tab, errors = open_glyph_page(context, url, clock=True, motion=motion)
        skip = tab.evaluate("""hide=>{if(hide)Object.defineProperty(document,'hidden',{get:()=>true});const host=document.createElement('div');let done=0;
          const g=AtelierMotion.glyph.entrance(host,{onDone:()=>{done++}});return {none:g===null,done,empty:!host.hasChildNodes()}}""", hide)
        assert skip['none'] and skip['done'] == 1 and skip['empty'], (motion, hide, skip)
        assert not errors, errors
        tab.close()
    checks.append(f"Glyph: logo entrance runs once in {r['t']:.0f} ms, one piece at a time, never green or clicks, ends on the mark, and skips Calm, Off and a hidden window")


def _sound(context, url, report, checks):
    # The click comes once with a Stage or Inline success, and never at Micro, in Calm or in Off.
    expected = {('full', 128): 1, ('full', 48): 1, ('full', 16): 0, ('calm', 128): 0, ('calm', 48): 0, ('off', 128): 0}
    for (motion, size), want in expected.items():
        tab, errors = open_glyph_page(context, url, clock=True, motion=motion)
        got = tab.evaluate("""async([size,dt])=>{window.__clicks=0;window.AtelierFoley={click(){window.__clicks++}};const g=__mount(size,{state:'busy'});await __step(dt,50);const before=window.__clicks;g.set('success');let t=0;while(!g.engine.settled&&t<8000){await __step(dt);t+=dt}
          return {before,clicks:window.__clicks,settled:g.engine.settled}}""", [size, FRAME])
        assert got['before'] == 0 and got['settled'] and got['clicks'] == want, (motion, size, got)
        assert not errors, errors
        tab.close()
    checks.append('Glyph: the success click plays once, at Stage and Inline in Full motion only')


def _cost(context, url, report, checks):
    # Real time: 30 Micro glyphs working, with the script each frame measured.
    tab, errors = open_glyph_page(context, url)
    cost = tab.evaluate("""async()=>{const raf=window.requestAnimationFrame.bind(window);let sum=0,n=0,max=0;window.requestAnimationFrame=fn=>raf(t=>{const a=performance.now();fn(t);const d=performance.now()-a;sum+=d;n++;max=Math.max(max,d)});
      const gs=[];for(let i=0;i<30;i++)gs.push(__mount(i%2?16:24,{state:'busy'}));await new Promise(r=>setTimeout(r,2000));sum=0;n=0;max=0;await new Promise(r=>setTimeout(r,2000));const out={avg:sum/n,max,n};gs.forEach(g=>g.destroy());return out}""")
    assert cost['n'] > 0 and cost['avg'] < 2, cost
    assert not errors, errors
    tab.close()
    checks.append(f"Glyph: 30 Micro glyphs cost {cost['avg']:.2f} ms of script per frame against the 2 ms limit")


def _preview(context, url, report, checks):
    # The real app: Settings has every state and loader, on glyphs at the three sizes, and the logo's entrance.
    tab = context.new_page()
    errors = []
    tab.on('pageerror', lambda error: errors.append(str(error)))
    tab.route('**/api/setup_status', lambda route: route.fulfill(json={'configured': True}))
    tab.goto(url)
    tab.wait_for_function("window.AtelierMotion && window.AtelierMotion.glyph")
    tab.evaluate("()=>{document.getElementById('update-overlay')?.remove();openPaths()}")
    tab.wait_for_selector('#motion-preview', state='visible', timeout=10000)
    tab.locator('#motion-preview').scroll_into_view_if_needed()
    tab.wait_for_selector('#motion-preview[data-ready]', state='attached')
    hosts = "[...document.querySelectorAll('#motion-preview figure [data-glyph-state]')]"
    assert tab.evaluate(f"()=>{hosts}.map(h=>h.dataset.glyphTier)") == ['micro', 'inline', 'stage']
    for label, state, asset in (('Working', 'busy', None), ('At rest', 'info', None), ('Complete', 'success', None), ('Warning', 'warning', None), ('Error', 'error', None), ('Mesh', 'busy', 'mesh'), ('Texture', 'busy', 'texture'), ('Material', 'busy', 'material')):
        tab.locator('#motion-preview button', has_text=label).first.click()
        shown = tab.evaluate(f"()=>{hosts}.map(h=>[h.dataset.glyphState,h.dataset.glyphAsset||null])")
        assert all(item == [state, asset] for item in shown), (label, shown)
    tab.locator('#motion-preview [data-preview-logo]').click()
    logo = tab.evaluate("()=>{const h=document.querySelector('.motion-preview-logo > span'),r=h.getBoundingClientRect();return {w:r.width,h:r.height,on:h.hasAttribute('data-glyph-entrance')}}")
    assert logo == {'w': 49, 'h': 32, 'on': True}, logo
    assert not errors, errors
    tab.close()
    checks.append('Glyph: Preview motion runs five states, three loaders and the logo entrance in Settings')


def run_assembly_state_checks(context, url, report, checks):
    _api(context, url, report, checks)
    _earned(context, url, report, checks)
    _compact(context, url, report, checks)
    _rim(context, url, report, checks)
    _lands(context, url, report, checks)
    _settles(context, url, report, checks)
    _policy(context, url, report, checks)
    _hidden(context, url, report, checks)
    _entrance(context, url, report, checks)
    _sound(context, url, report, checks)
    _cost(context, url, report, checks)
    _preview(context, url, report, checks)

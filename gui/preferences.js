// Local presentation preferences. Projects and exported assets never contain these values.
(() => {
  'use strict';
  const system = matchMedia('(prefers-reduced-motion: reduce)'), changes = new EventTarget();
  const read = (key, fallback) => { try { return localStorage.getItem('atelier.' + key) || fallback; } catch (_) { return fallback; } };
  const normalizedMotion=value=>value==='reduce'?'off':value==='system'?'full':['full','calm','off'].includes(value)?value:'full';
  let motion = normalizedMotion(read('motion', 'full')), density = read('density', 'comfortable'), adaptive = read('adaptiveAccent', '0') === '1';
  if (!['comfortable','compact'].includes(density)) density='comfortable';
  const mode=()=>system.matches?'off':motion;
  const tier=()=>mode()==='full'?3:mode()==='calm'?1:0;
  const query = {get matches() { return mode()==='off'; }, media: system.media,
    addEventListener:(...args) => changes.addEventListener(...args), removeEventListener:(...args) => changes.removeEventListener(...args)};
  function apply() {
    document.documentElement.dataset.motion = query.matches ? 'reduce' : 'full';
    document.documentElement.dataset.krackle = mode();
    document.documentElement.dataset.density = density === 'compact' ? 'compact' : 'comfortable';
    const event = new Event('change'); Object.defineProperty(event, 'matches', {value:query.matches}); changes.dispatchEvent(event);
    window.dispatchEvent(new Event('atelier:preferences'));
    for(const id of ['settings-motion','setup-motion-dial']){const control=document.getElementById(id);if(control)control.value=motion;}
    for(const note of document.querySelectorAll('[data-motion-note]'))note.textContent=system.matches?'System reduced motion is on; Off is active.':motion==='calm'?'Calm keeps small responses and still formations.':motion==='off'?'Stills only.':'Full motion follows real work.';
  }
  system.addEventListener('change', apply);
  window.addEventListener('storage', event => {
    if (event.key==='atelier.motion') motion=normalizedMotion(event.newValue);
    else if (event.key==='atelier.density') density=event.newValue==='compact'?'compact':'comfortable';
    else if (event.key==='atelier.adaptiveAccent') adaptive=event.newValue==='1';
    else return;
    const motionControl=document.getElementById('settings-motion'), densityControl=document.getElementById('settings-density'), accentControl=document.getElementById('settings-adaptive-accent');
    if(motionControl)motionControl.value=motion;if(densityControl)densityControl.value=density;if(accentControl)accentControl.checked=adaptive;apply();
  });
  window.AtelierMotionPolicy = Object.freeze({query:() => query,tier,allows:value=>Number(value)<=tier(),mode});
  const write = (key, value) => { try { localStorage.setItem('atelier.' + key, value); } catch (_) {} };
  if(read('motion','full')!==motion)write('motion',motion);
  let origin = null, reveal = null, themeAnimation = null;
  document.addEventListener('pointerdown', event => {
    origin = event.target.closest('[data-theme-picker],[data-theme-preset]') ? {x:event.clientX,y:event.clientY} : null;
  }, true);
  function revealTheme(update) {
    if (!origin || !window.AtelierMotionPolicy.allows(2) || !document.startViewTransition || document.hidden) { origin = null; return false; }
    const release=window.AtelierMotion?.moment?.claim('theme-wave',2);if(!release){origin=null;return false;}
    const point = origin; origin = null; reveal?.skipTransition();
    let current;try{current=document.startViewTransition(update);}catch(_){release();return false;}reveal = current;
    current.ready.then(() => {
      if(reveal!==current||document.hidden||!window.AtelierMotionPolicy.allows(2)){current.skipTransition();return;}
      // A print wash crosses the page from the chosen control's side. The modest
      // scalloped leading edge belongs to the sheet, never a floating screen-sized arc.
      const fromRight=point.x>innerWidth/2;
      const wash=front=>{
        const x=value=>fromRight?innerWidth-value:value;
        const points=[`${x(-24)}px -24px`,`${x(front)}px -24px`];
        for(let i=0;i<=12;i++)points.push(`${x(front+(i%2?5:-5))}px ${innerHeight*i/12}px`);
        points.push(`${x(front)}px ${innerHeight+24}px`,`${x(-24)}px ${innerHeight+24}px`);
        return `polygon(${points.join(',')})`;
      };
      themeAnimation = document.documentElement.animate({clipPath:[wash(-12),wash(innerWidth+12)]},
        {duration:300,easing:'cubic-bezier(.3,0,.2,1)',pseudoElement:'::view-transition-new(root)'});
      themeAnimation.finished.catch(()=>{});
    }).catch(() => {});
    current.finished.catch(() => {}).finally(() => {release(); if (reveal === current) {reveal = null;themeAnimation = null;} });
    return true;
  }
  changes.addEventListener('change', () => { if (!window.AtelierMotionPolicy.allows(2)) { themeAnimation?.cancel(); reveal?.skipTransition(); } });
  document.addEventListener('visibilitychange',()=>{if(document.hidden){themeAnimation?.cancel();reveal?.skipTransition();}});
  window.addEventListener('pagehide',()=>{themeAnimation?.cancel();reveal?.skipTransition();});
  window.AtelierPreferences = Object.freeze({revealTheme, adaptive:() => adaptive});
  apply();
  document.addEventListener('DOMContentLoaded', () => {
    const settings = [['settings-motion','motion',() => motion, value => motion = normalizedMotion(value)],
      ['settings-density','density',() => density, value => density = value]];
    for (const [id,key,get,set] of settings) {
      const control = document.getElementById(id); if (!control) continue;
      control.value = get(); control.addEventListener('change', () => { set(control.value); write(key, control.value); apply(); });
    }
    const motionNote=document.createElement('p');motionNote.className='setup-note';motionNote.dataset.motionNote='';
    document.getElementById('settings-motion')?.after(motionNote);apply();
    const accent = document.getElementById('settings-adaptive-accent');
    if (accent) { accent.checked = adaptive; accent.addEventListener('change', () => { adaptive = accent.checked; write('adaptiveAccent', adaptive ? '1' : '0'); apply(); }); }
  });
})();

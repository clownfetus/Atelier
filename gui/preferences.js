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
    const point = origin; origin = null; reveal?.skipTransition();
    const current = document.startViewTransition(update); reveal = current;
    current.ready.then(() => {
      const radius = Math.hypot(Math.max(point.x, innerWidth-point.x), Math.max(point.y, innerHeight-point.y));
      const wave=scale=>{
        let path='';for(let i=0;i<8;i++){const angle=i/8*Math.PI*2,r=Math.max(.1,radius*scale*(.78+i%3*.08));
          const x=point.x+Math.cos(angle)*radius*.22*scale,y=point.y+Math.sin(angle)*radius*.22*scale;
          path+=`M${x-r} ${y}a${r} ${r} 0 1 0 ${2*r} 0a${r} ${r} 0 1 0 ${-2*r} 0Z`;
        }return `path('${path}')`;
      };
      themeAnimation = document.documentElement.animate({clipPath:[wave(.001),wave(1.5)]},
        {duration:240,easing:'cubic-bezier(.2,0,0,1)',pseudoElement:'::view-transition-new(root)'});
    }).catch(() => {});
    current.finished.catch(() => {}).finally(() => { if (reveal === current) reveal = null; });
    return true;
  }
  changes.addEventListener('change', () => { if (!window.AtelierMotionPolicy.allows(2)) { themeAnimation?.cancel(); reveal?.skipTransition(); } });
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

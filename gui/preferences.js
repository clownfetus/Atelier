// Local presentation preferences. Projects and exported assets never contain these values.
(() => {
  'use strict';
  const system = matchMedia('(prefers-reduced-motion: reduce)'), changes = new EventTarget();
  const read = (key, fallback) => { try { return localStorage.getItem('atelier.' + key) || fallback; } catch (_) { return fallback; } };
  let motion = read('motion', 'system'), density = read('density', 'comfortable'), adaptive = read('adaptiveAccent', '0') === '1';
  if (!['system','reduce'].includes(motion)) motion='system';
  if (!['comfortable','compact'].includes(density)) density='comfortable';
  const query = {get matches() { return motion === 'reduce' || system.matches; }, media: system.media,
    addEventListener:(...args) => changes.addEventListener(...args), removeEventListener:(...args) => changes.removeEventListener(...args)};
  function apply() {
    document.documentElement.dataset.motion = query.matches ? 'reduce' : 'full';
    document.documentElement.dataset.density = density === 'compact' ? 'compact' : 'comfortable';
    const event = new Event('change'); Object.defineProperty(event, 'matches', {value:query.matches}); changes.dispatchEvent(event);
    window.dispatchEvent(new Event('atelier:preferences'));
  }
  system.addEventListener('change', apply);
  window.addEventListener('storage', event => {
    if (event.key==='atelier.motion') motion=event.newValue==='reduce'?'reduce':'system';
    else if (event.key==='atelier.density') density=event.newValue==='compact'?'compact':'comfortable';
    else if (event.key==='atelier.adaptiveAccent') adaptive=event.newValue==='1';
    else return;
    const motionControl=document.getElementById('settings-motion'), densityControl=document.getElementById('settings-density'), accentControl=document.getElementById('settings-adaptive-accent');
    if(motionControl)motionControl.value=motion;if(densityControl)densityControl.value=density;if(accentControl)accentControl.checked=adaptive;apply();
  });
  window.AtelierMotionPolicy = Object.freeze({query:() => query});
  const write = (key, value) => { try { localStorage.setItem('atelier.' + key, value); } catch (_) {} };
  let origin = null, reveal = null, themeAnimation = null;
  document.addEventListener('pointerdown', event => {
    origin = event.target.closest('[data-theme-picker],[data-theme-preset]') ? {x:event.clientX,y:event.clientY} : null;
  }, true);
  function revealTheme(update) {
    if (!origin || query.matches || !document.startViewTransition || document.hidden) { origin = null; return false; }
    const point = origin; origin = null; reveal?.skipTransition();
    const current = document.startViewTransition(update); reveal = current;
    current.ready.then(() => {
      const radius = Math.hypot(Math.max(point.x, innerWidth-point.x), Math.max(point.y, innerHeight-point.y));
      themeAnimation = document.documentElement.animate({clipPath:[`circle(0px at ${point.x}px ${point.y}px)`,`circle(${radius}px at ${point.x}px ${point.y}px)`]},
        {duration:240,easing:'cubic-bezier(.2,0,0,1)',pseudoElement:'::view-transition-new(root)'});
    }).catch(() => {});
    current.finished.catch(() => {}).finally(() => { if (reveal === current) reveal = null; });
    return true;
  }
  changes.addEventListener('change', () => { if (query.matches) { themeAnimation?.cancel(); reveal?.skipTransition(); } });
  window.AtelierPreferences = Object.freeze({revealTheme, adaptive:() => adaptive});
  apply();
  document.addEventListener('DOMContentLoaded', () => {
    const settings = [['settings-motion','motion',() => motion, value => motion = value],
      ['settings-density','density',() => density, value => density = value]];
    for (const [id,key,get,set] of settings) {
      const control = document.getElementById(id); if (!control) continue;
      control.value = get(); control.addEventListener('change', () => { set(control.value); write(key, control.value); apply(); });
    }
    const accent = document.getElementById('settings-adaptive-accent');
    if (accent) { accent.checked = adaptive; accent.addEventListener('change', () => { adaptive = accent.checked; write('adaptiveAccent', adaptive ? '1' : '0'); apply(); }); }
  });
})();

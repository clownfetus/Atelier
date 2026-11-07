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
  // A theme the person chooses cross-fades the page for 200 ms in Full and Calm, as interface chrome.
  // Off, and changes that arrive from elsewhere (storage, the system), apply at once.
  let armed = false, reveal = null, fades = [];
  const arm = event => { armed = !!event.target?.closest?.('[data-theme-picker],[data-theme-preset]'); };
  document.addEventListener('pointerdown', arm, true);
  document.addEventListener('keydown', arm, true);
  function stopFade() { for (const fade of fades) fade.cancel(); fades = []; reveal?.skipTransition(); }
  function revealTheme(update) {
    const chosen = armed; armed = false;
    if (!chosen || !window.AtelierMotionPolicy.allows(1) || !document.startViewTransition || document.hidden) return false;
    reveal?.skipTransition();
    let current;try{current=document.startViewTransition(update);}catch(_){return false;}reveal = current;
    current.ready.then(() => {
      if(reveal!==current||document.hidden||!window.AtelierMotionPolicy.allows(1)){current.skipTransition();return;}
      const timing={duration:200,easing:'linear'};
      fades=[document.documentElement.animate({opacity:[1,0]},{...timing,pseudoElement:'::view-transition-old(root)'}),
        document.documentElement.animate({opacity:[0,1]},{...timing,pseudoElement:'::view-transition-new(root)'})];
      for(const fade of fades)fade.finished.catch(()=>{});
    }).catch(() => {});
    current.finished.catch(() => {}).finally(() => { if (reveal === current) { reveal = null; fades = []; } });
    return true;
  }
  changes.addEventListener('change', () => { if (!window.AtelierMotionPolicy.allows(1)) stopFade(); });
  document.addEventListener('visibilitychange',()=>{if(document.hidden)stopFade();});
  window.addEventListener('pagehide',stopFade);
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

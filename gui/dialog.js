// One themed confirmation. The pending answer never blocks the renderer or native shell.
(() => {
  'use strict';
  let active = null;
  function show({title='Continue?', body='', confirmLabel='Continue', cancelLabel='Cancel', tone='default'} = {}) {
    if (active) return Promise.resolve(false);
    const opener = document.activeElement;
    const overlay = document.createElement('div'); overlay.id='atelier-confirm'; overlay.className='overlay active';
    // Confirmations may originate inside Model Studio (z-index 2200) or another
    // raised editor. Keep this modal above the currently open overlay.
    const layers=[...document.querySelectorAll('.overlay.active')].map(node=>Number.parseInt(getComputedStyle(node).zIndex,10)||0);
    overlay.style.zIndex=String(Math.max(300,...layers)+1);
    const panel = document.createElement('section'); panel.className='modal'; panel.tabIndex=-1;
    panel.setAttribute('role','alertdialog'); panel.setAttribute('aria-modal','true');
    panel.setAttribute('aria-labelledby','atelier-confirm-title'); panel.setAttribute('aria-describedby','atelier-confirm-body');
    const heading=document.createElement('h2'); heading.id='atelier-confirm-title'; heading.textContent=title;
    const text=document.createElement('p'); text.id='atelier-confirm-body'; text.textContent=body;
    const actions=document.createElement('div'); actions.className='modal-row';
    const cancel=document.createElement('button'); cancel.id='atelier-confirm-cancel'; cancel.className='btn'; cancel.textContent=cancelLabel;
    const accept=document.createElement('button'); accept.id='atelier-confirm-ok'; accept.className='btn primary'+(tone==='danger'?' danger':''); accept.textContent=confirmLabel;
    actions.append(cancel,accept); panel.append(heading,text,actions); overlay.append(panel); document.body.append(overlay);
    return new Promise(resolve => {
      const finish = answer => {
        if (active?.overlay !== overlay) return;
        document.removeEventListener('keydown', keys, true); document.removeEventListener('focusin', focus, true);
        overlay.remove(); active=null;
        if (opener?.isConnected) opener.focus();
        resolve(answer);
      };
      const focus = event => { if (!panel.contains(event.target)) cancel.focus(); };
      const keys = event => {
        event.stopImmediatePropagation();
        if (event.key==='Escape') { event.preventDefault(); finish(false); }
        else if (event.key==='Tab') {
          event.preventDefault();
          (document.activeElement===cancel ? accept : cancel).focus();
        }
      };
      active={overlay,finish};
      cancel.addEventListener('click',()=>finish(false)); accept.addEventListener('click',()=>finish(true));
      overlay.addEventListener('click', event=>{if(event.target===overlay)finish(false);});
      document.addEventListener('keydown',keys,true); document.addEventListener('focusin',focus,true);
      (tone==='danger'?cancel:accept).focus();
    });
  }
  window.addEventListener('pagehide',()=>active?.finish(false));
  window.AtelierDialog=Object.freeze({confirm:show});
})();

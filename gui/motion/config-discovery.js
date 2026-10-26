// Presentation for the actual setup-status request. It never discovers or validates data.
(() => {
  'use strict';
  const motion = window.AtelierMotion ||= {}, instances = new WeakMap(), live = new Set();
  const query = window.AtelierMotionPolicy?.query();
  const art = `<svg class="am-config-svg" viewBox="0 0 196 88" aria-hidden="true" focusable="false">
    <g class="am-config-scanner">
      <path class="am-config-ink" fill-rule="evenodd" d="M36 20C23 20 16 30 16 44S23 68 36 68H49Q57 68 57 60V50H65V38H57V28Q57 20 49 20ZM35 29C27 29 25 36 25 44S27 59 35 59H46V29ZM21 52a2 2 0 1 0 4 0a2 2 0 1 0-4 0"/>
      <path class="am-config-scan" d="M31 34V54"/>
    </g>
    <path class="am-config-channel" d="M62 44H155"/>
    <path class="am-config-flow" d="M62 44C90 44 118 44 155 44" pathLength="1"/>
    <g class="am-config-receiver">
      <path class="am-config-ink" fill-rule="evenodd" d="M157 22H178Q185 22 185 29V59Q185 66 178 66H157V53H167V56H175V32H167V35H157ZM177 58a2 2 0 1 0 4 0a2 2 0 1 0-4 0"/>
      <path class="am-config-latch" d="M153 36Q150 36 150 40V48Q150 52 153 52H166V36Z"/>
    </g>
  </svg>`;

  function begin(target) {
    const loader = target?.matches?.('#setup-loading') ? target : target?.querySelector?.('#setup-loading');
    const panel = loader?.closest('.modal');
    if (!loader || !panel) { const noop = () => {}; noop.dispose = noop; return noop; }
    instances.get(loader)?.dispose();
    const overlay = panel.closest('.overlay'), host = document.createElement('span');
    host.className = 'am-config-art'; host.setAttribute('aria-hidden', 'true'); host.innerHTML = art;
    const source = document.createElement('span'); source.className = 'am-config-source'; host.append(source);
    const NS = 'http://www.w3.org/2000/svg';
    const conduit = document.createElementNS(NS, 'svg'); conduit.classList.add('am-config-conduits');
    conduit.setAttribute('aria-hidden','true'); conduit.setAttribute('focusable','false');
    const makePath = (role, className) => {
      const path = document.createElementNS(NS,'path'); path.dataset.role=role; path.setAttribute('class',className);
      conduit.append(path); return path;
    };
    const inlet = makePath('panel-inlet','am-config-edge-channel');
    const outlet = makePath('panel-outlet','am-config-edge-channel');
    const inletFlow = makePath('inlet-flow','am-config-edge-flow');
    const outletFlow = makePath('outlet-flow','am-config-edge-flow');
    inletFlow.setAttribute('pathLength','1');outletFlow.setAttribute('pathLength','1');
    host.prepend(conduit);
    function measure() {
      if (!host.isConnected) return;
      const box=host.getBoundingClientRect(), frame=panel.getBoundingClientRect();
      const artBox=host.querySelector('.am-config-svg').getBoundingClientRect(), css=getComputedStyle(panel);
      if (!box.width || !artBox.width) return;
      const scale=artBox.width/196, y=artBox.top-box.top+artBox.height/2;
      const left=frame.left+(parseFloat(css.borderLeftWidth)||0)/2-box.left;
      const right=frame.right-(parseFloat(css.borderRightWidth)||0)/2-box.left;
      const scanner=artBox.left-box.left+16*scale, receiver=artBox.left-box.left+185*scale;
      conduit.setAttribute('viewBox',`0 0 ${box.width} ${box.height}`);
      inlet.setAttribute('d',`M${left} ${y} H${scanner}`);inletFlow.setAttribute('d',inlet.getAttribute('d'));
      outlet.setAttribute('d',`M${receiver} ${y} H${right}`);outletFlow.setAttribute('d',outlet.getAttribute('d'));
      source.style.cssText=`left:${left-2}px;top:${y-4}px;width:4px;height:8px`;
      conduit.dataset.sourceX=String(frame.left+(parseFloat(css.borderLeftWidth)||0)/2);
      conduit.dataset.destinationX=String(frame.right-(parseFloat(css.borderRightWidth)||0)/2);
      conduit.dataset.flowY=String(box.top+y);
    }

    loader.prepend(host); loader.classList.add('am-config-discovery-active');
    let state = 'busy', ended = false, destroyed = false, timeout = null;
    const current = () => panel.isConnected && (!overlay || overlay.classList.contains('active'));
    const endBorder = motion.working?.begin(panel, {kind: 'configuration', anchor: source, current}) || (() => {});
    const observer = new MutationObserver(sync);
    const resize = new ResizeObserver(measure);resize.observe(panel);resize.observe(host);
    measure();
    for (const element of new Set([loader, panel, overlay].filter(Boolean))) observer.observe(element, {attributes: true, attributeFilter: ['class', 'hidden']});
    function recolor() {
      const ink = motion.energy?.resolve(loader);
      if (ink) { host.style.setProperty('--krackle-energy', ink.charge); host.style.setProperty('--krackle-energy-rift', ink.rift); }
    }
    function sync() {
      if (destroyed) return;
      const visible = current() && loader.classList.contains('active') && loader.getClientRects().length;
      if (!visible) { dispose(); return; }
      measure();
      host.dataset.amConfigState = state;
      host.dataset.amConfigRunning = String(state === 'busy' && !document.hidden && window.AtelierMotionPolicy?.allows(2) !== false);
    }
    function dispose() {
      if (destroyed) return;
      destroyed = true; clearTimeout(timeout); observer.disconnect();resize.disconnect();
      if (!ended) { ended = true; endBorder('cancel'); }
      document.removeEventListener('visibilitychange', sync); query?.removeEventListener('change', sync);
      window.removeEventListener('atelier:energy', recolor);
      host.remove(); loader.classList.remove('am-config-discovery-active');
      if (instances.get(loader) === finish) instances.delete(loader);
      live.delete(finish);
    }
    function finish(outcome = 'cancel') {
      if (ended || destroyed) return;
      ended = true;
      state = ['success', 'warning', 'error'].includes(outcome) ? outcome : 'cancel';
      // The border owns the response after the loading cover goes away. No UI delay.
      endBorder(state);
      if (state === 'cancel' || document.hidden || !current()) { dispose(); return; }
      sync(); timeout = setTimeout(dispose, 240);
    }
    finish.dispose = dispose;
    instances.set(loader, finish); live.add(finish);
    document.addEventListener('visibilitychange', sync); query?.addEventListener('change', sync);
    window.addEventListener('atelier:energy', recolor);
    recolor(); sync();
    return finish;
  }
  window.addEventListener('pagehide', () => { for (const finish of [...live]) finish.dispose(); });
  motion.configDiscovery = Object.freeze({begin});
})();

// A coordinated SVG charge is painted in the panel's actual border, behind content.
// SVG owns its animation clock; no floating elements or JavaScript frame loop.
(() => {
  'use strict';
  const motion = window.AtelierMotion ||= {};
  const entries = new Map();
  const root = document.documentElement;
  const backgroundProperties = {image: 'backgroundImage', origin: 'backgroundOrigin',
    clip: 'backgroundClip', size: 'backgroundSize', position: 'backgroundPosition',
    repeat: 'backgroundRepeat', attachment: 'backgroundAttachment', blend: 'backgroundBlendMode'};
  const frameProperties = ['frame', ...Object.keys(backgroundProperties)];
  const finishMs = 780;
  const accepted = new Set(['success', 'warning', 'error']);
  let inkRevision = 0;
  let queued = false, disposed = false;
  const query = window.AtelierMotionPolicy?.query();
  const schedule = () => {
    if (queued || disposed) return;
    queued = true;
    queueMicrotask(() => { queued = false; if (!disposed) sync(); });
  };
  const resize = new ResizeObserver(schedule);
  const intersection = new IntersectionObserver(schedule);
  function entry(panel) {
    let item = entries.get(panel);
    if (item) return item;
    item = {panel, leases: new Set(), badge: null, glyph: null, geometry: '', source: null,
      started: performance.now(), timers: [], pending: null, finish: null, cancelled: false};
    entries.set(panel, item); resize.observe(panel); intersection.observe(panel);
    return item;
  }
  function stopBorder(item) {
    item.panel.removeAttribute('data-am-working-state');
    item.panel.removeAttribute('data-am-working-phase');
    item.panel.removeAttribute('data-am-working-outcome');
    if (!item.source) return;
    if (item.panel.classList.contains('am-working-border')) item.panel.classList.remove('am-working-border');
    for (const property of frameProperties) item.panel.style.removeProperty('--am-working-' + property);
    item.source = null; item.geometry = '';
  }
  function stopBadge(item) {
    item.glyph?.destroy(); item.glyph = null;
    item.badge?.remove(); item.badge = null;
    item.dock = null; item.dockGeometry = ''; item.inlet = null; item.glyphState = null;
  }
  function remove(item) {
    clearTimers(item);
    stopBorder(item); stopBadge(item);
    resize.unobserve(item.panel); intersection.unobserve(item.panel); entries.delete(item.panel);
  }
  function clearTimers(item) { item.timers.forEach(clearTimeout); item.timers.length = 0; }
  function current(lease) {
    try { return !lease.current || lease.current(); } catch (_) { return false; }
  }
  function captureAnchor(anchor, panel) {
    if (!anchor?.isConnected || !anchor.getClientRects().length) return null;
    const box = anchor.getBoundingClientRect(), frame = panel.getBoundingClientRect();
    if (!box.width || !box.height || !frame.width || !frame.height) return null;
    return {x: (box.left + box.width / 2 - frame.left) * panel.offsetWidth / frame.width,
      y: (box.top + box.height / 2 - frame.top) * panel.offsetHeight / frame.height};
  }
  function drawDock(item, anchor) {
    const {panel, badge} = item, icon = badge?.querySelector('.am-material-save-svg');
    const clear = () => { item.dock?.remove(); item.dock = null; item.dockGeometry = ''; item.inlet = null; };
    if (!icon || !anchor?.isConnected) { clear(); return; }
    const p = panel.getBoundingClientRect(), b = badge.getBoundingClientRect();
    const a = anchor.getBoundingClientRect(), g = icon.getBoundingClientRect();
    const sx = panel.offsetWidth / p.width, sy = panel.offsetHeight / p.height;
    // Only the real, empty footer gutter is eligible. Header controls and long
    // routes through content keep their native border plumbing without a dock.
    if (!p.width || !p.height || p.bottom - a.bottom > 64 || p.bottom - g.bottom > 64 ||
      a.bottom > p.bottom - 2 || g.bottom > p.bottom - 2 || a.left < g.right) { clear(); return; }
    const border = parseFloat(getComputedStyle(panel).borderBottomWidth) || 1;
    const from = {x: (g.left + g.width * 16 / 24 - b.left) * sx,
      y: (g.top + g.height * 21.5 / 24 - b.top) * sy};
    const to = {x: (a.left + a.width / 2 - b.left) * sx, y: (a.bottom - b.top) * sy};
    const bottom = (p.bottom - b.top) * sy - border / 2;
    const w = Math.ceil(to.x + 4), h = Math.ceil(bottom + border / 2);
    const radius = Math.min(8, (to.x - from.x) / 3, (bottom - Math.max(from.y, to.y)) / 2);
    if (radius < 1 || from.x < 3 || w <= 0 || h <= 0) { clear(); return; }
    const geometry = JSON.stringify([from, to, bottom, w, h, inkRevision, item.finish?.started]);
    item.inlet = {x: number((b.left - p.left) * sx + from.x), y: panel.offsetHeight};
    if (geometry === item.dockGeometry) return;
    const d = `M${number(from.x)} ${number(from.y)} V${number(bottom - radius)} Q${number(from.x)} ${number(bottom)} ${number(from.x + radius)} ${number(bottom)} H${number(to.x - radius)} Q${number(to.x)} ${number(bottom)} ${number(to.x)} ${number(bottom - radius)} V${number(to.y)}`;
    const duration = item.finish ? finishMs : (motion.beatMs || 1040) * 2;
    const elapsed = performance.now() - (item.finish?.started || item.started);
    const phase = number((item.finish ? Math.min(elapsed, finishMs) : elapsed % duration) / 1000);
    const color = xml(motion.energy?.resolve(panel).charge || getComputedStyle(panel).getPropertyValue('--acc').trim() || '#98b7e2');
    if (!item.dock) {
      item.dock = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
      item.dock.setAttribute('class', 'am-working-dock'); item.dock.setAttribute('aria-hidden', 'true');
      item.dock.setAttribute('focusable', 'false'); badge.append(item.dock);
    }
    item.dock.setAttribute('viewBox', `0 0 ${w} ${h}`);
    item.dock.setAttribute('width', w); item.dock.setAttribute('height', h);
    item.dock.setAttribute('data-role', 'footer-conduit');
    const offsets = item.finish?.outcome === 'error' ? '-100;-100;32;32' : '32;32;-100;-100';
    item.dock.innerHTML = `<path data-role="channel" d="${d}" fill="none" stroke="${color}" stroke-width="3.2" opacity=".3"/>` +
      `<path data-role="ribbon" d="${d}" fill="none" stroke="${color}" stroke-width="3.8" stroke-linecap="round" pathLength="100" stroke-dasharray="${item.finish?.outcome === 'warning' ? '18 82' : '32 68'}">` +
      `<animate attributeName="stroke-dashoffset" values="${offsets}" keyTimes="0;.14;.92;1" dur="${duration}ms" begin="-${phase}s" repeatCount="${item.finish ? 1 : 'indefinite'}" fill="freeze"/></path>`;
    item.dockGeometry = geometry;
  }
  function visible(panel, front) {
    if (document.hidden || !panel.isConnected || panel.closest('[hidden]') || !panel.getClientRects().length) return false;
    const overlay = panel.closest('.overlay');
    if ((overlay && !overlay.classList.contains('active')) || (front && overlay !== front)) return false;
    const rect = panel.getBoundingClientRect(), style = getComputedStyle(panel);
    return style.visibility === 'visible' && style.display !== 'none' &&
      rect.width > 12 && rect.height > 12 && rect.bottom > 0 && rect.right > 0 &&
      rect.top < innerHeight && rect.left < innerWidth;
  }
  const number = value => Math.round(value * 1000) / 1000;
  const xml = value => String(value).replaceAll('&', '&amp;').replaceAll('"', '&quot;').replaceAll('<', '&lt;');
  function corners(style, w, h) {
    const result = ['TopLeft', 'TopRight', 'BottomRight', 'BottomLeft'].map(corner => {
      const parts = style['border' + corner + 'Radius'].split(/\s+/);
      return [0, 1].map(axis => {
        const part = parts[axis] || parts[0];
        return Math.max(0, parseFloat(part) || 0) * (part.endsWith('%') ? (axis ? h : w) / 100 : 1);
      });
    });
    const factor = Math.min(1, w / (result[0][0] + result[1][0] || 1),
      w / (result[3][0] + result[2][0] || 1), h / (result[0][1] + result[3][1] || 1),
      h / (result[1][1] + result[2][1] || 1));
    return result.map(corner => corner.map(value => value * factor));
  }
  function roundedPath(w, h, radii, inset = [0, 0, 0, 0]) {
    const [t, r, b, l] = inset, x = w - r, y = h - b;
    const c = radii.map(([rx, ry], i) => [Math.max(0, rx - (i === 0 || i === 3 ? l : r)),
      Math.max(0, ry - (i < 2 ? t : b))]);
    const arc = (i, endX, endY) => c[i][0] && c[i][1]
      ? `A${number(c[i][0])} ${number(c[i][1])} 0 0 1 ${number(endX)} ${number(endY)}`
      : `L${number(endX)} ${number(endY)}`;
    return `M${number(l + c[0][0])} ${number(t)} H${number(x - c[1][0])} ` +
      arc(1, x, t + c[1][1]) + ` V${number(y - c[2][1])} ` + arc(2, x - c[2][0], y) +
      ` H${number(l + c[3][0])} ` + arc(3, l, y - c[3][1]) + ` V${number(t + c[0][1])} ` + arc(0, l + c[0][0], t) + ' Z';
  }
  function plumbing(w, h, radii, widths, anchor, kind, inlet) {
    const d = roundedPath(w, h, radii, widths.map(width => width / 2));
    const measure = document.createElementNS('http://www.w3.org/2000/svg', 'path');
    measure.setAttribute('d', d);
    const length = measure.getTotalLength();
    const point = at => measure.getPointAtLength(((at % length) + length) % length);
    function port(target) {
      let best = 0, distance = Infinity;
      const score = at => { const p = point(at); return (p.x - target.x) ** 2 + (p.y - target.y) ** 2; };
      for (let i = 0; i < 256; i++) {
        const at = i * length / 256, candidate = score(at);
        if (candidate < distance) { best = at; distance = candidate; }
      }
      let step = length / 256;
      for (let i = 0; i < 16; i++, step /= 2) {
        for (const at of [best - step, best + step]) if (score(at) < score(best)) best = at;
      }
      best = ((best % length) + length) % length;
      const p = point(best), before = point(best - .5), after = point(best + .5);
      return {x: number(p.x), y: number(p.y), at: number(best / length * 1000),
        angle: number(Math.atan2(after.y - before.y, after.x - before.x) * 180 / Math.PI)};
    }
    const saving = kind === 'saving' || kind === 'export';
    let source = port(inlet || (saving ? {x: w / 2, y: 0} : anchor || {x: w / 2, y: 0}));
    let receiver = port(saving && anchor ? anchor : {x: w / 2, y: h});
    if (Math.hypot(source.x - receiver.x, source.y - receiver.y) < 24) {
      if (saving && anchor) source = port({x: w / 2, y: receiver.y > h / 2 ? 0 : h});
      else receiver = port({x: w / 2, y: source.y > h / 2 ? 0 : h});
    }
    return {d, length, source, receiver, route: (receiver.at - source.at + 1000) % 1000};
  }
  function frameSVG(w, h, radii, widths, colors, charge, elapsed, ports, outcome) {
    const failed = outcome === 'error', partial = outcome === 'warning';
    const [t, r, b, l] = widths;
    const ring = roundedPath(w, h, radii) + ' ' + roundedPath(w, h, radii, widths);
    const maxRadius = Math.max(...radii.flat());
    const seam = Math.min(Math.max(2, maxRadius / Math.min(...widths.filter(Boolean)) + 2),
      w / (l + r || 1) * .45, h / (t + b || 1) * .45);
    const a = l * seam, c = w - r * seam, d = t * seam, e = h - b * seam;
    const faces = [`M0 0 H${w} L${c} ${d} H${a} Z`, `M${w} 0 V${h} L${c} ${e} V${d} Z`,
      `M${w} ${h} H0 L${a} ${e} H${c} Z`, `M0 ${h} V0 L${a} ${d} V${e} Z`];
    const {d: path, source, receiver, route, length} = ports;
    const duration = outcome ? finishMs : (motion.beatMs || 1040) * 2;
    const phase = number((outcome ? Math.min(elapsed, finishMs) : elapsed % duration) / 1000);
    const clock = `dur="${duration}ms" begin="-${phase}s" repeatCount="${outcome ? 1 : 'indefinite'}" fill="freeze"`;
    const animate = (attribute, values, times) => `<animate attributeName="${attribute}" values="${values}" keyTimes="${times}" ${clock}/>`;
    const stroke = Math.max(...widths) * 4 + 4;
    const dash = value => `${number(Math.max(0, value))} ${number(1000 - Math.max(0, value))}`;
    const offset = value => number(-source.at - route * value);
    const routeOpacity = outcome ? animate('opacity', '.16;.3;.3;0', '0;.23;.54;1') : '';
    // A single connected body grows from its inlet, travels along the native seam,
    // and drains into the receiver. The faint channel joins the whole route.
    const bodyTimes = outcome ? '0;.12;.23;.38;1' : '0;.14;.3;.64;.78;.92;1';
    const bodySizes = (outcome ? (partial || failed ? [.12, .2, .14, 0, 0] : [.18, .34, .2, 0, 0]) : [0, 0, .18, .36, .22, 0, 0])
      .map(value => dash(route * value)).join(';');
    const bodyOffsets = (failed ? [.56, .35, .15, 0, 0] : outcome ? [.56, .66, .8, 1, 1] : [0, 0, 0, .42, .78, 1, 1])
      .map(offset).join(';');
    const lobe = 'M-25 0 C-22-3-18-3-15-2 C-13-5-7-5-4-3 C0-6 7-5 9-3 C14-5 21-4 24 0 C21 4 14 5 9 3 C5 6-2 5-5 3 C-11 5-16 4-17 2 C-21 3-24 2-25 0 Z M-9 0 a1.4 1.4 0 1 0 2.8 0 a1.4 1.4 0 1 0-2.8 0 M8 0 a1.1 1.1 0 1 0 2.2 0 a1.1 1.1 0 1 0-2.2 0';
    const splitLobe = 'M-24 0 C-20-4-13-4-10-2 C-7-4-3-3-3 0 C-3 3-9 3-12 2 C-17 4-22 3-24 0 Z M3 0 C3-3 9-3 12-2 C17-4 22-3 24 0 C20 4 13 4 10 2 C7 4 3 3 3 0 Z';
    function seal(role, port, values, times, scales) {
      return `<g data-role="${role}" data-phase="${role === 'source' ? 'source' : failed ? 'drain' : 'receive'}" data-x="${port.x}" data-y="${port.y}" data-length="${port.at}" transform="translate(${port.x} ${port.y}) rotate(${port.angle})">` +
        `<g opacity="${values.split(';')[0]}">${animate('opacity', values, times)}` +
        `<animateTransform attributeName="transform" type="scale" values="${scales}" keyTimes="${times}" ${clock}/>` +
        `<path data-role="${role === 'source' ? 'reservoir' : 'receiver-seal'}" fill="${xml(charge)}" fill-rule="evenodd" d="${failed && role === 'receiver' ? splitLobe : lobe}"/></g></g>`;
    }
    const sourceSeal = outcome
      ? seal('source', source, '.65;.25;0;0', '0;.23;.38;1', '1 1;.75 .7;.55 .5;.55 .5')
      : seal('source', source, '.35;1;.85;.45;.35', '0;.14;.3;.78;1', '.6 .7;1.18 1;1 1;.65 .7;.6 .7');
    const receiverSeal = failed
      ? seal('receiver', receiver, '.3;.5;.45;.3;0', '0;.23;.385;.54;1', '.55 .4;.45 .3;.6 .35;.5 .3;.5 .3')
      : outcome ? seal('receiver', receiver, partial ? '.25;.7;.7;.55;0' : '.25;1;1;1;0', '0;.23;.385;.54;1',
        partial ? '.55 .7;.8 .8;.95 .5;.75 1;1 .65' : '.55 .7;1 1;1.3 .5;.82 1.45;1.5 .65')
      : seal('receiver', receiver, '.25;.25;1;.55;.25', '0;.64;.78;.92;1', '.65 .7;.65 .7;1.15 1;.8 .9;.65 .7');
    const extent = Math.min((partial ? 64 : 180) * 1000 / length, 240);
    const spread = outcome && !failed ? `<path data-role="spread" data-phase="spread" data-extent="${partial ? 'partial' : 'full'}" d="${path}" pathLength="1000" stroke="${xml(charge)}" stroke-width="${stroke}" stroke-linecap="round" stroke-dasharray="0 1000" stroke-dashoffset="${-receiver.at}" opacity="0">` +
      animate('stroke-dasharray', `${dash(0)};${dash(0)};${dash(extent * .65)};${dash(extent)}`, '0;.54;.8;1') +
      animate('stroke-dashoffset', `${-receiver.at};${-receiver.at};${number(-receiver.at + extent * .325)};${number(-receiver.at + extent / 2)}`, '0;.54;.8;1') +
      animate('opacity', '0;0;1;1;0', '0;.54;.62;.8;1') + '</path>' : '';
    return `<svg xmlns="http://www.w3.org/2000/svg" width="${w}" height="${h}" viewBox="0 0 ${w} ${h}" fill="none" data-cycle-ms="${duration}" data-arrival-ms="${outcome ? 180 : number(duration * .78)}" data-outcome="${outcome || ''}">` +
      `<defs><clipPath id="edge"><path d="${ring}" fill-rule="evenodd" clip-rule="evenodd"/></clipPath></defs>` +
      `<g clip-path="url(#edge)">` + faces.map((face, i) => `<path fill="${xml(colors[i])}" d="${face}"/>`).join('') +
      `<path data-role="channel" d="${path}" pathLength="1000" stroke="${xml(charge)}" stroke-width="${stroke}" stroke-dashoffset="${-source.at}" stroke-dasharray="${dash(route)}" opacity=".16">${routeOpacity}</path>` +
      `<path data-role="ribbon" data-phase="${failed ? 'retract' : 'flow'}" d="${path}" pathLength="1000" stroke="${xml(charge)}" stroke-width="${stroke}" stroke-linecap="round" stroke-dashoffset="${offset(0)}" stroke-dasharray="0 1000">` +
      animate('stroke-dasharray', bodySizes, bodyTimes) + animate('stroke-dashoffset', bodyOffsets, bodyTimes) + '</path>' +
      spread + sourceSeal + receiverSeal + '</g></svg>';
  }
  function drawBorder(item) {
    const {panel} = item;
    if (item.borderFailed || typeof SVGAnimateElement === 'undefined') return;
    try {
      const palette = [root.dataset.theme, root.dataset.appearance, root.dataset.themePreset, inkRevision].join('|');
      if (!item.source || item.palette !== palette) {
        // Read the native paint only on entry/palette changes, before replacing it.
        if (panel.classList.contains('am-working-border')) panel.classList.remove('am-working-border');
        const native = getComputedStyle(panel);
        item.source = {colors: ['Top', 'Right', 'Bottom', 'Left'].map(side => native['border' + side + 'Color']),
          charge: motion.energy?.resolve(panel).charge || native.getPropertyValue('--acc').trim() || '#98b7e2'};
        for (const [property, css] of Object.entries(backgroundProperties)) panel.style.setProperty('--am-working-' + property, native[css]);
        item.palette = palette; item.geometry = '';
      }
      const style = getComputedStyle(panel), w = panel.offsetWidth, h = panel.offsetHeight;
      const widths = ['Top', 'Right', 'Bottom', 'Left'].map(side => parseFloat(style['border' + side + 'Width']) || 0);
      if (!widths.some(Boolean)) { stopBorder(item); return; }
      const anchor = item.finish?.anchor || captureAnchor(item.anchor, panel) || item.anchorPoint;
      const radii = corners(style, w, h), geometry = JSON.stringify([w, h, radii, widths, item.kind,
        anchor, item.inlet, item.finish?.started, item.finish?.outcome]);
      if (geometry !== item.geometry) {
        const ports = item.finish?.ports && item.finish.size === `${w}:${h}` ? item.finish.ports :
          plumbing(w, h, radii, widths, anchor, item.kind, item.inlet);
        item.ports = ports;
        const svg = frameSVG(w, h, radii, widths, item.source.colors, item.source.charge,
          performance.now() - (item.finish?.started || item.started), ports, item.finish?.outcome);
        // This is the panel's background at border-box origin. The SVG is transparent
        // everywhere except the native border band, including clipped/scrolling panels.
        panel.style.setProperty('--am-working-frame', `url("data:image/svg+xml,${encodeURIComponent(svg)}")`);
        item.geometry = geometry;
      }
      panel.setAttribute('data-am-working-state', item.kind);
      const age = item.finish ? performance.now() - item.finish.started : 0;
      panel.setAttribute('data-am-working-phase', !item.finish ? 'working' :
        item.finish.outcome === 'error' ? (age < 300 ? 'retract' : age < 420 ? 'drain' : 'settle') :
        age < 180 ? 'receive' : age < 300 ? 'press' : age < 420 ? 'rebound' : 'spread');
      if (item.finish) panel.setAttribute('data-am-working-outcome', item.finish.outcome);
      else panel.removeAttribute('data-am-working-outcome');
      if (!panel.classList.contains('am-working-border')) panel.classList.add('am-working-border');
    } catch (_) { item.borderFailed = true; stopBorder(item); }
  }
  function sync() {
    const automatic = new Set();
    // Set by actual request/job controllers, never inferred from disabled buttons.
    for (const node of document.querySelectorAll('.modal[aria-busy="true"], #grid-area[aria-busy="true"], #viewport-stage canvas[aria-busy="true"]')) {
      automatic.add(node.id === 'grid-area' ? document.getElementById('explorer') : node.closest('#viewport-box') || node);
    }
    for (const node of document.querySelectorAll('[data-atelier-motion="viewport-loader"][data-am-state="loading"], .prog-krackle-stage[data-am-state="busy"]')) {
      automatic.add(node.closest('#viewport-box, #prog-box'));
    }
    for (const node of document.querySelectorAll('.job-state-glyph[data-am-state="busy"]')) automatic.add(node.closest('.modal'));
    for (const panel of automatic) if (panel) entry(panel);
    let front = null, top = -Infinity;
    for (const overlay of document.querySelectorAll('.overlay.active')) {
      if (!overlay.getClientRects().length) continue;
      const z = Number(getComputedStyle(overlay).zIndex) || 0;
      if (z >= top) { top = z; front = overlay; }
    }
    let count = 0;
    for (const item of entries.values()) {
      for (const lease of item.leases) if (!current(lease)) item.leases.delete(lease);
      const leases = [...item.leases], busy = leases.length || automatic.has(item.panel);
      const allowed = window.AtelierMotionPolicy?.allows(2) === true;
      // Confirmed handoffs outlive the intentionally closed source editor. The
      // source request guard was checked by end(), before ownership transferred.
      if (!busy && item.pending?.destination && item.pending.destination !== item.panel) {
        const result = item.pending, destination = result.destination;
        item.pending = null;
        if (destination.isConnected && allowed) {
          const receiver = entry(destination);
          if (!receiver.pending && !receiver.finish) {
            receiver.kind = result.kind || item.kind;
            receiver.pending = {...result, destination: null, waitUntil: performance.now() + 1200,
              anchor: captureAnchor(result.destinationAnchor, destination), ports: null, size: null};
            receiver.timers.push(setTimeout(schedule, 1205));
            schedule();
          }
        }
      }
      if (!item.panel.isConnected) { remove(item); continue; }
      const onScreen = visible(item.panel, front);
      if (!busy && item.pending && !item.cancelled && allowed && !item.finish) {
        if (onScreen) {
          if (item.pending.destinationAnchor)
            item.pending.anchor = captureAnchor(item.pending.destinationAnchor, item.panel) || item.pending.anchor;
          item.finish = {...item.pending, started: performance.now()};
          item.pending = null; clearTimers(item);
          for (const delay of [180, 300, 420, finishMs]) item.timers.push(setTimeout(schedule, delay + 2));
        } else if (!item.pending.waitUntil || performance.now() >= item.pending.waitUntil) {
          remove(item); continue;
        }
      }
      if (item.finish && (!onScreen || !allowed || performance.now() - item.finish.started >= finishMs)) {
        remove(item); continue;
      }
      if (!busy && !item.finish && (!item.pending || item.cancelled || !allowed)) { remove(item); continue; }
      const active = (busy || item.finish) && onScreen;
      const save = active && leases.find(lease => lease.kind === 'saving' && lease.anchor?.isConnected);
      if (save) item.saveAnchor = save.anchor;
      const retainedSave = active && item.finish && item.kind === 'saving' && item.badge && item.saveAnchor?.isConnected;
      if (busy && (leases.length || !item.pending)) {
        item.kind = leases.some(lease => lease.kind === 'saving') ? 'saving' :
          leases.some(lease => /export|install|build/.test(lease.kind || '')) ||
          item.panel.querySelector('.job-state-glyph[data-am-state="busy"]') ||
          item.panel.classList.contains('export-review-modal') ? 'export' :
          leases.some(lease => lease.kind === 'configuration') ? 'configuration' : 'loading';
        item.anchor = (save || leases.find(lease => lease.anchor))?.anchor;
        item.anchorPoint = captureAnchor(item.anchor, item.panel) || item.anchorPoint;
      } else if (busy && item.pending) item.kind = item.pending.kind;
      if ((save || retainedSave) && !item.badgeFailed && window.AtelierMotionPolicy?.allows(1) !== false && motion.materialSave) {
        if (!item.badge) {
          item.badge = document.createElement('span'); item.badge.className = 'am-working-save';
          item.badge.setAttribute('aria-hidden', 'true');
          const host = document.createElement('span'); item.badge.append(host); save.anchor.before(item.badge);
          try { item.glyph = motion.materialSave.mount(host, {state: 'saving'}); item.glyphState = 'saving'; }
          catch (_) { item.badgeFailed = true; stopBadge(item); }
        }
      } else stopBadge(item);
      if (item.badge) {
        item.badge.style.color = motion.energy?.resolve(item.badge).charge || '';
        const glyphState = item.finish?.outcome || 'saving';
        if (item.glyphState !== glyphState) { item.glyph?.setState(glyphState); item.glyphState = glyphState; }
        if (allowed) drawDock(item, item.saveAnchor);
        else { item.dock?.remove(); item.dock = null; item.dockGeometry = ''; item.inlet = null; }
      }
      if (active && allowed && count++ < 4) drawBorder(item);
      else stopBorder(item);
    }
  }
  const observer = new MutationObserver(schedule);
  observer.observe(document.documentElement, {subtree: true, childList: true, attributes: true,
    attributeFilter: ['aria-busy', 'class', 'hidden', 'data-am-state', 'data-theme', 'data-krackle']});
  document.addEventListener('visibilitychange', schedule);
  query?.addEventListener('change', schedule);
  window.addEventListener('resize', schedule, {passive: true});
  const inksChanged = () => { inkRevision++; schedule(); };
  window.addEventListener('atelier:inks', inksChanged);
  window.addEventListener('atelier:energy', inksChanged);
  window.addEventListener('pagehide', () => {
    disposed = true; observer.disconnect(); resize.disconnect(); intersection.disconnect();
    for (const item of [...entries.values()]) remove(item);
    document.removeEventListener('visibilitychange', schedule); query?.removeEventListener('change', schedule);
    window.removeEventListener('resize', schedule);
    window.removeEventListener('atelier:inks', inksChanged);
    window.removeEventListener('atelier:energy', inksChanged);
  }, {once: true});
  motion.working = Object.freeze({
    begin(panel, options = {}) {
      if (!panel || disposed) return () => {};
      const item = entry(panel), lease = {...options};
      if (!item.leases.size) {
        if (item.finish) item.started = performance.now();
        item.finish = null; item.pending = null; item.cancelled = false; clearTimers(item);
      }
      item.kind = options.kind || item.kind || 'loading';
      item.leases.add(lease); schedule();
      let stopped = false;
      return (outcome = 'cancel', finishOptions = {}) => {
        if (stopped) return;
        stopped = true;
        const valid = item.leases.has(lease) && current(lease);
        item.leases.delete(lease);
        if (!valid || disposed || entries.get(panel) !== item) { schedule(); return; }
        if (!accepted.has(outcome)) { item.cancelled = true; item.pending = null; }
        else if (!item.cancelled) {
          const priority = {success: 1, warning: 2, error: 3};
          if (!item.pending || priority[outcome] >= priority[item.pending.outcome]) {
            item.pending = {outcome, kind: lease.kind || item.kind,
              anchor: captureAnchor(lease.anchor, panel) || item.anchorPoint,
              ports: item.ports, size: `${panel.offsetWidth}:${panel.offsetHeight}`,
              destination: finishOptions.destination, destinationAnchor: finishOptions.anchor};
          }
        }
        schedule();
      };
    }
  });
  schedule();
})();

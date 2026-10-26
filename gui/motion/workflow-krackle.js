// Finite SVG gestures follow the owning surface's border after its action commits.
(() => {
  'use strict';
  const NS = 'http://www.w3.org/2000/svg', active = new Map();
  // Four gestures, one meaning each: something arrived, you moved, you
  // committed, you undid. Older call names stay as aliases of their gesture.
  const durations = {arrive: 720, trace: 620, seal: 560, release: 500};
  const gestures = {arrive: 'arrive', hero: 'arrive', arrival: 'arrive', editor: 'arrive',
    panel: 'arrive', workspace: 'arrive', project: 'arrive', trace: 'trace', navigation: 'trace',
    seal: 'seal', action: 'seal', selection: 'seal', pin: 'seal', release: 'release', unpin: 'release'};
  const wide = new Set(['trace', 'navigation', 'editor', 'workspace', 'panel']);
  let serial = 0;
  const clamp = n => Math.max(0, Math.min(1, n));
  const ease = n => 1 - (1 - clamp(n)) ** 3;
  const mode = () => window.AtelierMotionPolicy?.mode() || 'off';
  const svgNode = (name, attrs = {}) => {
    const node = document.createElementNS(NS, name);
    for (const [key, value] of Object.entries(attrs)) node.setAttribute(key, value);
    return node;
  };
  function palette(host) {
    const resolved = window.AtelierMotion?.energy?.resolve(host);
    const accent = getComputedStyle(host).getPropertyValue('--acc').trim() || 'currentColor';
    return resolved || {charge: accent, rift: accent, source: 'theme'};
  }
  function bounds(host, entering = false) {
    if (!host?.isConnected || !host.getClientRects().length) return null;
    const style = getComputedStyle(host);
    if (style.visibility !== 'visible' || !entering && Number(style.opacity) === 0) return null;
    const box = host.getBoundingClientRect();
    let left = Math.max(0, box.left), top = Math.max(0, box.top);
    let right = Math.min(innerWidth, box.right), bottom = Math.min(innerHeight, box.bottom);
    for (let parent = host.parentElement; parent; parent = parent.parentElement) {
      const css = getComputedStyle(parent), rect = parent.getBoundingClientRect();
      if (css.visibility !== 'visible' || !entering && Number(css.opacity) === 0) return null;
      if (/(auto|scroll|hidden|clip)/.test(css.overflowX)) { left = Math.max(left, rect.left); right = Math.min(right, rect.right); }
      if (/(auto|scroll|hidden|clip)/.test(css.overflowY)) { top = Math.max(top, rect.top); bottom = Math.min(bottom, rect.bottom); }
    }
    return right - left > 4 && bottom - top > 4 ? {box, left, top, right, bottom} : null;
  }
  function permitted(host) {
    return !document.hidden && mode() !== 'off'
      && [...document.querySelectorAll('.overlay.active,dialog[open]')].every(overlay => overlay.contains(host));
  }
  function stop() { for (const dispose of [...active.values()]) dispose(); }

  // Capture an actual initiating control, never a guessed point in the viewport.
  let origin = null;
  const remember = event => {
    if (event.type === 'keydown' && !['Enter', ' '].includes(event.key)) return;
    const host = event.target.closest?.('button,a,[role=button],.card,.sb-item');
    origin = host ? {host, time: performance.now()} : null;
  };
  document.addEventListener('pointerdown', remember, {capture: true, passive: true});
  document.addEventListener('keydown', remember, true);
  const linkedKinds = new Set(['navigation', 'editor', 'project', 'selection']);

  function connection(source, destination, colors) {
    if (!source || source === destination || source.contains(destination) || destination.contains(source)) return null;
    const first = bounds(source), last = bounds(destination);
    if (!first || !last) return null;
    const a = first.box, b = last.box;
    if (a.left < b.right && a.right > b.left && a.top < b.bottom && a.bottom > b.top) return null;
    const ac = {x: a.left + a.width / 2, y: a.top + a.height / 2};
    const bc = {x: b.left + b.width / 2, y: b.top + b.height / 2};
    const separatedX = a.right <= b.left || b.right <= a.left;
    const separatedY = a.bottom <= b.top || b.bottom <= a.top;
    const horizontal = separatedX && (!separatedY || Math.abs(bc.x - ac.x) > Math.abs(bc.y - ac.y));
    const forward = horizontal ? bc.x > ac.x : bc.y > ac.y, sign = forward ? 1 : -1;
    const start = horizontal ? {x: forward ? a.right - 1 : a.left + 1, y: ac.y}
      : {x: ac.x, y: forward ? a.bottom - 1 : a.top + 1};
    const end = horizontal ? {x: forward ? b.left + 1 : b.right - 1, y: bc.y}
      : {x: bc.x, y: forward ? b.top + 1 : b.bottom - 1};
    const distance = Math.hypot(end.x - start.x, end.y - start.y);
    const reach = Math.min(180, distance * .24), bow = Math.min(24, distance * .08);
    const middle = {x: (start.x + end.x) / 2 + (horizontal ? 0 : bow),
      y: (start.y + end.y) / 2 - (horizontal ? bow : 0)};
    const along = (point, amount) => ({x: point.x + (horizontal ? amount * sign : 0),
      y: point.y + (horizontal ? 0 : amount * sign)});
    // Two joined cubics leave and enter normal to their measured surface edges.
    const world = [start, along(start, reach), along(middle, -reach * .6), middle,
      along(middle, reach * .6), along(end, -reach), end];
    const left = Math.max(0, Math.min(...world.map(p => p.x)) - 12);
    const top = Math.max(0, Math.min(...world.map(p => p.y)) - 12);
    const w = Math.min(innerWidth, Math.max(...world.map(p => p.x)) + 12) - left;
    const h = Math.min(innerHeight, Math.max(...world.map(p => p.y)) + 12) - top;
    if (w <= 0 || h <= 0) return null;
    const points = world.map(p => ({x: p.x - left, y: p.y - top}));
    const [p0, p1, p2, p3, p4, p5, p6] = points;
    const pair = p => p.x.toFixed(2) + ' ' + p.y.toFixed(2);
    const d = 'M ' + pair(p0) + ' C ' + [p1,p2,p3].map(pair).join(' ')
      + ' C ' + [p4,p5,p6].map(pair).join(' ');
    const chargeMs = 120, travelMs = 440, arrivalMs = chargeMs + travelMs;
    const svg = svgNode('svg', {class: 'k-workflow-link', 'aria-hidden': 'true', focusable: 'false',
      width: w, height: h, viewBox: `0 0 ${w} ${h}`, 'data-phase': 'source',
      'data-charge-ms': chargeMs, 'data-travel-ms': travelMs, 'data-arrival-ms': arrivalMs,
      'data-source-x': start.x, 'data-source-y': start.y, 'data-destination-x': end.x, 'data-destination-y': end.y});
    svg.inert = true;
    Object.assign(svg.style, {left: left + 'px', top: top + 'px', width: w + 'px', height: h + 'px'});
    const id = 'k-workflow-link-' + ++serial;
    const defs = svgNode('defs'), mask = svgNode('mask', {id, maskUnits: 'userSpaceOnUse',
      x: 0, y: 0, width: w, height: h, 'mask-type': 'luminance'});
    mask.append(svgNode('rect', {width: w, height: h, fill: 'white'}));
    for (const box of [a, b]) {
      const inset = Math.min(6, Math.max(3, Math.min(box.width, box.height) * .12));
      mask.append(svgNode('rect', {x: box.left - left + inset, y: box.top - top + inset,
        width: Math.max(0, box.width - inset * 2), height: Math.max(0, box.height - inset * 2), fill: 'black'}));
    }
    const shield = box => {
      if (box.right <= left || box.left >= left + w || box.bottom <= top || box.top >= top + h) return;
      mask.append(svgNode('rect', {x: box.left - left - 1, y: box.top - top - 1,
        width: box.width + 2, height: box.height + 2, fill: 'black'}));
    };
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT), range = document.createRange();
    for (let text = walker.nextNode(); text; text = walker.nextNode()) {
      const parent = text.parentElement;
      if (!text.textContent.trim() || !parent?.getClientRects().length || parent.closest('script,style,svg')) continue;
      range.selectNodeContents(text); for (const line of range.getClientRects()) shield(line);
    }
    for (const node of document.querySelectorAll('img,video,canvas,input,select,textarea,svg.studio-icon,[data-swatch-color]'))
      if (node.getClientRects().length) shield(node.getBoundingClientRect());
    const sourceClip = svgNode('clipPath', {id: id + '-source', clipPathUnits: 'userSpaceOnUse'});
    sourceClip.append(svgNode('rect', {x: a.left - left, y: a.top - top, width: a.width, height: a.height,
      rx: Math.min(parseFloat(getComputedStyle(source).borderTopLeftRadius) || 0, a.width / 2, a.height / 2)}));
    defs.append(mask, sourceClip); svg.append(defs);
    const drawing = svgNode('g', {mask: `url(#${id})`});
    const angle = horizontal ? (forward ? 0 : 180) : (forward ? 90 : -90);
    const reservoir = svgNode('path', {
      d: 'M 0 -7 Q -2 -10 -4 -7 Q -7 -8 -5 -3 Q -8 0 -5 3 Q -7 8 -3.5 7 Q -1 10 0 6 Q 2 2 0 -7 Z '
        + 'M -4 -3 a 1.1 1.1 0 1 0 2.2 0 a 1.1 1.1 0 1 0 -2.2 0 Z '
        + 'M -4.4 3 a .9 .9 0 1 0 1.8 0 a .9 .9 0 1 0 -1.8 0 Z',
      fill: colors.charge, 'fill-rule': 'evenodd', opacity: 0, 'data-flow-role': 'reservoir'});
    const intake = svgNode('g', {'clip-path': `url(#${id}-source)`});
    intake.append(reservoir);
    const channel = svgNode('path', {d, fill: 'none', stroke: colors.charge, 'stroke-width': 3.2,
      'stroke-linejoin': 'round', 'stroke-linecap': 'round', pathLength: 1,
      'stroke-dasharray': '1 1', 'stroke-dashoffset': 1, opacity: 0, 'data-flow-role': 'channel'});
    const ribbon = svgNode('path', {fill: colors.charge, 'fill-rule': 'evenodd', opacity: 0,
      'data-flow-role': 'ribbon', 'data-max-width': 11.6});
    drawing.append(intake, channel, ribbon); svg.append(drawing);

    // Sample curve length once, so the thick fluid body travels at a readable
    // pace through both bends rather than accelerating at a cubic's control points.
    function cubic(t) {
      const second = t > .5, u = second ? (t - .5) * 2 : t * 2, v = 1 - u;
      const q = second ? [p3,p4,p5,p6] : [p0,p1,p2,p3];
      return {x: v**3*q[0].x + 3*v*v*u*q[1].x + 3*v*u*u*q[2].x + u**3*q[3].x,
        y: v**3*q[0].y + 3*v*v*u*q[1].y + 3*v*u*u*q[2].y + u**3*q[3].y};
    }
    const table = [{...p0, length: 0}];
    for (let i = 1; i <= 96; i++) {
      const point = cubic(i / 96), previous = table[i - 1];
      table.push({...point, length: previous.length + Math.hypot(point.x - previous.x, point.y - previous.y)});
    }
    const totalLength = table[96].length;
    function sample(progress) {
      const length = clamp(progress) * totalLength;
      let index = 1;
      while (index < 96 && table[index].length < length) index++;
      const before = table[index - 1], after = table[index], span = after.length - before.length || 1;
      const fraction = (length - before.length) / span, dx = (after.x - before.x) / span, dy = (after.y - before.y) / span;
      return {x: before.x + (after.x - before.x) * fraction, y: before.y + (after.y - before.y) * fraction, dx, dy};
    }
    function outline(outlinePoints) {
      let path = 'M ' + pair(outlinePoints[0]);
      for (let i = 0; i < outlinePoints.length; i++) {
        const a = outlinePoints[(i + outlinePoints.length - 1) % outlinePoints.length], b = outlinePoints[i];
        const c = outlinePoints[(i + 1) % outlinePoints.length], d = outlinePoints[(i + 2) % outlinePoints.length];
        path += ` C ${b.x + (c.x-a.x)/6} ${b.y + (c.y-a.y)/6} ${c.x - (d.x-b.x)/6} ${c.y - (d.y-b.y)/6} ${c.x} ${c.y}`;
      }
      return path + ' Z';
    }
    function fluid(head, tail, radius) {
      const upper = [], lower = [];
      for (let i = 0; i <= 14; i++) {
        const u = i / 14, point = sample(tail + (head - tail) * u);
        const breadth = radius * (.14 + .86 * Math.sin(u * Math.PI / 2));
        upper.push({x: point.x - point.dy * breadth, y: point.y + point.dx * breadth});
        lower.push({x: point.x + point.dy * breadth, y: point.y - point.dx * breadth});
      }
      const front = sample(head), rear = sample(tail);
      let path = outline([...upper, {x:front.x + front.dx * radius, y:front.y + front.dy * radius},
        ...lower.reverse(), {x:rear.x - rear.dx * radius * .14, y:rear.y - rear.dy * radius * .14}]);
      // Punched pockets travel inside the connected fluid body.
      if ((head - tail) * totalLength > 24) for (const [fraction, hole] of [[.74,1.15],[.48,.8]]) {
        const point = sample(tail + (head - tail) * fraction);
        path += ` M ${point.x-hole} ${point.y} a ${hole} ${hole} 0 1 0 ${hole*2} 0 a ${hole} ${hole} 0 1 0 ${-hole*2} 0 Z`;
      }
      return path;
    }
    return {svg, arrivalMs, receiver: {x: end.x - b.left, y: end.y - b.top, angle: angle + 90,
      side: horizontal ? (forward ? 'left' : 'right') : (forward ? 'top' : 'bottom')},
      recolor: next => { reservoir.setAttribute('fill', next.charge); channel.setAttribute('stroke', next.charge); ribbon.setAttribute('fill', next.charge); },
      valid: () => {
        const current = bounds(source);
        return !!current && Math.abs(current.box.left - a.left) < 1 && Math.abs(current.box.top - a.top) < 1
          && Math.abs(current.box.width - a.width) < 1 && Math.abs(current.box.height - a.height) < 1;
      },
      draw: elapsed => {
        const charge = clamp(elapsed / chargeMs), age = clamp((elapsed - chargeMs) / travelMs);
        const travel = .5 - Math.cos(Math.PI * age) / 2;
        const drain = clamp((elapsed - arrivalMs) / 120);
        const phase = elapsed < chargeMs ? 'source' : elapsed < arrivalMs ? 'flow' : elapsed < arrivalMs + 220 ? 'impact' : 'settle';
        svg.dataset.phase = phase;
        const pressure = .55 + ease(charge) * .55;
        reservoir.setAttribute('transform', `translate(${p0.x} ${p0.y}) rotate(${angle}) scale(${pressure} ${.7 + ease(charge)*.4})`);
        reservoir.setAttribute('opacity', ease(charge / .35) * (1 - ease((elapsed-chargeMs) / 150)) * .98);
        channel.setAttribute('stroke-dashoffset', 1 - travel);
        channel.setAttribute('opacity', elapsed >= chargeMs ? (1 - drain) * .24 : 0);
        const radius = (4.7 + Math.sin(Math.PI * age) * 1.1) * (1 - drain * .7);
        const tail = Math.max(0, travel - .28 * (1 - drain));
        ribbon.setAttribute('d', fluid(travel, tail, radius));
        ribbon.setAttribute('opacity', elapsed >= chargeMs ? (1 - drain) * .98 : 0);
        return phase;
      }};
  }

  function run(trigger, host, direction, source) {
    const kind = gestures[trigger];
    if (!kind || !host || !permitted(host)) return false;
    const initial = bounds(host);
    if (!initial) return false;
    active.get(host)?.();
    while (active.size >= 3) active.values().next().value();
    const colors = palette(host);
    if (mode() === 'calm') {
      if (typeof host.animate !== 'function') return false;
      const resting = getComputedStyle(host).boxShadow;
      const animation = host.animate([{boxShadow: resting},
        {boxShadow: `inset 0 -1px 0 ${colors.charge}`, offset: .35}, {boxShadow: resting}],
      {duration: 160, easing: 'ease-out'});
      let disposed = false;
      const dispose = () => {
        if (disposed) return;
        disposed = true; animation.cancel(); clearTimeout(timer);
        if (active.get(host) === dispose) active.delete(host);
      };
      const timer = setTimeout(dispose, 200);
      active.set(host, dispose); animation.finished.then(dispose, dispose);
      return true;
    }

    const {width: w, height: h} = initial.box;
    const id = 'k-workflow-' + ++serial;
    const radius = Math.min(parseFloat(getComputedStyle(host).borderTopLeftRadius) || 0, w / 2, h / 2);
    const band = Math.min(6, Math.max(3, Math.min(w, h) * .12));
    const svg = svgNode('svg', {class: 'k-workflow-svg', 'aria-hidden': 'true', focusable: 'false',
      viewBox: `0 0 ${w} ${h}`, width: w, height: h, 'data-workflow-kind': kind,
      'data-workflow-trigger': trigger, 'data-edge-band': band});
    svg.inert = true;
    Object.assign(svg.style, {position: 'fixed', width: w + 'px', height: h + 'px',
      overflow: 'hidden', pointerEvents: 'none'});
    const defs = svgNode('defs');
    const clip = svgNode('clipPath', {id: id + '-bounds', clipPathUnits: 'userSpaceOnUse'});
    clip.append(svgNode('rect', {width: w, height: h, rx: radius}));
    const viewport = svgNode('clipPath', {id: id + '-visible', clipPathUnits: 'userSpaceOnUse'});
    const viewportRect = svgNode('rect'); viewport.append(viewportRect);
    const mask = svgNode('mask', {id: id + '-edge', maskUnits: 'userSpaceOnUse',
      x: 0, y: 0, width: w, height: h, 'mask-type': 'luminance'});
    mask.append(svgNode('rect', {width: w, height: h, rx: radius, fill: 'white'}),
      svgNode('rect', {x: band, y: band, width: Math.max(0, w - band * 2),
        height: Math.max(0, h - band * 2), rx: Math.max(0, radius - band), fill: 'black'}));
    const protection = svgNode('g', {fill: 'black', 'data-content-protection': ''}); mask.append(protection);
    defs.append(clip, viewport, mask); svg.append(defs);
    const boundary = svgNode('g', {'clip-path': `url(#${id}-bounds)`});
    const visible = svgNode('g', {'clip-path': `url(#${id}-visible)`});
    const drawing = svgNode('g', {mask: `url(#${id}-edge)`});
    boundary.append(visible); visible.append(drawing); svg.append(boundary);
    const strokes = [], seals = [];
    // All coordinates sit within the viewport, including wide header seams.
    const inset = 1.2, l = inset, r = w - inset, t = inset, b = h - inset;
    const cx = w / 2, turn =Math.min(Math.max(radius, 3), w / 4, h / 4);
    const leftBottom = `L ${l + turn} ${b} Q ${l} ${b} ${l} ${b - turn}`;
    const rightBottom = `L ${r - turn} ${b} Q ${r} ${b} ${r} ${b - turn}`;
    function stroke(d, delay = 0, role = 'charge', width = 2.2, reverse = false) {
      const path = svgNode('path', {d, fill: 'none', stroke: colors[role], 'stroke-width': width,
        'stroke-linecap': 'round', 'stroke-linejoin': 'round', pathLength: 1,
        'stroke-dasharray': '1 1', 'stroke-dashoffset': 1, opacity: 0, 'data-ink': role});
      drawing.append(path); strokes.push({path, delay, reverse});
      return path;
    }
    // Paired scallops are part of the seam, never detached particles.
    function seal(x, y, horizontal = true, delay = .22) {
      const size = Math.min(2.4, band * .43);
      stroke(horizontal
        ? `M ${x - 6} ${y} q 2 ${-size} 4 0 t 4 0 t 4 0`
        : `M ${x} ${y - 6} q ${-size} 2 0 4 t 0 4 t 0 4`, delay, 'rift', 1.5);
    }
    function inkSeal(x, y, angle = 0, delay = .24) {
      // One connected ink mass, with two true punched holes; its flat edge
      // sits on the border and its lobes stay inside the protected edge band.
      const size = Math.min(1, band / 5.8);
      const d = 'M -6 0 Q -7 -2 -4 -2.4 Q -4 -5.2 -1.2 -3.3 Q 1 -5 2.8 -2.5 Q 6 -3.7 6 0 Z '
        + 'M -2.9 -2.5 a .7 .7 0 1 0 1.4 0 a .7 .7 0 1 0 -1.4 0 Z '
        + 'M 1.9 -1.8 a .65 .65 0 1 0 1.3 0 a .65 .65 0 1 0 -1.3 0 Z';
      const path = svgNode('path', {d, fill: colors.charge, 'fill-rule': 'evenodd',
        transform: `translate(${x} ${y}) rotate(${angle}) scale(${size})`, opacity: 0,
        'data-ink': 'charge', 'data-ink-seal': ''});
      drawing.append(path); seals.push({path, delay});
    }
    if (kind === 'arrive') {
      // Arrive: rails leave a lower seal, turn both corners and rise to greet
      // the surface; tall panels cap the rise so it stays a gesture.
      const rise = b - Math.min((b - t) * .38, 86);
      stroke(`M ${cx - 3} ${b} ${leftBottom} L ${l} ${rise}`, 0);
      stroke(`M ${cx + 3} ${b} ${rightBottom} L ${r} ${rise}`, .045);
      seal(cx, b);
      inkSeal(cx, b);
    } else if (kind === 'trace') {
      // Trace: a directional seam closes behind a short offset return stitch.
      const back = direction === 'back', from = back ? r : l, to = back ? l : r;
      stroke(`M ${from} ${b} L ${to} ${b}`, 0, 'charge', 2.5);
      stroke(`M ${from + (to - from) * .24} ${b - 2.7} L ${from + (to - from) * .67} ${b - 2.7}`, .11, 'rift', 1.1);
      inkSeal(back ? l + 9 : r - 9, b, 0, .34);
    } else {
      // Seal: two jaws close on a lower clasp. Release unwinds the same jaws
      // into the clasp, so undoing reads as the reverse of committing.
      const release = kind === 'release', rise = b - Math.min((b - t) * .5, 28);
      stroke(`M ${l} ${rise} L ${l} ${b - turn} Q ${l} ${b} ${l + turn} ${b} L ${cx - 4} ${b}`, 0, 'charge', 2.4, release);
      stroke(`M ${r} ${rise} L ${r} ${b - turn} Q ${r} ${b} ${r - turn} ${b} L ${cx + 4} ${b}`, .06, 'rift', 1.8, release);
      if (!release) seal(cx, b, true, .26);
      inkSeal(cx, b, 0, release ? 0 : .28);
    }

    // Native clipping contains ink. Additional cutouts protect real labels,
    // controls and artwork when their content reaches into the border lane.
    function protect(box, origin, margin = 0) {
      if (box.width <= 0 || box.height <= 0) return;
      const x = box.left - origin.left - margin, y = box.top - origin.top - margin;
      if (x >= band && y >= band && x + box.width + margin * 2 <= w - band && y + box.height + margin * 2 <= h - band) return;
      protection.append(svgNode('rect', {x, y, width: box.width + margin * 2, height: box.height + margin * 2}));
    }
    function updateProtection(box) {
      protection.replaceChildren();
      const walker = document.createTreeWalker(host, NodeFilter.SHOW_TEXT), range = document.createRange();
      for (let text = walker.nextNode(); text; text = walker.nextNode()) {
        if (!text.textContent.trim() || !text.parentElement?.getClientRects().length) continue;
        range.selectNodeContents(text);
        for (const line of range.getClientRects()) protect(line, box, 1);
      }
      for (const node of host.querySelectorAll('img,video,canvas,svg,input,textarea,select,[data-swatch-color]'))
        if (node.getClientRects().length) protect(node.getBoundingClientRect(), box);
    }
    updateProtection(initial.box);
    const link = connection(source, host, colors);
    let receiver;
    if (link) {
      const entry = link.receiver;
      svg.dataset.arrivalMs = link.arrivalMs;
      svg.dataset.phase = 'source';
      receiver = svgNode('path', {
        d: 'M -10 0 Q -11 -2 -7 -2.8 Q -7 -5.5 -3 -3.8 Q 0 -6 3 -3.6 Q 7 -5.8 7 -2.5 Q 11 -2 10 0 Z '
          + 'M -5 -2.7 a 1 1 0 1 0 2 0 a 1 1 0 1 0 -2 0 Z '
          + 'M 2.5 -2.5 a .9 .9 0 1 0 1.8 0 a .9 .9 0 1 0 -1.8 0 Z',
        fill: colors.charge, 'fill-rule': 'evenodd', opacity: 0,
        'data-flow-role': 'receiver', 'data-ink': 'charge', 'data-impact-state': 'waiting'});
      drawing.append(receiver);
      // Split the arriving ink at its exact entry point and carry it around
      // both neighbouring corners, beneath the same content and edge masks.
      const x = entry.x, y = entry.y, reachX = Math.min(w * .5, 140), reachY = Math.min(h * .5, 100);
      let paths;
      if (entry.side === 'left') paths = [
        `M ${l} ${y} L ${l} ${t+turn} Q ${l} ${t} ${l+turn} ${t} L ${reachX} ${t}`,
        `M ${l} ${y} L ${l} ${b-turn} Q ${l} ${b} ${l+turn} ${b} L ${reachX} ${b}`];
      else if (entry.side === 'right') paths = [
        `M ${r} ${y} L ${r} ${t+turn} Q ${r} ${t} ${r-turn} ${t} L ${w-reachX} ${t}`,
        `M ${r} ${y} L ${r} ${b-turn} Q ${r} ${b} ${r-turn} ${b} L ${w-reachX} ${b}`];
      else if (entry.side === 'top') paths = [
        `M ${x} ${t} L ${l+turn} ${t} Q ${l} ${t} ${l} ${t+turn} L ${l} ${reachY}`,
        `M ${x} ${t} L ${r-turn} ${t} Q ${r} ${t} ${r} ${t+turn} L ${r} ${reachY}`];
      else paths = [
        `M ${x} ${b} L ${l+turn} ${b} Q ${l} ${b} ${l} ${b-turn} L ${l} ${h-reachY}`,
        `M ${x} ${b} L ${r-turn} ${b} Q ${r} ${b} ${r} ${b-turn} L ${r} ${h-reachY}`];
      for (const path of paths) stroke(path, 0, 'charge', 4.4).dataset.flowRole = 'border-spread';
    }
    const release = wide.has(trigger) || link ? window.AtelierMotion?.moment?.claim('workflow-' + kind, 2) : () => {};
    if (!release) return false;
    let frame = 0, start = null, disposed = false, dirty = false, timer;
    const dispose = () => {
      if (disposed) return;
      disposed = true; cancelAnimationFrame(frame); clearTimeout(timer); svg.remove(); link?.svg.remove();
      if (active.get(host) === dispose) active.delete(host);
      release();
    };
    dispose.invalidate = () => { dirty = true; };
    dispose.emitted = false;
    dispose.connected = () => !link || link.valid();
    dispose.recolor = () => {
      const next = palette(host); svg.dataset.energySource = next.source || 'theme';
      for (const {path} of strokes) path.setAttribute('stroke', next[path.dataset.ink]);
      for (const {path} of seals) path.setAttribute('fill', next.charge);
      receiver?.setAttribute('fill', next.charge);
      link?.recolor(next);
    };
    function position(current) {
      svg.style.left = current.box.left + 'px'; svg.style.top = current.box.top + 'px';
      viewportRect.setAttribute('x', current.left - current.box.left);
      viewportRect.setAttribute('y', current.top - current.box.top);
      viewportRect.setAttribute('width', current.right - current.left);
      viewportRect.setAttribute('height', current.bottom - current.top);
    }
    active.set(host, dispose);
    try { position(initial); dispose.recolor(); if (link) document.body.append(link.svg); document.body.append(svg); }
    catch (error) { dispose(); throw error; }
    function tick(now) {
      const current = bounds(host);
      if (!permitted(host) || !current || mode() !== 'full' || !dispose.connected()
        || link && (Math.abs(current.box.left - initial.box.left) > 1 || Math.abs(current.box.top - initial.box.top) > 1)
        || Math.abs(current.box.width - w) > 1 || Math.abs(current.box.height - h) > 1) { dispose(); return; }
      try {
        position(current);
        if (dirty) { updateProtection(current.box); dirty = false; }
        if (start === null) start = now;
        const elapsed = now - start, lead = link ? link.arrivalMs + 140 : 0;
        const duration = link ? Math.min(durations[kind], 660) : durations[kind];
        if (link) {
          svg.dataset.phase = link.draw(elapsed);
          const impact = elapsed - link.arrivalMs;
          let sx = 1, sy = 1;
          if (impact < 80) { const press = ease(impact / 80); sx = .75 + press * .65; sy = 1.1 - press * .6; }
          else if (impact < 160) { const rebound = ease((impact-80) / 80); sx = 1.4 - rebound * .52; sy = .5 + rebound * .78; }
          else { const settle = ease((impact-160) / 90); sx = .88 + settle * .12; sy = 1.28 - settle * .28; }
          receiver.dataset.impactState = impact < 0 ? 'waiting' : impact < 80 ? 'compress' : impact < 160 ? 'rebound' : 'spread';
          const entry = link.receiver;
          receiver.setAttribute('transform', `translate(${entry.x} ${entry.y}) rotate(${entry.angle}) scale(${sx} ${sy})`);
          receiver.setAttribute('opacity', impact < 0 ? 0 : ease(impact / 26) * (1-ease((impact-400)/300)) * .98);
        }
        const progress = clamp((elapsed - lead) / duration);
        dispose.emitted = !!link || progress > 0;
        for (const {path, delay, reverse} of strokes) {
          const age = clamp((progress - delay) / (1 - delay));
          const drawn = ease(age / .58), erased = ease((age - .66) / .34);
          path.setAttribute('stroke-dashoffset', reverse ? -ease(age) : 1 - drawn);
          path.setAttribute('opacity', clamp(age / .12) * (1 - erased) * .94);
        }
        for (const {path, delay} of seals) {
          const age = clamp((progress - delay) / (1 - delay));
          const swell = ease(age / .22), fade = 1 - ease((age - .62) / .38);
          path.setAttribute('opacity', swell * fade * .94);
        }
        if (progress < 1) frame = requestAnimationFrame(tick); else dispose();
      } catch (_) { dispose(); }
    }
    frame = requestAnimationFrame(tick);
    timer = setTimeout(dispose, link ? link.arrivalMs + 140 + Math.min(durations[kind],660) + 200 : durations[kind] + 200);
    return true;
  }
  function entrances(host) {
    const animations = [];
    for (let node = host; node && node !== document.body; node = node.parentElement) {
      for (const animation of node.getAnimations?.() || []) {
        if (animation.playState !== 'running' || !Number.isFinite(animation.effect?.getComputedTiming().endTime)) continue;
        if (animation.effect.getKeyframes().some(frame => 'transform' in frame || 'opacity' in frame)) animations.push(animation);
      }
    }
    return animations;
  }
  const present = (kind, host, direction, source, strictSource = false) => {
    if (source === undefined && linkedKinds.has(kind) && origin && performance.now() - origin.time < 1500) source = origin.host;
    try {
      if (!host || !permitted(host)) return false;
      // Existing menu/editor entrances own their transform first. Sample the
      // settled edge rather than pinning an SVG to a shrinking or invisible box.
      const entering = entrances(host);
      if (entering.length) {
        const sourceBox = strictSource && bounds(source)?.box;
        if (strictSource && !sourceBox) return false;
        active.get(host)?.();
        while (active.size >= 3) active.values().next().value();
        let disposed = false;
        const dispose = () => {
          if (disposed) return;
          disposed = true; clearTimeout(timer);
          if (active.get(host) === dispose) active.delete(host);
        };
        dispose.waiting = true;
        const timer = setTimeout(dispose, 1200);
        active.set(host, dispose);
        Promise.allSettled(entering.map(animation => animation.finished)).then(() => {
          if (disposed) return;
          dispose();
          if (strictSource) {
            const current = bounds(source)?.box;
            if (!current || ['left', 'top', 'width', 'height'].some(key => Math.abs(current[key] - sourceBox[key]) > 1)) return;
          }
          if (host.isConnected && permitted(host)) present(kind, host, direction, source || null, strictSource);
        });
        return true;
      }
      return run(kind, host, direction, source);
    } catch (_) { active.get(host)?.(); return false; }
  };
  function transfer(source, destination, kind = 'arrival') {
    if (!gestures[kind] || !source || !destination || !permitted(destination)) return false;
    for (const host of [source, destination])
      if (!bounds(host) && (!bounds(host, true) || !entrances(host).length)) return false;
    if (mode() !== 'full') return present(kind, destination, undefined, source, true);
    // New sidebar rows can finish their layout a frame after their DOM arrives.
    // Establish both endpoints before emitting; once emitted, movement cancels.
    active.get(destination)?.();
    while (active.size >= 3) active.values().next().value();
    let frame = 0, previous = null, stable = 0, disposed = false;
    const dispose = () => {
      if (disposed) return;
      disposed = true; cancelAnimationFrame(frame); clearTimeout(timer);
      if (active.get(destination) === dispose) active.delete(destination);
    };
    dispose.waiting = true;
    dispose.connected = () => !!bounds(source, true);
    const timer = setTimeout(dispose, 500);
    active.set(destination, dispose);
    function settle() {
      const first = bounds(source)?.box, last = bounds(destination)?.box;
      if (!permitted(destination) || !bounds(source, true) || !bounds(destination, true)) { dispose(); return; }
      if (!first || !last || entrances(source).length || entrances(destination).length) {
        stable = 0; frame = requestAnimationFrame(settle); return;
      }
      const current = [first.left, first.top, first.width, first.height, last.left, last.top, last.width, last.height];
      stable = previous && current.every((value, index) => Math.abs(value - previous[index]) < .25) ? stable + 1 : 0;
      previous = current;
      if (stable >= 3) { dispose(); present(kind, destination, undefined, source, true); }
      else frame = requestAnimationFrame(settle);
    }
    frame = requestAnimationFrame(settle);
    return true;
  }
  window.AtelierMotion ||= {};
  window.AtelierMotion.workflow = Object.freeze({
    ...Object.fromEntries(Object.keys(gestures).map(trigger =>
      [trigger, (host, direction) => present(trigger, host, direction)])),
    // Context menus already scale open from the pointer, so they draw no edge ink.
    menu: () => false, stop, transfer,
  });
  window.AtelierMotionPolicy?.query().addEventListener('change', stop);
  window.addEventListener('atelier:inks', stop);
  window.addEventListener('atelier:energy', () => {
    for (const dispose of [...active.values()]) {
      if (dispose.waiting) continue;
      if (dispose.recolor) { try { dispose.recolor(); } catch (_) { dispose(); } }
      else dispose();
    }
  });
  window.addEventListener('resize', stop);
  const removals = new MutationObserver(records => {
    if (!active.size || records.every(record => record.target.closest?.('.k-workflow-svg,.k-workflow-link'))) return;
    for (const [host, dispose] of active) {
      const hidden = dispose.waiting ? !host.getClientRects().length || getComputedStyle(host).visibility !== 'visible' : !bounds(host);
      if (!host.isConnected || !permitted(host) || hidden || dispose.connected?.() === false) dispose();
      else dispose.invalidate?.();
    }
  });
  removals.observe(document.documentElement, {childList: true, subtree: true, attributes: true,
    attributeFilter: ['class', 'hidden', 'open', 'style']});
  document.addEventListener('scroll', () => {
    // A focus scroll may finish just after a replay click. Pending gestures
    // measure their final endpoints; ink already in flight cancels immediately.
    for (const dispose of [...active.values()]) if (!dispose.waiting && dispose.emitted !== false) dispose();
  }, {capture: true, passive: true});
  document.addEventListener('visibilitychange', () => { if (document.hidden) stop(); });
  window.addEventListener('pagehide', () => {
    stop(); removals.disconnect();
    document.removeEventListener('pointerdown', remember, true); document.removeEventListener('keydown', remember, true);
  });
})();

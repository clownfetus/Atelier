/* A view over the VFX editor's real LUT groups. No animation data is stored here. */
(function () {
  'use strict';
  const D = window.AtelierMotionboardData;
  if (!D) return;
  const roleNames = {color: 'Colour', opacity: 'Opacity', scale: 'Scale', emission: 'Emission', rate: 'Emission rate'};
  const components = ['R', 'G', 'B', 'A'], axes = ['X', 'Y', 'Z'];
  const views = new Map();
  let current;
  const make = (tag, text, className) => {
    const node = document.createElement(tag);
    if (text != null) node.textContent = text;
    if (className) node.className = className;
    return node;
  };
  const fmt = value => Number.isFinite(value) ? Number(value.toPrecision(5)).toString() : '—';
  const label = (group, index) => group.label && group.label !== '(unbound)' ? group.label : (group.exports?.[0]?.name || group.kind || 'Curve') + ' · #' + (group.export_indices?.[0] ?? index);
  function mount(host, editor, callbacks, legacy) {
    destroy();
    const owner = window.atelierProject() + ':' + editor.game_rel;
    const previous = views.get(owner) || {}, groups = editor.groups, keys = groups.map(D.key);
    const automatic = D.assignments(groups);
    const state = {time: previous.time || 0, playing: false, speed: previous.speed || 1,
      duration: previous.duration || 2, loop: previous.loop !== false, arrangement: previous.arrangement || 'burst', compare: 'edited',
      order: [...(previous.order || []).filter(key => keys.includes(key)), ...keys.filter(key => !(previous.order || []).includes(key))],
      hidden: new Set(previous.hidden || []), solo: previous.solo || '', selected: keys.includes(previous.selected) ? previous.selected : keys[0],
      point: previous.point || 0, channel: previous.channel || 0, maps: {...automatic.values, ...(previous.maps || {})}, query: '', filter: 'all'};
    for (const role of D.roles) if (!keys.includes(state.maps[role])) state.maps[role] = '';
    const byKey = new Map(groups.map((g, i) => [D.key(g), {g, i}]));
    const abort = new AbortController(), root = make('div', null, 'motionboard');
    let rowAbort = new AbortController();
    let raf = 0, last = 0, disposed = false, drag = null, lastReadout = -Infinity;
    const rows = new Map(), mapSelects = new Map(), colors = ['#df5759', '#459d68', '#5e8fe8', '#a890c8'];
    const on = (node, name, fn, options = {}) => node.addEventListener(name, fn, {signal: abort.signal, ...options});
    root.innerHTML = `
      <div class="mb-toolbar"><div class="mb-identity"><span class="mb-kicker">VFX Motionboard</span><span id="mb-dirty" role="status"></span></div>
        <div class="mb-compare" role="group" aria-label="Preview comparison"><button type="button" data-mb-compare="edited" aria-pressed="true">Edited</button><button type="button" data-mb-compare="original" aria-pressed="false">Original</button><button type="button" data-mb-compare="compare" aria-pressed="false">Compare</button></div>
      </div>
      <div class="mb-workspace">
        <section class="mb-stage-panel" aria-label="Particle proxy preview">
          <div class="mb-stage-heading"><span>Particle proxies</span><label>Arrangement <select id="mb-arrangement"><option value="burst">Burst</option><option value="trail">Trail</option><option value="smoke">Smoke</option><option value="continuous">Continuous</option></select></label></div>
          <div class="mb-stage"><canvas id="mb-canvas" tabindex="0" aria-label="Artistic particle proxy preview; Space plays or pauses"></canvas><span class="mb-stage-badge">2D PROXY · NOT UNREAL RENDERING</span><span id="mb-preview-caption"></span></div>
          <p class="mb-preview-note">Artistic proxy: curves are sampled over a simulated lifetime. Layouts and motion are preview choices; ambiguous tracks stay unassigned.</p>
        </section>
        <aside class="mb-inspector" aria-label="Track properties">
          <div class="mb-inspector-heading"><span class="mb-kicker">Selected track</span><h3 id="mb-track-name"></h3><span id="mb-binding-badge" class="mb-binding-badge"></span></div>
          <div class="mb-point-navigation"><label>Point <input id="mb-point" type="number" min="1" step="1"></label><span id="mb-point-time"></span></div>
          <label class="mb-field">Component <select id="mb-channel"></select></label>
          <label class="mb-field">Edited value <input id="mb-value" type="number" step="any"></label>
          <div id="mb-reference-values" class="mb-reference-values"></div>
          <div class="mb-reset-actions"><button id="mb-reset-point" type="button">Restore point</button><button id="mb-original-point" type="button">Game value</button><button id="mb-reset-track" type="button">Restore track</button><button id="mb-original-track" type="button">Game original</button></div>
          <p id="mb-edit-note" role="status" class="mb-edit-note"></p>
          <details class="mb-details" open><summary>Preview inputs</summary><div id="mb-bindings"></div><p>One curve per input. Named bindings are selected only when unambiguous. Other assignments are manual preview choices.</p><p>Opacity uses a scalar or A; scale uses X/Y or a uniform scalar. Emission uses RGB peak or a scalar; rate controls relative proxy density.</p></details>
          <details class="mb-details"><summary>Gradient & numeric controls</summary><label class="mb-all-controls"><input id="mb-all-controls" type="checkbox"> Show every track’s controls</label><div id="mb-legacy-controls"></div></details>
          <details class="mb-details"><summary>Source & limits</summary><div id="mb-source"></div><p>Editing points are uniformly spaced LUT stops. Their times cannot move; export rebuilds the native sample count with linear interpolation. Authored Niagara keys, tangents and full simulation are unavailable.</p><p>Proxy size and density share a scale across original and edited data. Negative size/rates and opacity are clamped for display; HDR colour is normalized. Source values are retained.</p><p id="mb-unsupported"></p></details>
        </aside>
        <section class="mb-timeline-panel" aria-label="Synchronized LUT timeline">
          <div class="mb-transport"><div class="mb-play-buttons"><button id="mb-back" type="button" title="Previous preview frame" aria-label="Previous preview frame">‹</button><button id="mb-play" type="button" aria-pressed="false">Play</button><button id="mb-forward" type="button" title="Next preview frame" aria-label="Next preview frame">›</button></div>
            <label class="mb-loop"><input id="mb-loop" type="checkbox" checked> Loop</label>
            <label>Speed <select id="mb-speed"><option value="0.25">¼×</option><option value="0.5">½×</option><option value="1">1×</option><option value="2">2×</option><option value="4">4×</option></select></label>
            <label>Preview <input id="mb-duration" type="number" min="0.1" max="60" step="0.1" value="2"> s</label>
            <output id="mb-clock"></output>
          </div>
          <div class="mb-track-toolbar"><input id="mb-track-search" type="search" placeholder="Find a track or export" aria-label="Find a Motionboard track"><select id="mb-track-filter" aria-label="Track category"><option value="all">All tracks</option><option value="color">Colour</option><option value="emission">Emission</option><option value="opacity">Opacity</option><option value="scalar">Scalar</option><option value="vector">Vectors</option></select><button id="mb-show-all" type="button">Show all</button></div>
          <div class="mb-ruler"><label for="mb-scrub">Normalized LUT input</label><div class="mb-ruler-scale"><input id="mb-scrub" type="range" min="0" max="1" step="0.0001" value="0" aria-label="Normalized LUT playhead"><div aria-hidden="true"><span>0</span><span>0.25</span><span>0.50</span><span>0.75</span><span>1</span></div></div></div>
          <div id="mb-tracks" class="mb-tracks" role="group" aria-label="Editable curve tracks"></div>
          <p class="mb-timeline-note">Drag points vertically to edit. ← → selects points; ↑ ↓ adjusts values (Shift for fine steps). Visibility, order and preview settings never change export data.</p>
        </section>
      </div>`;
    host.append(root);
    const get = id => root.querySelector('#' + id);
    const canvas = get('mb-canvas'), context = canvas.getContext('2d');
    const overlay = host.closest('.overlay');
    get('mb-legacy-controls').append(legacy);
    const activeGroup = () => byKey.get(state.selected);
    const sourceStops = (group, mode) => mode === 'original' ? D.original(group) || [] : D.edited(group);
    const visible = () => {
      if (disposed || document.hidden || !root.isConnected || !overlay?.classList.contains('active')) return false;
      const overlays = [...document.querySelectorAll('.overlay.active')];
      return overlays.at(-1) === overlay;
    };
    function remember() {
      views.delete(owner);
      views.set(owner, {time: state.time, speed: state.speed, duration: state.duration, loop: state.loop,
        arrangement: state.arrangement, order: state.order.slice(), hidden: [...state.hidden], solo: state.solo,
        selected: state.selected, point: state.point, channel: state.channel, maps: {...state.maps}});
      if (views.size > 16) views.delete(views.keys().next().value);
    }
    function schedule() { if (!raf && visible()) raf = requestAnimationFrame(frame); }
    function visibilityChanged() {
      if (!visible()) { cancelAnimationFrame(raf); raf = 0; last = 0; }
      else schedule();
    }
    function setPlaying(value) {
      state.playing = value;
      if (value && state.time >= 1) state.time = 0;
      get('mb-play').textContent = value ? 'Pause' : 'Play';
      get('mb-play').setAttribute('aria-pressed', String(value)); last = 0; schedule();
    }
    function seek(value) { setPlaying(false); state.time = D.clamp(value); updateTime(true); schedule(); }
    function updateTime(force = false) {
      root.style.setProperty('--mb-playhead', (state.time * 100) + '%');
      get('mb-scrub').value = String(state.time);
      get('mb-clock').textContent = state.time.toFixed(3) + ' · ' + Math.round(state.time * state.duration * 60) + 'f / ' + Math.round(state.duration * 60) + 'f';
      const now = performance.now();
      if (!force && now - lastReadout < 70) return;
      lastReadout = now;
      for (const [key, row] of rows) if (!row.element.hidden) {
        const group = byKey.get(key).g;
        row.readout.textContent = D.sample(sourceStops(group, state.compare === 'original' ? 'original' : 'edited'), state.time).map(fmt).join(' / ');
      }
    }
    function refreshInspector(rebuild = false) {
      const entry = activeGroup(); if (!entry) return;
      const {g, i} = entry;
      state.point = D.clamp(state.point, 0, g.stops.length - 1); state.channel = D.clamp(state.channel, 0, g.channels - 1);
      get('mb-track-name').textContent = label(g, i);
      const info = D.binding(g), badge = get('mb-binding-badge');
      badge.textContent = info.role ? 'Named binding · ' + roleNames[info.role] : info.source === 'ambiguous' ? 'Ambiguous binding' : 'Unbound · no automatic preview';
      badge.title = info.note;
      const point = get('mb-point'); point.max = g.stops.length;
      if (document.activeElement !== point) point.value = state.point + 1;
      const time = g.stops.length === 1 ? 0 : state.point / (g.stops.length - 1);
      get('mb-point-time').textContent = time.toFixed(4) + ' input';
      const channel = get('mb-channel');
      if (rebuild || channel.options.length !== g.channels) {
        channel.replaceChildren(...Array.from({length: g.channels}, (_, c) => {
          const option = make('option', g.channels === 4 ? components[c] : g.channels === 1 ? 'Value' : axes[c]); option.value = c; return option;
        }));
      }
      channel.value = String(state.channel);
      if (document.activeElement !== get('mb-value')) get('mb-value').value = g.stops[state.point][state.channel];
      const saved = callbacks.savedGroup(i), original = D.original(g);
      const gameValue = original ? D.sample(original, time)[state.channel] : null;
      get('mb-reference-values').textContent = 'Saved: ' + fmt(D.sample(saved.stops, time)[state.channel]) + ' · Game: ' + fmt(gameValue);
      const readOnly=state.compare==='original';
      get('mb-value').disabled=readOnly;
      get('mb-original-point').disabled = readOnly || !original; get('mb-original-track').disabled = readOnly || !g.original_stops;
      get('mb-reset-point').disabled=get('mb-reset-track').disabled=readOnly;
      const count = groups.filter(D.modified).length;
      get('mb-dirty').textContent = callbacks.isDirty() ? 'Unsaved changes' : count ? count + ' saved edited tracks' : 'Game original';
      for (const node of legacy.querySelectorAll('[data-vfx-group]')) node.hidden = !get('mb-all-controls').checked && Number(node.dataset.vfxGroup) !== i;
      if (rebuild) {
        const source = get('mb-source'); source.replaceChildren();
        source.append(make('p', g.stops.length + ' editing stops → ' + g.sample_count + ' native samples · ' + g.channels + ' channels'));
        source.append(make('p', 'Exports: ' + (g.export_indices || []).join(', ')));
        source.append(make('p', g.time_range ? 'LUT input domain: ' + g.time_range.map(fmt).join(' … ') + '. The playhead is normalized; this does not establish seconds or particle age.' : 'The native time domain is unavailable or degenerate. Preview seconds and frame rate are display choices.'));
        source.append(make('p', g.channels === 4 ? 'Colour / emission / opacity category is inferred from sample values; only named bindings establish an automatic preview input.' : 'Component count establishes a scalar or vector, not its particle behaviour.'));
        for (const binding of g.bindings || []) {
          source.append(make('p', (binding.source === 'binding' ? 'Binding: ' : 'Owner only: ') + ((binding.names || []).join(' · ') || binding.label || 'Unavailable')));
        }
      }
      for (const [key, row] of rows) row.element.classList.toggle('mb-selected', key === state.selected);
    }
    function choose(key, point = 0, channel = state.channel) {
      if (!byKey.has(key)) return;
      const old = state.selected; state.selected = key; state.point = point; state.channel = channel;
      refreshInspector(true); if (rows.has(old)) plot(old); plot(key); schedule();
    }
    function setValue(value) {
      if (!Number.isFinite(value) || Math.abs(value) > 3.4028234663852886e38) {
        get('mb-edit-note').textContent = 'Enter a finite value within the native float range.'; return;
      }
      const {i} = activeGroup(); callbacks.setValue(i, state.point, state.channel, value);
      get('mb-edit-note').textContent = '';
    }
    function path(stops, channel, bounds, limit = 512) {
      if (!stops.length) return '';
      const count = Math.min(stops.length, limit);
      return Array.from({length: count}, (_, i) => {
        const time = count === 1 ? 0 : i / (count - 1), value = D.sample(stops, time)[channel];
        return (i ? 'L' : 'M') + (10 + time * 980).toFixed(2) + ',' + (66 - (value - bounds.min) / (bounds.max - bounds.min) * 48).toFixed(2);
      }).join(' ');
    }
    function plot(key) {
      const row = rows.get(key), group = byKey.get(key).g;
      if (!row || row.element.hidden || state.hidden.has(key)) return;
      const reference = D.original(group), bounds = drag?.key === key ? drag.bounds : D.extent([...group.stops, ...(reference || [])]); row.bounds = bounds;
      const selectedChannel = key === state.selected ? state.channel : 0;
      let svg = '<line class="mb-zero" x1="10" x2="990" y1="' + (66 - (0 - bounds.min) / (bounds.max - bounds.min) * 48) + '" y2="' + (66 - (0 - bounds.min) / (bounds.max - bounds.min) * 48) + '"/>';
      if (group.channels === 4) {
        const maximum = Math.max(1, ...group.stops.flatMap(stop => stop.slice(0, 3)));
        const stops = group.stops.map((s, i) => '<stop offset="' + (group.stops.length === 1 ? 0 : i / (group.stops.length - 1) * 100) + '%" stop-color="rgb(' + s.slice(0, 3).map(v => Math.round(D.clamp(v / maximum) * 255)).join(',') + ')" stop-opacity="' + D.clamp(s[3]) + '"/>').join('');
        svg += '<defs><linearGradient id="mb-grad-' + byKey.get(key).i + '">' + stops + '</linearGradient></defs><rect x="10" y="2" width="980" height="8" rx="2" fill="url(#mb-grad-' + byKey.get(key).i + ')"/>';
      }
      for (let c = 0; c < group.channels; c++) {
        const color = group.channels === 1 ? 'var(--acc)' : colors[c];
        if (reference && state.compare !== 'edited') svg += '<path class="mb-reference-line" d="' + path(reference, c, bounds) + '" style="stroke:' + color + '"/>';
        if (state.compare !== 'original') svg += '<path class="mb-value-line" d="' + path(D.edited(group), c, bounds) + '" style="stroke:' + color + ';opacity:' + (c === selectedChannel ? 1 : .48) + '"/>';
      }
      if (state.compare !== 'original') {
        const every = Math.max(1, Math.ceil(group.stops.length / 64));
        group.stops.forEach((stop, index) => {
          if (index % every && !(key === state.selected && index === state.point)) return;
          const time = group.stops.length === 1 ? 0 : index / (group.stops.length - 1);
          svg += '<circle class="mb-key' + (key === state.selected && index === state.point ? ' mb-key-selected' : '') + '" data-mb-point="' + index + '" data-mb-channel="' + selectedChannel + '" cx="' + (10 + time * 980) + '" cy="' + (66 - (stop[selectedChannel] - bounds.min) / (bounds.max - bounds.min) * 48) + '" r="4"/>';
        });
      }
      row.svg.innerHTML = svg;
      row.range.textContent = fmt(bounds.min) + ' … ' + fmt(bounds.max);
    }
    function applyVisibility() {
      let count = 0;
      for (const [key, row] of rows) {
        const group = byKey.get(key).g;
        const named = D.binding(group).role;
        const category = state.filter === 'all' || state.filter === 'scalar' && group.channels === 1 ||
          state.filter === 'vector' && [2,3].includes(group.channels) || named === state.filter || !named && group.kind === state.filter;
        row.element.hidden = !category || ![label(group, byKey.get(key).i), ...(group.export_indices || [])].join(' ').toLowerCase().includes(state.query) || !!state.solo && state.solo !== key;
        row.element.classList.toggle('mb-track-hidden', state.hidden.has(key));
        row.hide.setAttribute('aria-pressed', String(state.hidden.has(key)));
        row.solo.setAttribute('aria-pressed', String(state.solo === key));
        if (!row.element.hidden) { count++; plot(key); }
      }
      get('mb-tracks').dataset.empty = String(!count);
      updateTime(true);
    }
    function renderRows() {
      rowAbort.abort(); rowAbort=new AbortController(); drag=null;
      const rowOn=(node,name,fn)=>on(node,name,fn,{signal:rowAbort.signal});
      const container = get('mb-tracks'); container.replaceChildren(); rows.clear();
      state.order.forEach((key, orderIndex) => {
        const {g, i} = byKey.get(key), element = make('div', null, 'mb-track'); element.dataset.trackKey = key;
        const heading = make('div', null, 'mb-track-heading'), title = make('button', label(g, i), 'mb-track-select'); title.type = 'button'; title.title = label(g, i); rowOn(title,'click',()=>choose(key));
        const named=D.binding(g).role;
        const description = make('span', (named ? roleNames[named].toLowerCase() : g.kind || 'curve') + (g.channels === 4 && !named ? ' · inferred' : '') + (g.export_indices.length > 1 ? ' · ×' + g.export_indices.length : ''), 'mb-track-kind');
        const actions = make('div', null, 'mb-track-actions');
        const button = (text, name, action) => {
          const node = make('button', text); node.type = 'button'; node.setAttribute('aria-label', name + ' ' + label(g, i)); node.title = name + ' (timeline only)'; rowOn(node, 'click', action); actions.append(node); return node;
        };
        const solo = button('S', 'Isolate', () => { state.solo = state.solo === key ? '' : key; applyVisibility(); });
        const hide = button('H', 'Hide graph', () => { state.hidden.has(key) ? state.hidden.delete(key) : state.hidden.add(key); applyVisibility(); });
        const up = button('↑', 'Move up', () => move(key, -1)), down = button('↓', 'Move down', () => move(key, 1));
        up.disabled = orderIndex === 0; down.disabled = orderIndex === state.order.length - 1;
        heading.append(title, description, actions);
        const area = make('div', null, 'mb-plot-area'), svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
        svg.setAttribute('viewBox', '0 0 1000 76'); svg.setAttribute('preserveAspectRatio', 'none'); svg.setAttribute('tabindex', '0');
        svg.setAttribute('role', 'img'); svg.setAttribute('aria-label', label(g, i) + '. Arrow keys select points and edit the active component.');
        const playhead = make('span', null, 'mb-playhead'), range = make('span', null, 'mb-plot-range'), readout = make('span', null, 'mb-track-value');
        playhead.setAttribute('aria-hidden', 'true'); area.append(svg, playhead, range, readout); element.append(heading, area); container.append(element);
        rows.set(key, {element, svg, hide, solo, range, readout, bounds: null});
        rowOn(svg, 'pointerdown', event => {
          if (event.button !== 0) return;
          const point = event.target.closest('[data-mb-point]');
          if (point && state.compare !== 'original') {
            event.preventDefault(); choose(key, Number(point.dataset.mbPoint), Number(point.dataset.mbChannel));
            const row = rows.get(key); drag = {key, bounds: {...row.bounds}, top: svg.getBoundingClientRect().top, height: svg.getBoundingClientRect().height};
            svg.setPointerCapture(event.pointerId); svg.focus();
          } else {
            choose(key); const bounds = svg.getBoundingClientRect(); seek(D.clamp(((event.clientX - bounds.left) / bounds.width * 1000 - 10) / 980));
          }
        });
        rowOn(svg, 'pointermove', event => {
          if (!drag || drag.key !== key) return;
          const y = (event.clientY - drag.top) / drag.height * 76;
          let value = drag.bounds.min + (66 - y) / 48 * (drag.bounds.max - drag.bounds.min);
          if (event.shiftKey) value = Math.round(value * 1000) / 1000;
          setValue(Number(value.toPrecision(9)));
        });
        const release = event => { drag = null; if (svg.hasPointerCapture(event.pointerId)) svg.releasePointerCapture(event.pointerId); plot(key); schedule(); };
        rowOn(svg, 'pointerup', release); rowOn(svg, 'pointercancel', release);
        rowOn(svg, 'keydown', event => {
          if (!['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown', 'Home', 'End'].includes(event.key)) return;
          event.preventDefault(); choose(key, key === state.selected ? state.point : 0);
          if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') choose(key, D.clamp(state.point + (event.key === 'ArrowRight' ? 1 : -1), 0, g.stops.length - 1));
          else if (event.key === 'Home' || event.key === 'End') choose(key, event.key === 'Home' ? 0 : g.stops.length - 1);
          else if (state.compare !== 'original') {
            const bounds = rows.get(key).bounds, step = (bounds.max - bounds.min) / (event.shiftKey ? 1000 : 100);
            setValue(Number((g.stops[state.point][state.channel] + (event.key === 'ArrowUp' ? step : -step)).toPrecision(9)));
          }
        });
      });
      applyVisibility(); refreshInspector(true);
    }
    function move(key, direction) {
      const index = state.order.indexOf(key), next = index + direction;
      if (next < 0 || next >= state.order.length) return;
      [state.order[index], state.order[next]] = [state.order[next], state.order[index]];
      renderRows();
      rows.get(key)?.element.querySelector('.mb-track-select').focus();
    }
    function renderMappings() {
      const container = get('mb-bindings'); container.replaceChildren(); mapSelects.clear();
      for (const role of D.roles) {
        const wrapper = make('label', roleNames[role], 'mb-field'), select = make('select'); select.id = 'mb-map-' + role;
        const empty = make('option', automatic.candidates[role].length > 1 ? 'Unassigned · multiple named tracks' : 'Unassigned · neutral proxy'); empty.value = ''; select.append(empty);
        groups.forEach((g, i) => {
          if (!D.allowed(role, g)) return;
          const named = D.binding(g).role === role, option = make('option', label(g, i) + (named ? ' · named' : ' · manual'));
          option.value = D.key(g); select.append(option);
        });
        select.value = state.maps[role]; on(select, 'change', () => { state.maps[role] = select.value; schedule(); });
        wrapper.append(select); container.append(wrapper); mapSelects.set(role, select);
      }
    }
    function proxyInputs(time, mode) {
      const values = {};
      for (const role of D.roles) {
        const entry = byKey.get(state.maps[role]);
        if (entry) values[role] = {sample: D.sample(sourceStops(entry.g, mode), time), group: entry.g};
      }
      return values;
    }
    function paintSide(x, width, height, mode) {
      const style = getComputedStyle(root), muted = style.getPropertyValue('--muted').trim(), ink = style.getPropertyValue('--text').trim();
      context.save(); context.beginPath(); context.rect(x, 0, width, height); context.clip();
      context.strokeStyle = style.getPropertyValue('--border').trim(); context.lineWidth = 1;
      for (let gx = 24; gx < width; gx += 36) for (let gy = 24; gy < height; gy += 36) { context.fillStyle = context.strokeStyle; context.fillRect(x + gx, gy, 1, 1); }
      const cx = x + width * .5, cy = height * .53;
      context.globalAlpha = .45; context.beginPath(); context.moveTo(cx - 10, cy); context.lineTo(cx + 10, cy); context.moveTo(cx, cy - 10); context.lineTo(cx, cy + 10); context.stroke(); context.globalAlpha = 1;
      const global = proxyInputs(state.time, mode), rate = global.rate;
      const rangeSamples=g=>[...g.stops,...(D.original(g)||[])];
      const maxRate = rate ? Math.max(1e-12, ...rangeSamples(rate.group).map(stop => Math.max(0, stop[0]))) : 1;
      const scaleMax = global.scale ? Math.max(1e-12, ...rangeSamples(global.scale.group).flatMap(stop => stop.map(v => Math.max(0, v)))) : 1;
      const count = rate ? Math.round(76 * D.clamp(rate.sample[0] / maxRate)) : 56;
      const scale = Math.min(width / 650, height / 330, 1.3);
      for (let i = 0; i < count; i++) {
        const seed = Math.sin((i + 1) * 127.1) * 43758.5453, rand = seed - Math.floor(seed);
        const age = state.arrangement === 'burst' ? state.time : (state.time + i / Math.max(count, 1)) % 1;
        const inputs = proxyInputs(age, mode), color = inputs.color?.sample || (inputs.emission?.sample.length >= 3 ? inputs.emission.sample : null);
        const opacity = inputs.opacity?.sample;
        let alpha = opacity ? opacity.length === 4 ? opacity[3] : opacity[0] : color?.length === 4 ? color[3] : 1;
        alpha = D.clamp(alpha);
        const intensity = inputs.emission?.sample;
        const energy = intensity ? Math.max(0, ...(intensity.length >= 3 ? intensity.slice(0, 3) : intensity)) : 1;
        const size = inputs.scale;
        const sx = size ? D.clamp(size.sample[0] / scaleMax, 0, 2) : 1;
        const sy = size ? D.clamp((size.sample[1] ?? size.sample[0]) / scaleMax, 0, 2) : 1;
        let px, py;
        if (state.arrangement === 'burst') {
          const angle = i * 2.399963, distance = (20 + age * 125) * (.45 + rand * .6) * scale;
          px = cx + Math.cos(angle) * distance; py = cy + Math.sin(angle) * distance * .7;
        } else if (state.arrangement === 'trail') {
          px = x + width * (.16 + (1 - age) * .68); py = cy + Math.sin(age * 6.2) * 34 * scale + (rand - .5) * 18 * scale;
        } else if (state.arrangement === 'smoke') {
          px = cx + Math.sin(i * 1.7 + age * 3) * (12 + age * 55) * scale; py = height * .8 - age * height * .62;
        } else {
          const angle = i * 2.399963; px = cx + Math.cos(angle) * (10 + age * 110) * scale; py = cy + Math.sin(angle) * (10 + age * 95) * scale;
        }
        if (sx <= 0 || sy <= 0 || alpha <= 0 || energy <= 0) continue;
        const radius = (state.arrangement === 'smoke' ? 15 + age * 10 : 6 + rand * 8) * scale;
        let pigment = ink;
        if (color) { const peak = Math.max(1, ...color.slice(0, 3)); pigment = 'rgb(' + color.slice(0, 3).map(value => Math.round(D.clamp(value / peak) * 255)).join(',') + ')'; }
        context.save(); context.translate(px, py); context.scale(sx, sy);
        context.globalAlpha = alpha * (state.arrangement === 'smoke' ? .28 : .8) * Math.min(1, energy);
        if (intensity) { context.shadowColor = pigment; context.shadowBlur = Math.min(22, energy * 5) * scale; }
        context.fillStyle = pigment;
        if (state.arrangement === 'smoke') {
          const gradient = context.createRadialGradient(0, 0, 0, 0, 0, radius); gradient.addColorStop(0, pigment); gradient.addColorStop(1, 'transparent'); context.fillStyle = gradient;
        }
        context.beginPath(); context.arc(0, 0, radius, 0, Math.PI * 2); context.fill(); context.restore();
      }
      context.fillStyle = muted; context.font = '11px ' + (style.getPropertyValue('--studio-font').trim() || 'sans-serif');
      context.fillText(mode === 'original' ? 'GAME ORIGINAL' : 'EDITED LUT', x + 16, 24);
      context.restore();
    }
    function paint() {
      if (!context) return;
      const bounds = canvas.getBoundingClientRect(), ratio = Math.min(2, window.devicePixelRatio || 1);
      const width = Math.max(1, Math.round(bounds.width)), height = Math.max(1, Math.round(bounds.height));
      if (canvas.width !== Math.round(width * ratio) || canvas.height !== Math.round(height * ratio)) { canvas.width = Math.round(width * ratio); canvas.height = Math.round(height * ratio); }
      context.setTransform(ratio, 0, 0, ratio, 0, 0); context.clearRect(0, 0, width, height);
      if (state.compare === 'compare') {
        paintSide(0, width / 2, height, 'original'); paintSide(width / 2, width / 2, height, 'edited');
        context.strokeStyle = getComputedStyle(root).getPropertyValue('--border'); context.beginPath(); context.moveTo(width / 2, 0); context.lineTo(width / 2, height); context.stroke();
      } else paintSide(0, width, height, state.compare === 'original' ? 'original' : 'edited');
      const assigned = D.roles.filter(role => state.maps[role]);
      get('mb-preview-caption').textContent = assigned.length ? assigned.map(role => roleNames[role] + (automatic.candidates[role].includes(state.maps[role]) ? ' · named' : ' · manual')).join('   /   ') : 'Neutral proxy · assign inputs to preview curve values';
    }
    function frame(now) {
      raf = 0; if (!visible()) { last = 0; return; }
      if (state.playing && last) {
        state.time += Math.min(.1, (now - last) / 1000) * state.speed / state.duration;
        if (state.time >= 1) { if (state.loop) state.time %= 1; else { state.time = 1; setPlaying(false); } }
      }
      last = now; updateTime(); paint(); if (state.playing) schedule();
    }
    on(get('mb-play'), 'click', () => setPlaying(!state.playing));
    on(get('mb-back'), 'click', () => seek(state.time - 1 / (state.duration * 60)));
    on(get('mb-forward'), 'click', () => seek(state.time + 1 / (state.duration * 60)));
    on(get('mb-loop'), 'change', event => { state.loop = event.target.checked; });
    on(get('mb-speed'), 'change', event => { state.speed = Number(event.target.value); });
    on(get('mb-duration'), 'change', event => { const value = Number(event.target.value); if (value >= .1 && value <= 60) state.duration = value; else event.target.value = state.duration; updateTime(true); });
    on(get('mb-arrangement'), 'change', event => { state.arrangement = event.target.value; schedule(); });
    on(get('mb-scrub'), 'input', event => seek(Number(event.target.value)));
    on(get('mb-point'), 'input', event => { const value = Number(event.target.value); if (Number.isInteger(value) && value >= 1) choose(state.selected, value - 1); });
    on(get('mb-channel'), 'change', event => choose(state.selected, state.point, Number(event.target.value)));
    on(get('mb-value'), 'input', event => { if (event.target.value.trim()) setValue(Number(event.target.value)); });
    on(get('mb-value'), 'change', () => { if (!get('mb-value').value.trim()) refreshInspector(); });
    for (const [id, mode, point] of [['mb-reset-point', 'saved', true], ['mb-original-point', 'original', true], ['mb-reset-track', 'saved', false], ['mb-original-track', 'original', false]]) {
      on(get(id), 'click', () => { const {i} = activeGroup(); callbacks.restore(i, mode, point ? state.point : null, state.channel); get('mb-edit-note').textContent = ''; });
    }
    on(get('mb-track-search'), 'input', event => { state.query = event.target.value.toLowerCase(); applyVisibility(); });
    on(get('mb-track-filter'), 'change', event => { state.filter = event.target.value; applyVisibility(); });
    on(get('mb-show-all'), 'click', () => { state.hidden.clear(); state.solo = ''; state.query = ''; state.filter = 'all'; get('mb-track-search').value = ''; get('mb-track-filter').value = 'all'; applyVisibility(); });
    on(get('mb-all-controls'), 'change', () => refreshInspector());
    for (const button of root.querySelectorAll('[data-mb-compare]')) on(button, 'click', () => {
      state.compare = button.dataset.mbCompare;
      for (const other of root.querySelectorAll('[data-mb-compare]')) other.setAttribute('aria-pressed', String(other === button));
      get('mb-value').disabled = state.compare === 'original';
      legacy.inert = state.compare === 'original';
      get('mb-reset-point').disabled=get('mb-reset-track').disabled=state.compare==='original';
      get('mb-original-point').disabled=state.compare==='original' || !D.original(activeGroup().g);
      get('mb-original-track').disabled=state.compare==='original' || !activeGroup().g.original_stops;
      for (const key of rows.keys()) plot(key); updateTime(true); schedule();
    });
    on(root, 'keydown', event => {
      if (event.code === 'Space' && !event.target.closest('input, select, textarea, button, summary')) { event.preventDefault(); setPlaying(!state.playing); }
    });
    const resize = new ResizeObserver(schedule); resize.observe(canvas.parentElement);
    const visibility = new MutationObserver(visibilityChanged); visibility.observe(document.body, {attributes: true, attributeFilter: ['class', 'hidden'], subtree: true});
    const theme = new MutationObserver(schedule); theme.observe(document.documentElement, {attributes: true, attributeFilter: ['data-theme', 'style']});
    on(document, 'visibilitychange', visibilityChanged);
    get('mb-speed').value = state.speed; get('mb-duration').value = state.duration; get('mb-loop').checked = state.loop; get('mb-arrangement').value = state.arrangement;
    const originalsAvailable = groups.every(g => D.original(g));
    if (!originalsAvailable) root.querySelectorAll('[data-mb-compare]:not([data-mb-compare="edited"])').forEach(button => { button.disabled = true; button.title = 'Original LUT samples are unavailable'; });
    get('mb-unsupported').textContent = (editor.unsupportedExports?.length || 0) + ' exports have no supported LUT. ' + (editor.unmatchedEdits || 0) + ' saved edit groups are unavailable and are preserved; restore the entire effect to clear them.';
    renderMappings(); renderRows(); updateTime(true); schedule();
    current = {
      sync(index) {
        if (disposed) return;
        if (index == null) for (const key of rows.keys()) plot(key); else if (groups[index]) plot(D.key(groups[index]));
        refreshInspector(); updateTime(true); schedule();
      },
      destroy() { disposed = true; remember(); cancelAnimationFrame(raf); abort.abort(); rowAbort.abort(); resize.disconnect(); visibility.disconnect(); theme.disconnect(); rows.clear(); root.remove(); },
    };
    return current;
  }
  function destroy() { current?.destroy(); current = null; }
  window.AtelierMotionboard = Object.freeze({mount, destroy, sync: index => current?.sync(index)});
})();

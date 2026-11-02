// Recolour texture: blend a colour into a part's base-colour map, previewed live on the model and
// saved as an ordinary edited PNG (handlers/texture_recolour.py). The preview is never an edit:
// it lives only on the model until Apply, and choosing another part puts the map back.
import * as THREE from 'three';

const MODES = [['color','Colour'],['hue','Hue'],['multiply','Multiply'],['screen','Screen'],['overlay','Overlay'],['soft_light','Soft light']];
const STRAIGHT = [[0,0],[1,1]];
const PRESETS = [['Lighter',[[0,0],[.5,.65],[1,1]]],['Darker',[[0,0],[.5,.35],[1,1]]],
  ['More contrast',[[0,0],[.25,.17],[.75,.83],[1,1]]],['Less contrast',[[0,.08],[.5,.5],[1,.92]]]];
const MAX_POINTS = 8, GAP = .03;
const SVG = 'http://www.w3.org/2000/svg';
const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);
const round = v => Math.round(v * 1000) / 1000;

// The curve through `points` as y(x): a monotone cubic (Fritsch-Carlson), the same maths
// handlers/texture_recolour.py bakes with, so the drawn line is the one the texture gets.
export function curveAt(points) {
  const xs = points.map(p => p[0]), ys = points.map(p => p[1]), n = points.length;
  const d = xs.slice(1).map((x, k) => (ys[k + 1] - ys[k]) / (x - xs[k]));
  const m = xs.map((_, k) => k === 0 ? d[0] : k === n - 1 ? d[n - 2] : d[k - 1] * d[k] > 0 ? (d[k - 1] + d[k]) / 2 : 0);
  for (let k = 0; k < n - 1; k++) {
    if (d[k] === 0) { m[k] = m[k + 1] = 0; continue; }
    const a = m[k] / d[k], b = m[k + 1] / d[k], s = a * a + b * b;
    if (s > 9) { const t = 3 / Math.sqrt(s); m[k] = t * a * d[k]; m[k + 1] = t * b * d[k]; }
  }
  return x => {
    let k = 0; while (k < n - 2 && x >= xs[k + 1]) k++;
    const h = xs[k + 1] - xs[k], t = (x - xs[k]) / h;
    const y = (2*t**3 - 3*t**2 + 1) * ys[k] + (t**3 - 2*t**2 + t) * h * m[k] + (3*t**2 - 2*t**3) * ys[k + 1] + (t**3 - t**2) * h * m[k + 1];
    return Math.min(1, Math.max(0, y));
  };
}

function curvePath(points, size = 100) {
  const y = curveAt(points);
  return Array.from({length:65}, (_, i) => `${i ? 'L' : 'M'}${(i / 64 * size).toFixed(2)} ${((1 - y(i / 64)) * size).toFixed(2)}`).join('');
}

function svg(tag, attrs = {}) {
  const node = document.createElementNS(SVG, tag);
  for (const [key, value] of Object.entries(attrs)) node.setAttribute(key, value);
  return node;
}

function icon(name) {
  const node = document.createElement('i'); node.dataset.lucide = name; node.setAttribute('size', '18'); return node;
}

function iconButton(className, name, text) {
  const button = document.createElement('button'); button.type = 'button'; button.className = className;
  const label = document.createElement('span'); label.textContent = text;
  button.append(icon(name), label); return button;
}

// Presets for one click, and the line itself for anything else: drag a point, click the line
// to add one, double-click (or Delete) to remove it. Arrow keys move the focused point.
function curveEditor(initial, view, onChange) {
  let points = initial.map(p => [...p]);
  const box = document.createElement('div'); box.className = 'vp-curve';
  const presets = document.createElement('div'); presets.className = 'vp-curve-presets';
  const buttons = PRESETS.map(([label, shape]) => {
    const button = document.createElement('button'); button.type = 'button'; button.className = 'vp-curve-preset';
    button.dataset.preset = label;
    const glyph = svg('svg', {viewBox:'0 0 20 20', width:'20', height:'20', 'aria-hidden':'true'});
    glyph.append(svg('path', {d:'M2 18L18 2', class:'vp-curve-glyph-base'}),
      svg('path', {d:curvePath(shape, 16), transform:'translate(2 2)', class:'vp-curve-glyph-line'}));
    const text = document.createElement('span'); text.textContent = label;
    button.append(glyph, text);
    button.addEventListener('click', () => set(shape));
    return [shape, button];
  });
  presets.append(...buttons.map(([, button]) => button));

  const graph = svg('svg', {viewBox:'-4 -4 108 108', class:'vp-curve-graph', role:'group',
    'aria-label':'Brightness curve. Drag a point, or click the line to add one.'});
  const frame = svg('rect', {x:0, y:0, width:100, height:100, class:'vp-curve-frame'});
  const grid = svg('path', {d:'M25 0V100M50 0V100M75 0V100M0 25H100M0 50H100M0 75H100', class:'vp-curve-grid'});
  const diagonal = svg('path', {d:'M0 100L100 0', class:'vp-curve-diagonal'});
  const line = svg('path', {class:'vp-curve-line'});
  const handles = svg('g');
  graph.append(frame, grid, diagonal, line, handles);
  const scale = document.createElement('div'); scale.className = 'vp-curve-scale';
  scale.innerHTML = '<span>Shadows</span><span>Highlights</span>';
  const hint = document.createElement('p'); hint.className = 'vp-curve-hint';
  hint.textContent = 'Drag a point up to lighten, down to darken. Click the line to add a point; double-click a point to remove it.';

  const reset = iconButton('vp-curve-reset', 'rotate-ccw', 'Straighten curve');
  reset.addEventListener('click', () => set(STRAIGHT));
  // The graph is for fine-tuning: the presets cover most needs and the inspector is short, so it
  // stays folded unless asked for or the curve is already one no preset matches.
  const custom = document.createElement('details'); custom.className = 'vp-curve-custom';
  custom.open = view.open || !(same(points, STRAIGHT) || PRESETS.some(([, shape]) => same(shape, points)));
  custom.addEventListener('toggle', () => { view.open = custom.open; });
  const summary = document.createElement('summary');
  const summaryText = document.createElement('span'); summaryText.textContent = 'Edit curve by hand';
  summary.append(icon('pencil'), summaryText, icon('chevron-down'));
  custom.append(summary, graph, scale, hint);
  box.append(presets, reset, custom);

  function draw(focus = -1) {
    line.setAttribute('d', curvePath(points));
    handles.replaceChildren(...points.map(([x, y], index) => {
      const handle = svg('circle', {cx:x * 100, cy:(1 - y) * 100, r:4.5, class:'vp-curve-point', tabindex:'0', role:'slider',
        'aria-label': index === 0 ? 'Darkest point' : index === points.length - 1 ? 'Lightest point' : `Curve point ${index}`,
        'aria-valuemin':'0', 'aria-valuemax':'100', 'aria-valuenow':String(Math.round(y * 100))});
      handle.dataset.index = index; return handle;
    }));
    if (focus >= 0) handles.children[focus]?.focus();
    for (const [shape, button] of buttons) button.setAttribute('aria-pressed', String(same(shape, points)));
    reset.hidden = same(points, STRAIGHT);
  }
  function set(next, focus) { points = next.map(([x, y]) => [round(x), round(y)]); draw(focus); onChange(points); }
  function at(event) {
    const r = graph.getBoundingClientRect(), unit = r.width / 108;
    return [Math.min(1, Math.max(0, (event.clientX - r.left) / unit / 100 - .04)),
            Math.min(1, Math.max(0, 1 - ((event.clientY - r.top) / unit / 100 - .04)))];
  }
  function move(index, x, y) {
    const next = points.map(p => [...p]), last = next.length - 1;
    next[index] = [index === 0 ? 0 : index === last ? 1 : Math.min(next[index + 1][0] - GAP, Math.max(next[index - 1][0] + GAP, x)),
                   Math.min(1, Math.max(0, y))];
    return next;
  }
  function remove(index, focus) {
    if (index > 0 && index < points.length - 1) set(points.filter((_, i) => i !== index), focus);
  }

  let dragging = -1;
  graph.addEventListener('pointerdown', event => {
    if (event.button !== 0) return;
    let index = Number(event.target.dataset?.index ?? -1);
    if (index < 0) {
      const [x, y] = at(event);
      if (points.length >= MAX_POINTS || x < GAP || x > 1 - GAP || points.some(p => Math.abs(p[0] - x) < GAP)) return;
      index = points.findIndex(p => p[0] > x);
      set([...points.slice(0, index), [x, y], ...points.slice(index)]);
    }
    dragging = index; graph.setPointerCapture(event.pointerId); event.preventDefault();
  });
  graph.addEventListener('pointermove', event => {
    if (dragging < 0) return;
    const [x, y] = at(event); set(move(dragging, x, y));
  });
  const stop = () => { dragging = -1; };
  graph.addEventListener('pointerup', stop); graph.addEventListener('pointercancel', stop);
  graph.addEventListener('dblclick', event => remove(Number(event.target.dataset?.index ?? -1)));
  graph.addEventListener('keydown', event => {
    const index = Number(event.target.dataset?.index ?? -1); if (index < 0) return;
    const step = event.shiftKey ? .05 : .01, [x, y] = points[index];
    const moves = {ArrowUp:[0, step], ArrowDown:[0, -step], ArrowRight:[step, 0], ArrowLeft:[-step, 0]};
    if (moves[event.key]) { set(move(index, x + moves[event.key][0], y + moves[event.key][1]), index); event.preventDefault(); }
    else if (event.key === 'Delete' || event.key === 'Backspace') { remove(index, index - 1); event.preventDefault(); }
  });
  draw();
  return box;
}

export function createViewportRecolour(api) {
  const drafts = new Map();       // material -> {colour, mode, strength}
  const states = new Map();       // texture game_rel -> server state (recipe, edited, token…)
  let preview = null;             // {name, texture, revision}
  let revision = 0, timer = 0;
  const curveView = {open:false};  // whether "Edit curve by hand" stays open across panel rebuilds

  const textureOf = info => info?.texture_roles?.basecolor;
  const eligible = info => !!textureOf(info) && !info.dyeable && !info.eye_preview && !info.texture_urls?.basecolor;

  function restoreMap() {
    if (!preview) return;
    for (const material of api.materials(preview.name)) {
      if (material.map === preview.texture) { material.map = api.baseline(preview.name) || null; material.needsUpdate = true; }
    }
    preview.texture?.dispose();
    preview = null;
  }

  // The panel rebuilds often; only a part other than `keep` loses its draft and preview.
  function discard(keep = null) {
    if (preview && preview.name !== keep) restoreMap();
    for (const name of [...drafts.keys()]) if (name !== keep) drafts.delete(name);
    if (!keep || !drafts.has(keep)) { clearTimeout(timer); revision++; }
  }

  async function showPreview(name, info, draft, status) {
    const ticket = ++revision;
    status.textContent = 'Preparing preview…';
    try {
      const response = await api.fetch('/api/texture_recolour/preview', {method:'POST', headers:{'Content-Type':'application/json'},
        body: JSON.stringify({game_rel:textureOf(info), ...draft})});
      if (!response.ok) throw Error((await response.json().catch(() => ({}))).error || 'Preview unavailable');
      const url = URL.createObjectURL(await response.blob());
      let texture;
      try { texture = await api.loader.loadAsync(url); } finally { URL.revokeObjectURL(url); }
      if (ticket !== revision || !drafts.has(name)) { texture.dispose(); return; }
      texture.colorSpace = THREE.SRGBColorSpace; texture.flipY = false;
      texture.wrapS = texture.wrapT = THREE.RepeatWrapping;
      const previous = preview?.name === name ? preview.texture : null;
      if (preview && preview.name !== name) restoreMap();
      for (const material of api.materials(name)) { material.map = texture; material.needsUpdate = true; }
      previous?.dispose();
      preview = {name, texture};
      api.retint(name);
      status.textContent = 'Preview only. Apply recolour to keep it.';
    } catch (error) {
      if (ticket === revision) status.textContent = error.message;
    }
  }

  async function apply(name, info, controls, replace = false) {
    const draft = drafts.get(name); if (!draft) return;
    controls.apply.disabled = true; controls.status.textContent = 'Saving recolour…';
    try {
      const result = await api.fetch('/api/texture_recolour', {method:'POST', headers:{'Content-Type':'application/json'},
        body: JSON.stringify({game_rel:textureOf(info), ...draft, replace})}).then(r => r.json());
      if (result.needs_replace) {
        const ok = await window.AtelierDialog.confirm({title:'Replace edited texture?', confirmLabel:'Replace', tone:'danger',
          body:'This texture has edits made another way, such as painting or a replacement. Recolouring replaces them with the game texture plus this colour.'});
        if (ok) return apply(name, info, controls, true);
        controls.status.textContent = 'Recolour not applied.'; return;
      }
      if (!result.ok) throw Error(result.error || 'Could not save the recolour');
      states.delete(textureOf(info));
      drafts.delete(name); revision++;
      await api.applied(textureOf(info), result.ver);
      if (preview?.name === name) { preview.texture.dispose(); preview = null; }
      api.note('Recolour saved to your mod', 'success');
      await window.loadSidebar?.();
    } catch (error) {
      controls.status.textContent = error.message;
    } finally { api.rebuild(); }
  }

  function field(label, name, input, tag = 'label') {
    const row = document.createElement(tag); row.className = 'vp-recolour-row';
    const caption = document.createElement('span'); caption.className = 'vp-recolour-caption';
    const text = document.createElement('span'); text.textContent = label;
    caption.append(icon(name), text);
    row.append(caption, input); return row;
  }

  function section(name, info) {
    discard(name);
    if (!eligible(info)) return null;
    const texture = textureOf(info);
    const box = document.createElement('section'); box.className = 'vp-recolour'; box.setAttribute('aria-label','Recolour texture');
    const title = document.createElement('h4'); title.textContent = 'Recolour texture';
    const hint = document.createElement('p'); hint.className = 'vp-inspector-hint';
    hint.textContent = 'Blend a colour into this part\'s texture. The game shows it exactly as previewed.';
    const status = document.createElement('p'); status.className = 'vp-recolour-status'; status.setAttribute('role','status');
    box.append(title, hint);

    const saved = states.get(texture);
    const draft = {curve:STRAIGHT, ...(drafts.get(name) || saved?.recipe || {colour:'#3F6FD8', mode:'color', strength:1})};
    const picker = document.createElement('input'); picker.type = 'color'; picker.value = draft.colour.toLowerCase();
    picker.setAttribute('aria-label', 'Recolour colour');
    const hex = document.createElement('input'); hex.type = 'text'; hex.className = 'vp-hex'; hex.value = draft.colour.toUpperCase();
    hex.maxLength = 7; hex.spellcheck = false; hex.setAttribute('aria-label','Recolour hex colour');
    const colour = document.createElement('div'); colour.className = 'vp-color-controls'; colour.append(picker, hex);
    const mode = document.createElement('select'); mode.setAttribute('aria-label','Blend mode');
    mode.replaceChildren(...MODES.map(([value, text]) => new Option(text, value))); mode.value = draft.mode;
    const strength = document.createElement('input'); strength.type = 'range'; strength.min = '0'; strength.max = '100';
    strength.value = String(Math.round(draft.strength * 100)); strength.setAttribute('aria-label','Strength');
    const amount = document.createElement('output'); amount.textContent = strength.value + '%';
    const strengthRow = document.createElement('div'); strengthRow.className = 'vp-recolour-strength'; strengthRow.append(strength, amount);
    let curve = draft.curve;
    const curveRow = field('Curve', 'spline', curveEditor(curve, curveView, points => { curve = points; changed(); }), 'div');
    curveRow.classList.add('vp-recolour-curve');
    box.append(field('Colour', 'palette', colour), field('Blend', 'layers', mode), field('Strength', 'sliders-horizontal', strengthRow), curveRow);

    const actions = document.createElement('div'); actions.className = 'vp-recolour-actions';
    const applyButton = iconButton('vp-recolour-apply', 'check', 'Apply recolour'); applyButton.disabled = !drafts.has(name);
    const cancel = iconButton('vp-recolour-cancel', 'x', 'Cancel preview'); cancel.hidden = !drafts.has(name);
    const restore = iconButton('vp-recolour-restore', 'rotate-ccw', 'Restore original texture');
    restore.hidden = !saved?.edited || drafts.has(name);
    actions.append(applyButton, cancel, restore);
    box.append(actions, status);
    const controls = {apply:applyButton, status};

    const changed = () => {
      const value = {colour:picker.value.toUpperCase(), mode:mode.value, strength:Number(strength.value) / 100, curve};
      drafts.set(name, value);
      applyButton.disabled = false; cancel.hidden = false; restore.hidden = true;
      amount.textContent = strength.value + '%';
      clearTimeout(timer); timer = setTimeout(() => showPreview(name, info, value, status), 180);
    };
    picker.addEventListener('input', () => { hex.value = picker.value.toUpperCase(); changed(); });
    hex.addEventListener('change', () => {
      const value = hex.value.startsWith('#') ? hex.value : '#' + hex.value;
      if (!/^#[0-9a-f]{6}$/i.test(value)) { hex.setCustomValidity('Use #RRGGBB'); hex.reportValidity(); return; }
      hex.setCustomValidity(''); picker.value = value.toLowerCase(); hex.value = value.toUpperCase(); changed();
    });
    mode.addEventListener('change', changed);
    strength.addEventListener('input', changed);
    applyButton.addEventListener('click', () => apply(name, info, controls));
    cancel.addEventListener('click', () => { drafts.delete(name); revision++; restoreMap(); api.rebuild(); });
    restore.addEventListener('click', async () => {
      if (!saved?.token || !(await window.AtelierModTray?.restore(saved.token))) return;
      states.delete(texture); api.reload();
    });

    if (saved) {
      if (saved.hand_edited && !drafts.has(name)) status.textContent = 'This texture already has other edits. Applying a recolour replaces them.';
      else if (saved.recipe && !drafts.has(name)) status.textContent = 'This recolour is in your mod.';
    } else {
      api.fetch('/api/texture_recolour?game_rel=' + encodeURIComponent(texture)).then(r => r.json()).then(data => {
        if (!data.ok) return;
        states.set(texture, data);
        if (!drafts.has(name) && box.isConnected) api.rebuild();
      }).catch(() => {});
    }
    return box;
  }

  return {section, discard, eligible, previewing:() => preview?.name || null};
}

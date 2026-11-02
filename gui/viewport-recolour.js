// Recolour texture: blend a colour into a part's base-colour map, previewed live on the model and
// saved as an ordinary edited PNG (handlers/texture_recolour.py). The preview is never an edit:
// it lives only on the model until Apply, and choosing another part puts the map back.
import * as THREE from 'three';

const MODES = [['color','Colour'],['hue','Hue'],['multiply','Multiply'],['screen','Screen'],['overlay','Overlay'],['soft_light','Soft light']];

export function createViewportRecolour(api) {
  const drafts = new Map();       // material -> {colour, mode, strength}
  const states = new Map();       // texture game_rel -> server state (recipe, edited, token…)
  let preview = null;             // {name, texture, revision}
  let revision = 0, timer = 0;

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

  function field(label, input) {
    const row = document.createElement('label'); row.className = 'vp-recolour-row';
    const caption = document.createElement('span'); caption.textContent = label;
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
    const draft = drafts.get(name) || saved?.recipe || {colour:'#3F6FD8', mode:'color', strength:1};
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
    box.append(field('Colour', colour), field('Blend', mode), field('Strength', strengthRow));

    const actions = document.createElement('div'); actions.className = 'vp-recolour-actions';
    const applyButton = document.createElement('button'); applyButton.type = 'button'; applyButton.className = 'vp-recolour-apply';
    applyButton.textContent = 'Apply recolour'; applyButton.disabled = !drafts.has(name);
    const cancel = document.createElement('button'); cancel.type = 'button'; cancel.className = 'vp-recolour-cancel';
    cancel.textContent = 'Cancel preview'; cancel.hidden = !drafts.has(name);
    const restore = document.createElement('button'); restore.type = 'button'; restore.className = 'vp-recolour-restore';
    restore.textContent = 'Restore original texture'; restore.hidden = !saved?.edited || drafts.has(name);
    actions.append(applyButton, cancel, restore);
    box.append(actions, status);
    const controls = {apply:applyButton, status};

    const changed = () => {
      const value = {colour:picker.value.toUpperCase(), mode:mode.value, strength:Number(strength.value) / 100};
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

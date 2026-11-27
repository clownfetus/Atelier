import {
  ALL_FORMS, ENTRY_LIMIT, FILE_LIMIT, blankEntry, blankSetup, decodeSetup, encodeSetup,
  indexedNiagaraPath, niagaraSystemPath, setupFilename,
} from './skin-vfx-data.js';
import { attachmentPoint, mirroredPlacement } from './skin-vfx-placement.js';

const $ = id => document.getElementById(id);
const element = (tag, text, className) => {
  const node = document.createElement(tag);
  if (text) node.textContent = text;
  if (className) node.className = className;
  return node;
};

export function createSkinVfxEditor(fetchAssets) {
  const toggle = $('viewport-skin-vfx-toggle');
  const panel = $('viewport-skin-vfx-panel');
  const inspector = $('viewport-materials');
  const guide = $('skin-vfx-guide');
  const [guideLink, guideBone, guidePoint] = guide.children;
  const control = suffix => $('skin-vfx-' + suffix);
  const name = control('name'), mesh = control('mesh'), selection = control('selection');
  const system = control('system'), bone = control('bone'), results = control('results');
  const entryName = control('entry-name'), form = control('form'), loop = control('loop');
  const status = control('status'), previewNote = control('preview-note');
  const download = control('export'), file = control('file'), mirror = control('mirror');
  const drafts = new Map();
  let model = null, draft = null, jointName = '', output = '', exporting = false;
  let searchTimer, searchRequest, fileRequest = 0;
  const modelKey = value => value ? value.project + '/' + value.skin : '';
  const entry = () => draft?.setup.entries[draft.selected];
  const opened = () => !panel.hidden;

  const transforms = [
    ['location', 'Offset (cm)', ['X', 'Y', 'Z']],
    ['rotation', 'Rotation (°)', ['Pitch', 'Yaw', 'Roll']],
    ['scale', 'Scale', ['X', 'Y', 'Z']],
  ];
  const inputs = transforms.map(([field, title, axes]) => {
    const group = element('fieldset', '', 'skin-vfx-transform');
    group.append(element('legend', title));
    const axesInputs = axes.map((axis, index) => {
      const input = element('input');
      input.type = 'number';
      input.step = 'any';
      input.setAttribute('aria-label', title + ' ' + axis);
      input.addEventListener('input', () => {
        entry()[field][index] = input.valueAsNumber;
        edited();
      });
      const label = element('label', axis, 'skin-vfx-field');
      label.append(input);
      group.append(label);
      return input;
    });
    control('transforms').append(group);
    return [field, axesInputs];
  });

  function showStatus(message, kind = '') {
    if (status.textContent !== message) status.textContent = message;
    status.dataset.kind = kind;
    status.hidden = !message;
  }

  function validate() {
    const setup = draft.setup;
    output = '';
    let message = '';
    if (setup.entries.length) {
      try { output = encodeSetup(setup); }
      catch (error) { message = error.message; }
    }
    showStatus(message, message ? 'error' : '');
    download.disabled = exporting || !output;
    control('new').hidden = !setup.name && !setup.targetMesh && !setup.entries.length;
    control('add').disabled = setup.entries.length >= ENTRY_LIMIT;
    control('duplicate').disabled = control('add').disabled;
    control('add').title = control('add').disabled ? 'Galacta supports up to 16 effects per setup.' : '';
  }

  function refreshPlacement() {
    const effect = entry();
    const typed = effect?.bone.trim();
    const bones = model?.rig.nodes;
    jointName = typed && (bones.has(typed) ? typed : [...bones.keys()].find(key => key.toLowerCase() === typed.toLowerCase())) || '';
    const visibleOnForm = !effect || effect.form === ALL_FORMS || effect.form === model.form;
    const message = !effect || !typed ? '' : !visibleOnForm ? 'Switch the preview mesh to Form ' + effect.form + ' to see placement.'
      : !jointName ? 'This bone is missing from the preview mesh.' : '';
    if (previewNote.textContent !== message) previewNote.textContent = message;
    previewNote.hidden = !message;
    mirror.disabled = !jointName || !visibleOnForm || !effect.location.every(Number.isFinite) || !effect.rotation.every(Number.isFinite);
  }

  function edited() {
    draft.dirty = true;
    validate();
    refreshPlacement();
  }

  function showSystem() {
    const value = entry()?.system || '';
    const path = niagaraSystemPath(value);
    system.title = path;
    system.value = path && document.activeElement !== system ? path.split('.').pop() : value;
  }

  function clearSearch() {
    clearTimeout(searchTimer);
    searchRequest?.abort();
    results.hidden = true;
    results.replaceChildren();
  }

  function renderSelection() {
    const {entries} = draft.setup;
    selection.replaceChildren(...entries.map((effect, i) => new Option(effect.name.trim() || 'Effect ' + (i + 1), i)));
    if (!entries.length) selection.add(new Option('No effects', ''));
    selection.disabled = !entries.length;
    selection.value = entries.length ? draft.selected : '';
  }

  function renderForms() {
    const effect = entry();
    const forms = new Set(model.forms);
    if (effect?.form >= 0) forms.add(effect.form);
    form.replaceChildren(new Option('All forms', ALL_FORMS),
      ...[...forms].sort((a, b) => a - b).map(value => new Option('Form ' + value, value)));
    form.value = effect?.form ?? ALL_FORMS;
  }

  function renderEntry() {
    clearSearch();
    renderSelection();
    const effect = entry();
    control('entry').hidden = !effect;
    control('empty').hidden = !!effect;
    if (effect) {
      entryName.value = effect.name;
      showSystem();
      bone.value = effect.bone;
      loop.checked = effect.loop;
      for (const [field, fields] of inputs) fields.forEach((input, i) => {
        input.value = Number.isFinite(effect[field][i]) ? effect[field][i] : '';
      });
    }
    renderForms();
    refreshPlacement();
    validate();
  }

  function renderModel() {
    const bones = [...model.rig.nodes.keys()].sort((a, b) => a.localeCompare(b));
    control('bones').replaceChildren(...bones.map(value => new Option(value)));
    renderForms();
    refreshPlacement();
  }

  function show(value) {
    if (value && !model) return;
    if (value && $('viewport-uv-toggle').getAttribute('aria-expanded') === 'true') $('viewport-uv-toggle').click();
    toggle.setAttribute('aria-expanded', String(value));
    panel.hidden = !value;
    inspector.classList.toggle('skin-vfx-open', value);
    guide.hidden = true;
    if (!value) { fileRequest++; clearSearch(); return; }
    if (!draft) {
      const key = modelKey(model);
      draft = drafts.get(key) || {setup: blankSetup(model), selected: 0, dirty: false};
      drafts.set(key, draft);
    }
    name.value = draft.setup.name;
    mesh.value = draft.setup.targetMesh;
    control('mesh-options').open = !!draft.setup.targetMesh;
    renderModel();
    renderEntry();
  }

  function setModel(next) {
    const previous = model;
    if (!next || modelKey(previous) !== modelKey(next)) {
      show(false);
      draft = null;
      control('placement').open = false;
    }
    model = next;
    toggle.hidden = !next;
    if (opened() && (previous.rig !== model.rig || previous.form !== model.form)) renderModel();
  }

  function showMatches() {
    clearSearch();
    const query = system.value.trim();
    if (query.length < 2 || /[/\\'"]/.test(query)) return;
    const current = entry();
    const controller = new AbortController();
    searchRequest = controller;
    searchTimer = setTimeout(async () => {
      const active = () => !controller.signal.aborted && opened() && entry() === current;
      const showHint = message => {
        results.replaceChildren(element('p', message, 'skin-vfx-hint'));
        results.hidden = false;
      };
      try {
        const response = await fetchAssets('/api/search?limit=50&q=' + encodeURIComponent('ns_ ' + query),
          {signal: controller.signal});
        if (!response.ok) throw Error('Search unavailable');
        const found = await response.json();
        if (!active()) return;
        const options = (found.assets || []).map(item => ({item, path: indexedNiagaraPath(item)}))
          .filter(match => match.path).slice(0, 5);
        if (!options.length) {
          showHint(found.building ? 'Atelier is still indexing game effects.' : 'No matching game effects.');
          return;
        }
        results.replaceChildren(...options.map(({item, path}) => {
          const button = element('button');
          button.type = 'button';
          button.title = path;
          button.append(element('span', item.name));
          button.addEventListener('click', () => {
            current.system = system.value = path;
            clearSearch();
            edited();
            bone.focus();
            showSystem();
          });
          return button;
        }));
        results.hidden = false;
      } catch {
        if (active()) showHint('Effect search is unavailable. Paste a Niagara system path to continue.');
      }
    }, 180);
  }

  function addEffect(copy) {
    const entries = draft.setup.entries;
    if (entries.length >= ENTRY_LIMIT) return;
    const names = new Set(entries.map(effect => effect.name.trim().toLowerCase()));
    const stem = copy?.name.trim() || 'Effect';
    let n = 1, candidate = copy ? stem + ' copy' : 'Effect 1';
    while (names.has(candidate.toLowerCase())) candidate = (copy ? stem + ' copy ' : 'Effect ') + ++n;
    const effect = copy ? {...structuredClone(copy), name: candidate} : blankEntry(candidate);
    draft.selected = entries.length;
    entries.push(effect);
    draft.dirty = true;
    renderEntry();
    (copy ? entryName : system).focus();
  }

  async function replaceSetup(next, current, request) {
    if (draft !== current || request !== fileRequest || !opened()) return false;
    const sameSetup = output && next.entries.length && encodeSetup(next) === output;
    if (current.dirty && !sameSetup && !await window.AtelierDialog.confirm({
      title: 'Discard this Skin VFX draft?',
      body: 'Opening or starting another setup will replace these changes.',
      tone: 'danger', confirmLabel: 'Discard changes',
    })) return false;
    if (draft !== current || request !== fileRequest || !opened()) return false;
    drafts.set(modelKey(model), draft = {setup: next, selected: 0, dirty: false});
    control('placement').open = false;
    show(true);
    return true;
  }

  toggle.addEventListener('click', () => show(!opened()));
  $('viewport-uv-toggle').addEventListener('click', () => { if (opened()) show(false); });
  control('open').addEventListener('click', () => file.click());
  file.addEventListener('change', async () => {
    const selected = file.files[0];
    file.value = '';
    if (!selected || !draft || !model) return;
    const request = ++fileRequest, current = draft, target = model;
    try {
      if (selected.size > FILE_LIMIT) throw Error('Choose a GalactaVFX JSON file under 128 KB.');
      const setup = decodeSetup(await selected.arrayBuffer(), target);
      if (await replaceSetup(setup, current, request)) showStatus('Setup opened.');
    } catch (error) {
      if (opened() && draft === current && request === fileRequest) showStatus(error.message, 'error');
    }
  });
  control('new').addEventListener('click', async () => {
    if (await replaceSetup(blankSetup(model), draft, ++fileRequest)) name.focus();
  });
  name.addEventListener('input', () => { draft.setup.name = name.value; edited(); });
  mesh.addEventListener('input', () => { draft.setup.targetMesh = mesh.value.trim(); edited(); });
  selection.addEventListener('change', () => { draft.selected = Number(selection.value); renderEntry(); });
  entryName.addEventListener('input', () => {
    entry().name = entryName.value;
    selection.selectedOptions[0].textContent = entryName.value.trim() || 'Effect ' + (draft.selected + 1);
    edited();
  });
  system.addEventListener('focus', () => {
    system.value = entry().system;
    system.select();
  });
  system.addEventListener('blur', event => {
    if (!results.contains(event.relatedTarget)) clearSearch();
    showSystem();
  });
  system.addEventListener('keydown', event => {
    if (event.key !== 'ArrowDown' || results.hidden || !results.querySelector('button')) return;
    event.preventDefault();
    results.querySelector('button').focus();
  });
  system.addEventListener('input', () => { entry().system = system.value; edited(); showMatches(); });
  bone.addEventListener('input', () => { entry().bone = bone.value; edited(); });
  loop.addEventListener('change', () => { entry().loop = loop.checked; edited(); });
  form.addEventListener('change', () => { entry().form = Number(form.value); edited(); });
  control('add').addEventListener('click', () => addEffect());
  control('duplicate').addEventListener('click', () => addEffect(entry()));
  control('remove').addEventListener('click', () => {
    draft.setup.entries.splice(draft.selected, 1);
    draft.selected = Math.max(0, Math.min(draft.selected, draft.setup.entries.length - 1));
    draft.dirty = true;
    renderEntry();
    (entry() ? selection : control('add')).focus();
  });
  mirror.addEventListener('click', () => {
    const effect = entry();
    Object.assign(effect, mirroredPlacement(model.rig, jointName, effect));
    draft.dirty = true;
    renderEntry();
  });
  function requestDownload(blob, filename) {
    const url = URL.createObjectURL(blob);
    const anchor = element('a');
    anchor.href = url;
    anchor.download = filename;
    anchor.click();
    setTimeout(() => URL.revokeObjectURL(url), 30000);
  }

  download.addEventListener('click', async () => {
    if (exporting || !output) return;
    const current = draft, json = output;
    const filename = setupFilename(current.setup.name);
    const blob = new Blob([json], {type: 'application/json'});
    exporting = true;
    download.disabled = true;
    try {
      if (typeof window.showSaveFilePicker === 'function') {
        let location;
        try {
          location = await window.showSaveFilePicker({
            id: 'atelier-galacta-vfx', suggestedName: filename,
            types: [{description: 'Galacta VFX setup', accept: {'application/json': ['.json']}}],
          });
        } catch (error) {
          if (error.name === 'AbortError') return;
          if (error.name !== 'SecurityError' && error.name !== 'NotAllowedError') throw error;
        }
        if (location) {
          const stream = await location.createWritable();
          await stream.write(blob);
          await stream.close();
          if (draft === current && output === json) current.dirty = false;
        } else requestDownload(blob, filename);
      } else requestDownload(blob, filename);
      if (opened() && current === draft && output === json) {
        showStatus('Use this JSON to build the mod in Galacta.');
        panel.querySelector('.skin-vfx-handoff').open = true;
      }
    } catch {
      if (opened() && current === draft) showStatus('The setup could not be saved. Choose another save location.', 'error');
    } finally {
      exporting = false;
      download.disabled = !output;
    }
  });

  function drawGuide(camera, enabled) {
    const effect = entry();
    const joint = model?.rig.nodes.get(jointName);
    const draw = enabled && opened() && !inspector.hidden && joint && model.rig.root.visible
      && (effect.form === ALL_FORMS || effect.form === model.form) && effect.location.every(Number.isFinite);
    if (!draw) { guide.hidden = true; return; }
    const point = attachmentPoint(joint, effect.location).project(camera);
    if (point.z < -1 || point.z > 1 || Math.abs(point.x) > 1 || Math.abs(point.y) > 1) {
      guide.hidden = true;
      return;
    }
    const root = attachmentPoint(joint, [0, 0, 0]).project(camera);
    guide.hidden = false;
    const {clientWidth: w, clientHeight: h} = guide;
    const xy = value => [(value.x + 1) * w * 0.5, (1 - value.y) * h * 0.5];
    const [x, y] = xy(point), [rx, ry] = xy(root);
    guidePoint.style.left = x + 'px';
    guidePoint.style.top = y + 'px';
    guideBone.style.left = rx + 'px';
    guideBone.style.top = ry + 'px';
    guideLink.style.left = rx + 'px';
    guideLink.style.top = ry + 'px';
    guideLink.style.width = Math.hypot(x - rx, y - ry) + 'px';
    guideLink.style.transform = 'rotate(' + Math.atan2(y - ry, x - rx) + 'rad)';
  }

  return {
    setModel, drawGuide,
    dirty: () => [...drafts.values()].some(item => item.dirty),
    dismiss: () => {
      if (!opened()) return false;
      if (!results.hidden) { clearSearch(); system.focus(); }
      else { show(false); toggle.focus(); }
      return true;
    },
  };
}

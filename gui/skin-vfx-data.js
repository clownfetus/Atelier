// Project Galacta v1.6.0 VFX Lab interchange. The addon writes transforms as
// Unreal vector/rotator strings. Its Companion App turns these files into mods.
export const ALL_FORMS = -1;
export const ENTRY_LIMIT = 16;
export const FILE_LIMIT = 128 * 1024;

const axes = 'XYZ';
const transformFields = [
  ['location', 'Location', axes, 'offset'],
  ['rotation', 'Rotation', 'PYR', 'rotation'],
  ['scale', 'Scale', axes, 'scale'],
];
const decimal = '[+-]?(?:\\d+(?:\\.\\d*)?|\\.\\d+)';
const plainNumber = new Intl.NumberFormat('en-US', {useGrouping: false, maximumSignificantDigits: 17});
const invalidName = /[\x00-\x1f\x7f|]/;
const assetPath = /^((?:\/[\p{L}\p{N}_]+){2,})(?:\.([\p{L}\p{N}_]+))?$/u;

export function skinVfxTarget(gameRel) {
  const ids = /^Characters\/(\d{4})\/(\d{7})\/(?:[^/]+\/)*SK_[^/]+$/i.exec(gameRel || '');
  if (!ids || !ids[2].startsWith(ids[1])) return null;
  const [, hero, skin] = ids;
  const body = /\/SK_(\d{4})(\d?)_(\d{7})(?:_|\.uasset$|$)/i.exec(gameRel);
  const form = body?.[1] === hero && body[3] === skin ? Number(body[2] || 0) : 0;
  return {hero: Number(hero), skin: Number(skin), form};
}

export function niagaraSystemPath(value) {
  const path = typeof value === 'string' ? value.trim() : '';
  const quoted = /^(?:NiagaraSystem)?(['"])(.*)\1$/i.exec(path);
  const match = assetPath.exec(quoted?.[2] ?? path);
  if (!match) return '';
  const [, pkg, object] = match;
  return pkg + '.' + (object && !/^\d+$/.test(object) ? object : pkg.split('/').pop());
}

export function indexedNiagaraPath(item) {
  const relative = item?.game_rel;
  // Atelier's index groups emitters, curves and other effect assets here too.
  if (item?.type !== 'vfx' || !/^(?:VFX|Characters)\/(?:[^/]+\/)*NS_[^/]+$/i.test(relative)) return '';
  return niagaraSystemPath('/Game/Marvel/' + relative);
}

function targetMeshPath(path, hero, skin) {
  if (path === '') return path;
  const mesh = niagaraSystemPath(path);
  const prefix = '/Game/Marvel/ProjectGalacta/Meshes/' + hero + '/' + skin + '/';
  if (!mesh.toLowerCase().startsWith(prefix.toLowerCase()) || mesh.slice(prefix.length).split('/').length < 2) {
    throw Error('Use a Project Galacta Skin Swapper mesh for this costume.');
  }
  return mesh;
}

function requiredName(value, label) {
  if (typeof value !== 'string' || !value.trim() || invalidName.test(value)) {
    throw Error(label + ' needs a name without line breaks or | characters.');
  }
  return value.trim();
}

function transformNumbers(text, components, label) {
  const pattern = components.split('').map(axis => axis + '\\s*=\\s*(' + decimal + ')').join('\\s+');
  const match = typeof text === 'string' && new RegExp('^\\s*' + pattern + '\\s*$', 'i').exec(text);
  if (!match) throw Error('The ' + label + ' values could not be read.');
  return match.slice(1).map(Number);
}

function formatTransform(values, components, label) {
  if (!Array.isArray(values) || values.length !== 3 || !values.every(Number.isFinite)) {
    throw Error('Enter a number for each ' + label + ' axis.');
  }
  return values.map((value, i) => components[i] + '=' + plainNumber.format(value === 0 ? 0 : value)).join(' ');
}

export function blankSetup(target) {
  return {name: '', hero: target.hero, skin: target.skin, targetMesh: '', entries: []};
}

export function blankEntry(name, bone = '') {
  return {name, system: '', bone, location: [0, 0, 0], rotation: [0, 0, 0], scale: [1, 1, 1], loop: false, form: ALL_FORMS};
}

export function setupFilename(name) {
  const stem = name.trim().replace(/[<>:"/\\|?*\x00-\x1f]/g, '_').slice(0, 100).trim();
  return 'GalactaVFX_' + stem + '.json';
}

export function encodeSetup(setup) {
  const name = requiredName(setup.name, 'The setup');
  if (!/[\p{L}\p{N}]/u.test(name)) throw Error('Use at least one letter or digit in the setup name.');
  const {hero, skin} = setup;
  if (!Number.isInteger(hero) || !Number.isInteger(skin) || !/^\d{4}$/.test(hero)
      || !/^\d{7}$/.test(skin) || !String(skin).startsWith(String(hero))) {
    throw Error('Choose a character costume in Model Studio.');
  }
  const mesh = targetMeshPath(setup.targetMesh, hero, skin);
  if (!setup.entries.length) throw Error('Add at least one effect.');
  if (setup.entries.length > ENTRY_LIMIT) throw Error('A setup can contain up to 16 effects.');
  const names = new Set();
  const entries = setup.entries.map((entry, index) => {
    const label = 'Effect ' + (index + 1);
    const entryName = requiredName(entry.name, label);
    const key = entryName.toLowerCase();
    if (names.has(key)) throw Error('Give each effect a unique name.');
    names.add(key);
    const system = niagaraSystemPath(entry.system);
    if (!system) throw Error(entryName + ' needs a Niagara system path.');
    const bone = requiredName(entry.bone, 'The target bone for ' + entryName);
    if (/^none$/i.test(bone)) throw Error('Choose a target bone for ' + entryName + '.');
    if (!Number.isInteger(entry.form) || entry.form < ALL_FORMS || entry.form > 9) {
      throw Error('Choose a valid form for ' + entryName + '.');
    }
    if (typeof entry.loop !== 'boolean') throw Error('Check the loop setting for ' + entryName + '.');
    const output = {EntryName: entryName, System: system, Bone: bone};
    for (const [field, property, components, description] of transformFields) {
      output[property] = formatTransform(entry[field], components, description + ' for ' + entryName);
    }
    return {...output, Loop: entry.loop, Form: entry.form};
  });
  const json = JSON.stringify({VFXName: name, TargetHeroID: hero, TargetSkinID: skin, TargetMesh: mesh, Entries: entries}, null, 2) + '\n';
  if (new TextEncoder().encode(json).length > FILE_LIMIT) throw Error('Use shorter names or paths to keep the setup under 128 KB.');
  return json;
}

export function decodeSetup(buffer, target) {
  const bytes = ArrayBuffer.isView(buffer)
    ? new Uint8Array(buffer.buffer, buffer.byteOffset, buffer.byteLength)
    : new Uint8Array(buffer);
  if (bytes.length > FILE_LIMIT) throw Error('Choose a GalactaVFX JSON file under 128 KB.');
  const encoding = bytes[0] === 0xff && bytes[1] === 0xfe ? 'utf-16le'
    : bytes[0] === 0xfe && bytes[1] === 0xff ? 'utf-16be' : 'utf-8';
  let input;
  try { input = JSON.parse(new TextDecoder(encoding, {fatal: true}).decode(bytes)); }
  catch { throw Error('Choose a valid Galacta VFX Lab JSON file.'); }
  if (!input || !Array.isArray(input.Entries) || !Number.isInteger(input.TargetHeroID)
      || !Number.isInteger(input.TargetSkinID) || typeof input.TargetMesh !== 'string') {
    throw Error('Choose a setup exported by Galacta VFX Lab.');
  }
  if (input.TargetHeroID !== target.hero || input.TargetSkinID !== target.skin) {
    throw Error('Open costume ' + input.TargetSkinID + ' in Model Studio to edit this setup.');
  }
  if (input.Entries.length > ENTRY_LIMIT) throw Error('A setup can contain up to 16 effects.');
  const entries = input.Entries.map(value => {
    if (!value || typeof value !== 'object') throw Error('An effect entry could not be read.');
    const entry = {
      name: value.EntryName, system: niagaraSystemPath(value.System), bone: value.Bone,
      loop: value.Loop, form: value.Form,
    };
    for (const [key, property, components, label] of transformFields) {
      entry[key] = transformNumbers(value[property], components, label);
    }
    return entry;
  });
  const setup = {
    ...blankSetup(target), name: input.VFXName,
    targetMesh: targetMeshPath(input.TargetMesh, target.hero, target.skin), entries,
  };
  encodeSetup(setup);
  return setup;
}

import * as THREE from 'three';
const $ = id => document.getElementById(id);

const CATEGORY_ORDER = ['idle', 'lobby', 'emote', 'combat', 'other'];
const CATEGORY_LABELS = {
  idle: 'Standing idles',
  lobby: 'Lobby & MVP',
  emote: 'Emotes',
  combat: 'Combat & movement',
  other: 'Other poses',
};

export function createViewportAnimation(api) {
  let generation = 0, meshRel = '', selected = '', loaded = '', loading = false, discovering = false, playing = false;
  let mixers = [], embedded = [], entries = [];
  let clipDuration = 0, currentTime = 0;
  const poses = new Map();
  const verifiedIdles = new Map();

  function formatTime(t, total) {
    return `${t.toFixed(1)}s / ${total.toFixed(1)}s`;
  }

  function syncScrub() {
    const wrap = $('viewport-scrub-wrap');
    const scrub = $('viewport-scrub');
    const readout = $('viewport-scrub-time');
    if (!wrap || !scrub) return;
    const active = !loading && !discovering && mixers.length > 0 && clipDuration > 0;
    wrap.hidden = !active;
    if (!active) return;
    scrub.max = String(clipDuration);
    scrub.step = String(Math.max(0.005, +(clipDuration / 200).toFixed(4)));
    scrub.value = String(Math.min(clipDuration, Math.max(0, currentTime)));
    if (readout) readout.textContent = formatTime(currentTime, clipDuration);
  }

  function sync() {
    const button = $('viewport-play');
    button.disabled = loading || discovering || !entries.length;
    button.textContent = discovering ? 'Finding poses…' : loading ? 'Loading pose…' : playing ? 'Pause' : entries.length ? 'Play' : 'No poses';
    button.setAttribute('aria-pressed', String(playing));
    button.title = loading ? 'Decoding the selected pose or animation' : entries.length ? 'Choose a pose or animation, then play, pause or scrub frames' : 'No compatible animations were found for this mesh';
    $('viewport-animation').disabled = loading || discovering || !entries.length;
    syncScrub();
    api.changed?.();
  }

  function restore() {
    for (const mixer of mixers) { mixer.stopAllAction(); mixer.uncacheRoot(mixer.getRoot()); }
    mixers = [];
    clipDuration = 0;
    currentTime = 0;
    for (const [node,pose] of poses) { node.position.copy(pose.position); node.quaternion.copy(pose.quaternion); node.scale.copy(pose.scale); }
    poses.clear(); playing = false;
  }

  function reset() {
    generation++; restore(); embedded = []; entries = []; meshRel = selected = loaded = ''; loading = discovering = false;
    $('viewport-animation').replaceChildren(new Option('Rest pose','')); sync();
  }

  function remember(root) {
    root.traverse(node => { if (node.isBone && !poses.has(node)) poses.set(node,{position:node.position.clone(),quaternion:node.quaternion.clone(),scale:node.scale.clone()}); });
  }

  function register(gltf) {
    for (const clip of gltf.animations || []) if (/idle/i.test(clip.name)) embedded.push({root:gltf.scene,clip});
  }

  function seek(time) {
    if (!mixers.length || clipDuration <= 0) return;
    const clamped = Math.min(clipDuration, Math.max(0, Number(time) || 0));
    playing = false;
    currentTime = clamped;
    for (const mixer of mixers) mixer.setTime(clamped);
    sync();
  }

  function apply(data) {
    if (data.version !== 2 || data.space !== 'atelier-gltf-local') throw Error('Rebuild this clip with the current animation decoder');
    restore();
    let count = 0;
    for (const {root} of api.objects()) {
      const tracks = [];
      for (const track of data.tracks || []) {
        const bone = root.getObjectByName(THREE.PropertyBinding.sanitizeNodeName(track.bone));
        if (!bone?.isBone) continue;
        const times = track.times;
        if (!Array.isArray(times) || times.length<2 || !times.every(Number.isFinite)) throw Error('Invalid animation times');
        for (const [field,property,width,Track] of [['positions','position',3,THREE.VectorKeyframeTrack],['rotations','quaternion',4,THREE.QuaternionKeyframeTrack],['scales','scale',3,THREE.VectorKeyframeTrack]]) {
          const values = track[field]; if (!values) continue;
          if (values.length !== times.length*width || !values.every(Number.isFinite)) throw Error('Invalid bone track');
          tracks.push(new Track(`${bone.uuid}.${property}`,times,values));
        }
      }
      if (!tracks.length) continue;
      remember(root);
      const mixer = new THREE.AnimationMixer(root);
      mixer.clipAction(new THREE.AnimationClip(data.name,data.duration,tracks)).setLoop(THREE.LoopRepeat,Infinity).play();
      mixer.update(0); mixers.push(mixer); count += tracks.length;
    }
    if (!count) throw Error('This animation has no matching bones on the loaded model');
    clipDuration = Number(data.duration) || 0;
    currentTime = 0;
    playing = true;
  }

  async function play({quiet = false} = {}) {
    selected = $('viewport-animation').value || entries[0]?.game_rel;
    if (!selected || loading) return;
    $('viewport-animation').value = selected;
    if (selected === loaded && mixers.length) { playing = !playing; sync(); return; }
    const stamp = generation; loading = true; sync();
    try {
      if (selected.startsWith('embedded:')) {
        restore(); const item = embedded[Number(selected.split(':')[1])]; remember(item.root);
        const mixer = new THREE.AnimationMixer(item.root); mixer.clipAction(item.clip).setLoop(THREE.LoopRepeat,Infinity).play(); mixer.update(0);
        mixers = [mixer]; clipDuration = Number(item.clip.duration) || 0; currentTime = 0; playing = true;
      } else {
        const chosen = entries.find(e => e.game_rel === selected);
        const useAll = chosen && chosen.is_idle === false;
        const response = await api.fetch('/api/idle_animation',{method:'POST',headers:{'Content-Type':'application/json'},
          body:JSON.stringify({game_rel:meshRel,animation_rel:selected,...(useAll ? {all:true} : {})})}).then(r=>r.json());
        if (stamp !== generation) return;
        if (!response.ok) throw Error(response.error || 'Animation unavailable');
        apply(response);
      }
      loaded = selected;
      const chosen = entries.find(e => e.game_rel === selected);
      if (!selected.startsWith('embedded:') && chosen?.is_idle !== false) verifiedIdles.set(meshRel, selected);
      api.frame();
    } catch (error) {
      if (stamp === generation) {
        restore(); loaded = '';
        if (!quiet) api.notify(`Animation unavailable: ${error.message}`, 'warning');
      }
      return error;
    } finally { if (stamp === generation) { loading = false; sync(); } }
  }

  function populateSelect(select) {
    const rest = new Option(entries.length ? 'Rest pose' : 'No compatible pose found', '');
    const categories = new Set(entries.map(item => item.category).filter(Boolean));
    if (categories.size <= 1) {
      select.replaceChildren(rest, ...entries.map(item => new Option(item.label, item.game_rel)));
      return;
    }
    const groups = [];
    for (const cat of CATEGORY_ORDER) {
      const items = entries.filter(item => (item.category || 'idle') === cat);
      if (!items.length) continue;
      const group = document.createElement('optgroup');
      group.label = CATEGORY_LABELS[cat] || cat;
      for (const item of items) group.append(new Option(item.label, item.game_rel));
      groups.push(group);
    }
    select.replaceChildren(rest, ...groups);
  }

  async function discover(gameRel) {
    meshRel = gameRel; const stamp = generation;
    const select = $('viewport-animation');
    discovering = true; sync();
    entries = embedded.map((item,i) => ({label:item.clip.name,game_rel:`embedded:${i}`,category:'idle',is_idle:true}));
    try {
      const response = await api.fetch(`/api/idle_animations?game_rel=${encodeURIComponent(gameRel)}&all=1`).then(r=>r.json());
      if (stamp !== generation) return;
      if (response.ok) entries.push(...response.animations);
    } catch (_) { /* Rest pose and any embedded clips remain usable offline. */ }
    if (stamp !== generation) return;
    discovering = false;
    populateSelect(select);
    sync();
    // Auto-play only standing idles on open so emotes or combat clips never jump unexpectedly.
    const idleEntries = entries.filter(entry => entry.is_idle !== false);
    if (!idleEntries.length) return;
    let failure;
    const verified = verifiedIdles.get(gameRel);
    const choices = verified ? [...idleEntries.filter(entry=>entry.game_rel===verified), ...idleEntries.filter(entry=>entry.game_rel!==verified)] : idleEntries;
    for (const entry of choices) {
      select.value = entry.game_rel;
      failure = await play({quiet:true});
      if (stamp !== generation || !failure) return;
      if (!/skeleton is incompatible|Additive clips require/i.test(failure.message)) break;
    }
    if (failure) api.notify(`Standing idle unavailable: ${failure.message}`, 'warning');
  }

  $('viewport-play').addEventListener('click',play);
  $('viewport-animation').addEventListener('change',() => {
    if (!$('viewport-animation').value) { restore(); loaded = ''; api.frame(); sync(); }
    else play();
  });
  $('viewport-scrub')?.addEventListener('input', event => {
    seek(event.target.value);
  });

  return {
    reset,
    register,
    discover,
    seek,
    loading: () => loading || discovering,
    update: delta => {
      if (!playing || !mixers.length) return;
      for (const mixer of mixers) mixer.update(delta);
      if (clipDuration > 0) {
        currentTime = (currentTime + delta) % clipDuration;
        const scrub = $('viewport-scrub');
        const readout = $('viewport-scrub-time');
        if (scrub && document.activeElement !== scrub) scrub.value = String(currentTime);
        if (readout) readout.textContent = formatTime(currentTime, clipDuration);
      }
    },
    pause: () => { const value = playing; playing = false; sync(); return value; },
    resume: value => { playing = !!value && !!mixers.length; sync(); },
  };
}

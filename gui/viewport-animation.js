import * as THREE from 'three';
const $ = id => document.getElementById(id);

export function createViewportAnimation(api) {
  let generation = 0, meshRel = '', selected = '', loaded = '', loading = false, discovering = false, playing = false;
  let mixers = [], embedded = [], entries = [];
  const poses = new Map();
  function sync() {
    const button = $('viewport-play');
    button.disabled = loading || discovering || !entries.length;
    button.textContent = discovering ? 'Finding idle…' : loading ? 'Loading idle…' : playing ? 'Pause idle' : entries.length ? 'Play idle' : 'No idle available';
    button.setAttribute('aria-pressed', String(playing));
    button.title = loading ? 'Decoding the selected standing idle' : entries.length ? 'Choose an idle, then play or pause it' : 'No standing idle was found for this mesh';
    $('viewport-animation').disabled = loading || discovering || !entries.length;
    api.changed?.();
  }
  function restore() {
    for (const mixer of mixers) { mixer.stopAllAction(); mixer.uncacheRoot(mixer.getRoot()); }
    mixers = [];
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
  function apply(data) {
    if (data.version !== 2 || data.space !== 'atelier-gltf-local') throw Error('Rebuild this idle with the current animation decoder');
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
    if (!count) throw Error('This idle has no matching bones on the loaded model');
    playing = true;
  }
  async function play() {
    selected = $('viewport-animation').value || entries[0]?.game_rel;
    if (!selected || loading) return;
    $('viewport-animation').value = selected;
    if (selected === loaded && mixers.length) { playing = !playing; sync(); return; }
    const stamp = generation; loading = true; sync();
    try {
      if (selected.startsWith('embedded:')) {
        restore(); const item = embedded[Number(selected.split(':')[1])]; remember(item.root);
        const mixer = new THREE.AnimationMixer(item.root); mixer.clipAction(item.clip).setLoop(THREE.LoopRepeat,Infinity).play(); mixer.update(0);
        mixers = [mixer]; playing = true;
      } else {
        const response = await api.fetch('/api/idle_animation',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({game_rel:meshRel,animation_rel:selected})}).then(r=>r.json());
        if (stamp !== generation) return;
        if (!response.ok) throw Error(response.error || 'Idle animation unavailable');
        apply(response);
      }
      loaded = selected; api.frame();
    } catch (error) {
      if (stamp === generation) { restore(); loaded = ''; api.notify(`Standing idle unavailable: ${error.message}`, 'warning'); }
    } finally { if (stamp === generation) { loading = false; sync(); } }
  }
  async function discover(gameRel) {
    meshRel = gameRel; const stamp = generation;
    const select = $('viewport-animation');
    discovering = true; sync();
    entries = embedded.map((item,i) => ({label:item.clip.name,game_rel:`embedded:${i}`}));
    try {
      const response = await api.fetch(`/api/idle_animations?game_rel=${encodeURIComponent(gameRel)}`).then(r=>r.json());
      if (stamp !== generation) return;
      if (response.ok) entries.push(...response.animations);
    } catch (_) { /* Rest pose and any embedded clips remain usable offline. */ }
    if (stamp !== generation) return;
    discovering = false;
    select.replaceChildren(new Option(entries.length ? 'Rest pose' : 'No compatible idle found',''),...entries.map(item=>new Option(item.label,item.game_rel)));
    sync();
    if (entries.length) { select.value=entries[0].game_rel; await play(); }
  }
  $('viewport-play').addEventListener('click',play);
  $('viewport-animation').addEventListener('change',() => {
    if (!$('viewport-animation').value) { restore(); loaded = ''; api.frame(); sync(); }
    else play();
  });
  return {reset,register,discover,loading:()=>loading||discovering,update:delta=>{if(playing) for(const mixer of mixers) mixer.update(delta);},
    pause:()=>{const value=playing;playing=false;sync();return value;},resume:value=>{playing=!!value && !!mixers.length;sync();}};
}

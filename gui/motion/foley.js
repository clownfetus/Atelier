// Opt-in synthesized motion sounds. No files, no audio until an enabled gesture.
(() => {
  'use strict';
  let enabled=false,context=null;const active=new Set();
  try{enabled=localStorage.getItem('atelier.foley')==='1';}catch(_){}
  const allowed=()=>enabled&&AtelierMotionPolicy.mode()==='full'&&!document.hidden;
  function audio(){
    if(!context){const Audio=window.AudioContext||window.webkitAudioContext;if(!Audio)return null;context=new Audio();}
    if(context.state==='suspended')context.resume().catch(()=>{});return context;
  }
  document.addEventListener('pointerdown',()=>{if(allowed())try{audio();}catch(_){}},{capture:true,passive:true});
  function play(kind){
    if(!allowed()||!['drop','pop','splat'].includes(kind))return false;
    if(!context)return false;
    try{
      const ctx=audio();if(!ctx||ctx.state!=='running')return false;
      const time=ctx.currentTime,duration=kind==='pop'?.09:.14,gain=ctx.createGain();
      gain.gain.setValueAtTime(.0001,time);gain.gain.exponentialRampToValueAtTime(.055,time+.008);gain.gain.exponentialRampToValueAtTime(.0001,time+duration);gain.connect(ctx.destination);
      let source;
      if(kind==='splat'){
        const buffer=ctx.createBuffer(1,Math.ceil(ctx.sampleRate*duration),ctx.sampleRate),samples=buffer.getChannelData(0);
        for(let i=0;i<samples.length;i++)samples[i]=(Math.random()*2-1)*(1-i/samples.length);
        source=ctx.createBufferSource();source.buffer=buffer;
      }else{source=ctx.createOscillator();source.type=kind==='pop'?'triangle':'sine';source.frequency.setValueAtTime(kind==='pop'?350:220,time);source.frequency.exponentialRampToValueAtTime(kind==='pop'?650:65,time+duration);}
      const sound={source,gain};active.add(sound);
      source.connect(gain);source.onended=()=>{active.delete(sound);source.disconnect();gain.disconnect();};source.start(time);source.stop(time+duration);return true;
    }catch(_){return false;}
  }
  // The success click (SPEC section 6): a tick, a thump and a two-note chime, once per moment,
  // however many glyphs reach the same success together.
  let lastClick=-1;
  function click(){
    if(!allowed()||!context)return false;
    try{
      const ctx=audio();if(!ctx||ctx.state!=='running')return false;
      const time=ctx.currentTime;if(lastClick>=0&&time-lastClick<.2)return false;lastClick=time;
      const out=ctx.createGain();out.gain.value=.5;out.connect(ctx.destination);
      const sources=[];
      const noise=ctx.createBufferSource(),buffer=ctx.createBuffer(1,Math.ceil(ctx.sampleRate*.03),ctx.sampleRate),samples=buffer.getChannelData(0);
      for(let i=0;i<samples.length;i++)samples[i]=(Math.random()*2-1)*Math.pow(1-i/samples.length,4);
      noise.buffer=buffer;const band=ctx.createBiquadFilter();band.type='bandpass';band.frequency.value=3200;band.Q.value=1.2;
      noise.connect(band).connect(out);noise.start(time);sources.push(noise);
      const thump=ctx.createOscillator(),body=ctx.createGain();thump.type='sine';
      thump.frequency.setValueAtTime(180,time);thump.frequency.exponentialRampToValueAtTime(70,time+.12);
      body.gain.setValueAtTime(.0001,time);body.gain.exponentialRampToValueAtTime(.9,time+.004);body.gain.exponentialRampToValueAtTime(.0001,time+.16);
      thump.connect(body).connect(out);thump.start(time);thump.stop(time+.18);sources.push(thump);
      for(const [frequency,delay] of [[880,.16],[1318.5,.24]]){
        const chime=ctx.createOscillator(),level=ctx.createGain();chime.type='triangle';chime.frequency.value=frequency;
        level.gain.setValueAtTime(.0001,time+delay);level.gain.exponentialRampToValueAtTime(.18,time+delay+.01);level.gain.exponentialRampToValueAtTime(.0001,time+delay+.5);
        chime.connect(level).connect(out);chime.start(time+delay);chime.stop(time+delay+.55);sources.push(chime);
      }
      let playing=sources.length;
      for(const source of sources){
        const sound={source,gain:out};active.add(sound);
        source.onended=()=>{active.delete(sound);source.disconnect();if(--playing===0)out.disconnect();};
      }
      return true;
    }catch(_){return false;}
  }
  function sync(){const control=document.getElementById('settings-foley');if(control)control.checked=enabled;}
  document.addEventListener('DOMContentLoaded',()=>{sync();document.getElementById('settings-foley')?.addEventListener('change',event=>{enabled=event.target.checked;try{localStorage.setItem('atelier.foley',enabled?'1':'0');}catch(_){}if(!enabled)stop();});});
  window.addEventListener('storage',event=>{if(event.key==='atelier.foley'){enabled=event.newValue==='1';sync();}});
  const stop=()=>{for(const {source,gain} of active){try{source.stop();}catch(_){}gain.disconnect();}active.clear();if(context?.state==='running')context.suspend().catch(()=>{});};
  document.addEventListener('visibilitychange',()=>{if(document.hidden)stop();});
  AtelierMotionPolicy.query().addEventListener('change',()=>{if(!allowed())stop();});
  window.addEventListener('pagehide',()=>{stop();context?.close().catch(()=>{});context=null;});
  window.AtelierFoley=Object.freeze({play,click,enabled:()=>enabled});
})();

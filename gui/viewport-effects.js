import * as THREE from 'three';

// Display effects own their GPU resources and never modify project assets.
export function createViewportFloor() {
  const floor = new THREE.Group();
  const vertexShader = `varying vec2 vUv;void main(){vUv=uv;gl_Position=projectionMatrix*modelViewMatrix*vec4(position,1.);}`;
  const grid = new THREE.Mesh(new THREE.PlaneGeometry(1200,1200), new THREE.ShaderMaterial({
    transparent:true, depthWrite:false, toneMapped:false, vertexShader,
    fragmentShader:`varying vec2 vUv;void main(){
      vec2 p=vUv*60.,edge=abs(fract(p-.5)-.5)/max(fwidth(p),vec2(.001));
      float line=1.-min(min(edge.x,edge.y),1.);
      float fade=1.-smoothstep(.12,.49,length(vUv-.5));
      gl_FragColor=vec4(.27,.36,.46,line*fade*.35);
      #include <colorspace_fragment>
    }`,
  }));
  grid.rotation.x=-Math.PI/2; floor.add(grid);
  const shadow = new THREE.Mesh(new THREE.PlaneGeometry(150,100), new THREE.ShaderMaterial({
    transparent:true,depthWrite:false,toneMapped:false,vertexShader,
    fragmentShader:`varying vec2 vUv;void main(){float a=1.-smoothstep(.03,.5,length(vUv-.5));gl_FragColor=vec4(0.,0.,0.,a*a*.36);}`,
  }));
  shadow.rotation.x=-Math.PI/2; shadow.position.y=.05; floor.add(shadow);
  floor.userData.dispose=()=>floor.traverse(o=>{o.geometry?.dispose();o.material?.dispose();});
  return floor;
}

export function createViewportEffects({renderer,scene,camera,modelRoot,grid,reduced}) {
  const colors=new Map(), configured=new WeakSet(), retired=new Map();
  let bloom=null, bloomEnabled=false;
  const outline=new THREE.ShaderMaterial({
    uniforms:{accent:{value:new THREE.Color('#98b7e2')},resolution:{value:new THREE.Vector2(1,1)}},
    side:THREE.BackSide,depthWrite:false,toneMapped:false,
    vertexShader:`
      #include <common>
      #include <morphtarget_pars_vertex>
      #include <skinning_pars_vertex>
      uniform vec2 resolution;
      void main(){
        #include <beginnormal_vertex>
        #include <morphnormal_vertex>
        #include <skinbase_vertex>
        #include <skinnormal_vertex>
        #include <begin_vertex>
        #include <morphtarget_vertex>
        #include <skinning_vertex>
        vec4 p=projectionMatrix*modelViewMatrix*vec4(transformed,1.);
        vec2 n=(projectionMatrix*vec4(normalize(normalMatrix*objectNormal),0.)).xy;
        if(length(n)>.0001)p.xy+=normalize(n)*3.5/resolution*p.w;
        gl_Position=p;
      }`,
    fragmentShader:`uniform vec3 accent;void main(){gl_FragColor=vec4(accent,1.);
      #include <colorspace_fragment>
    }`,
  });
  const invisible=new THREE.MeshBasicMaterial({visible:false});
  const loadingScan=new THREE.ShaderMaterial({transparent:true,depthWrite:false,toneMapped:false,
    uniforms:{height:{value:new THREE.Vector2(0,1)},phase:{value:0},accent:{value:new THREE.Color('#accbff')}},
    vertexShader:`
      #include <common>
      #include <morphtarget_pars_vertex>
      #include <skinning_pars_vertex>
      varying float worldHeight;
      void main(){
        #include <skinbase_vertex>
        #include <begin_vertex>
        #include <morphtarget_vertex>
        #include <skinning_vertex>
        worldHeight=(modelMatrix*vec4(transformed,1.)).y;
        gl_Position=projectionMatrix*modelViewMatrix*vec4(transformed,1.);
      }`,
    fragmentShader:`varying float worldHeight;uniform vec2 height;uniform float phase;uniform vec3 accent;
      void main(){float y=(worldHeight-height.x)/max(.001,height.y-height.x);
        float band=1.-smoothstep(.01,.15,abs(y-phase));gl_FragColor=vec4(accent,.03+band*.38);
        #include <colorspace_fragment>
      }`});
  function tint(display, source, instant=false, emissiveOnly=false) {
    const now=performance.now(), emissive=source.emissive||new THREE.Color(0);
    let state=colors.get(source);
    if(!state) {
      state={color:source.color.clone(),emissive:emissive.clone(),fromColor:source.color.clone(),fromEmissive:emissive.clone(),
        targetColor:source.color.clone(),targetEmissive:emissive.clone(),start:now,map:source.map,mapStart:now-150,
        uniforms:{atelierPreviousMap:{value:source.map},atelierMapMix:{value:1}}};
      colors.set(source,state);
    }
    if(!state.targetColor.equals(source.color)||!state.targetEmissive.equals(emissive)) {
      state.fromColor.copy(state.color);state.fromEmissive.copy(state.emissive);
      state.targetColor.copy(source.color);state.targetEmissive.copy(emissive);state.start=now;
    }
    const amount=instant||reduced.matches||document.hidden?1:Math.min(1,(now-state.start)/150);
    if(amount===1){state.color.copy(state.targetColor);state.emissive.copy(state.targetEmissive);}
    else{state.color.lerpColors(state.fromColor,state.targetColor,amount);state.emissive.lerpColors(state.fromEmissive,state.targetEmissive,amount);}
    display.color.copy(emissiveOnly?state.emissive:state.color);display.emissive?.copy(state.emissive);
    if(emissiveOnly)display.color.multiplyScalar(source.emissiveIntensity||0);
    if(state.map!==source.map) {
      state.uniforms.atelierPreviousMap.value=state.map||source.map;
      state.mapStart=state.map&&source.map?now:now-150;state.map=source.map;
    }
    state.uniforms.atelierMapMix.value=instant||reduced.matches||document.hidden||display.map!==source.map?1:Math.min(1,(now-state.mapStart)/150);
    if(state.uniforms.atelierMapMix.value===1)state.uniforms.atelierPreviousMap.value=source.map;
    if(!configured.has(display)) {
      configured.add(display);display.customProgramCacheKey=()=> 'atelier-color-transition-v1';
      display.onBeforeCompile=shader=>{
        Object.assign(shader.uniforms,state.uniforms);
        shader.fragmentShader='uniform sampler2D atelierPreviousMap;\nuniform float atelierMapMix;\n'+shader.fragmentShader;
        shader.fragmentShader=shader.fragmentShader.replace('#include <map_fragment>',THREE.ShaderChunk.map_fragment.replace(
          'diffuseColor *= sampledDiffuseColor;',
          'diffuseColor *= mix(texture2D(atelierPreviousMap,vMapUv),sampledDiffuseColor,atelierMapMix);'));
      };
    }
  }
  function retireTexture(texture) {
    if(!texture)return;clearTimeout(retired.get(texture));
    retired.set(texture,setTimeout(()=>{texture.dispose();retired.delete(texture);},220));
  }
  function withMaterials(convert,draw) {
    const restore=[],floorVisible=grid.visible;grid.visible=false;
    const shown=m=>m.visible?convert(m):m;
    modelRoot.traverse(mesh=>{if(mesh.isMesh){restore.push([mesh,mesh.material]);mesh.material=Array.isArray(mesh.material)?mesh.material.map(shown):shown(mesh.material);}});
    try{draw();}finally{for(const [mesh,material]of restore)mesh.material=material;grid.visible=floorVisible;}
  }
  function drawOutline(name) {
    if(!name)return;
    outline.uniforms.accent.value.set(getComputedStyle(document.documentElement).getPropertyValue('--acc').trim()||'#98b7e2');
    renderer.getSize(outline.uniforms.resolution.value);
    const clear=renderer.autoClear;renderer.autoClear=false;
    try{withMaterials(m=>m.name===name?outline:invisible,()=>renderer.render(scene,camera));}finally{renderer.autoClear=clear;}
  }
  function drawLoading(bounds) {
    if(!bounds || bounds.isEmpty())return;
    loadingScan.uniforms.height.value.set(bounds.min.y,bounds.max.y);
    loadingScan.uniforms.phase.value=reduced.matches ? .5 : (performance.now()%1800)/1800;
    const clear=renderer.autoClear;renderer.autoClear=false;
    try{withMaterials(()=>loadingScan,()=>renderer.render(scene,camera));}finally{renderer.autoClear=clear;}
  }
  const quadVertex=`varying vec2 vUv;void main(){vUv=uv;gl_Position=vec4(position.xy,0.,1.);}`;
  function makeBloom() {
    const targets=Array.from({length:3},()=>new THREE.WebGLRenderTarget(1,1,{type:THREE.HalfFloatType,depthBuffer:false}));targets[0].depthBuffer=true;
    const blur=new THREE.ShaderMaterial({depthTest:false,depthWrite:false,toneMapped:false,
      uniforms:{image:{value:null},stepSize:{value:new THREE.Vector2()}},vertexShader:quadVertex,
      fragmentShader:`varying vec2 vUv;uniform sampler2D image;uniform vec2 stepSize;
        void main(){vec4 c=texture2D(image,vUv)*.227027;
          c+=(texture2D(image,vUv+stepSize*1.384615)+texture2D(image,vUv-stepSize*1.384615))*.316216;
          c+=(texture2D(image,vUv+stepSize*3.230769)+texture2D(image,vUv-stepSize*3.230769))*.070270;gl_FragColor=c;}`});
    const composite=new THREE.ShaderMaterial({depthTest:false,depthWrite:false,toneMapped:false,transparent:true,
      blending:THREE.CustomBlending,blendSrc:THREE.OneFactor,blendDst:THREE.OneFactor,blendSrcAlpha:THREE.OneFactor,blendDstAlpha:THREE.OneFactor,
      uniforms:{image:{value:targets[2].texture}},vertexShader:quadVertex,
      fragmentShader:`varying vec2 vUv;uniform sampler2D image;void main(){vec3 glow=vec3(1.)-exp(-texture2D(image,vUv).rgb*.45);
        gl_FragColor=vec4(glow,max(max(glow.r,glow.g),glow.b));
        #include <colorspace_fragment>
      }`});
    const quad=new THREE.Mesh(new THREE.PlaneGeometry(2,2),blur),quadScene=new THREE.Scene();quadScene.add(quad);
    return {targets,blur,composite,quad,quadScene,camera:new THREE.OrthographicCamera(),materials:new Map()};
  }
  function releaseBloom() {
    if(!bloom)return;bloom.targets.forEach(t=>t.dispose());bloom.blur.dispose();bloom.composite.dispose();bloom.quad.geometry.dispose();
    for(const m of bloom.materials.values())m.dispose();bloom=null;
  }
  function drawBloom() {
    if(!bloomEnabled)return;bloom ||= makeBloom();
    const {targets,blur,composite,quad,quadScene}=bloom;
    const size=renderer.getSize(new THREE.Vector2()),scale=Math.min(.5,512/size.x,512/size.y);
    const width=Math.max(1,Math.round(size.x*scale)),height=Math.max(1,Math.round(size.y*scale));
    for(const target of targets)if(target.width!==width||target.height!==height)target.setSize(width,height);
    const saved={target:renderer.getRenderTarget(),scissor:renderer.getScissor(new THREE.Vector4()),test:renderer.getScissorTest(),
      clear:renderer.autoClear,color:renderer.getClearColor(new THREE.Color()),alpha:renderer.getClearAlpha()};
    try {
      renderer.setScissorTest(false);renderer.autoClear=true;renderer.setClearColor(0x000000,0);renderer.setRenderTarget(targets[0]);
      withMaterials(source=>{
        let material=bloom.materials.get(source);if(!material){material=new THREE.MeshBasicMaterial();bloom.materials.set(source,material);}
        material.color.copy(source.emissive||new THREE.Color(0)).multiplyScalar(source.emissiveIntensity||0);
        if(material.map!==source.emissiveMap){material.map=source.emissiveMap||null;material.needsUpdate=true;}
        material.side=source.side;material.transparent=source.transparent;material.opacity=source.opacity;
        material.alphaMap=source.alphaMap;material.alphaTest=source.alphaTest;material.clippingPlanes=source.clippingPlanes;
        return material;
      },()=>renderer.render(scene,camera));
      quad.material=blur;blur.uniforms.image.value=targets[0].texture;blur.uniforms.stepSize.value.set(2/width,0);
      renderer.setRenderTarget(targets[1]);renderer.render(quadScene,bloom.camera);
      blur.uniforms.image.value=targets[1].texture;blur.uniforms.stepSize.value.set(0,2/height);
      renderer.setRenderTarget(targets[2]);renderer.render(quadScene,bloom.camera);
      renderer.setRenderTarget(saved.target);renderer.setScissor(saved.scissor);renderer.setScissorTest(saved.test);
      renderer.autoClear=false;quad.material=composite;renderer.render(quadScene,bloom.camera);
    }finally{renderer.setRenderTarget(saved.target);renderer.setScissor(saved.scissor);renderer.setScissorTest(saved.test);
      renderer.setClearColor(saved.color,saved.alpha);renderer.autoClear=saved.clear;}
  }
  function clear(){colors.clear();for(const [texture,timer]of retired){clearTimeout(timer);texture.dispose();}retired.clear();releaseBloom();}
  function destroy(){clear();outline.dispose();invisible.dispose();loadingScan.dispose();grid.userData.dispose?.();}
  window.addEventListener('pagehide',destroy,{once:true});
  return {tint,retireTexture,drawOutline,drawLoading,drawBloom,clear,setBloom:value=>{bloomEnabled=value;if(!value)releaseBloom();},
    state:()=>({bloom:bloomEnabled,targets:bloom?.targets.length||0,tweens:colors.size,
      colors:[...colors].map(([source,state])=>({name:source.name,target:source.color.toArray(),shown:state.color.toArray(),mapMix:state.uniforms.atelierMapMix.value}))})};
}

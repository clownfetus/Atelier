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
  // Krackle loading scan (gui/motion/README.md): while the appearance loads, a band of solid charge
  // energy travels up the model's screen silhouette. Bubbles are holes that show the model behind,
  // rift satellites trail it and a 45° screen of charge dots covers the rest. Sizes are CSS pixels.
  const scanUniforms={span:{value:new THREE.Vector4()},edges:{value:new THREE.Vector2()},mode:{value:0},time:{value:0},
    boil:{value:0},ratio:{value:1},charge:{value:new THREE.Color()},rift:{value:new THREE.Color()},glint:{value:new THREE.Color()}};
  const opaque=new THREE.DataTexture(new Uint8Array([255,255,255,255]),1,1);opaque.needsUpdate=true;
  const scanVertex=`
    #include <common>
    #include <morphtarget_pars_vertex>
    #include <skinning_pars_vertex>
    uniform mat3 cutTransform,alphaTransform;
    varying vec2 vCutUv,vAlphaUv;varying vec3 vFacing,vView;
    void main(){
      #include <beginnormal_vertex>
      #include <morphnormal_vertex>
      #include <skinbase_vertex>
      #include <skinnormal_vertex>
      #include <begin_vertex>
      #include <morphtarget_vertex>
      #include <skinning_vertex>
      vec4 view=modelViewMatrix*vec4(transformed,1.);
      vFacing=normalMatrix*objectNormal;vView=-view.xyz;vCutUv=(cutTransform*vec3(uv,1.)).xy;vAlphaUv=(alphaTransform*vec3(uv,1.)).xy;
      gl_Position=projectionMatrix*view;
    }`;
  const scanFragment=`
    uniform vec4 span;uniform vec2 edges;uniform float mode,time,boil,ratio,cutoff;
    uniform vec3 charge,rift,glint;uniform sampler2D cutMap,alphaMap;
    varying vec2 vCutUv,vAlphaUv;varying vec3 vFacing,vView;
    float hash(vec2 c){return fract(sin(dot(c,vec2(127.1,311.7)))*43758.5453);}
    // A bubbly edge: circles of varied size strung along a line; returns the edge's offset at x.
    float scallop(float x,float cell,float seed){
      float c=floor(x/cell),h=-cell;
      for(int i=-1;i<=1;i++){float k=c+float(i),r=cell*(.52+.3*hash(vec2(k,seed))),d=x-(k+.5)*cell;h=max(h,sqrt(max(r*r-d*d,0.))-r*.4);}
      return h;
    }
    void main(){
      if(texture2D(cutMap,vCutUv).a*texture2D(alphaMap,vAlphaUv).g<cutoff)discard;
      vec2 p=gl_FragCoord.xy/ratio;
      float top=edges.y+scallop(p.x,16.,1.),bottom=edges.x-scallop(p.x+7.,21.,5.),alpha=1.;
      vec3 ink=vec3(-1.);
      if(p.y>=bottom&&p.y<=top){
        // Energy. Bubbles ride with the band, gather on the shadow (left) side, keep one step clear
        // of the band's edges and of the model's own silhouette, and boil out of step.
        vec2 local=vec2(p.x,p.y-edges.y),cell=floor(local/13.),centre=(cell+.5)*13.;
        float seed=hash(cell),r=mix(1.7,4.4,hash(cell+17.))*(1.+boil*.2*sin(time*6.04+seed*6.28));
        float side=((span.x+span.z)*.5-centre.x)/max(8.,(span.z-span.x)*.5);
        float depth=min(-6.-centre.y,centre.y+edges.y-edges.x-7.);
        float facing=abs(dot(normalize(vFacing),normalize(vView)));
        if(seed<.06+.36*smoothstep(-.2,.9,side)&&depth>=r+3.&&facing>.3)alpha=clamp((length(local-centre)-r)*ratio+.5,0.,1.);
        alpha=min(alpha,clamp(min(top-p.y,p.y-bottom)*ratio+.5,0.,1.));
        ink=charge;
        // A few crisp Paper glints catch on the crest.
        float g=floor(p.x/41.),gx=(g+.5)*41.+(hash(vec2(g,3.))-.5)*16.;
        if(hash(vec2(g,11.))<.45&&length(p-vec2(gx,edges.y+scallop(gx,16.,1.)-6.-hash(vec2(g,9.))*3.))<1.6+hash(vec2(g,13.)))ink=glint;
      } else if(p.y<bottom){
        // The handover sweep leaves the finished appearance behind it; the loop trails rift satellites.
        if(mode>.5)discard;
        vec2 local=vec2(p.x,p.y-edges.x),cell=floor(local/18.),centre=(cell+.5)*18.+(vec2(hash(cell+3.),hash(cell+5.))-.5)*6.;
        float r=(5.4+min(0.,centre.y)*.075)*(.55+.45*hash(cell+7.)),d=length(local-centre);
        if(hash(cell)<.5&&r>1.&&d<r+1./ratio){
          ink=rift;alpha=clamp((r-d)*ratio+.5,0.,1.);
          if(r>2.6)alpha=min(alpha,clamp((length(local-centre-vec2(.3,-.25)*r)-r*.42)*ratio+.5,0.,1.));
        }
      }
      if(ink.r<0.){
        // Charge dots on a 45° screen swell as the crest approaches.
        vec2 c=floor(mat2(.70710678,-.70710678,.70710678,.70710678)*p/7.)+.5,centre=mat2(.70710678,.70710678,-.70710678,.70710678)*c*7.;
        float ahead=centre.y-edges.y,r=ahead>0.?mix(3.3,1.35,smoothstep(0.,52.,ahead)):1.35;
        ink=charge;alpha=clamp((r-length(p-centre))*ratio+.5,0.,1.);
      }
      if(alpha<=0.)discard;
      gl_FragColor=vec4(ink,alpha);
      #include <colorspace_fragment>
    }`;
  const scans=new Map(),corner=new THREE.Vector3(),canvasSize=new THREE.Vector2();
  let inkKey='',inks=null,scan=null,scanFrames=0;
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
    const shown=m=>m.userData?.heldDuplicate?invisible:m.visible?convert(m):m;
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
  // One scan variant per source keeps its side and alpha cut-out, so hair cards stay cards.
  function scanFor(source) {
    let material=scans.get(source);
    if(!material){
      material=new THREE.ShaderMaterial({transparent:true,depthWrite:false,toneMapped:false,vertexShader:scanVertex,fragmentShader:scanFragment,
        uniforms:{...scanUniforms,cutMap:{value:opaque},alphaMap:{value:opaque},cutoff:{value:0},cutTransform:{value:new THREE.Matrix3()},alphaTransform:{value:new THREE.Matrix3()}}});
      scans.set(source,material);
    }
    const cut=source.map&&(source.alphaTest>0||source.transparent)?source.map:null;
    material.side=source.side;material.uniforms.cutMap.value=cut||opaque;material.uniforms.alphaMap.value=source.alphaMap||opaque;
    material.uniforms.cutoff.value=cut||source.alphaMap?source.alphaTest||.5:0;
    if(cut){cut.updateMatrix();material.uniforms.cutTransform.value.copy(cut.matrix);}else material.uniforms.cutTransform.value.identity();
    if(source.alphaMap){source.alphaMap.updateMatrix();material.uniforms.alphaTransform.value.copy(source.alphaMap.matrix);}else material.uniforms.alphaTransform.value.identity();
    return material;
  }
  // Live theme inks; charge is fitted (3:1) against the stage backdrop the energy meets at the silhouette.
  function scanInks() {
    const stage=document.getElementById('viewport-stage')||document.documentElement,style=getComputedStyle(stage);
    const read=(name,fallback)=>style.getPropertyValue(name).trim()||fallback,backdrop=stage.dataset?.backdrop||'gradient';
    const charge=read('--krackle-charge','#2a9fd6'),rift=read('--krackle-rift','#8a6cff'),glint=read('--krackle-glint','#eee5cf');
    const ends=[read('--vp-stage-top','#2b3e56'),read('--vp-stage-bottom','#111c2d'),read('--viewport-backdrop','#14161b')];
    const key=[charge,rift,glint,backdrop,...ends].join();
    if(key===inkKey)return inks;
    let surface=backdrop==='solid'?ends[2]:backdrop==='checker'?'#cbd0d7':'',fitted=charge;
    try{
      if(!surface)surface='#'+new THREE.Color(ends[0]).lerp(new THREE.Color(ends[1]),.5).getHexString();
      fitted=window.AtelierKrackleInks?.fit(charge,surface)||charge;
      scanUniforms.charge.value.set(fitted);scanUniforms.rift.value.set(rift);scanUniforms.glint.value.set(glint);
    }catch(_){scanUniforms.charge.value.set('#2a9fd6');scanUniforms.rift.value.set('#8a6cff');scanUniforms.glint.value.set('#eee5cf');}
    inkKey=key;inks={charge:'#'+scanUniforms.charge.value.getHexString(),rift:'#'+scanUniforms.rift.value.getHexString(),surface};
    return inks;
  }
  // The model's on-screen extent in CSS pixels, y up like gl_FragCoord.
  function screenSpan(bounds) {
    renderer.getSize(canvasSize);camera.updateMatrixWorld();
    let x0=Infinity,y0=Infinity,x1=-Infinity,y1=-Infinity;
    for(let i=0;i<8;i++){
      corner.set(i&1?bounds.max.x:bounds.min.x,i&2?bounds.max.y:bounds.min.y,i&4?bounds.max.z:bounds.min.z).applyMatrix4(camera.matrixWorldInverse);
      if(corner.z>-camera.near)return [0,0,canvasSize.x,canvasSize.y];
      corner.applyMatrix4(camera.projectionMatrix);
      const x=(corner.x+1)*canvasSize.x/2,y=(corner.y+1)*canvasSize.y/2;
      x0=Math.min(x0,x);x1=Math.max(x1,x);y0=Math.min(y0,y);y1=Math.max(y1,y);
    }
    return [Math.max(0,x0),Math.max(0,y0),Math.min(canvasSize.x,x1),Math.min(canvasSize.y,y1)];
  }
  // sweep=null loops while loading (still under reduced motion); 0..1 is the one handover sweep
  // that leaves the loaded appearance behind it.
  function drawLoading(bounds,sweep=null) {
    if(reduced.matches || window.AtelierMotionPolicy?.allows(2)===false || document.hidden){stopLoading();return;}
    if(!bounds || bounds.isEmpty())return;
    const span=screenSpan(bounds),height=Math.max(1,span[3]-span[1]),band=THREE.MathUtils.clamp(height*.17,26,84);
    const still=reduced.matches||window.AtelierMotionPolicy?.allows(2)===false,now=performance.now();
    const period=2*(window.AtelierMotion?.beatMs||1040);
    const crest=sweep!==null?THREE.MathUtils.lerp(span[1],span[3]+band,sweep)
      :still?span[1]+height*.58+band/2:THREE.MathUtils.lerp(span[1]-8,span[3]+band+72,now%period/period);
    scanUniforms.span.value.set(...span);scanUniforms.edges.value.set(crest-band,crest);
    scanUniforms.mode.value=sweep===null?0:1;scanUniforms.time.value=still?0:now/1000%1000;scanUniforms.boil.value=still?0:1;
    scanUniforms.ratio.value=renderer.getPixelRatio();
    scan={mode:sweep!==null?'sweep':still?'still':'loop',at:now,span,trailing:crest-band,crest,...scanInks()};
    const clear=renderer.autoClear;renderer.autoClear=false;
    try{withMaterials(scanFor,()=>{scanFrames++;renderer.render(scene,camera);});}finally{renderer.autoClear=clear;}
  }
  function releaseScans(){for(const material of scans.values())material.dispose();scans.clear();}
  function stopLoading(){if(scan || scans.size){scan=null;releaseScans();}}
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
  function clear(){colors.clear();for(const [texture,timer]of retired){clearTimeout(timer);texture.dispose();}retired.clear();releaseBloom();stopLoading();}
  function destroy(){clear();outline.dispose();invisible.dispose();opaque.dispose();grid.userData.dispose?.();}
  window.addEventListener('pagehide',destroy,{once:true});
  return {tint,retireTexture,drawOutline,drawLoading,stopLoading,drawBloom,clear,setBloom:value=>{bloomEnabled=value;if(!value)releaseBloom();},
    state:()=>({bloom:bloomEnabled,targets:bloom?.targets.length||0,tweens:colors.size,scan,scans:scans.size,scanFrames,
      colors:[...colors].map(([source,state])=>({name:source.name,target:source.color.toArray(),shown:state.color.toArray(),mapMix:state.uniforms.atelierMapMix.value}))})};
}

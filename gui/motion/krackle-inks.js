// Pure sRGB ink fitting and CIE76 distance (CIELAB, D65 reference white).
// Transfer/XYZ conventions: https://www.w3.org/TR/css-color-4/#color-conversion-code
(() => {
  'use strict';
  const clamp=(n,a=0,b=1)=>Math.max(a,Math.min(b,n));
  function rgb(value) {
    if(Array.isArray(value)&&value.length>=3&&value.slice(0,3).every(Number.isFinite))return value.slice(0,3).map(n=>clamp(n,0,255));
    let match=/^#([\da-f]{3}|[\da-f]{6})$/i.exec(String(value).trim());
    if(match){let hex=match[1];if(hex.length===3)hex=[...hex].map(c=>c+c).join('');return hex.match(/../g).map(n=>parseInt(n,16));}
    match=/^rgba?\(\s*([\d.]+)[, ]+\s*([\d.]+)[, ]+\s*([\d.]+)/.exec(String(value));
    if(match)return match.slice(1).map(n=>clamp(+n,0,255));
    throw Error('Expected an sRGB colour.');
  }
  const hex=color=>'#'+rgb(color).map(n=>Math.round(n).toString(16).padStart(2,'0')).join('');
  const linear=n=>{n/=255;return n<=.04045?n/12.92:((n+.055)/1.055)**2.4;};
  const luminance=color=>rgb(color).map(linear).reduce((sum,n,i)=>sum+n*[.2126,.7152,.0722][i],0);
  const contrast=(a,b)=>(Math.max(luminance(a),luminance(b))+.05)/(Math.min(luminance(a),luminance(b))+.05);
  const surfaceKind=surface=>luminance(surface)<.179?'dark':'light';
  function hsl(color) {
    const [r,g,b]=rgb(color).map(n=>n/255),max=Math.max(r,g,b),min=Math.min(r,g,b),d=max-min,l=(max+min)/2;
    const h=!d?0:max===r?((g-b)/d+6)%6:max===g?(b-r)/d+2:(r-g)/d+4;
    return [h*60,d?d/(1-Math.abs(2*l-1)):0,l];
  }
  function fromHsl(h,s,l) {
    h=((h%360)+360)%360;s=clamp(s);l=clamp(l);
    const c=(1-Math.abs(2*l-1))*s,x=c*(1-Math.abs(h/60%2-1)),m=l-c/2;
    const values=h<60?[c,x,0]:h<120?[x,c,0]:h<180?[0,c,x]:h<240?[0,x,c]:h<300?[x,0,c]:[c,0,x];
    return hex(values.map(n=>(n+m)*255));
  }
  function lab(color) {
    const [r,g,b]=rgb(color).map(linear);
    const xyz=[.4123907993*r+.3575843394*g+.1804807884*b,
      .2126390059*r+.7151686788*g+.0721923154*b,
      .0193308187*r+.1191947798*g+.9505321522*b];
    const white=[.3127/.329,1,(1-.3127-.329)/.329];
    const f=xyz.map((n,i)=>{n/=white[i];return n>216/24389?Math.cbrt(n):(24389/27*n+16)/116;});
    return [116*f[1]-16,500*(f[0]-f[1]),200*(f[1]-f[2])];
  }
  const deltaE=(a,b)=>{const x=lab(a),y=lab(b);return Math.hypot(...x.map((n,i)=>n-y[i]));};
  const hueDistance=(a,b)=>{const d=Math.abs(hsl(a)[0]-hsl(b)[0]);return Math.min(d,360-d);};
  function defaults(surface) {
    const dark=surfaceKind(surface)==='dark';
    return {charge:dark?'#2a9fd6':'#2693c6',rift:'#8a6cff',success:dark?'#eee5cf':'#121216',
      warn:dark?'#f5c02e':'#9a6b00',fault:dark?'#e0407a':'#c8336a',hole:'#121216',successHole:dark?'#121216':'#eee5cf'};
  }
  function fit(color,surface) {
    color=hex(color);if(contrast(color,surface)>=3)return color;
    const [h,s,l]=hsl(color),dark=surfaceKind(surface)==='dark';
    let low=0,high=1,result=dark?'#ffffff':'#000000';
    for(let i=0;i<18;i++) {
      const t=(low+high)/2,candidate=fromHsl(h,s,l+(dark?1-l:-l)*t);
      if(contrast(candidate,surface)>=3){result=candidate;high=t;}else low=t;
    }
    return result;
  }
  function clashes(color,surface,other=null) {
    const inks=defaults(surface),outcomes=[inks.success,inks.warn,inks.fault];
    const saturated=hsl(color)[1]>.35;
    return outcomes.some(ink=>deltaE(color,ink)<25) ||
      saturated&&[inks.warn,inks.fault].some(ink=>hueDistance(color,ink)<12) ||
      !!other&&(deltaE(color,other)<25||hueDistance(color,other)<35);
  }
  const cache=new Map();
  function guard(charge,rift,surface,options={}) {
    const key=JSON.stringify([charge,rift,surface,options]);if(cache.has(key))return {...cache.get(key)};
    const candidates=options.candidates||[],inks=defaults(surface);
    function resolve(value,other) {
      const initial=fit(value,surface),valid=c=>contrast(c,surface)>=3&&!clashes(c,surface,other);
      if(valid(initial))return {color:initial,shifted:false,clash:false};
      if(options.handPicked)return {color:initial,shifted:false,clash:true};
      const [h,s,l]=hsl(initial);
      // Gold/amber move toward orange; pink moves toward magenta. Avoid turning warm skins green.
      const directions=h>=30&&h<=75||h>=300&&h<=355?[-1]:[-1,1];
      const lightness=[0];for(let i=1;i<=14;i++)lightness.push(-i*.02,i*.02);
      function nudge(start,end,dirs) {
        let best=null,cost=Infinity;
        for(let angle=start;angle<=end;angle++) {
          for(const direction of dirs)for(const dl of lightness) {
            const candidate=fromHsl(h+direction*angle,s,clamp(l+dl));
            if(!valid(candidate))continue;
            const distance=deltaE(initial,candidate);if(distance<cost){best=candidate;cost=distance;}
          }
        }
        return best;
      }
      let color=nudge(0,45,directions);
      if(!color)for(const candidate of candidates){const fitted=fit(candidate,surface);if(valid(fitted)){color=fitted;break;}}
      if(!color)color=nudge(46,180,[-1,1]);
      // A neutral second swatch has no hue to rotate; use a readable chromatic fallback.
      if(!color)for(let angle=0;angle<360;angle+=5){const candidate=fit(fromHsl(angle,.8,.5),surface);if(valid(candidate)){color=candidate;break;}}
      return {color:color||initial,shifted:!!color,clash:!color};
    }
    const a=resolve(charge||inks.charge,null),b=resolve(rift||inks.rift,a.color);
    const result={charge:a.color,rift:b.color,shifted:a.shifted||b.shifted,clash:a.clash||b.clash};
    if(cache.size>100)cache.clear();cache.set(key,result);return {...result};
  }
  const api=Object.freeze({fit,guard,defaults,contrast,deltaE,hueDistance,lab,surfaceKind});
  if(typeof module!=='undefined'&&module.exports)module.exports=api;
  else globalThis.AtelierKrackleInks=api;
})();

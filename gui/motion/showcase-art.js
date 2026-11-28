// Shared still backdrop for explicit Showcase views and their exported images: a neutral gradient,
// with a quiet centre that separates the model from the frame without changing its materials.
(() => {
  'use strict';
  function tintMask(image, width, height, fill) {
    const buffer = document.createElement('canvas');
    buffer.width = Math.max(1, Math.round(width));
    buffer.height = Math.max(1, Math.round(height));
    const bctx = buffer.getContext('2d');
    if (!bctx) return null;
    bctx.drawImage(image, 0, 0, buffer.width, buffer.height);
    bctx.globalCompositeOperation = 'source-in';
    bctx.fillStyle = fill;
    bctx.fillRect(0, 0, buffer.width, buffer.height);
    return buffer;
  }
  function draw(context,width,height,options) {
    context.save();
    const ground=context.createRadialGradient(width*.5,height*.34,0,width*.5,height*.42,Math.max(width,height)*.78);
    ground.addColorStop(0,'#323c4a');ground.addColorStop(.48,'#1d2632');ground.addColorStop(1,'#10151c');
    context.fillStyle=ground;context.fillRect(0,0,width,height);
    const mode=options&&typeof options==='object'?options.mode:'';
    if(mode==='story'&&options.art&&options.art.naturalWidth){
      const img=options.art,scale=Math.max(width/img.naturalWidth,height/img.naturalHeight);
      const dw=img.naturalWidth*scale,dh=img.naturalHeight*scale;
      context.save();
      context.globalAlpha=.28;
      context.drawImage(img,(width-dw)/2,(height-dh)*.35,dw,dh);
      context.restore();
      const vignette=context.createRadialGradient(width*.5,height*.44,Math.min(width,height)*.16,width*.5,height*.48,Math.max(width,height)*.72);
      vignette.addColorStop(0,'rgb(16 21 28 / 28%)');vignette.addColorStop(.62,'rgb(16 21 28 / 64%)');vignette.addColorStop(1,'rgb(16 21 28 / 90%)');
      context.fillStyle=vignette;context.fillRect(0,0,width,height);
    }
    if(mode==='emblem'&&options.emblem&&options.emblem.naturalWidth){
      const img=options.emblem,maxSize=Math.min(width,height)*.56;
      const scale=Math.min(maxSize/img.naturalWidth,maxSize/img.naturalHeight);
      const dw=img.naturalWidth*scale,dh=img.naturalHeight*scale;
      const tinted=tintMask(img,dw,dh,'#ffffff');
      if(tinted){
        context.save();
        context.globalAlpha=.09;
        context.drawImage(tinted,(width-dw)/2,(height-dh)*.46,dw,dh);
        context.restore();
      }
    }
    if(mode==='story'&&options.signature&&options.signature.naturalWidth){
      const sig=options.signature,maxW=width*.22,maxH=height*.09;
      const scale=Math.min(maxW/sig.naturalWidth,maxH/sig.naturalHeight);
      const dw=sig.naturalWidth*scale,dh=sig.naturalHeight*scale;
      const tinted=tintMask(sig,dw,dh,'#ffffff');
      if(tinted){
        context.save();
        context.globalAlpha=.28;
        context.drawImage(tinted,width-dw-width*.04,height-dh-height*.04,dw,dh);
        context.restore();
      }
    }
    const floor=context.createRadialGradient(width*.5,height*.92,0,width*.5,height*.92,width*.46);
    floor.addColorStop(0,'rgb(255 255 255 / 4%)');floor.addColorStop(1,'transparent');
    context.fillStyle=floor;context.fillRect(0,0,width,height);
    context.restore();
  }
  window.AtelierShowcaseArt=Object.freeze({draw});
})();

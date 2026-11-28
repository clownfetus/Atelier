// Shared still backdrop for explicit Showcase views and their exported images: a neutral gradient,
// with a quiet centre that separates the model from the frame without changing its materials.
(() => {
  'use strict';
  function draw(context,width,height) {
    context.save();
    const ground=context.createRadialGradient(width*.5,height*.34,0,width*.5,height*.42,Math.max(width,height)*.78);
    ground.addColorStop(0,'#323c4a');ground.addColorStop(.48,'#1d2632');ground.addColorStop(1,'#10151c');
    context.fillStyle=ground;context.fillRect(0,0,width,height);
    const floor=context.createRadialGradient(width*.5,height*.92,0,width*.5,height*.92,width*.46);
    floor.addColorStop(0,'rgb(255 255 255 / 4%)');floor.addColorStop(1,'transparent');
    context.fillStyle=floor;context.fillRect(0,0,width,height);
    context.restore();
  }
  window.AtelierShowcaseArt=Object.freeze({draw});
})();

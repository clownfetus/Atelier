// Shared still backdrop for explicit Showcase views and their exported images: a neutral gradient,
// with a quiet centre that separates the model from the frame without changing its materials.
(() => {
  'use strict';
  function draw(context,width,height) {
    context.save();
    const ground=context.createRadialGradient(width*.58,height*.4,0,width*.58,height*.4,Math.max(width,height)*.72);
    ground.addColorStop(0,'#2c3440');ground.addColorStop(.55,'#1b232d');ground.addColorStop(1,'#13171e');
    context.fillStyle=ground;context.fillRect(0,0,width,height);
    context.restore();
  }
  window.AtelierShowcaseArt=Object.freeze({draw});
})();

// Shared still backdrop for explicit Showcase views and their exported images.
(() => {
  'use strict';
  function palette(colors=[]) {
    return window.AtelierKrackleInks?.guard(colors[0]||'#2a9fd6',colors[1]||'#8a6cff','#14161b',{candidates:colors.slice(2)})||{charge:'#2a9fd6',rift:'#8a6cff'};
  }
  function draw(context,width,height,inks,{burst=true}={}) {
    context.save();
    // A neutral, quiet centre separates the model from the frame without changing its materials.
    const ground=context.createRadialGradient(width*.58,height*.4,0,width*.58,height*.4,Math.max(width,height)*.72);
    ground.addColorStop(0,'#2c3440');ground.addColorStop(.55,'#1b232d');ground.addColorStop(1,'#13171e');
    context.fillStyle=ground;context.fillRect(0,0,width,height);
    const pitch=Math.max(12,width/64),step=pitch/Math.SQRT2,bands=[[],[],[]];
    for(let row=0,y=0;y<height;y+=step,row++)for(let x=(row%2)*step;x<width;x+=2*step){
      const distance=Math.hypot((x-width*.6)/(width*.36),(y-height*.45)/(height*.58));
      if(distance<.78)continue;
      bands[distance<1.1?0:distance<1.45?1:2].push([x,y]);
    }
    context.fillStyle=inks.rift;
    bands.forEach((dots,index)=>{
      context.globalAlpha=[.035,.065,.1][index];context.beginPath();
      for(const [x,y] of dots){context.moveTo(x+1,y);context.arc(x,y,1,0,Math.PI*2);}context.fill();
    });context.globalAlpha=1;
    if(burst){
      const cx=width*.23,cy=height*.63,outer=Math.min(width,height)*.27;context.beginPath();
      for(let i=0;i<24;i++){const angle=i/24*Math.PI*2-.1,r=outer*(i%2?.58:1);const x=cx+Math.cos(angle)*r,y=cy+Math.sin(angle)*r;i?context.lineTo(x,y):context.moveTo(x,y);}context.closePath();
      context.fillStyle=inks.charge;context.globalAlpha=.18;context.fill();context.globalAlpha=1;context.clip();
      context.fillStyle=ground;context.beginPath();for(let i=0;i<15;i++){const x=cx-outer*.45+(i%4)*outer*.12,y=cy+Math.floor(i/4)*outer*.12,r=outer*(.02+(i%3)*.012);context.moveTo(x+r,y);context.arc(x,y,r,0,Math.PI*2);}context.fill();
    }
    context.restore();
  }
  window.AtelierShowcaseArt=Object.freeze({palette,draw});
})();

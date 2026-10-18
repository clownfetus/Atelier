// Shared still backdrop for explicit Showcase views and their exported images.
(() => {
  'use strict';
  function palette(colors=[]) {
    return window.AtelierKrackleInks?.guard(colors[0]||'#2a9fd6',colors[1]||'#8a6cff','#14161b',{candidates:colors.slice(2)})||{charge:'#2a9fd6',rift:'#8a6cff'};
  }
  function draw(context,width,height,inks,{burst=true}={}) {
    context.save();context.fillStyle='#14161b';context.fillRect(0,0,width,height);
    const pitch=Math.max(10,width/75),step=pitch/Math.SQRT2;
    context.fillStyle=inks.rift;context.globalAlpha=.22;context.beginPath();
    for(let row=0,y=0;y<height;y+=step,row++)for(let x=(row%2)*step;x<width;x+=2*step){context.moveTo(x+1.2,y);context.arc(x,y,1.2,0,Math.PI*2);}context.fill();context.globalAlpha=1;
    if(burst){
      const cx=width*.5,cy=height*.52,outer=Math.min(width,height)*.43;context.beginPath();
      for(let i=0;i<24;i++){const angle=i/24*Math.PI*2-.1,r=outer*(i%2?.58:1);const x=cx+Math.cos(angle)*r,y=cy+Math.sin(angle)*r;i?context.lineTo(x,y):context.moveTo(x,y);}context.closePath();
      context.fillStyle=inks.charge;context.globalAlpha=.65;context.fill();context.globalAlpha=1;context.clip();
      context.fillStyle='#121216';context.beginPath();for(let i=0;i<15;i++){const x=cx-outer*.45+(i%4)*outer*.12,y=cy+Math.floor(i/4)*outer*.12,r=outer*(.02+(i%3)*.012);context.moveTo(x+r,y);context.arc(x,y,r,0,Math.PI*2);}context.fill();
    }
    context.restore();
  }
  window.AtelierShowcaseArt=Object.freeze({palette,draw});
})();

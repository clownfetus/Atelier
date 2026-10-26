"""Visible source, travelling ink and arrival response share one finite timeline."""
import base64


def run_ink_flow_checks(tab, report, checks):
    handoff = tab.get_by_role('button', name='Replay ink handoff', exact=True)
    handoff.scroll_into_view_if_needed()
    tab.wait_for_function("!document.querySelector('.k-workflow-svg,.k-workflow-link')")
    frames = tab.evaluate("""async () => {
        const hosts=[...document.querySelectorAll('.k-motion-handoff .k-motion-sample-art')];
        const [source,destination]=hosts;
        const originalStyle=destination.getAttribute('style');
        destination.style.transform='translateY(12px)';
        destination.style.setProperty('--roster-skin-accent','#d85b8c');
        const a=source.getBoundingClientRect(),b=destination.getBoundingClientRect();
        const nativeRAF=requestAnimationFrame,nativeCancel=cancelAnimationFrame;
        const callbacks=new Map(),snapshots=[];
        let next=900000,clock=performance.now();
        window.requestAnimationFrame=fn=>{callbacks.set(++next,fn);return next;};
        window.cancelAnimationFrame=id=>callbacks.delete(id);
        const step=delta=>{
            clock+=delta;const queued=[...callbacks.values()];callbacks.clear();
            for(const fn of queued)fn(clock);
        };
        const serialize=svg=>{
            const clone=svg.cloneNode(true);
            for(const key of ['position','left','top'])clone.style.removeProperty(key);
            return new XMLSerializer().serializeToString(clone);
        };
        try {
            AtelierMotion.workflow.stop();
            if(!AtelierMotion.workflow.transfer(source,destination,'arrival'))throw Error('Visible handoff refused');
            for(let i=0;i<10&&!document.querySelector('.k-workflow-link');i++)step(16);
            const link=document.querySelector('.k-workflow-link');
            const receiver=document.querySelector('.k-workflow-svg[data-workflow-trigger=arrival]');
            if(!link||!receiver)throw Error('Handoff did not establish its measured endpoints');
            step(0);const started=clock;
            const charge=Number(link.dataset.chargeMs),travel=Number(link.dataset.travelMs);
            const arrival=Number(link.dataset.arrivalMs);
            if(!(charge>0&&travel>0&&arrival===charge+travel))throw Error('Missing shared flow timeline');
            for(const [stage,elapsed] of [['source',charge*.65],['flow',charge+travel*.6],
                    ['impact',arrival+70],['rebound',arrival+180],['settle',arrival+360]]) {
                step(started+elapsed-clock);
                const ribbon=link.querySelector('[data-flow-role=ribbon]');
                snapshots.push({stage,phase:link.dataset.phase,
                    link:serialize(link),receiver:serialize(receiver),
                    linkBox:link.getBoundingClientRect().toJSON(),receiverBox:b.toJSON(),sourceBox:a.toJSON(),
                    band:Number(receiver.dataset.edgeBand),
                    ribbonFill:ribbon&&getComputedStyle(ribbon).fill});
            }
        } finally {
            AtelierMotion.workflow.stop();
            window.requestAnimationFrame=nativeRAF;window.cancelAnimationFrame=nativeCancel;
            if(originalStyle===null)destination.removeAttribute('style');else destination.setAttribute('style',originalStyle);
        }
        const paint=async markup=>{
            const image=new Image();image.src='data:image/svg+xml;charset=utf-8,'+encodeURIComponent(markup);
            await image.decode();const canvas=document.createElement('canvas');
            canvas.width=image.naturalWidth;canvas.height=image.naturalHeight;
            const ctx=canvas.getContext('2d');ctx.drawImage(image,0,0);
            return {canvas,ctx};
        };
        const ink=(ctx,box)=>{
            const x=Math.max(0,Math.ceil(box.x)),y=Math.max(0,Math.ceil(box.y));
            const w=Math.min(ctx.canvas.width-x,Math.floor(box.x+box.width)-x);
            const h=Math.min(ctx.canvas.height-y,Math.floor(box.y+box.height)-y);
            if(w<=0||h<=0)return 0;
            return ctx.getImageData(x,y,w,h).data.filter((v,i)=>i%4===3&&v>32).length;
        };
        const output=[];
        for(const snapshot of snapshots) {
            const link=await paint(snapshot.link),receiver=await paint(snapshot.receiver);
            const {linkBox:l,receiverBox:r,sourceBox:s}=snapshot;
            const sourceInk=ink(link.ctx,{x:s.left-l.left-1,y:s.top-l.top-1,width:s.width+2,height:s.height+2});
            const receiverInk=ink(receiver.ctx,{x:0,y:0,width:r.width,height:r.height});
            const inset=Math.ceil(snapshot.band)+2;
            const interiorInk=ink(receiver.ctx,{x:inset,y:inset,width:r.width-inset*2,height:r.height-inset*2});
            const left=Math.min(s.left,l.left,r.left)-8,top=Math.min(s.top,l.top,r.top)-20;
            const scene=document.createElement('canvas');
            scene.width=Math.ceil(Math.max(s.right,l.right,r.right)-left+8);
            scene.height=Math.ceil(Math.max(s.bottom,l.bottom,r.bottom)-top+24);
            const ctx=scene.getContext('2d');ctx.fillStyle='#17191e';ctx.fillRect(0,0,scene.width,scene.height);
            ctx.strokeStyle='#535c6a';ctx.lineWidth=1;
            for(const box of [s,r]){ctx.fillStyle='#23272e';ctx.fillRect(box.left-left,box.top-top,box.width,box.height);ctx.strokeRect(box.left-left,box.top-top,box.width,box.height);}
            ctx.drawImage(link.canvas,l.left-left,l.top-top);ctx.drawImage(receiver.canvas,r.left-left,r.top-top);
            ctx.fillStyle='#e5e9ef';ctx.font='12px sans-serif';ctx.fillText('Edit',s.left-left+10,s.bottom-top+17);ctx.fillText('Mod tray',r.left-left+4,r.bottom-top+17);
            output.push({stage:snapshot.stage,phase:snapshot.phase,sourceInk,receiverInk,interiorInk,
                totalInk:ink(link.ctx,{x:0,y:0,width:link.canvas.width,height:link.canvas.height}),
                ribbonFill:snapshot.ribbonFill,png:scene.toDataURL('image/png').split(',')[1]});
        }
        return output;
    }""")
    pictures = {frame['stage']: frame.pop('png') for frame in frames}
    for stage, png in pictures.items():
        (report / f"ink-flow-{stage}.png").write_bytes(base64.b64decode(png))
    by_stage = {frame['stage']: frame for frame in frames}
    assert by_stage['source']['phase'] == 'source', by_stage['source']
    assert by_stage['source']['sourceInk'] >= 20, 'The source must visibly gather ink before release'
    assert by_stage['flow']['phase'] == 'flow', by_stage['flow']
    assert by_stage['flow']['totalInk'] > by_stage['source']['totalInk'], 'The travelling stream must be visibly bolder than its source'
    assert by_stage['flow']['ribbonFill'] not in (None, 'none', 'rgba(0, 0, 0, 0)')
    for stage in ('source', 'flow'):
        assert by_stage[stage]['receiverInk'] == 0, 'The destination must wait for the ink to arrive'
    for stage in ('impact', 'rebound'):
        assert by_stage[stage]['receiverInk'] >= 30, 'Arrival must leave a visible receiving reaction'
    assert pictures['impact'] != pictures['rebound'], 'The catch must compress and rebound'
    assert all(frame['interiorInk'] == 0 for frame in frames), 'Receiving ink must remain on its border'
    assert by_stage['settle']['phase'] == 'settle'
    checks.append('Rendered handoffs visibly charge at the source, carry a filled stream and wait for arrival before a border-confined catch and rebound')

"""Opt-in real Motionboard-shaped LUT edits through the unchanged Niagara export pipeline."""
import argparse
import copy
import json
import os
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report-dir',type=Path,required=True)
    parser.add_argument('--asset',default='VFX/Particles/Characters/1031/1031001/103101/NS_103101_Buff_01')
    args=parser.parse_args()
    if not os.environ.get('ATELIER_DATA_DIR'): parser.error('Use configured isolated ATELIER_DATA_DIR')
    from atelier import config as C,tools,hostos
    from atelier.handlers import vfx as V,texture as T
    from atelier.handlers.world import RETOC
    report=args.report_dir.resolve()
    if report.exists() or report.is_relative_to(Path(C.PAKS).resolve()) or Path(C.DATA_ROOT).resolve()==Path(C.ROOT).resolve():
        parser.error('Use a fresh report directory outside the game Paks folder and isolated application data')
    project=report/'project'; project.mkdir(parents=True)
    result={'ok':False,'asset':args.asset,'checks':[],'in_game_verified':False}
    def raw(path):
        proc=tools.uat(['niagara_details',str(path),'--usmap',C.USMAP])
        assert proc.returncode==0,proc.stderr
        return {e['exportIndex']:e['shaderLut']['samples'] for e in json.loads(proc.stdout)['exports'] if e.get('shaderLut',{}).get('samples')}
    try:
        with C.project_context(str(project)):
            source=V.read_vfx(args.asset,original=True)
            candidates=[next((g for g in source['groups'] if g['channels']==channels and len(g['stops'])>1),None) for channels in (1,4)]
            assert all(candidates),'Choose an asset with supported scalar and RGBA LUTs'
            groups=[{k:copy.deepcopy(g[k]) for k in ('export_indices','stops','channels','sample_count')} for g in candidates]
            groups[0]['stops'][len(groups[0]['stops'])//2][0]+=.125
            stop=groups[1]['stops'][len(groups[1]['stops'])//2];stop[0]+=.2;stop[3]=.25
            V.save_vfx(args.asset,groups)
            before=Path(V.vfx_sidecar(args.asset)).read_bytes()
            print('Building two edited LUT groups and preserving every other native LUT…',flush=True)
            built=T.build_mod('AtelierMotionboardCheck',[],[],str(report/'exported'),vfx_items=[args.asset])
            result['build']=built;assert built['ok'] and not built['skipped'],built
            utoc=next(p for p in built['artifacts'] if p.endswith('.utoc'))
            unpacked=report/'unpacked'
            proc=hostos.run_exe([RETOC,'unpack',utoc,'--game-paks-dir',C.PAKS,'-o',str(unpacked)],
                               env=C.retoc_env(),capture_output=True,text=True,timeout=120)
            assert proc.returncode==0,proc.stderr
            actual=raw(next(unpacked.rglob(Path(args.asset).name+'.uasset')))
            expected={i:g['original_samples'] for g in source['groups'] for i in g['export_indices']}
            changed=set()
            for group in groups:
                flat=V._rebuild_lut(group['stops'],group['sample_count'],group['channels'])
                samples=[flat[i:i+group['channels']] for i in range(0,len(flat),group['channels'])]
                for index in group['export_indices']: expected[index]=samples;changed.add(index)
            for index,samples in expected.items():
                assert index in actual and len(actual[index])==len(samples),index
                assert all(len(a)==len(b) and all(abs(x-y)<=max(1e-5,abs(y)*1e-5) for x,y in zip(a,b)) for a,b in zip(actual[index],samples)),index
            assert Path(V.vfx_sidecar(args.asset)).read_bytes()==before
            result['checks'] += ['Timeline-shaped scalar and RGBA edits survive native IoStore build/readback with original channel/sample counts',
                                 f'All {len(expected)-len(changed)} untouched supported exports retain their complete original LUT samples',
                                 'Build leaves saved project edits unchanged']
            V.save_vfx(args.asset,[groups[0]])
            restored=report/'restored';V.stage_vfx(str(restored),args.asset)
            restored_samples=raw(next(restored.rglob(Path(args.asset).name+'.uasset')))
            for index in groups[1]['export_indices']:
                assert restored_samples[index]==candidates[1]['original_samples'],index
            result['checks'].append('Removing one track override restores its exact original LUT without resampling')
            V.save_vfx(args.asset,[])
            final=report/'all-original';V.stage_vfx(str(final),args.asset)
            base=V._ensure_extracted(args.asset)
            assert next(final.rglob(Path(args.asset).name+'.uasset')).read_bytes()==Path(base+'.uasset').read_bytes()
            result['checks'].append('Restoring every track stages the byte-identical original cooked package')
            result['edited_export_count']=len(changed);result['checked_export_count']=len(expected)
            result['ok']=True
    finally:
        (report/'results.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k!='build'},indent=2))


if __name__=='__main__':main()

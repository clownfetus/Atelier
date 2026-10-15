"""Opt-in real curve, MPC and Niagara batch edit/export/readback in isolated data."""
import argparse
import json
import math
import os
from pathlib import Path
import shutil
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from native_material_dye import fingerprints, digest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report-dir', type=Path, required=True)
    parser.add_argument('--curve', default='VFX/Materials/Characters/1032/Curves/C_1032_6_601')
    parser.add_argument('--mpc', default='VFX/Materials/Characters/1017/Lobby/MPC/MPC_1015_6_001')
    parser.add_argument('--niagara', default='VFX/Particles/Characters/1031/1031303/103100/NS_103100_Body_01')
    args = parser.parse_args()
    if not os.environ.get('ATELIER_DATA_DIR'):
        parser.error('Use configured isolated ATELIER_DATA_DIR.')
    from atelier import config as C, bulk, tools, hostos
    from atelier.handlers import curve as CV, vfx as V, texture as T
    from atelier.handlers.world import RETOC
    from atelier.storage import atomic_json, publish_files

    report = args.report_dir.resolve()
    if report.exists() or Path(C.DATA_ROOT).resolve() == Path(C.ROOT).resolve():
        parser.error('Use a fresh report directory and isolated app data.')
    if report.is_relative_to(Path(C.PAKS).resolve()):
        parser.error('Report must be outside the game Paks directory.')
    report.mkdir(parents=True)
    project = Path(C.project_dir('Bulk Native Check '+time.strftime('%Y%m%d-%H%M%S')))
    before = fingerprints(Path(C.PROJECTS_ROOT))
    project.mkdir(parents=True)
    result = dict(project=str(project), checks=[], started=time.time(), in_game_verified=False)
    try:
        with C.project_context(str(project)):
            items = [args.curve,args.mpc,args.niagara]
            preview = bulk.preview(items,dict(operation='multiply',scope='all',factor=.8))
            print('Preview:',json.dumps(preview['assets']),flush=True)
            assert preview['changed_assets']==3, 'Choose three assets with nonzero editable values'
            assert not list(project.rglob('*.json')), 'Preview wrote project JSON'
            applied = bulk.apply(preview['preview_id'])
            assert applied['changed_assets']==3
            expected_curve = CV.read_curve(args.curve)['channels']
            expected_mpc = V.read_mpc(args.mpc)
            expected_groups = V._load_edits(args.niagara)
            source_hashes = fingerprints(project)
            print('Building native curve + MPC + Niagara…',flush=True)
            built = T.build_mod('AtelierBulkNativeCheck',[],[],str(report/'exported'),
                                curve_items=[{'game_rel':args.curve}],vfx_items=[args.mpc,args.niagara])
            result.update(preview=preview,build=built,items=items)
            assert built['ok'] and not built['skipped'],built
            installed = publish_files(built['artifacts'],str(report/'test-mods'))
            assert [digest(p) for p in installed]==[digest(p) for p in built['artifacts']]
            unpacked = report/'unpacked'
            utoc = next(p for p in built['artifacts'] if p.endswith('.utoc'))
            proc = hostos.run_exe([RETOC,'-a','0x'+C.get_aes_key(),'unpack',utoc,
                                   '--game-paks-dir',C.PAKS,'-o',str(unpacked)],capture_output=True,text=True,timeout=120)
            assert proc.returncode==0,proc.stderr
            def asset(gr):
                matches=list(unpacked.rglob(Path(gr).name+'.uasset'))
                assert len(matches)==1,(gr,matches)
                return matches[0]
            def decoded(gr):
                source=asset(gr);out=report/'json'/source.stem;out.mkdir(parents=True)
                proc=tools.uat(['to_json',str(source),C.USMAP,str(out)])
                assert proc.returncode==0,proc.stderr
                data=json.loads((out/(source.stem+'.json')).read_text(encoding='utf-8-sig'))
                assert isinstance(data['Exports'][0].get('Data'),list),(gr,proc.stderr)
                return data
            actual_curve=CV._channels(decoded(args.curve))
            assert actual_curve.keys()==expected_curve.keys()
            for channel, keys in expected_curve.items():
                actual=actual_curve[channel]
                assert len(actual)==len(keys),(channel,len(actual),len(keys))
                for got,want in zip(actual,keys):
                    for field,value in want.items():
                        if isinstance(value,(int,float)):
                            assert math.isclose(got[field],value,rel_tol=1e-5,abs_tol=1e-6),(channel,field,got[field],value)
                        else:
                            assert got[field]==value,(channel,field,got[field],value)
            result['checks'].append('real curve key values, times and tangents survive bulk save and container readback')
            raw_mpc=decoded(args.mpc)
            sl,vl=V._mpc_lists(raw_mpc)
            actual_scalars={V._param_name(e):V._f(V._gn(e['Value'],'DefaultValue')['Value']) for e in sl}
            actual_vectors={V._param_name(e):[V._f(V._unwrap(V._gn(e['Value'],'DefaultValue')['Value'])[k]) for k in 'RGBA'] for e in vl}
            for p in expected_mpc['scalars']:
                assert abs(actual_scalars[p['name']]-p['value'])<.0001
            for p in expected_mpc['vectors']:
                assert all(abs(a-b)<.0001 for a,b in zip(actual_vectors[p['name']],p['rgba']))
            result['checks'].append('real global MPC scalar/vector edits survive readback')
            proc=tools.uat(['niagara_details',str(asset(args.niagara)),'--usmap',C.USMAP])
            details=json.loads(proc.stdout)
            exports={e['exportIndex']:e for e in details['exports']}
            for group in expected_groups:
                expected=V._rebuild_lut(group['stops'],group['sample_count'],group['channels'])
                for index in group['export_indices']:
                    actual=[v for sample in exports[index]['shaderLut']['samples'] for v in sample]
                    assert len(actual)==len(expected),(index,len(actual),len(expected))
                    assert all(abs(a-b)<max(.0001,abs(b)*.00001) for a,b in zip(actual,expected)),index
            result['checks'].append('every edited Niagara export retains LUT sample count, channel count and rebuilt values')
            assert fingerprints(project)==source_hashes,'Build changed saved project edits'
        after=fingerprints(Path(C.PROJECTS_ROOT))
        assert all(after.get(p)==h for p,h in before.items()),'An existing project changed'
        result['checks'].append('preview is read-only; existing projects, source edits and isolated install hashes are preserved')
        result.update(ok=True,artifacts=[dict(path=p,sha256=digest(p)) for p in built['artifacts']])
        print('PASS '+'; '.join(result['checks']),flush=True)
    except BaseException as error:
        result.update(ok=False,error=str(error));raise
    finally:
        result['elapsed_seconds']=round(time.time()-result['started'],2)
        atomic_json(str(report/'results.json'),result,indent=2)


if __name__=='__main__':
    main()

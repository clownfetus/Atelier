"""Opt-in real Blender export, sculpt import, mesh build and Skin Swapper readback.

Set ATELIER_DATA_DIR to configured disposable data. All published files remain
in a fresh report directory; the game is only read. No native tools are mocked.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report-dir', type=Path, required=True)
    parser.add_argument('--mesh', default='Characters/1015/1015502/Meshes/SK_1015_1015502')
    args = parser.parse_args()
    if not os.environ.get('ATELIER_DATA_DIR'):
        parser.error('Set ATELIER_DATA_DIR to configured disposable data.')
    from atelier import config, skin_swapper, tools
    from atelier.handlers import mesh, meshedit, meshport, meshreplace, meshstudio, meshvisibility, texture
    from atelier.storage import atomic_json
    import numpy as np

    report = args.report_dir.resolve()
    data, paks = Path(config.DATA_ROOT).resolve(), Path(config.PAKS).resolve()
    if report.exists() or data == ROOT or report.is_relative_to(paks) or data.is_relative_to(paks):
        parser.error('Use disposable data and a fresh report outside the game Paks directory.')
    report.mkdir(parents=True)
    project = Path(config.project_dir('Native model workflows '+report.name[:48]+'-'+os.urandom(4).hex()))
    project.mkdir(parents=True, exist_ok=False)
    before_game = {p.name: (p.stat().st_size, p.stat().st_mtime_ns) for p in paks.iterdir() if p.is_file()}
    result = dict(ok=False, mesh=args.mesh, project=str(project), checks=[], skips=[], in_game_verified=False)
    started = time.monotonic()

    def passed(message):
        result['checks'].append(message)
        atomic_json(str(report/'results.json'), result, indent=2)
        print('PASS '+message, flush=True)

    def readback(build, label):
        destination = report/label
        containers = destination/'paks'
        containers.mkdir(parents=True)
        for source in build['artifacts']:
            shutil.copy2(source, containers/Path(source).name)
        for source in paks.glob('global.*'):
            shutil.copy2(source, containers/source.name)
        unpacked = destination/'unpacked'
        proc = tools.uat(['extract_iostore_legacy', str(containers), str(unpacked), '--filter', Path(args.mesh).name, 'GAL_AtelierFeatureTest'])
        assert proc.returncode == 0, (proc.stderr or proc.stdout)[-1500:]
        matches = list(unpacked.rglob(Path(args.mesh).name+'.uasset'))
        assert len(matches) == 1, matches
        return unpacked, mesh.Mesh(str(matches[0].with_suffix('')))

    try:
        with config.project_context(str(project)):
            print('Preparing real mesh and portable Blender materials...', flush=True)
            source = meshstudio.complete_mesh_source(args.mesh)
            original = mesh.Mesh(source)
            portable = meshport.export(args.mesh)
            audit = portable['material_report']
            assert portable['ok'] and Path(portable['blend']).is_file()
            assert portable['materials'] and portable['textures'] and audit['armatures']
            assert not audit['unconnected_textures']
            assert all(row['packed'] for row in audit['images'])
            assert all(row['deformation_rig'] and row['rest_deformation_error'] <= 1e-4 for row in audit['meshes'])
            result['portable'] = portable
            passed('portable real-game Blender scene has packed connected textures, materials, deformation bones and an unchanged resting surface')

            authored = report/'sculpt.blend'
            meshedit.extract_blend(args.mesh, base_path=source, blend_path=str(authored), with_materials=False)
            sculpt = report/'sculpt.py'
            sculpt.write_text('import bpy\n'
                'for model in bpy.data.meshes:\n'
                '    for vertex in model.vertices:\n'
                '        vertex.co.x += 0.01\n'
                'bpy.ops.wm.save_as_mainfile(filepath=bpy.data.filepath)\n'
                'print("SCULPT_OK")\n', encoding='utf-8')
            from atelier import jobs
            proc = jobs.run_process([meshedit.find_blender(), '--background', '--factory-startup', '--disable-autoexec',
                str(authored), '--python', str(sculpt)], capture_output=True, text=True, timeout=180)
            (report/'sculpt.log').write_text(proc.stdout+proc.stderr, encoding='utf-8')
            assert proc.returncode == 0 and 'SCULPT_OK' in proc.stdout
            imported = meshreplace.prepare(args.mesh, str(authored))
            assert imported['ok'] and imported['validation']['skeleton_preserved']
            assert imported['validation']['lods'] == len(original.lods)
            result['replacement'] = imported
            passed('real Blender sculpt imports with the original skeleton and validates every cooked LOD')

            blend = Path(config.project_base(args.mesh)+'.blend')
            before = digest(blend)
            built = texture.build_mod('AtelierModelFeatureTest', [], [], str(report/'exported'), mesh_items=[args.mesh])
            assert built['ok'] and not built['skipped'] and len(built['artifacts']) == 3, built
            result['build'] = built
            _, cooked = readback(built, 'mesh-readback')
            assert cooked.bones == original.bones and cooked.materials == original.materials
            assert len(cooked.lods) == len(original.lods)
            shift = np.mean(cooked.positions(cooked.lods[0]), axis=0)-np.mean(original.positions(original.lods[0]), axis=0)
            assert shift[0] > .5, shift
            assert digest(blend) == before
            result['sculpt_centroid_shift_cm'] = shift.tolist()
            passed('mesh mod builds and unpacks with the sculpt, skeleton, material slots and all LODs intact; authored Blender file is preserved')

            skin_swapper.refresh_flag()
            availability = skin_swapper.status()
            if availability['available']:
                swapped = skin_swapper.build('AtelierFeatureTest', [{'game_rel': args.mesh, 'sculpt': 0}],
                    'Feature verification', 'Atelier QA', str(report/'skin-swapper'))
                assert swapped['ok'] and not swapped['skipped'], swapped
                unpacked, _ = readback(swapped, 'swapper-readback')
                configs = list(unpacked.rglob('GAL_AtelierFeatureTest.uasset'))
                assert len(configs) == 1 and 'ProjectGalacta/Meshes/' in configs[0].as_posix()
                assert not list(unpacked.rglob('skins.txt'))
                result['skin_swapper'] = swapped
                passed('Skin Swapper publishes the edited mesh and native config together under Project Galacta and both survive container readback')
            else:
                result['skips'].append({'feature': 'Skin Swapper native build', 'reasons': availability['reasons']})
                print('SKIP Skin Swapper: '+' '.join(availability['reasons']), flush=True)
            meshreplace.revert(args.mesh)
            assert meshreplace.is_original(args.mesh)
            passed('Restore original replaces the sculpt and marks the model as original')
            source_hashes = {suffix: digest(source+suffix) for suffix in ('.uasset', '.uexp', '.ubulk') if Path(source+suffix).is_file()}
            slot = original.materials[0]['slot_name']
            meshvisibility.set_hidden(args.mesh, 0, slot, True)
            hidden = meshedit.stage_mesh(args.mesh, str(report/'hidden-stage'))
            hidden_mesh = mesh.Mesh(hidden['uasset'][:-7])
            assert len(hidden['visibility']) == len(original.lods)
            for old_lod, new_lod in zip(original.lods, hidden_mesh.lods):
                np.testing.assert_array_equal(original.positions(old_lod), hidden_mesh.positions(new_lod))
                dtype = '<u4' if new_lod['idx_stride'] == 4 else '<u2'
                for old_section, new_section in zip(old_lod['sections'], new_lod['sections']):
                    start = new_lod['idx_off']+new_section['base_index']*new_lod['idx_stride']
                    indices = np.frombuffer(hidden_mesh._blob(new_lod), dtype=dtype, count=new_section['num_tris']*3, offset=start)
                    if new_section['mat'] == 0:
                        assert np.all(indices == new_section['base_vertex'])
                    else:
                        old_start = old_lod['idx_off']+old_section['base_index']*old_lod['idx_stride']
                        np.testing.assert_array_equal(indices, np.frombuffer(original._blob(old_lod), dtype=dtype,
                            count=old_section['num_tris']*3, offset=old_start))
            meshvisibility.set_hidden(args.mesh, 0, slot, False)
            restored = meshedit.stage_mesh(args.mesh, str(report/'restored-stage'))
            assert all(digest(restored['uasset'][:-7]+suffix) == expected for suffix, expected in source_hashes.items())
            assert all(digest(source+suffix) == expected for suffix, expected in source_hashes.items())
            passed('section visibility changes only the chosen indices in every LOD; unhiding restores byte-identical original files')
        after_game = {p.name: (p.stat().st_size, p.stat().st_mtime_ns) for p in paks.iterdir() if p.is_file()}
        assert before_game == after_game
        passed('game container sizes and modification times remain unchanged; every export is report-local')
        result['ok'] = True
    except BaseException as error:
        result['error'] = str(error)
        raise
    finally:
        result['seconds'] = round(time.monotonic()-started, 2)
        atomic_json(str(report/'results.json'), result, indent=2)


if __name__ == '__main__':
    main()

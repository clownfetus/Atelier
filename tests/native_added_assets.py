"""Opt-in native add/edit/export checks, writing only a new disposable report project."""
import argparse
import json
import os
from pathlib import Path
import shutil
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report-dir', type=Path, required=True)
    args = parser.parse_args()
    if not os.environ.get('ATELIER_DATA_DIR'):
        parser.error('Set ATELIER_DATA_DIR to configured isolated development data.')
    from PIL import Image
    from atelier import config as C, added_assets as A, tools
    from atelier.handlers import texture as T, material as M, meshedit, mesh, meshreplace, custom_texture as CT
    from atelier.web import browse as B
    report = args.report_dir.resolve()
    if report.exists() or report.is_relative_to(Path(C.PAKS).resolve()):
        parser.error('Use a new report directory outside the game Paks folder.')
    report.mkdir(parents=True)
    project = report / 'project'; project.mkdir()
    entries = [entry[0][:-7] for entry in A.ensure_index()
               if entry[0].startswith('Characters/1015/1015502/') and entry[0].endswith('.uasset')]
    sources = {kind: next(gr for gr in entries if B._classify_file(Path(gr).name) == kind)
               for kind in A.CLASSES}
    sources['mesh'] = 'Characters/1015/1015502/Meshes/SK_1015_1015502'
    result = {'sources': sources, 'checks': [], 'in_game_verified': False}
    try:
        with C.project_context(str(project)):
            image = report / 'MyTexture.png'; Image.new('RGBA', (16, 16), (200, 40, 90, 255)).save(image)
            texture = A.add('texture', 'Atelier/AddedAssetCheck/Textures', 'MyTexture', sources['texture'], [image])
            material = A.add('material', 'Atelier/AddedAssetCheck/Materials', 'MyMaterial', sources['material'])
            model = A.add('mesh', 'Atelier/AddedAssetCheck/Meshes', 'MyMesh', sources['mesh'])
            assets = [texture, material, model]
            assert {row['game_rel'] for row in B.all_imported()} == {row['game_rel'] for row in assets}
            assert len(B.browse_dispatch('Atelier/AddedAssetCheck')) == 3
            result['checks'].append('native add and library/Mod tray discovery for texture, material and mesh')
            original_mesh = mesh.Mesh(meshedit._resolve_base(sources['mesh']))
            added_mesh = mesh.Mesh(T.ensure_work_base(model['game_rel']))
            assert added_mesh.bones == original_mesh.bones
            assert len(added_mesh.lods) == len(original_mesh.lods)
            assert added_mesh.materials == original_mesh.materials
            result['checks'].append('renamed mesh retains its skeleton, materials and LODs')
            preview = Path(meshreplace.preview(model['game_rel']))
            assert preview.read_bytes()[:4] == b'glTF'
            result['checks'].append('added mesh creates a local GLB preview without Blender or a game index entry')
            assert M.read_material(material['game_rel'])['colors'] == M.read_material_original(material['game_rel'])['colors']
            M.save_material(material['game_rel'], {}, {})
            Image.new('RGBA', (16, 16), (30, 180, 90, 255)).save(C.project_base(texture['game_rel']) + '.png')
            built = T.build_mod('AtelierAddedAssetsCheck', [texture['game_rel']], [{'game_rel': material['game_rel']}],
                                str(report / 'exported'), mesh_items=[model['game_rel']])
            assert built['ok'] and not built['skipped'], built
            result['checks'].append('added texture edits, material edits and unchanged mesh build together')
            result['build'] = built
            readback = report / 'readback-paks'; readback.mkdir()
            for artifact in built['artifacts']: shutil.copy2(artifact, readback / Path(artifact).name)
            for source in Path(C.PAKS).glob('global.*'): shutil.copy2(source, readback / source.name)
            unpacked = report / 'unpacked'
            proc = tools.uat(['extract_iostore_legacy', str(readback), str(unpacked), '--filter'] + [asset['name'] for asset in assets])
            assert proc.returncode == 0, (proc.stderr or proc.stdout)[-1000:]
            for asset in assets:
                matches = list(unpacked.rglob(asset['name'] + '.uasset'))
                assert len(matches) == 1, (asset['name'], matches)
                actual = A._read_package(str(matches[0].with_suffix('')), str(report / 'readback-json'))
                assert any(e.get('ObjectName') == asset['name'] and not e.get('OuterIndex') for e in actual['Exports'])
                assert asset['game_rel'] in matches[0].as_posix()
                if asset['file_type'] == 'texture':
                    decoded = CT._decoded(str(matches[0]), str(report / 'exported-texture.png'))
                    assert decoded and decoded[0] == (16, 16)
            result['checks'].append('all three custom package paths and export names survive native container readback; the texture decodes')
        result['ok'] = True
    finally:
        (report / 'results.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps(result, indent=2), flush=True)


if __name__ == '__main__':
    main()

"""Opt-in native image import and legacy texture export repair, without mod installation.

Requires ATELIER_DATA_DIR pointing at isolated configured app data. A supplied
legacy project is copied into the fresh report; the original stays read-only.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def fingerprints(root):
    return {path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in root.rglob('*') if path.is_file()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report-dir', type=Path, required=True)
    parser.add_argument('--template', default='Characters/1063/1063001/Textures/T_1063001_Equip_01_D')
    parser.add_argument('--legacy-project', type=Path)
    args = parser.parse_args()
    if not os.environ.get('ATELIER_DATA_DIR'):
        parser.error('Use isolated configured application data')
    from PIL import Image, ImageDraw
    from atelier import config, added_assets as A, tools
    from atelier.handlers import texture as T, custom_texture as CT
    report = args.report_dir.resolve()
    paks = Path(config.PAKS).resolve()
    if report.exists() or report.is_relative_to(paks):
        parser.error('Choose a fresh report outside the game Paks folder')
    report.mkdir(parents=True)
    project = report / 'project'; project.mkdir()
    gr = 'Characters/1063/1063001/Meshes/T_Visor'
    image = Image.new('RGBA', (1024, 1024), (70, 130, 200, 255))
    ImageDraw.Draw(image).rectangle((0, 0, 511, 511), fill=(190, 45, 90, 255))
    uploaded = report / 'visor.png'; image.save(uploaded)
    result = {'ok': False, 'in_game_verified': False, 'checks': [], 'packages': {}, 'template': args.template}
    game_before = {p.name: [p.stat().st_size, p.stat().st_mtime_ns] for p in paks.iterdir()
                   if p.is_file() and p.suffix.lower() in ('.utoc', '.ucas', '.pak')}

    def inspect(asset, label, expected_delta=0):
        doc = A._read_package(str(asset.with_suffix('')), str(report / 'documents' / label))
        delta = CT._duplicate_none_bytes(doc, str(asset))
        assert delta == expected_delta, (label, delta, expected_delta)
        export = doc['Exports'][0]
        decoded = CT._decoded(str(asset), str(report / (label + '.png')))
        assert decoded and decoded[0] == (1024, 1024), (label, decoded)
        row = {'serial_size': export['SerialSize'], 'unconsumed_bytes': delta,
               'dimensions': list(decoded[0]), 'pixels_sha256': decoded[1]}
        result['packages'][label] = row
        return row

    try:
        with config.project_context(str(project)):
            A.add('texture', 'Characters/1063/1063001/Meshes', 'Visor', source=args.template, files=[uploaded])
            inspect(Path(A.source_base(gr) + '.uasset'), 'new-source')
            before = fingerprints(project)
            T.stage_inject(str(report / 'new-stage'), gr)
            staged = report / 'new-stage/Marvel/Content/Marvel' / (gr + '.uasset')
            row = inspect(staged, 'new-single-mip')
            if T.texture_format(str(staged.with_suffix(''))) == 'DXT1':
                assert row['serial_size'] == 524428, row
            T.stage_inject(str(report / 'mip-stage'), gr, {'no_mips': False, 'lod_group': 'TEXTUREGROUP_Character'})
            inspect(report / 'mip-stage/Marvel/Content/Marvel' / (gr + '.uasset'), 'mips-and-group')
            assert fingerprints(project) == before
            result['checks'].append('new image import and both mip modes have no unconsumed export bytes; project unchanged by export')

        export_project = project
        if args.legacy_project:
            export_project = report / 'legacy-project'
            source = args.legacy_project.resolve()
            source_before = fingerprints(source)
            shutil.copytree(source, export_project)
            with config.project_context(str(export_project)):
                legacy_source = Path(A.source_base(gr) + '.uasset')
                doc = A._read_package(str(legacy_source.with_suffix('')), str(report / 'documents/legacy-source'))
                assert CT._duplicate_none_bytes(doc, str(legacy_source)) == 8
                before = fingerprints(export_project)
                T.stage_inject(str(report / 'legacy-stage'), gr)
                inspect(report / 'legacy-stage/Marvel/Content/Marvel' / (gr + '.uasset'), 'repaired-legacy')
                assert fingerprints(export_project) == before
            assert fingerprints(source) == source_before
            result['checks'].append('existing saved texture repairs on export; original and copied project files remain unchanged')

        with config.project_context(str(export_project)):
            built = T.build_mod('AtelierVisorCheck', [gr], [], str(report / 'exported'))
            assert built.get('ok') and not built.get('skipped'), built
            readback = report / 'readback-paks'; readback.mkdir()
            for artifact in built['artifacts']:
                shutil.copy2(artifact, readback / Path(artifact).name)
            for path in paks.glob('global.*'):
                shutil.copy2(path, readback / path.name)
            unpacked = report / 'unpacked'
            proc = tools.uat(['extract_iostore_legacy', str(readback), str(unpacked), '--filter', 'T_Visor'])
            assert proc.returncode == 0, 'Native container readback failed'
            matches = list(unpacked.rglob('T_Visor.uasset'))
            assert len(matches) == 1, matches
            inspect(matches[0], 'container-readback')
            result['checks'].append('actual mod container readback retains the chosen path, 1024px image and exact serialized export extent')
        game_after = {p.name: [p.stat().st_size, p.stat().st_mtime_ns] for p in paks.iterdir()
                      if p.is_file() and p.suffix.lower() in ('.utoc', '.ucas', '.pak')}
        assert game_after == game_before
        result['checks'].append('installed game container sizes and timestamps unchanged; no mod installed')
        result['ok'] = True
    finally:
        (report / 'results.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps(result, indent=2), flush=True)


if __name__ == '__main__':
    main()

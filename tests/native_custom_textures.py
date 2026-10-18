"""Opt-in custom texture assign/location/build/readback check using real native tools.

Set ATELIER_DATA_DIR to isolated configured app data and pass a NEW --report-dir.
The game is read-only; containers are published only into that report directory.
No native calls, package documents or index entries are mocked.
"""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import sys
import time
import traceback

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def sha256(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def fingerprints(root):
    return {path.relative_to(root).as_posix(): sha256(path)
            for path in root.rglob('*') if path.is_file()}


def game_files(root):
    return {path.name: [path.stat().st_size, path.stat().st_mtime_ns]
            for path in root.iterdir() if path.is_file() and path.suffix.lower() in ('.pak', '.utoc', '.ucas')}


def safe_output(value):
    return re.sub(r'(?i)(?:0x)?[0-9a-f]{64}', '[redacted]', str(value))


def slot_references(document, material):
    result = {}
    for name, slot in material.texture_slots(document).items():
        result[name] = {'game_rel': slot['game_rel'], 'package': slot['package']['ObjectName'],
                        'object': slot['import']['ObjectName'], 'class': slot['class'],
                        'parameter_value': slot['value']['Value'],
                        'object_outer': slot['import']['OuterIndex']}
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report-dir', type=Path, required=True)
    parser.add_argument('--material', default='Characters/1015/1015502/Materials/MI_1015502_Equip_01')
    parser.add_argument('--slots', nargs='+', default=['BaseColor', 'Normal'])
    parser.add_argument('--folder', default='/Game/Marvel/Atelier/NativeCustomCheck/UserChosen/Textures')
    parser.add_argument('--name', default='T_ChosenPaint_D')
    args = parser.parse_args()
    if not os.environ.get('ATELIER_DATA_DIR'):
        parser.error('Set ATELIER_DATA_DIR to configured isolated development data.')

    from PIL import Image, ImageDraw
    from atelier import added_assets, config, tools
    from atelier.handlers import custom_texture, material, texture
    from atelier.storage import atomic_json

    report = args.report_dir.resolve()
    data, paks = Path(config.DATA_ROOT).resolve(), Path(config.PAKS).resolve()
    if data == ROOT or report.exists() or report.is_relative_to(paks) or data.is_relative_to(paks):
        parser.error('Use isolated app data and a fresh report outside the game Paks directory.')
    if report == data or data.is_relative_to(report):
        parser.error('Keep the report separate from the isolated app data.')
    if len(set(args.slots)) != len(args.slots):
        parser.error('Choose distinct texture slots.')
    report.mkdir(parents=True)
    project = report / 'project'
    project.mkdir()
    result = {'ok': False, 'in_game_verified': False, 'material': args.material,
              'chosen_folder': args.folder, 'chosen_name': args.name,
              'project': str(project), 'checks': [], 'started': time.time()}
    before_game = game_files(paks)

    def passed(message):
        result['checks'].append(message)
        atomic_json(str(report / 'results.json'), result, indent=2)
        print('PASS ' + message, flush=True)

    def read_package(asset, label):
        return added_assets._read_package(str(asset.with_suffix('')), str(report / 'json' / label))

    try:
        for label, path in {'UAssetTool': Path(tools.UAT), 'mapping': Path(config.USMAP),
                            'texconv': Path(config.TOOLS) / 'texconv.exe'}.items():
            if not path.is_file():
                raise RuntimeError('Required native input missing: ' + str(path))
            result.setdefault('native_inputs', {})[label] = {'path': str(path), 'sha256': sha256(path)}

        with config.project_context(str(project)):
            original = material._original_document(args.material)
            original_slots = material.texture_slots(original)
            if not all(slot in original_slots and original_slots[slot]['class'] == 'Texture2D' for slot in args.slots):
                raise RuntimeError('Choose existing Texture2D slots on the real material.')
            (report / 'original-material.json').write_text(json.dumps(original, indent=2), encoding='utf-8')
            material.save_material(args.material, {}, {})
            expected, formats = {}, {}
            for index, slot in enumerate(args.slots):
                # Distinct diffuse/normal patterns make accidental template reuse observable.
                image = Image.new('RGBA', (64,64), (40,180,80,255) if slot != 'Normal' else (128,144,250,255))
                draw = ImageDraw.Draw(image)
                draw.rectangle((0,0,31,31), fill=(200,40,90,255) if slot != 'Normal' else (100,156,240,255))
                draw.rectangle((32,32,63,63), fill=(20,80,210,255) if slot != 'Normal' else (160,120,240,255))
                image.save(report / (slot + '-source.png'))
                content = io.BytesIO(); image.save(content, 'PNG')
                template = original_slots[slot]['game_rel']
                base = texture.ensure_work_base(template)
                if not base:
                    raise RuntimeError('Could not extract the real template for ' + slot)
                formats[slot] = texture.texture_format(base)
                custom_texture.assign(args.material, slot, slot+'-source.png', content.getvalue(), template)
                name = args.name if index == 0 else args.name+'_'+re.sub(r'[^A-Za-z0-9_]', '_', slot)
                record = custom_texture.set_location(args.material, slot, name, args.folder)[slot]
                # Change the image after choosing the destination, as the editor permits.
                image.putpixel((48,16), (80,120,220,255))
                replacement = io.BytesIO(); image.save(replacement, 'PNG')
                record_after = custom_texture.assign(args.material, slot, 'replacement.png', replacement.getvalue(), template)[slot]
                if (record_after['name'], record_after['folder'], record_after['game_rel']) != (record['name'], record['folder'], record['game_rel']):
                    raise AssertionError('Changing the image lost the chosen package location.')
                expected[slot] = {'name': record['name'], 'game_rel': record['game_rel'],
                                  'package': custom_texture.GAME_PREFIX+record['game_rel'], 'template': template}
            result.update(expected=expected, template_formats=formats)
            before_project = fingerprints(project)
            passed('real material loaded; chosen folder/name persist after changing both custom slot images')

            stage = report / 'staged'
            label = material.stage_material(str(stage), args.material, {}, {})
            result['staged_label'] = label
            staged_material = stage / (texture.pak_game_path(args.material)+'.uasset')
            compiled = read_package(staged_material, 'staged-material')
            compiled_refs = slot_references(compiled, material)
            expected_textures = material._mat_textures(original)
            expected_textures.update({slot: record['game_rel'] for slot, record in expected.items()})
            if material._mat_textures(compiled) != expected_textures:
                raise AssertionError('The compiled material lost a texture slot or its chosen package path.')
            decoded_before = {}
            for slot, record in expected.items():
                actual = compiled_refs[slot]
                if (actual['package'], actual['object'], actual['class']) != (record['package'], record['name'], 'Texture2D'):
                    raise AssertionError('Compiled material reference differs from the chosen texture: '+slot)
                asset = stage / ('Marvel/Content/Marvel/'+record['game_rel']+'.uasset')
                document = read_package(asset, 'staged-'+slot)
                if not any(e.get('ObjectName') == record['name'] and not e.get('OuterIndex') for e in document['Exports']):
                    raise AssertionError('Compiled texture export name was lost: '+slot)
                decoded = custom_texture._decoded(str(asset), str(report / ('staged-'+slot+'.png')))
                if not decoded or decoded[0] != (64,64):
                    raise AssertionError('Compiled texture does not decode at the uploaded resolution: '+slot+' '+str(decoded))
                if texture.texture_format(str(asset.with_suffix(''))) != formats[slot]:
                    raise AssertionError('Template texture format was lost: '+slot)
                decoded_before[slot] = decoded
            result['staged_references'] = compiled_refs
            passed('native compilation preserves both chosen texture export names, package paths, formats and material import links')

            print('Building real pak/utoc/ucas containers through build_mod...', flush=True)
            built = texture.build_mod('AtelierNativeCustomTextures', [], [{'game_rel': args.material}], str(report / 'exported'))
            result['build'] = built
            if not built.get('ok') or built.get('skipped'):
                raise AssertionError('Native build failed or skipped an asset: '+str(built))
            if {Path(path).suffix.lower() for path in built['artifacts']} != {'.pak', '.utoc', '.ucas'}:
                raise AssertionError('The native build did not publish a complete container set.')
            result['artifacts'] = [{'path': path, 'bytes': Path(path).stat().st_size, 'sha256': sha256(path)}
                                   for path in built['artifacts']]
            passed('production build_mod publishes a complete native container set with no skipped assets')

            readback = report / 'readback-paks'
            readback.mkdir()
            for path in built['artifacts']:
                shutil.copy2(path, readback / Path(path).name)
            for path in paks.glob('global.*'):
                shutil.copy2(path, readback / path.name)
            unpacked = report / 'unpacked'
            wanted = [args.material, *[record['game_rel'] for record in expected.values()]]
            proc = tools.uat(['extract_iostore_legacy', str(readback), str(unpacked)] + texture.uat_filter(wanted))
            (report / 'native-readback.log').write_text(safe_output(proc.stdout)+'\n'+safe_output(proc.stderr), encoding='utf-8')
            if proc.returncode:
                raise RuntimeError('Native container readback failed: '+safe_output(proc.stderr or proc.stdout)[-1000:])
            for game_rel in wanted:
                actual = list(unpacked.rglob(game_rel.rsplit('/',1)[-1]+'.uasset'))
                if len(actual) != 1 or not actual[0].as_posix().endswith('/Marvel/Content/Marvel/'+game_rel+'.uasset'):
                    raise AssertionError('Wrong or missing package path after container readback: '+game_rel+' '+str(actual))
            actual_material = next(unpacked.rglob(Path(args.material).name+'.uasset'))
            actual = read_package(actual_material, 'readback-material')
            actual_refs = slot_references(actual, material)
            if material._mat_textures(actual) != expected_textures:
                raise AssertionError('Texture parameter package references changed during container build/readback.')
            if material._mat_params(actual) != material._mat_params(compiled):
                raise AssertionError('Material parameter values changed during container build/readback.')
            for slot, record in expected.items():
                reference = actual_refs[slot]
                if (reference['package'], reference['object'], reference['class']) != (record['package'], record['name'], 'Texture2D'):
                    raise AssertionError('Readback material does not resolve the chosen texture name/path: '+slot+' '+str(reference))
                asset = next(unpacked.rglob(record['name']+'.uasset'))
                document = read_package(asset, 'readback-'+slot)
                if not any(e.get('ObjectName') == record['name'] and not e.get('OuterIndex') for e in document['Exports']):
                    raise AssertionError('Readback texture export name was lost: '+slot)
                decoded = custom_texture._decoded(str(asset), str(report / ('readback-'+slot+'.png')))
                if decoded != decoded_before[slot]:
                    raise AssertionError('Decoded pixels or dimensions changed after container readback: '+slot+' '+str(decoded))
                if texture.texture_format(str(asset.with_suffix(''))) != formats[slot]:
                    raise AssertionError('Texture format changed after container readback: '+slot)
                record['decoded_size'], record['decoded_rgba_sha256'] = decoded
            result['readback_references'] = actual_refs
            passed('unpacked native containers retain the exact folder, export names, Texture2D material links and untouched texture parameters')
            passed('both unpacked textures retain their 64x64 resolution, format and decoded pixel hashes')
            if fingerprints(project) != before_project:
                raise AssertionError('The build changed authored project files.')
            if game_files(paks) != before_game:
                raise AssertionError('The game container files changed during this read-only check.')
            passed('source project hashes and game container metadata remain unchanged; outputs are report-local')
            result['ok'] = True
    except Exception as error:
        result['error'] = safe_output(error)
        (report / 'failure.txt').write_text(safe_output(traceback.format_exc()), encoding='utf-8')
        raise
    finally:
        result['seconds'] = round(time.time()-result['started'], 2)
        atomic_json(str(report / 'results.json'), result, indent=2)
    print(json.dumps({'ok': result['ok'], 'report': str(report / 'results.json'),
                      'textures': result['expected'], 'seconds': result['seconds']}, indent=2), flush=True)


if __name__ == '__main__':
    main()

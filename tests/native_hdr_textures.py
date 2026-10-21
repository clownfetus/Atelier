"""Exercise real HDR imports, replacement, mod packing and independent engine readback.

Run only with isolated configured application data; its mods folder must be
inside the report directory. Never installs the built test mod into the game.
"""
import argparse
import hashlib
import json
import os
import re
from pathlib import Path
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT/'scripts')]


def sha(path):
    with open(path, 'rb') as stream: return hashlib.file_digest(stream, 'sha256').hexdigest()


def engine_probe(report, tools, dotnet, paks, usmap, aes, assets, material_slots=None):
    from dotnet_bundle import extract_assemblies
    from native_inputs import load_lock, verify_mesh, verify_files
    lock = load_lock(); verified = verify_mesh(tools, lock)
    work = report/'engine-probe'; work.mkdir()
    assemblies = work/'assemblies'; extract_assemblies(tools/'AtelierMesh/AtelierMesh.exe', assemblies)
    verified.update(verify_files(assemblies, lock['mesh']['assemblies']))
    version = subprocess.run([dotnet, '--version'], capture_output=True, text=True, cwd=ROOT/'tools-src', check=True).stdout.strip()
    assert version == lock['dotnet']['sdk'], 'The engine probe requires the pinned SDK'
    project = ET.Element('Project', Sdk='Microsoft.NET.Sdk')
    props = ET.SubElement(project, 'PropertyGroup')
    for key, value in {'OutputType':'Exe', 'TargetFramework':'net10.0', 'ImplicitUsings':'enable', 'Nullable':'enable',
                       'InvariantGlobalization':'true', 'EnableDefaultCompileItems':'false'}.items():
        ET.SubElement(props, key).text = value
    items = ET.SubElement(project, 'ItemGroup')
    ET.SubElement(items, 'Compile', Include=str(ROOT/'tests/TextureCubeProbe.cs'))
    ET.SubElement(items, 'Reference', Include=str(assemblies/'*.dll'),
                  Exclude=';'.join(str(assemblies/name) for name in ('System.*','Microsoft.*','mscorlib.dll','netstandard.dll','WindowsBase.dll','AtelierMesh.dll')))
    source = work/'CubeProbe.csproj'; ET.ElementTree(project).write(source, encoding='utf-8', xml_declaration=True)
    result = subprocess.run([dotnet, 'build', str(source), '-c', 'Release', '-o', str(work/'bin'), '--nologo'],
                            capture_output=True, text=True, timeout=180, cwd=ROOT/'tools-src')
    (work/'build.log').write_text(result.stdout+result.stderr, encoding='utf-8')
    assert result.returncode == 0, 'Independent cube reader failed to build; see engine-probe/build.log'
    for name in ('CUE4Parse-Natives.dll', 'oo2core_9_win64.dll'):
        shutil.copy2(tools/'AtelierMesh'/name, work/'bin'/name)
    result = subprocess.run([dotnet, str(work/'bin/CubeProbe.dll')],
                            input=json.dumps({'paks': str(paks), 'usmap': usmap, 'aes': aes, 'assets': assets,
                                              **({'material_slots': material_slots} if material_slots else {})}),
                            capture_output=True, text=True, timeout=180)
    # Keep credentials out of diagnostics even if an upstream failure quotes them.
    errors = re.sub(re.escape(aes.removeprefix('0x').removeprefix('0X')), '[runtime key]', result.stderr, flags=re.I)
    (work/'readback.log').write_text(errors, encoding='utf-8')
    data = json.loads(result.stdout.strip())
    assert result.returncode == 0 and data.get('ok'), 'Independent CUE4Parse cube readback failed: '+str(data)
    assert 'read incorrectly' not in errors.lower() and 'bytes remaining' not in errors.lower(), errors
    return data, {'sdk': version, 'assemblies': verified, 'probe_source': sha(ROOT/'tests/TextureCubeProbe.cs')}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir', type=Path, required=True)
    parser.add_argument('--report-dir', type=Path, required=True)
    parser.add_argument('--dotnet', required=True)
    args = parser.parse_args()
    report = args.report_dir.resolve(); report.mkdir(parents=True, exist_ok=False)
    os.environ['ATELIER_DATA_DIR'] = str(args.data_dir.resolve())
    from atelier import added_assets as A, config, tools
    from atelier.handlers import hdr_texture as H, texture as T, material as M, custom_texture as CT
    from test_hdr_textures import pixels, radiance
    assert Path(config.get_mods_folder()).resolve().is_relative_to(report.parent), 'Use an isolated test-mods destination'
    paks = Path(config.PAKS)
    before = {p.name: [p.stat().st_size, p.stat().st_mtime_ns] for p in paks.iterdir() if p.is_file()}
    project = report/'project'; project.mkdir()
    result = {'checks': [], 'assets': [], 'tools': {name: sha(Path(config.TOOLS)/name)
              for name in ('UAssetTool.exe', 'texconv.exe')}}
    expected = {}
    with config.project_context(str(project)):
        for kind, source in (
            ('Float', 'Blueprints/LevelGameplay/TimestreamRaid/Texture/WaterMaterials/Textures/T_Cubemap'),
            ('BC6H', 'Characters/1028/1028001/Textures/T_CubeCity')):
            image = report/(kind+'.hdr'); image.write_bytes(radiance(pixels().reshape(48,8,4)))
            added = A.add('texture', 'AtelierHDRVerification/'+kind, 'T_Reflection', source=source, files=[image])
            gr = added['game_rel']; base = config.project_base(gr)
            cube = H.read_dds(Path(base+'.dds').read_bytes())
            assert cube.size == 8 and len(cube.mips[0]) == 6
            values = H.float_faces(cube, report/('decoded-'+kind))
            np.testing.assert_allclose(values[..., :3].mean(axis=(1,2,3)), [2,4,6,8,10,12], rtol=.03, atol=.15)
            original_base = A.source_base(gr)
            source_hashes = {ext: sha(original_base+ext) for ext in ('.uasset','.uexp')}
            info = H.replace_project(gr, 'replacement.hdr', radiance((pixels()*np.array([2,2,2,1],np.float32)).reshape(48,8,4)))
            assert info['texture_class'] == 'TextureCube'
            assert source_hashes == {ext: sha(original_base+ext) for ext in source_hashes}
            cube = H.read_dds(Path(base+'.dds').read_bytes()); expected[gr] = cube
            means = H.float_faces(cube, report/('replaced-'+kind))[..., :3].mean(axis=(1,2,3))
            np.testing.assert_allclose(means, [4,8,12,16,20,24], rtol=.03, atol=.2)
            single = report/('single-'+kind)
            T.stage_inject(str(single), gr, {'no_mips': True})
            path = single/'Marvel/Content/Marvel'/Path(gr+'.uasset')
            doc = H.document(str(path.with_suffix('')), report/('single-json-'+kind))
            actual = H.read_cooked(doc, str(path.with_suffix('')))[0]
            assert len(actual.mips) == 1 and actual.mips[0] == cube.mips[0]
            result['assets'].append({'path': gr, **info, 'maximum': float(means.max()), 'face_means': [float(x) for x in means]})
        result['checks'].append('Real FloatRGBA and BC6H TextureCube templates accept Radiance six-face strips and preserve values above one')
        result['checks'].append('Replacing an added HDR cube preserves its source package and every independent face; single-mip export preserves all six faces')
        panorama = report/'panorama.hdr'
        panorama.write_bytes(radiance(np.full((16,32,3), 16, dtype=np.float32)))
        added = A.add('texture', 'AtelierHDRVerification/Panorama', 'T_Panorama',
                      source='Blueprints/LevelGameplay/TimestreamRaid/Texture/WaterMaterials/Textures/T_Cubemap', files=[panorama])
        gr = added['game_rel']; expected[gr] = H.read_dds(Path(config.project_base(gr)+'.dds').read_bytes())
        assert expected[gr].size == 8
        assert H.float_faces(expected[gr], report/'panorama-float')[..., :3].min() > 15
        tex_items = list(expected)
        material_gr = 'Characters/1028/1028001/Materials/Lobby/MI_1028001_Equip_01'
        slot = 'CubeMap_Tex'
        material_path = Path(M.mat_json(material_gr)); material_before = material_path.read_bytes()
        assignment = CT.assign(material_gr, slot, 'Sky.hdr', radiance(pixels().reshape(48,8,4)),
                                'Characters/1028/1028001/Textures/T_CubeCity', name='HDR_Sky',
                                folder='AtelierHDRVerification/Slot', texture_class='TextureCube')
        custom_gr = assignment[slot]['game_rel']; record = CT.assignments(material_gr)[slot]
        expected[custom_gr] = H.read_dds((Path(CT.store_dir())/record['hdr_file']).read_bytes())
        assert material_path.read_bytes() == material_before
        opts = {gr: {'no_mips': False, **({'lod_group':'TEXTUREGROUP_UI'} if '/BC6H/' in gr else {})} for gr in tex_items}
        blank_gr = tex_items[0]
        T.stage_inject(str(report/'blank-stage'), blank_gr, {'blank': True, 'no_mips': True})
        blank_base = report/'blank-stage/Marvel/Content/Marvel'/blank_gr
        blank_doc = H.document(str(blank_base), report/'blank-json')
        blank = H.read_cooked(blank_doc, str(blank_base))[0]
        assert H.float_faces(blank, report/'blank-float')[..., :3].max() == 0
        built = T.build_mod('AtelierHDRCheck', tex_items, [{'game_rel': material_gr}], str(report/'exported'), asset_opts=opts)
        assert built.get('ok') and not built.get('skipped'), 'HDR mod packing failed'
        readback = report/'readback-paks'; readback.mkdir()
        for file in built['artifacts']: shutil.copy2(file, readback/Path(file).name)
        for file in paks.glob('global.*'): shutil.copy2(file, readback/file.name)
        unpacked = report/'unpacked'
        proc = tools.uat(['extract_iostore_legacy', str(readback), str(unpacked), '--filter', 'T_'])
        assert proc.returncode == 0, 'Native container extraction failed'
        paths = [path for path in unpacked.rglob('*.uasset') if any(str(path).replace('\\','/').endswith(gr+'.uasset') for gr in expected)]
        assert len(paths) == len(expected), paths
        for path in paths:
            gr = next(gr for gr in expected if str(path).replace('\\','/').endswith(gr+'.uasset'))
            doc = H.document(str(path.with_suffix('')), report/('readback-'+gr.split('/')[-2]))
            assert H.read_cooked(doc, str(path.with_suffix('')))[0] == expected[gr]
        result['checks'].append('Actual IoStore mod readback preserves TextureCube class, format, face ordering and every authored mip byte')
        engine, inputs = engine_probe(report, Path(config.TOOLS), args.dotnet, readback,
                                      config.USMAP, config.get_aes_key(), [*expected, material_gr], material_slots=[slot])
        for asset in engine['results']:
            if asset['asset'] == material_gr:
                reference = asset['textures'][0]
                assert reference['texture_class'] == 'TextureCube' and reference['path'].split('.')[0] == '/Game/Marvel/'+custom_gr
                continue
            cube = expected[asset['asset']]
            assert asset['texture_class'] == 'UTextureCube' and asset['slices'] == 6
            assert len(asset['mips']) == len(cube.mips)
            for actual, faces in zip(asset['mips'], cube.mips):
                assert actual['face_sha256'] == [hashlib.sha256(face).hexdigest() for face in faces]
            if cube.format == 'PF_FloatRGBA': assert asset['mips'][0]['maximum'] > 1
            if '/BC6H/' in asset['asset']: assert asset['group'] == 'TEXTUREGROUP_UI'
        assert material_path.read_bytes() == material_before
        result['checks'].append('HDR panorama projection, blanking and texture group overrides preserve cube structure; a real Ultron reflection slot references its new TextureCube with the source material unchanged')
        result['engine'] = engine; result['build_inputs'] = inputs
        result['checks'].append('Independent pinned CUE4Parse reads the complete mod as six-slice UTextureCube assets without serialization warnings; every face hash matches')
    assert before == {p.name: [p.stat().st_size, p.stat().st_mtime_ns] for p in paks.iterdir() if p.is_file()}
    assert not list(Path(config.get_mods_folder()).iterdir()), 'A test mod reached the install destination'
    result['checks'].append('Game container metadata is unchanged and the test mod installation directory remains empty')
    (report/'results.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps({'ok': True, 'checks': result['checks'], 'assets': result['assets']}, indent=2), flush=True)


if __name__ == '__main__': main()

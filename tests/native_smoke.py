"""Opt-in real-tool texture round trip. Reads game paks; writes only isolated app data.

Requires ATELIER_DATA_DIR configured by DEVELOPMENT.md. Never installs into the game's mods.
"""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import shutil
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def digest(path):
    with open(path, 'rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main():
    if not os.environ.get('ATELIER_DATA_DIR'):
        raise SystemExit('Set ATELIER_DATA_DIR to the isolated development directory first.')
    from atelier import config as C
    from atelier.handlers import texture as T
    from atelier.storage import publish_files
    from atelier import tools
    from PIL import Image
    import io_lib

    data = Path(C.DATA_ROOT)
    assert data.resolve() != Path(C.ROOT).resolve(), 'A separate data directory is required'
    report = data / 'native-checks'
    report.mkdir(exist_ok=True)
    capabilities = {}
    for label, relative, required in (
        ('retoc-shaders', 'shaders/retoc-rivals-cli.exe', ['dump-shaders', 'extract-shader', 'unpack', 'pack']),
        ('retoc-containers', 'retoc-rivals-cli/retoc-rivals-cli.exe', ['unpack', 'pack']),
        ('dxc', 'shaders/dxc.exe', []),
    ):
        exe = Path(C.TOOLS) / relative
        result = subprocess.run([str(exe), '--help'], capture_output=True, text=True, timeout=45)
        assert all(cmd in result.stdout for cmd in required), f'{label}: missing required commands'
        capabilities[label] = {'path': str(exe), 'sha256': digest(exe), 'commands_checked': required}
    for relative in ('AtelierMesh/AtelierMesh.exe', 'AtelierMesh/CUE4Parse-Natives.dll',
                     'retoc-rivals-cli/oo2core_9_win64.dll', 'UAssetTool.exe', 'texconv.exe'):
        path = Path(C.TOOLS) / relative
        assert path.is_file(), relative
        capabilities[relative] = {'path': str(path), 'sha256': digest(path)}
    assert C.get_prereq_status()['ok'], C.get_prereq_status()
    print('PASS native tool presence, hashes, command compatibility and prerequisites', flush=True)

    name = 'Native Smoke ' + time.strftime('%Y%m%d-%H%M%S')
    project = Path(C.project_dir(name))
    project.mkdir(parents=True)
    game_rel = 'UI/Textures/img_empty'
    with C.project_context(str(project)):
        original = T.ensure_work_base(game_rel)
        assert original and Path(original + '.uasset').is_file(), 'Live game extraction failed'
        T.decode_flat([game_rel], str(project))
        png = Path(C.project_base(game_rel) + '.png')
        assert png.is_file(), 'PNG decode failed'
        with Image.open(png) as img:
            dimensions = img.size
            changed = img.convert('RGBA')
            original_pixels = changed.tobytes()
        changed.putpixel((0, 0), (190, 50, 100, 255))
        changed.save(png)
        fmt = T.texture_format(original)
        print(f'PASS real game extraction and PNG decode: {dimensions}, {fmt}', flush=True)
        result = T.build_mod('AtelierNativeSmoke', [game_rel], [], str(report / 'exported'))
        assert result['ok'], result
        assert len(result['artifacts']) == 3, result
        installed = publish_files(result['artifacts'], str(report / 'test-mods'))
        assert all(digest(a) == digest(b) for a, b in zip(result['artifacts'], installed))
        toc = io_lib.parse_toc(result['pak'][:-4] + '.utoc')
        entries = io_lib.parse_dir_index(toc)
        assert entries, 'Export has no directory entries'
        # Use the same native unpack/decode path to check that our newly built container is readable.
        unpacked = report / ('unpacked-' + time.strftime('%H%M%S'))
        # Loose mod containers refer to script imports from the game's global container.
        # Include a copy for readback, just as the game does when mounting the mod.
        readback = report / 'readback-paks'
        readback.mkdir(exist_ok=True)
        for path in result['artifacts']:
            shutil.copy2(path, readback / Path(path).name)
        for path in Path(C.PAKS).glob('global.*'):
            shutil.copy2(path, readback / path.name)
        proc = tools.uat(['extract_iostore_legacy', str(readback), str(unpacked)]
                         + T.uat_filter([game_rel]))
        assets = list(unpacked.rglob('img_empty.uasset')) if unpacked.exists() else []
        assert assets, 'Export could not be extracted: ' + (proc.stderr or proc.stdout)[-800:]
        roundtrip = str(report / 'roundtrip')
        T.decode_png(roundtrip, str(assets[0].with_suffix('')))
        with Image.open(roundtrip + '.png') as img:
            assert img.size == dimensions, (img.size, dimensions)
            assert img.convert('RGBA').tobytes() != original_pixels, 'Texture edit was lost in the round trip'
        assert T.texture_format(str(assets[0].with_suffix(''))) == fmt
        print('PASS build, IoStore index, isolated install hashes, unpack, texture format and dimensions', flush=True)
    (report / 'results.json').write_text(json.dumps({
        'tools': capabilities, 'project': str(project), 'game_rel': game_rel,
        'dimensions': dimensions, 'format': fmt, 'build': result,
        'installed': installed, 'roundtrip': roundtrip + '.png',
    }, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()

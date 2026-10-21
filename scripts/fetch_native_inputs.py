"""Stage only checksum-pinned mesh/shader inputs from the historical release seed."""
import argparse
import json
from pathlib import Path
import shutil
import tempfile
import urllib.request
import zipfile

from native_inputs import digest, load_lock, verify_files


def stage_seed(seed, output, lock=None):
    lock = lock or load_lock()
    output = Path(output).resolve()
    if output.exists():
        raise ValueError(f'Output exists; choose a fresh Tools folder: {output}')
    if digest(seed) != lock['seed']['sha256']:
        raise ValueError('Native release seed SHA-256 mismatch')
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.atelier-inputs-', dir=output.parent) as folder:
        stage = Path(folder) / 'Tools'
        stage.mkdir()
        files = {}
        with zipfile.ZipFile(seed) as archive:
            for group, inputs in [('AtelierMesh', lock['mesh']['files']), ('shaders', lock['shader']['seed_files'])]:
                for name in inputs:
                    rel = group + '/' + name
                    member = 'Tools/' + rel
                    if archive.namelist().count(member) != 1:
                        raise ValueError(f'Missing or duplicate pinned archive member: {member}')
                    target = (stage / rel).resolve()
                    if not target.is_relative_to(stage):
                        raise ValueError('Unsafe native input path')
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with archive.open(member) as source, target.open('wb') as destination:
                        shutil.copyfileobj(source, destination)
                    files[rel] = inputs[name]
        verify_files(stage, files)
        provenance = dict(schema=1, seed=lock['seed'], files=files,
                          shader_status='legacy seed only; build AtelierShader before use')
        (stage / 'input-provenance.json').write_text(json.dumps(provenance, indent=2) + '\n', encoding='utf-8')
        created = False
        try:
            output.mkdir()
            created = True
            for path in stage.iterdir():
                if path.is_dir():
                    shutil.copytree(path, output / path.name)
                else:
                    shutil.copyfile(path, output / path.name)
        except BaseException:
            if created:
                shutil.rmtree(output)
            raise
    return provenance


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tools', type=Path, required=True, help='Fresh Tools directory to create')
    parser.add_argument('--seed', type=Path, help='Already downloaded, checksum-matching windows-tools.zip')
    args = parser.parse_args()
    if args.tools.exists():
        parser.error('Choose a fresh Tools directory; existing installations are preserved.')
    lock = load_lock()
    with tempfile.TemporaryDirectory(prefix='atelier-native-download-') as folder:
        seed = args.seed
        if seed is None:
            seed = Path(folder) / 'windows-tools.zip'
            request = urllib.request.Request(lock['seed']['url'], headers={'User-Agent': 'Atelier-native-inputs'})
            with urllib.request.urlopen(request, timeout=60) as response, seed.open('wb') as stream:
                shutil.copyfileobj(response, stream)
        stage_seed(seed, args.tools, lock)
    print(f'Pinned mesh/shader inputs staged: {args.tools.resolve()}')
    print('Build AtelierShader from pinned source before verifying or shipping the shader tool.')


if __name__ == '__main__':
    main()

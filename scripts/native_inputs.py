"""Verify native-tool inputs without executing or logging their embedded defaults."""
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
LOCK_PATH = ROOT / 'tools-src/native-tools.lock.json'


def digest(path, algorithm='sha256'):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, algorithm).hexdigest()


def load_lock():
    lock = json.loads(LOCK_PATH.read_text(encoding='utf-8'))
    if lock['schema'] != 1:
        raise ValueError('Unsupported native input lock')
    return lock


def verify_files(root, entries):
    root = Path(root).resolve(strict=True)
    verified = {}
    for name, expected in entries.items():
        path = (root / name).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            raise ValueError(f'Missing or unsafe pinned input: {name}')
        actual = digest(path)
        if actual != expected:
            raise ValueError(f'Pinned input SHA-256 mismatch: {name}')
        verified[name] = actual
    return verified


def verify_mesh(tools, lock=None):
    lock = lock or load_lock()
    return verify_files(Path(tools) / 'AtelierMesh', lock['mesh']['files'])


def verify_shaders(tools, lock=None):
    lock = lock or load_lock()
    folder = Path(tools).resolve() / 'shaders'
    files = verify_files(folder, lock['shader']['files'])
    source = lock['shader']['source']
    if source['status'] != 'verified':
        raise ValueError('Shader tool must be rebuilt from the pinned AtelierShader source')
    source_lock_path = ROOT / 'tools-src' / source['build_lock']
    if digest(source_lock_path) != source['build_lock_sha256']:
        raise ValueError('Shader source build lock SHA-256 mismatch')
    build_lock = json.loads(source_lock_path.read_text(encoding='utf-8'))
    verify_files(source_lock_path.parent, build_lock['sources'])
    verify_files(ROOT, build_lock['recipe'])
    manifest = json.loads((folder / 'build-inputs.json').read_text(encoding='utf-8'))
    if manifest.get('tool') != 'AtelierShader' or manifest.get('build_lock_sha256') != source['build_lock_sha256']:
        raise ValueError('Shader executable has no matching source-build provenance')
    for name in ('sources', 'recipe', 'upstream', 'compiler', 'git_dependencies', 'native_files'):
        if manifest.get(name) != build_lock[name]:
            raise ValueError('Shader build provenance differs from the pinned inputs: ' + name)
    verify_files(folder, manifest['outputs'])
    if manifest['outputs'].get('retoc-rivals-cli.exe') != files['retoc-rivals-cli.exe']:
        raise ValueError('Shader provenance does not identify the pinned executable')
    executable = folder / 'retoc-rivals-cli.exe'
    flags = {'creationflags': subprocess.CREATE_NO_WINDOW} if hasattr(subprocess, 'CREATE_NO_WINDOW') else {}
    # Retain this precaution for compatibility with historical executables.
    version = subprocess.run([str(executable), '--version'], cwd=folder,
        capture_output=True, text=True, timeout=15, **flags)
    help_result = subprocess.run([str(executable), '--help'], cwd=folder,
        capture_output=True, text=True, timeout=15, **flags)
    if version.returncode or version.stdout.strip() != lock['shader']['version']:
        raise ValueError('Pinned shader executable has an unexpected version')
    commands = lock['shader']['commands']
    import re
    if help_result.returncode or any(not re.search(r'^\s+' + re.escape(command) + r'\s',
                                                  help_result.stdout, re.M) for command in commands):
        raise ValueError('Shader executable is missing required custom commands')
    return dict(files=files, version=version.stdout.strip(), commands=commands,
                source_status=source['status'], rebuildable=True,
                source_kind=source['kind'], build_lock_sha256=source['build_lock_sha256'],
                upstream=build_lock['upstream'])

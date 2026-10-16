"""Build an auditable Windows review package from a clean, committed checkout.

Run with the development virtual environment. Native modding tools and user data
are never copied. Output must live outside the source checkout. This produces a
portable onedir ZIP, a matching Git source ZIP, runtime licenses and SHA-256 sums;
it does not run an installer or publish a release.
"""
import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import zipfile
from packaging.requirements import Requirement

ROOT = Path(__file__).resolve().parents[1]


def git(*args):
    return subprocess.check_output(['git', *args], cwd=ROOT, text=True).strip()


def sha256(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def collect_licenses(destination):
    records = []
    packages = set()
    for line in (ROOT / 'requirements.txt').read_text(encoding='utf-8').splitlines():
        match = re.match(r'([A-Za-z0-9_-]+)==', line)
        if match:
            requirement = Requirement(line)
            if requirement.marker and not requirement.marker.evaluate():
                continue
            packages.add(match[1])
    # Included by PyInstaller's runtime hooks, rather than imported directly by Atelier.
    packages.update(('setuptools', 'pyinstaller'))
    for package in sorted(packages):
        dist = importlib.metadata.distribution(package)
        copied = []
        for entry in dist.files or []:
            if not any(part.lower().startswith(('license', 'copying', 'notice')) for part in entry.parts):
                continue
            source = Path(dist.locate_file(entry))
            if not source.is_file():
                continue
            # Distribution RECORD paths may traverse to Scripts; keep only safe basenames
            # under their distribution-relative directory, never write outside this tree.
            parts = [part for part in entry.parts if part not in ('..', '.', '')]
            target = destination / f'{package}-{dist.version}' / Path(*parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            copied.append(target.relative_to(destination).as_posix())
        supplemental = ROOT / 'licenses' / package
        if supplemental.is_dir():
            for source in supplemental.iterdir():
                if source.is_file():
                    target = destination / f'{package}-{dist.version}' / source.name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, target)
                    copied.append(target.relative_to(destination).as_posix())
        records.append({'name': package, 'version': dist.version,
                        'license': dist.metadata.get('License-Expression') or dist.metadata.get('License', ''),
                        'files': copied})
    python_version = f'python{sys.version_info.major}.{sys.version_info.minor}'
    python_license = next((path for path in (
        Path(sys.base_prefix) / 'LICENSE.txt',
        Path(sys.base_prefix) / 'lib' / python_version / 'LICENSE.txt',
        Path('/usr/share/doc') / python_version / 'copyright',
        Path('/usr/share/doc/python3/copyright'),
    ) if path.is_file()), None)
    if python_license is None:
        raise RuntimeError('Python license missing from this build environment')
    shutil.copy2(python_license, destination / 'PYTHON-LICENSE.txt')
    (destination / 'runtime-packages.json').write_text(json.dumps(records, indent=2), encoding='utf-8')
    missing = [record['name'] for record in records if not record['files']]
    if missing:
        raise RuntimeError('Installed wheels lack license files: ' + ', '.join(missing))
    return records


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    if os.name != 'nt' or sys.maxsize <= 2**32:
        raise SystemExit('Build this package with 64-bit Python on Windows.')
    output = args.output_dir.resolve()
    if output == ROOT or ROOT in output.parents:
        raise SystemExit('Choose an output directory outside the source checkout.')
    if git('status', '--porcelain', '--untracked-files=all'):
        raise SystemExit('Commit or exclude local files first; the release requires a clean checkout.')
    commit = git('rev-parse', 'HEAD')
    short = commit[:12]
    work = output / 'build' / short
    dist = work / 'dist'
    report = output / f'package-{short}'
    report.mkdir(parents=True, exist_ok=False)
    command = [sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean',
               '--distpath', str(dist), '--workpath', str(work / 'work'), 'Atelier.spec']
    with (report / 'build.log').open('w', encoding='utf-8') as log:
        subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, check=True)
    bundle = dist / 'Atelier'
    forbidden_dirs = {'tools', 'assets', '_cache', '_logs', '_webview', '.git', '.venv', '__pycache__'}
    forbidden_files = {'mr_config.json', 'aes_key.txt', '.env', '.mcp.json'}
    forbidden_extensions = {'.usmap', '.uasset', '.uexp', '.ubulk', '.pak', '.ucas', '.utoc', '.blend'}
    for path in bundle.rglob('*'):
        rel = path.relative_to(bundle)
        # Python's stdlib and dependencies legitimately include __pycache__ folders;
        # source caches must never be collected from GUI or Blender script directories.
        parts = {part.lower() for part in rel.parts}
        denied = (parts & (forbidden_dirs - {'__pycache__'})) or path.name.lower() in forbidden_files
        source_cache = '__pycache__' in parts and ('gui' in parts or 'atelier' in parts)
        if denied or source_cache or path.suffix.lower() in forbidden_extensions:
            raise RuntimeError(f'Unexpected local/game data in bundle: {rel}')
    for source in (ROOT / 'gui').rglob('*'):
        if source.is_file():
            target = bundle / '_internal' / 'gui' / source.relative_to(ROOT / 'gui')
            if not target.is_file() or sha256(source) != sha256(target):
                raise RuntimeError(f'GUI asset missing or stale: {source.relative_to(ROOT)}')
    for source in (ROOT / 'atelier' / 'blender').rglob('*.py'):
        target = bundle / '_internal' / source.relative_to(ROOT)
        if not target.is_file() or sha256(source) != sha256(target):
            raise RuntimeError(f'Blender script missing or stale: {source.relative_to(ROOT)}')
    shutil.copy2(ROOT / 'LICENSE', bundle / 'LICENSE')
    licenses = bundle / 'licenses'
    licenses.mkdir()
    runtime_packages = collect_licenses(licenses)
    source_name = f'Atelier-Studio-source-{short}.zip'
    archive_name = f'Atelier-Studio-Windows-x64-{short}.zip'
    readme = f'''Atelier Studio modernization - Windows review build

Source commit: {commit}
Base application version: {(ROOT / 'version').read_text().strip()}
This is an unsigned review build of a contributor fork, not an official upstream release.

Extract the whole ZIP into a new writable folder. Keep Atelier.exe beside _internal.
Do not copy the EXE alone. Windows x64 and Microsoft Edge WebView2 are required.
Do not run two Atelier instances on the same port or against the same data folder.

Native modding tools (UAssetTool, AtelierMesh, retoc/Oodle, DXC and Blender), game
files, AES keys and mappings are intentionally excluded. Configure external tools
and game paths through Setup/Settings. Review DEVELOPMENT.md in the matching source
archive for the verified tool installer and isolated-data setup. Preserve existing
projects and back up the original installation before testing an upgrade.

For isolated testing in PowerShell:
  $env:ATELIER_DATA_DIR = 'D:\\AtelierReviewData'
  $env:ATELIER_PORT = '8778'
  .\\Atelier.exe
Use a separate test-mods destination; this package does not install any mods.

Atelier is licensed under the included LICENSE. GUI third-party licenses and
provenance are under _internal/gui/vendor; Python runtime/package licenses are
under licenses. The matching complete project source archive is {source_name}.
Native export round trips and in-game checks remain separate from UI smoke tests.

MANIFEST.json records source provenance and every packaged file's SHA-256 digest
(excluding the manifest itself). External SHA256SUMS.txt covers both ZIPs.
'''
    (bundle / 'README.txt').write_text(readme, encoding='utf-8')
    files = [{ 'path': path.relative_to(bundle).as_posix(), 'bytes': path.stat().st_size,
               'sha256': sha256(path)} for path in sorted(bundle.rglob('*')) if path.is_file()]
    manifest = {'source_commit': commit, 'application_version': (ROOT / 'version').read_text().strip(),
                'python': sys.version.split()[0], 'pyinstaller': importlib.metadata.version('pyinstaller'),
                'platform': 'windows-x64', 'native_tools_included': False,
                'user_or_game_data_included': False, 'files': files,
                'runtime_packages': [{k: p[k] for k in ('name', 'version')} for p in runtime_packages]}
    (bundle / 'MANIFEST.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    # Guard against an edit made while PyInstaller was running.
    if git('rev-parse', 'HEAD') != commit or git('status', '--porcelain', '--untracked-files=all'):
        raise RuntimeError('Source changed during the build; do not distribute this build.')
    subprocess.run(['git', 'archive', '--format=zip', '--prefix=Atelier-source/',
                    '--output', str(output / source_name), commit], cwd=ROOT, check=True)
    with zipfile.ZipFile(output / archive_name, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in sorted(bundle.rglob('*')):
            if path.is_file():
                archive.write(path, 'Atelier/' + path.relative_to(bundle).as_posix())
    for name in (archive_name, source_name):
        with zipfile.ZipFile(output / name) as archive:
            corrupt = archive.testzip()
            if corrupt:
                raise RuntimeError(f'Archive integrity check failed: {name}: {corrupt}')
    sums = '\n'.join(f'{sha256(output / name)}  {name}' for name in (archive_name, source_name)) + '\n'
    (output / 'SHA256SUMS.txt').write_text(sums, encoding='utf-8')
    shutil.copy2(bundle / 'MANIFEST.json', report / 'MANIFEST.json')
    print(json.dumps({'commit': commit, 'executable': str(bundle / 'Atelier.exe'),
                      'windows_zip': str(output / archive_name), 'source_zip': str(output / source_name),
                      'checksums': str(output / 'SHA256SUMS.txt'), 'files': len(files)}, indent=2))


if __name__ == '__main__':
    main()

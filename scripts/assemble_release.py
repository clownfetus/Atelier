"""Assemble and sign the exact tested binaries, without per-release handwork."""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from atelier import update_protocol as protocol
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


def read(path):
    return json.loads(path.read_bytes())


def assemble(artifacts, output, context, private_key):
    release_version, commit = context['version'], context['source_commit']
    actual_commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    changed = subprocess.check_output(['git', 'diff', '--name-only', 'HEAD'], cwd=ROOT, text=True).splitlines()
    if actual_commit != commit or set(changed) - {'version', 'CHANGELOG.md'}:
        raise ValueError('Release source differs from the tested commit.')
    windows = artifacts / 'release-windows'
    linux = artifacts / 'release-linux'
    reports = artifacts / 'release-windows-reports'
    manifest = read(windows / 'installer-manifest.json')
    if manifest['source_commit'] != commit or manifest['application_version'] != release_version:
        raise ValueError('Windows build belongs to another source commit or version.')
    installer = windows / 'AtelierSetup.exe'
    if protocol.digest(installer) != manifest['installer_sha256']:
        raise ValueError('Installer differs from its manifest.')
    frozen = read(reports / 'frozen/results.json')
    exe = next(row for row in manifest['files'] if row['path'] == 'Atelier.exe')
    if frozen.get('page_errors') or not frozen.get('checks') or frozen.get('exe_sha256') != exe['sha256']:
        raise ValueError('Packaged Windows application gate failed.')
    checks = {'windows_frozen': frozen}
    for name, folder in [('windows', reports), ('linux', artifacts / 'release-linux-reports')]:
        backend = read(folder / 'backend/results.json')
        browser = read(folder / 'browser/results.json')
        if not backend.get('results') or any(row['exit_code'] for row in backend['results']):
            raise ValueError(name + ' backend gate failed.')
        if browser.get('page_errors') or not browser.get('checks'):
            raise ValueError(name + ' browser gate failed.')
        checks[name + '_backend'] = backend
        checks[name + '_browser'] = browser
    linux_report = read(artifacts / 'release-linux-reports/appimage/results.json')
    image = linux / f'Atelier-{release_version}-x86_64.AppImage'
    inputs = read(ROOT / '_release/inputs.json')
    if not linux_report.get('ok') or linux_report['appimage_sha256'] != protocol.digest(image) or linux_report['previous_appimage_sha256'] != inputs['previous_linux_sha256']:
        raise ValueError('Linux application/upgrade gate failed.')
    checks['linux_appimage'] = linux_report
    if context['full_checks']:
        for runner in ('windows-2022', 'windows-2025'):
            report = read(artifacts / ('release-installer-' + runner) / 'results.json')
            if not report.get('ok') or report.get('page_errors') or report['installer_sha256'] != manifest['installer_sha256'] or report['previous_installer_sha256'] != inputs['previous_windows_sha256']:
                raise ValueError('Installer gate failed: ' + runner)
            checks[runner + '_installer'] = report
    metadata = read(windows / 'windows-update.json')
    inventory = protocol.validate_inventory(read(windows / f'Atelier-Windows-{release_version}-inventory.json'))
    if inventory['version'] != release_version or inventory['source_commit'] != commit:
        raise ValueError('Update inventory belongs to another build.')
    if metadata.get('installer') != protocol.file_record(installer) or metadata.get('runtime_id') != inventory['runtime_id']:
        raise ValueError('Installer or runtime differs from the update metadata.')
    for row in [metadata['full'], *metadata['patches']]:
        path = windows / row['name']
        if protocol.file_record(path) != {key: row[key] for key in ('name', 'bytes', 'sha256')}:
            raise ValueError('Update package differs from its manifest.')
    if metadata['patches']:
        patch_report = read(reports / 'patch/results.json')
        if not patch_report.get('ok') or patch_report['patch_sha256'] != metadata['patches'][0]['sha256']:
            raise ValueError('Patch upgrade/rollback gate failed.')
        checks['windows_patch'] = patch_report
    # Match every portable file to the same inventory tested above.
    from verify_portable import verify
    verify(windows / metadata['full']['name'], manifest)
    with zipfile.ZipFile(windows / metadata['full']['name']) as archive:
        if json.loads(archive.read('Atelier/' + protocol.INVENTORY)) != inventory:
            raise ValueError('Portable inventory differs from its published baseline.')
    output.mkdir(parents=True, exist_ok=False)
    assets = [installer, image, windows / f'Atelier-Windows-{release_version}-inventory.json',
              windows / metadata['full']['name'], *[windows / row['name'] for row in metadata['patches']]]
    for path in assets:
        shutil.copy2(path, output / path.name)
    changelog = (ROOT / 'CHANGELOG.md').read_text(encoding='utf-8')
    notes = next((section for section in re.split(r'(?m)^## ', changelog)[1:]
                  if section.startswith(release_version + ' ') or section.startswith(release_version + '\n')), release_version + '\n')
    (output / 'RELEASE_NOTES.md').write_text('# Atelier ' + notes.strip() + '\n', encoding='utf-8')
    source = output / f'Atelier-{release_version}-source.zip'
    raw_source = output / 'source-input.zip'
    subprocess.run(['git', 'archive', '--format=zip', '--output', str(raw_source), commit], cwd=ROOT, check=True)
    with zipfile.ZipFile(raw_source) as original, zipfile.ZipFile(source, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for member in original.infolist():
            if member.is_dir() or member.filename in {'version', 'CHANGELOG.md'}:
                continue
            archive.writestr('Atelier-source/' + member.filename, original.read(member))
        for name in ('version', 'CHANGELOG.md'):
            archive.writestr('Atelier-source/' + name, (ROOT / name).read_bytes())
    raw_source.unlink()
    verification = {'schema': 1, 'version': release_version, 'source_commit': commit,
                    'generated_source_metadata': ['version', 'CHANGELOG.md'],
                    'full_installer_checks': context['full_checks'], 'checks': checks,
                    'workflow_url': f"https://github.com/clownfetus/Atelier/actions/runs/{os.environ.get('GITHUB_RUN_ID', 'local')}",
                    'files': [protocol.file_record(path) for path in sorted(output.iterdir())]}
    protocol.atomic_json(output / 'VERIFICATION.json', verification)
    platforms = {'windows-x64': metadata, 'linux-x64': {'full': protocol.file_record(image), 'patches': []}}
    feed = {'schema': 1, 'version': release_version, 'source_commit': commit, 'platforms': platforms}
    key = Ed25519PrivateKey.from_private_bytes(base64.b64decode(private_key, validate=True))
    public = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    key_id = hashlib.sha256(public).hexdigest()[:16]
    envelope = protocol.sign_feed(feed, private_key, key_id)
    protocol.verify_feed(envelope, read(ROOT / 'update_keys.json'))
    protocol.atomic_json(output / protocol.FEED, envelope)
    sums = ''.join(f'{protocol.digest(path)}  {path.name}\n' for path in sorted(output.iterdir()))
    (output / 'SHA256SUMS.txt').write_text(sums, encoding='utf-8')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--artifacts', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    private_key = os.environ.get('ATELIER_UPDATE_PRIVATE_KEY')
    if not private_key:
        raise ValueError('Configure the ATELIER_UPDATE_PRIVATE_KEY repository secret before releasing.')
    assemble(args.artifacts, args.output, read(ROOT / '_release/context.json'), private_key)


if __name__ == '__main__':
    main()

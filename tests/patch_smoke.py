"""Apply and roll back the emitted delta against the actual prior portable build."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from atelier import update_protocol as protocol


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report-dir', type=Path, required=True)
    args = parser.parse_args()
    report = args.report_dir.resolve()
    report.mkdir(parents=True, exist_ok=False)
    context = json.loads((ROOT / '_release/context.json').read_bytes())
    metadata = json.loads((ROOT / 'dist/windows-update.json').read_bytes())
    if not metadata['patches']:
        print('No compatible previous inventory; the signed full update will be used.')
        return
    previous_version = context['previous_version']
    asset = context['previous_assets'][f'Atelier-Windows-{previous_version}.zip']
    archive_path = report / 'previous.zip'
    with urllib.request.urlopen(asset['browser_download_url'], timeout=180) as source, archive_path.open('wb') as destination:
        import shutil
        shutil.copyfileobj(source, destination)
    if protocol.digest(archive_path) != asset['digest'].removeprefix('sha256:'):
        raise ValueError('Previous portable archive failed its GitHub digest.')
    with zipfile.ZipFile(archive_path) as archive:
        protocol._members(archive)
        archive.extractall(report / 'installed')
    installation = report / 'installed/Atelier'
    previous = protocol.load_inventory(installation)
    canary = installation / 'assets/projects/Update canary/keep.txt'
    canary.parent.mkdir(parents=True)
    canary.write_text('preserve project data', encoding='utf-8')
    patch = ROOT / 'dist' / metadata['patches'][0]['name']
    plan = protocol.stage_windows(installation, patch, report / 'staging', 'patch')
    protocol.apply_windows(installation, report / 'staging', plan, report / 'transaction')
    protocol.verify_files(installation, plan['target']['files'])
    # Exercise the real upgraded executable before rolling back its file transaction.
    subprocess.run([sys.executable, str(ROOT / 'tests/frozen_smoke.py'), '--exe', str(installation / 'Atelier.exe'),
                    '--report-dir', str(report / 'frozen')], cwd=ROOT, check=True)
    protocol.rollback_windows(report / 'transaction')
    protocol.verify_files(installation, previous['files'])
    if canary.read_text() != 'preserve project data':
        raise ValueError('Update changed a user project.')
    protocol.atomic_json(report / 'results.json', {'ok': True, 'patch_sha256': protocol.digest(patch),
                                                 'from_version': previous_version, 'version': plan['target']['version']})


if __name__ == '__main__':
    main()

"""Inventory a Windows build and emit its full package and optional file patch."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from atelier import update_protocol as protocol


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--inventory-only', action='store_true')
    parser.add_argument('--dist', type=Path, default=ROOT / 'dist/Atelier')
    parser.add_argument('--output', type=Path, default=ROOT / 'dist')
    args = parser.parse_args()
    release_version = (ROOT / 'version').read_text().strip()
    commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    inventory = protocol.make_inventory(args.dist, release_version, commit)
    args.output.mkdir(parents=True, exist_ok=True)
    shutil.copy2(args.dist / protocol.INVENTORY, args.output / f'Atelier-Windows-{release_version}-inventory.json')
    if args.inventory_only:
        return
    full = args.output / f'Atelier-Windows-{release_version}.zip'
    with zipfile.ZipFile(full, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(args.dist.rglob('*')):
            if path.is_file():
                archive.write(path, 'Atelier/' + path.relative_to(args.dist).as_posix())
    metadata = {'full': protocol.file_record(full), 'patches': [], 'runtime_id': inventory['runtime_id'],
                'installer': protocol.file_record(args.output / 'AtelierSetup.exe')}
    previous = ROOT / '_release/previous-inventory.json'
    if previous.is_file():
        base = protocol.validate_inventory(json.loads(previous.read_bytes()))
        patch = args.output / f"Atelier-Windows-{release_version}-from-{base['version']}.patch.zip"
        try:
            record = protocol.make_patch(args.dist, base, patch)
            if record['bytes'] < metadata['full']['bytes']:
                metadata['patches'].append(record)
            else:
                patch.unlink()
        except ValueError:
            patch.unlink(missing_ok=True)
            print('This file layout requires the full update package.')
    protocol.atomic_json(args.output / 'windows-update.json', metadata)
    print(json.dumps({'version': inventory['version'], 'files': len(inventory['files']), **metadata}, indent=2))


if __name__ == '__main__':
    main()

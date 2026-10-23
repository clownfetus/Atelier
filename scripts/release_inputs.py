"""Download the previous Linux release the AppImage upgrade gate starts from.

The pin lives in tests/fixtures/installer/release-<version>-inputs.json. Native tools are not
seeded from a previous release any more: scripts/toolchain.py builds them from
toolchain/tools.lock.json. No game or user data is involved.
"""
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
import urllib.request

ROOT = Path(__file__).resolve().parents[1]


def download(url, path, sha):
    request = urllib.request.Request(url, headers={'User-Agent': 'Atelier-release', 'Accept': 'application/octet-stream'})
    with urllib.request.urlopen(request, timeout=180) as response, path.open('wb') as output:
        shutil.copyfileobj(response, output)
    with path.open('rb') as stream:
        if hashlib.file_digest(stream, 'sha256').hexdigest() != sha:
            path.unlink()
            raise RuntimeError('Release input hash mismatch: ' + path.name)


def main():
    version = (ROOT / 'version').read_text(encoding='utf-8').strip()
    inputs = json.loads((ROOT / 'tests/fixtures/installer' / f'release-{version}-inputs.json').read_text(encoding='utf-8'))
    target = Path(os.environ.get('RUNNER_TEMP') or tempfile.gettempdir()) / 'atelier-previous.AppImage'
    download(inputs['linux_seed_url'], target, inputs['linux_seed_sha256'])
    target.chmod(0o755)
    print('Previous AppImage staged: ' + str(target))


if __name__ == '__main__':
    main()

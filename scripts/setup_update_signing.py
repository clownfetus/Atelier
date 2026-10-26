"""Configure release signing without printing or committing the private key."""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import subprocess

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repository', default='clownfetus/Atelier')
    parser.add_argument('--configure-github', action='store_true')
    args = parser.parse_args()
    directory = Path(os.environ.get('LOCALAPPDATA', Path.home() / '.local/share')) / 'AtelierRelease'
    directory.mkdir(parents=True, exist_ok=True)
    private_path = directory / 'update-ed25519.key'
    if private_path.exists():
        raw = base64.b64decode(private_path.read_bytes(), validate=True)
        key = Ed25519PrivateKey.from_private_bytes(raw)
    else:
        key = Ed25519PrivateKey.generate()
        raw = key.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption())
        with private_path.open('xb') as stream:
            stream.write(base64.b64encode(raw))
        private_path.chmod(0o600)
    public = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    key_id = hashlib.sha256(public).hexdigest()[:16]
    key_path = ROOT / 'update_keys.json'
    keys = json.loads(key_path.read_bytes()) if key_path.exists() else {}
    keys[key_id] = base64.b64encode(public).decode('ascii')
    key_path.write_text(json.dumps(keys, indent=2) + '\n', encoding='utf-8')
    if args.configure_github:
        subprocess.run(['gh', 'secret', 'set', 'ATELIER_UPDATE_PRIVATE_KEY', '--repo', args.repository],
                       input=base64.b64encode(raw), check=True)
    print('Public update verification key: ' + key_id)
    print('Private backup is stored in the current user\'s AtelierRelease application-data folder.')
    if args.configure_github:
        print('GitHub Actions release-signing secret configured for ' + args.repository + '.')


if __name__ == '__main__':
    main()

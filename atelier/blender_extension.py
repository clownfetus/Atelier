"""Build the bundled, inspectable Blender extension from Atelier's own source."""
import hashlib
import io
import json
from pathlib import Path
import sys
import zipfile

# Same files and fingerprint as build_identity in atelier_live_bridge/safety.py; a test keeps them in step.
BUILD_FILES = ('__init__.py', 'tracking.py', 'safety.py', 'material_nodes.py', 'blender_manifest.toml')


def archive_bytes(root=None):
    root = Path(root) if root is not None else Path(__file__).resolve().parents[1]
    source = root / 'atelier/blender'
    files = {name: source / 'atelier_live_bridge' / name for name in
             ('blender_manifest.toml', '__init__.py', 'tracking.py', 'safety.py')}
    files.update({'material_nodes.py': source / 'material_nodes.py', 'LICENSE': root / 'LICENSE'})
    # Stable timestamps and LF source make local and hosted extension bytes agree.
    payload = {name: path.read_text(encoding='utf-8').replace('\r\n', '\n').encode('utf-8')
               for name, path in files.items()}
    record = {'schema': 1, 'application_version': (root / 'version').read_text().strip(),
              'files': {name: hashlib.sha256(data).hexdigest() for name, data in payload.items()}}
    payload['build-inputs.json'] = (json.dumps(record, indent=2, sort_keys=True) + '\n').encode()
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in sorted(payload.items()):
            info = zipfile.ZipInfo(name, (2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, data)
    return stream.getvalue()


def shipped_archive(root=None):
    """The add-on this Atelier offers for download: prebuilt in a frozen app, built from source otherwise."""
    if root is None and getattr(sys, 'frozen', False):
        return (Path(sys._MEIPASS) / 'extensions' / 'Atelier-Live-Bridge.zip').read_bytes()
    return archive_bytes(root)


def expected_build(root=None):
    """Fingerprint of the shipped add-on's code, as the running add-on reports its own."""
    with zipfile.ZipFile(io.BytesIO(shipped_archive(root))) as archive:
        digests = {name: hashlib.sha256(archive.read(name).replace(b'\r\n', b'\n')).hexdigest()
                   for name in BUILD_FILES}
    return hashlib.sha256(json.dumps(digests, sort_keys=True).encode('utf-8')).hexdigest()

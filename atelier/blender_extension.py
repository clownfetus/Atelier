"""Build the bundled, inspectable Blender extension from Atelier's own source."""
import hashlib
import io
import json
from pathlib import Path
import zipfile


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

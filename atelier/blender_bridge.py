"""Atelier -> persistent Blender add-on via local, versioned, atomic spool.

No TCP port or plugin code is sent from the application. Only explicit staged GLB
files and JSON are accepted by the add-on. Model Studio edits are read-only here.
"""
import json
import os
from pathlib import Path
import time
import uuid


PROTOCOL = 1


def bridge_root():
    if os.name == 'nt':
        base = Path(os.environ.get('LOCALAPPDATA') or (Path.home() / 'AppData' / 'Local'))
    else:
        base = Path(os.environ.get('XDG_STATE_HOME') or (Path.home() / '.local' / 'state'))
    return base / 'Atelier' / 'BlenderBridge'


def _atomic_json(path, document):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name('.' + path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        temporary.write_text(json.dumps(document), encoding='utf-8')
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def receiver_status(root=None, now=None):
    root = Path(root) if root is not None else bridge_root()
    try:
        data = json.loads((root / 'receiver.json').read_text(encoding='utf-8'))
        now = time.time() if now is None else now
        if data.get('protocol') != PROTOCOL or abs(now - data['time']) > 8:
            raise ValueError('Blender receiver is not active')
        return data
    except (OSError, ValueError, TypeError, KeyError):
        raise RuntimeError('Blender live-send add-on is not running. Enable Atelier Live Bridge in Blender, then try again.')


def new_job_id():
    return uuid.uuid4().hex


def submit(root, job_id, parts):
    root = Path(root)
    _atomic_json(root / 'requests' / (job_id + '.json'),
                 {'protocol': PROTOCOL, 'job': job_id, 'parts': parts})


def await_receipt(root, job_id, *, timeout=120, checkpoint=lambda: None,
                  sleep=time.sleep, monotonic=time.monotonic):
    """Wait only until Blender ACKs, not until someone saves their .blend."""
    root = Path(root)
    receipt = root / 'receipts' / (job_id + '.json')
    start = monotonic()
    while monotonic() - start < timeout:
        checkpoint()
        if receipt.exists():
            try:
                data = json.loads(receipt.read_text(encoding='utf-8'))
            finally:
                receipt.unlink(missing_ok=True)
            if data.get('job') != job_id or data.get('protocol') != PROTOCOL:
                raise RuntimeError('Blender returned an invalid receipt')
            if not data.get('ok'):
                raise RuntimeError(data.get('error') or 'Blender import failed')
            return data
        sleep(.25)
    (root / 'requests' / (job_id + '.json')).unlink(missing_ok=True)
    raise TimeoutError('Blender did not acknowledge the import within two minutes. Check its console and add-on status.')

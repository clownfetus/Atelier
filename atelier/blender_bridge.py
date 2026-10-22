"""Atelier -> persistent Blender add-on via local, versioned, atomic spool.

No TCP port or plugin code is sent from the application. Only explicit staged GLB
files and JSON are accepted by the add-on. Model Studio edits are read-only here.
"""
import json
import math
import os
from pathlib import Path
import time
import uuid


PROTOCOL = 2


def _identity(value):
    return isinstance(value, str) and len(value) == 32 and all(c in '0123456789abcdef' for c in value)


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
        if (data.get('protocol') != PROTOCOL or not _identity(data.get('receiver'))
                or not math.isfinite(data['time']) or abs(now - data['time']) > 8):
            raise ValueError('Blender receiver is not active')
        return data
    except (OSError, ValueError, TypeError, KeyError):
        raise RuntimeError('Blender live-send add-on is not running. Enable Atelier Live Bridge in Blender, then try again.')


def new_job_id():
    return uuid.uuid4().hex


def submit(root, job_id, parts):
    root = Path(root)
    if not _identity(job_id):
        raise ValueError('Invalid Blender job identity')
    receiver = receiver_status(root)['receiver']
    _atomic_json(root / 'requests' / (job_id + '.json'),
                 {'protocol': PROTOCOL, 'job': job_id, 'parts': parts,
                  'receiver': receiver, 'expires': time.time() + 120})
    return receiver


def await_receipt(root, job_id, *, receiver=None, timeout=120, checkpoint=lambda: None,
                  sleep=time.sleep, monotonic=time.monotonic):
    """Wait only until Blender ACKs, not until someone saves their .blend."""
    root = Path(root)
    if not _identity(job_id) or not _identity(receiver):
        raise ValueError('Invalid Blender receipt identity')
    receipt = root / 'receipts' / (job_id + '.json')
    start = monotonic()
    while monotonic() - start < timeout:
        checkpoint()
        if receipt.exists():
            try:
                data = json.loads(receipt.read_text(encoding='utf-8'))
            finally:
                receipt.unlink(missing_ok=True)
            if (data.get('job') != job_id or data.get('protocol') != PROTOCOL
                    or data.get('receiver') != receiver):
                raise RuntimeError('Blender returned an invalid receipt')
            if not data.get('ok'):
                raise RuntimeError(data.get('error') or 'Blender import failed')
            return data
        sleep(.25)
    (root / 'requests' / (job_id + '.json')).unlink(missing_ok=True)
    raise TimeoutError('Blender did not acknowledge the import within two minutes. Check its console and add-on status.')

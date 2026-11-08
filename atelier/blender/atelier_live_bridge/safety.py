"""Validate the local bridge envelope without importing Blender or executing content."""
import hashlib
import json
import math
from pathlib import Path
import re
import time

PROTOCOL = 2
# The add-on's own code. Atelier fingerprints the copy it ships the same way
# (atelier/blender_extension.py), so it can tell when Blender runs an older one.
BUILD_FILES = ('__init__.py', 'tracking.py', 'safety.py', 'material_nodes.py', 'blender_manifest.toml')


def identity(value):
    return isinstance(value, str) and re.fullmatch('[0-9a-f]{32}', value) is not None


def build_identity(read):
    """Fingerprint BUILD_FILES; read(name) returns a file's bytes, or None when it is missing."""
    digests = {}
    for name in BUILD_FILES:
        data = read(name)
        if data is None:
            return None
        digests[name] = hashlib.sha256(data.replace(b'\r\n', b'\n')).hexdigest()
    return hashlib.sha256(json.dumps(digests, sort_keys=True).encode('utf-8')).hexdigest()


def validate_request(request, root, session):
    if not isinstance(request, dict) or request.get('protocol') != PROTOCOL:
        raise ValueError('Unsupported Atelier bridge protocol')
    job = request.get('job')
    if not identity(job) or not identity(session) or request.get('receiver') != session:
        raise ValueError('Invalid or expired Blender receiver identity')
    expires = request.get('expires')
    if not isinstance(expires, (int, float)) or not math.isfinite(expires) or not time.time() <= expires <= time.time() + 180:
        raise ValueError('Expired Blender request')
    parts = request.get('parts')
    if not isinstance(parts, list) or not 1 <= len(parts) <= 33:
        raise ValueError('Choose a valid number of Blender parts')
    root = Path(root).resolve(strict=True)
    staging = (root / 'staging').resolve(strict=True)
    stage = (staging / job).resolve(strict=True)
    if staging.parent != root or stage.parent != staging:
        raise ValueError('The Blender staging directory escapes its bridge root')
    for part in parts:
        if not isinstance(part, dict):
            raise ValueError('Invalid Blender part')
        for field, extension in [('glb', '.glb'), ('materials', '.json')]:
            path = Path(part.get(field, '')).resolve(strict=True)
            if not path.is_file() or path.suffix.lower() != extension or not path.is_relative_to(stage):
                raise ValueError('The Blender request references a file outside its staging directory')
        transform = part.get('transform')
        if (not isinstance(transform, list) or len(transform) != 4 or
                any(not isinstance(row, list) or len(row) != 4 or
                    any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or abs(v) > 1e9 for v in row)
                    for row in transform)):
            raise ValueError('Invalid Blender part transform')
    return parts

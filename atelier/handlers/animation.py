"""Discover real standing idles and decode compatible bone tracks for the viewport."""
import hashlib
import json
import os
import re
import tempfile
import threading
from pathlib import Path

from atelier import config, hostos
from atelier.paths import pak_game_path

_decode_lock = threading.Lock()
_STANDING = re.compile(r"^(?:lobby_)?(?:stand(?:ing)?_?idle|idle_?stand(?:ing)?)$", re.I)


def idle_candidates(mesh_rel):
    config.validate_game_rel(mesh_rel)
    match = re.match(r"Characters/(\d{4})/(\d+)/Meshes/(.+)$", mesh_rel, re.I)
    if not match:
        return []
    hero, skin, mesh_path = match.groups()
    rig = mesh_path.split('/')[0] if '/' in mesh_path else hero
    from atelier.index import ensure_index
    candidates = []
    from atelier.index import prefix_entries
    for path, *_ in prefix_entries(f"characters/{hero}/"):
        if not path.lower().endswith('.uasset'):
            continue
        name = os.path.basename(path)[:-7]
        relative = path.split('/')[3:]
        if not relative or relative[0].lower() != 'animations' or not _STANDING.fullmatch(name):
            continue
        # Show the source explicitly: names alone do not establish skeleton compatibility.
        game_rel = path[:-7]
        same_rig = f"/animations/{rig.lower()}/" in path.lower()
        same_skin = path.lower().startswith(f"characters/{hero}/{skin}/")
        candidates.append({"name": name, "game_rel": game_rel,
                           "label": f"{name} · {path.split('/')[2]}",
                           "_rank": (not same_rig, not same_skin, path.lower())})
    candidates.sort(key=lambda item: item.pop('_rank'))
    return candidates[:24]


def decode_idle(mesh_rel, animation_rel):
    config.validate_game_rel(mesh_rel)
    config.validate_game_rel(animation_rel)
    if animation_rel not in {item['game_rel'] for item in idle_candidates(mesh_rel)}:
        raise ValueError("Choose a standing idle listed for this character")
    tool = Path(config.TOOLS) / 'AtelierAnimation' / 'AtelierAnimation.exe'
    if not tool.is_file():
        raise RuntimeError("Standing idle decoder is missing from this build.")
    mapping_stamp = os.path.getmtime(config.USMAP) if os.path.isfile(config.USMAP) else 0
    identity = f"v2:{mesh_rel}:{animation_rel}:{tool.stat().st_mtime_ns}:{mapping_stamp}"
    target = Path(config.CACHE_3DVIEW) / 'animations' / (hashlib.sha256(identity.encode()).hexdigest() + '.json')
    with _decode_lock:
        if target.is_file():
            return json.loads(target.read_text(encoding='utf-8'))
        target.parent.mkdir(parents=True, exist_ok=True)
        from atelier.tools import _vanilla_paks_dir, _aes_hex
        handle, temporary = tempfile.mkstemp(prefix='.idle-', suffix='.json', dir=target.parent)
        os.close(handle)
        try:
            result = hostos.run_exe([str(tool), '--paks', os.path.abspath(_vanilla_paks_dir()),
                '--aes', _aes_hex(), '--usmap', config.USMAP, '--mesh', pak_game_path(mesh_rel),
                '--animation', pak_game_path(animation_rel), '--out', temporary],
                capture_output=True, text=True, cwd=str(tool.parent), timeout=240)
            if result.returncode:
                raise RuntimeError((result.stderr or 'Animation decoding failed').strip()[-1200:])
            data = json.loads(Path(temporary).read_text(encoding='utf-8'))
            if data.get('version') != 2 or data.get('space') != 'atelier-gltf-local' or not data.get('tracks') or not 0 < data.get('duration', 0) <= 120:
                raise ValueError("Decoder returned an invalid standing idle")
            os.replace(temporary, target)
            return data
        finally:
            if os.path.exists(temporary):
                os.remove(temporary)

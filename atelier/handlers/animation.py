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
_STANDING = re.compile(r"^(?:(?:lobby_)?(?:stand(?:ing)?_?idle|idle_?stand(?:ing)?)|idle_n)$", re.I)
_EXCLUDED_ANIM = re.compile(
    r"(?:^|_)(?:half|ao|aimoffset|additive|add|face|facial|mouth|lip|eye|blink|brow|"
    r"blendspace|bs|abp|montage|am|phys|ragdoll|rig|skel|slot|upper|lower|hand|finger|"
    r"camera|cam|cine|seq|ctrl|control|test|temp|debug|ik|fk|retarget|poseasset)(?:_|$)",
    re.I,
)
_EXCLUDED_PATH = re.compile(r"/(?:aimoffset|additive|facial|face|weapon|weapons|camera|montage)/", re.I)
_CATEGORY_RULES = (
    ("lobby", re.compile(r"(?:lobby|mvp|victory|win|select|show|display|entrance|hero_?detail|pose|stand)", re.I)),
    ("emote", re.compile(r"(?:emote|dance|taunt|wave|sit|clap|bow|cheer|laugh|salute)", re.I)),
    ("combat", re.compile(r"(?:attack|atk|skill|ult|ability|melee|cast|fire|shoot|reload|run|sprint|jump|fly|dash|dodge|walk|crouch|turn|block|hit|ko|death)", re.I)),
)
CATEGORY_ORDER = {"idle": 0, "lobby": 1, "emote": 2, "combat": 3, "other": 4}
CATEGORY_LABELS = {
    "idle": "Standing idles",
    "lobby": "Lobby & MVP",
    "emote": "Emotes",
    "combat": "Combat & movement",
    "other": "Other poses",
}


def _classify_animation(name: str, path: str) -> str:
    if _STANDING.fullmatch(name):
        return "idle"
    haystack = f"{path}/{name}"
    for category, pattern in _CATEGORY_RULES:
        if pattern.search(haystack):
            return category
    return "other"


def _discover_animations(mesh_rel: str, *, include_all: bool = False, limit: int = 24):
    config.validate_game_rel(mesh_rel)
    match = re.match(r"Characters/(\d{4})/(\d+)/Meshes/(.+)$", mesh_rel, re.I)
    if not match:
        return []
    hero, skin, mesh_path = match.groups()
    rig = mesh_path.split('/')[0] if '/' in mesh_path else hero
    lobby_mesh = bool(re.search(r'_lobby(?:_|$)', mesh_path.rsplit('/', 1)[-1], re.I))
    from atelier.index import prefix_entries
    candidates = []
    seen = set()
    for path, *_ in prefix_entries(f"characters/{hero}/"):
        if not path.lower().endswith('.uasset'):
            continue
        name = os.path.basename(path)[:-7]
        relative = path.split('/')[3:]
        if not relative or relative[0].lower() != 'animations':
            continue
        is_idle = bool(_STANDING.fullmatch(name))
        if not include_all and not is_idle:
            continue
        if not is_idle and (_EXCLUDED_ANIM.search(name) or _EXCLUDED_PATH.search(path.lower())):
            continue
        # Show the source explicitly: names alone do not establish skeleton compatibility.
        game_rel = path[:-7]
        key = game_rel.casefold()
        if key in seen:
            continue
        seen.add(key)
        same_rig = f"/animations/{rig.lower()}/" in path.lower()
        same_skin = path.lower().startswith(f"characters/{hero}/{skin}/")
        # The game body and the lobby body can use different skeletons for the
        # same costume. Idle_N is the normal gameplay idle; a lobby mesh keeps
        # preferring its full-body lobby clip. Native hierarchy checks still apply.
        gameplay_idle = name.lower() == 'idle_n'
        category = "idle" if is_idle else _classify_animation(name, path)
        entry = {
            "name": name,
            "game_rel": game_rel,
            "label": f"{name} · {path.split('/')[2]}",
            "category": category,
            "is_idle": is_idle,
            "_rank": (
                CATEGORY_ORDER.get(category, 9),
                not same_rig,
                gameplay_idle == lobby_mesh if is_idle else False,
                not same_skin,
                path.lower(),
            ),
        }
        candidates.append(entry)
    candidates.sort(key=lambda item: item.pop('_rank'))
    return candidates[:limit]


def idle_candidates(mesh_rel):
    return _discover_animations(mesh_rel, include_all=False, limit=24)


def animation_candidates(mesh_rel):
    """Discover standing idles plus categorized full-body lobby, emote and combat clips."""
    return _discover_animations(mesh_rel, include_all=True, limit=96)


def _decode_animation_file(mesh_rel, animation_rel, *, allowed_rels):
    config.validate_game_rel(mesh_rel)
    config.validate_game_rel(animation_rel)
    if animation_rel not in allowed_rels:
        raise ValueError("Choose a compatible animation listed for this character")
    from atelier.tools import NATIVE
    installed = hostos.installed_tool(NATIVE)
    tool = Path(installed or NATIVE)
    if not installed:
        raise RuntimeError("Animation decoder is missing from this build.")
    mapping_stamp = os.path.getmtime(config.USMAP) if os.path.isfile(config.USMAP) else 0
    identity = f"v2:{mesh_rel}:{animation_rel}:{tool.stat().st_mtime_ns}:{mapping_stamp}"
    target = Path(config.CACHE_3DVIEW) / 'animations' / (hashlib.sha256(identity.encode()).hexdigest() + '.json')
    with _decode_lock:
        if target.is_file():
            return json.loads(target.read_text(encoding='utf-8'))
        target.parent.mkdir(parents=True, exist_ok=True)
        from atelier.tools import _aes_hex
        handle, temporary = tempfile.mkstemp(prefix='.anim-', suffix='.json', dir=target.parent)
        os.close(handle)
        try:
            result = hostos.run_exe([str(tool), 'animation', '--paks', os.path.abspath(config.PAKS),
                '--aes', _aes_hex(), '--usmap', config.USMAP, '--mesh', pak_game_path(mesh_rel),
                '--animation', pak_game_path(animation_rel), '--out', temporary],
                capture_output=True, text=True, cwd=str(tool.parent), timeout=240)
            if result.returncode:
                raise RuntimeError((result.stderr or 'Animation decoding failed').strip()[-1200:])
            data = json.loads(Path(temporary).read_text(encoding='utf-8'))
            if data.get('version') != 2 or data.get('space') != 'atelier-gltf-local' or not data.get('tracks') or not 0 < data.get('duration', 0) <= 120:
                raise ValueError("Decoder returned an invalid animation clip")
            os.replace(temporary, target)
            return data
        finally:
            if os.path.exists(temporary):
                os.remove(temporary)


def decode_idle(mesh_rel, animation_rel):
    config.validate_game_rel(mesh_rel)
    config.validate_game_rel(animation_rel)
    allowed = {item['game_rel'] for item in idle_candidates(mesh_rel)}
    return _decode_animation_file(mesh_rel, animation_rel, allowed_rels=allowed)


def decode_animation(mesh_rel, animation_rel):
    config.validate_game_rel(mesh_rel)
    config.validate_game_rel(animation_rel)
    allowed = {item['game_rel'] for item in animation_candidates(mesh_rel)}
    return _decode_animation_file(mesh_rel, animation_rel, allowed_rels=allowed)

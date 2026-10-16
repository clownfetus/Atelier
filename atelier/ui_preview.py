"""Small sidebar previews read only existing project JSON; never extract game assets."""
import json
import math
from pathlib import Path
from atelier.config import project_base, project_base_legacy


def saved_preview(game_rel, file_type):
    if file_type not in ('material', 'curve'):
        return None
    path = next((Path(base + '.json') for base in (project_base(game_rel), project_base_legacy(game_rel))
                 if Path(base + '.json').is_file()), None)
    if path is None:
        return None
    try:
        # No native calls or fallback extraction, including on a corrupt project file.
        if path.stat().st_size > 8 * 1024 * 1024:
            return None
        data = json.loads(path.read_text(encoding='utf-8-sig'))
        if file_type == 'material':
            from atelier.handlers.material import _mat_params
            colors, _ = _mat_params(data)
            return {'colors': [color['rgba'] for color in colors[:4]
                               if len(color['rgba']) >= 3 and all(math.isfinite(v) for v in color['rgba'])]}
        from atelier.handlers.curve import _channels
        channels = _channels(data)
        keys = next((keys for keys in channels.values() if keys), [])
        keys = [key for key in keys if all(math.isfinite(key[k]) for k in ('time', 'value'))]
        if not keys:
            return None
        keys = sorted(keys, key=lambda key: key['time'])
        if len(keys) > 48:
            keys = [keys[round(i*(len(keys)-1)/47)] for i in range(48)]
        low, high = min(k['value'] for k in keys), max(k['value'] for k in keys)
        start, end = keys[0]['time'], keys[-1]['time']
        return {'points': [[round(2+36*(k['time']-start)/(end-start or 1), 2),
                            round(25-22*(k['value']-low)/(high-low or 1), 2)] for k in keys]}
    except (OSError, ValueError, KeyError, TypeError, IndexError, AttributeError):
        return None

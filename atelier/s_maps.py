"""Pair edited diffuse maps with same-folder S maps and apply built-in Color blending."""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
import threading
import time
import uuid

import numpy as np
from PIL import Image

from atelier import config as C, jobs
from atelier.handlers import texture as T
from atelier.index import ensure_index
from atelier.storage import publish_project_files

_plans = {}
_lock = threading.RLock()
LIFETIME = 15 * 60


def digest(path):
    if not os.path.isfile(path):
        return None
    with open(path, 'rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def project_png(gr, root=None):
    root = root or C.get_import_root()
    path = C.project_base(gr, root) + '.png'
    if os.path.isfile(path):
        return path
    legacy = C.project_base_legacy(gr, root) + '.png'
    return legacy if os.path.isfile(legacy) else path


def pair_maps(edited, available):
    """Exact _D/_S names first; a numbered family may share an unnumbered S map.

    Every S target owns its complete list of candidate D maps, so shared targets
    require an explicit choice. Folder identity is always part of the match.
    """
    catalog = {}
    for gr in available:
        C.validate_game_rel(gr)
        if gr.lower().endswith('_s'):
            catalog.setdefault(gr.casefold(), set()).add(gr)
    pairs, skipped = {}, []
    for gr in sorted(set(edited)):
        C.validate_game_rel(gr)
        if not gr.lower().endswith('_d'):
            continue
        stem = gr[:-2]
        candidates = catalog.get((stem + '_S').casefold())
        if not candidates:
            folder, name = os.path.split(stem)
            family = re.sub(r'_\d+$', '', name)
            if family != name:
                candidates = catalog.get(((folder + '/' if folder else '') + family + '_S').casefold())
        if not candidates:
            skipped.append({'d': gr, 'reason': 'No matching S map in the same folder'})
        elif len(candidates) != 1:
            skipped.append({'d': gr, 'reason': 'S map names differ only by letter case; rename or resolve them first'})
        else:
            target = next(iter(candidates))
            pairs.setdefault(target, []).append(gr)
    return [{'s': s, 'candidates': ds} for s, ds in sorted(pairs.items())], skipped


def plan():
    from atelier.web.browse import all_imported
    edited = [item['game_rel'] for item in all_imported() if item['file_type'] == 'texture']
    diffuse = [gr for gr in edited if gr.lower().endswith('_d')]
    if not diffuse:
        raise ValueError('Add a texture ending in _D to Edited Assets first.')
    folders = {os.path.dirname(gr).casefold() for gr in diffuse}
    # Existing project maps take precedence over spelling from the game index.
    edited_s = [gr for gr in edited if gr.lower().endswith('_s')]
    project_names = {gr.casefold() for gr in edited_s}
    available = [gr[:-7] for gr, *_ in ensure_index()
                 if gr.lower().endswith('_s.uasset') and os.path.dirname(gr).casefold() in folders
                 and gr[:-7].casefold() not in project_names]
    pairs, skipped = pair_maps(diffuse, available + edited_s)
    root = C.get_import_root()
    before = {gr: digest(project_png(gr, root)) for gr in diffuse + [row['s'] for row in pairs]}
    identifier = str(uuid.uuid4())
    with _lock:
        for key in list(_plans):
            if time.monotonic() - _plans[key]['created'] > LIFETIME:
                del _plans[key]
        if len(_plans) >= 40:
            del _plans[min(_plans, key=lambda key: _plans[key]['created'])]
        _plans[identifier] = dict(root=os.path.realpath(root), created=time.monotonic(),
                                  pairs=pairs, skipped=skipped, before=before)
    return {'ok': True, 'plan_id': identifier, 'pairs': pairs, 'skipped': skipped}


def color_blend(diffuse, surface):
    """W3C non-separable Color, 100% layer opacity, with S alpha retained.

    https://www.w3.org/TR/compositing-1/#blendingcolor
    Transparent D pixels mask the color change. Processing row bands bounds
    temporary NumPy memory; neither source image is resized or modified in place.
    """
    base = surface.convert('RGBA')
    resized = diffuse.convert('RGBA').resize(base.size, Image.Resampling.BICUBIC)
    output = Image.new('RGBA', base.size)
    weights = np.array([.30, .59, .11], dtype=np.float32)
    for y in range(0, base.height, 256):
        jobs.checkpoint()
        box = (0, y, base.width, min(y + 256, base.height))
        bottom = np.asarray(base.crop(box), dtype=np.float32) / 255
        top = np.asarray(resized.crop(box), dtype=np.float32) / 255
        lum = np.sum(bottom[..., :3] * weights, axis=-1, keepdims=True)
        color = top[..., :3] + lum - np.sum(top[..., :3] * weights, axis=-1, keepdims=True)
        low, high = color.min(axis=-1, keepdims=True), color.max(axis=-1, keepdims=True)
        color = np.where(low < 0, lum + (color - lum) * lum / np.maximum(lum - low, 1e-7), color)
        color = np.where(high > 1, lum + (color - lum) * (1 - lum) / np.maximum(high - lum, 1e-7), color)
        rgb = bottom[..., :3] * (1 - top[..., 3:4]) + np.clip(color, 0, 1) * top[..., 3:4]
        rgba = np.concatenate((rgb, bottom[..., 3:4]), axis=-1)
        output.paste(Image.fromarray(np.floor(np.clip(rgba, 0, 1) * 255 + .5).astype(np.uint8)), (0, y))
    return output


def process(plan_id, choices=None):
    root = C.get_import_root()
    with _lock:
        saved = _plans.get(plan_id) if isinstance(plan_id, str) else None
        if not saved or saved['root'] != os.path.realpath(root) or time.monotonic()-saved['created'] > LIFETIME:
            raise ValueError('S-map plan expired or belongs to another project. Click Process S maps again.')
        choices = {} if choices is None else choices
        if not isinstance(choices, dict) or set(choices) - {row['s'] for row in saved['pairs']}:
            raise ValueError('Invalid S-map pairing choices.')
        selected, skipped = [], list(saved['skipped'])
        for row in saved['pairs']:
            d = choices.get(row['s'], row['candidates'][0] if len(row['candidates']) == 1 else None)
            if d == 'skip':
                skipped.append({'s': row['s'], 'reason': 'Skipped by your pairing choice'})
                continue
            if d not in row['candidates']:
                raise ValueError('Choose which D map should drive ' + row['s'])
            selected.append({'d': d, 's': row['s']})
        # Never process the same saved plan twice, including concurrent submissions.
        del _plans[plan_id]
    if not selected:
        return {'ok': True, 'processed': [], 'skipped': skipped}
    inputs = {gr: project_png(gr, root) for row in selected for gr in row.values()}
    for gr, path in inputs.items():
        if digest(path) != saved['before'][gr]:
            raise RuntimeError('Texture changed while pairing maps. Click Process S maps again: ' + gr)
    batch = str(uuid.uuid4())
    backup_root = '.atelier/s-map-backups/' + batch
    changes, processed = [], []
    with tempfile.TemporaryDirectory(prefix='atelier-s-maps-') as scratch:
        for i, row in enumerate(selected):
            jobs.progress('Processing ' + os.path.basename(row['s']), i, len(selected))
            d_path, s_path = inputs[row['d']], inputs[row['s']]
            if not os.path.isfile(d_path):
                raise ValueError('Edited D map is missing: ' + row['d'])
            if not os.path.isfile(s_path):
                cb = T.ensure_work_base(row['s'])
                if not cb:
                    raise RuntimeError('Could not extract S map: ' + row['s'])
                base = os.path.join(scratch, str(i) + '-base')
                T.decode_png(base, cb)
                s_path = base + '.png'
                if not os.path.isfile(s_path):
                    raise RuntimeError('Could not decode S map: ' + row['s'])
            # Snapshot both sources so an external writer cannot alter a partly read PNG.
            d_copy, s_copy = os.path.join(scratch, str(i) + '-d.png'), os.path.join(scratch, str(i) + '-s.png')
            shutil.copy2(d_path, d_copy); shutil.copy2(s_path, s_copy)
            if digest(d_copy) != saved['before'][row['d']]:
                raise RuntimeError('D map changed during processing: ' + row['d'])
            if saved['before'][row['s']] is not None and digest(s_copy) != saved['before'][row['s']]:
                raise RuntimeError('S map changed during processing: ' + row['s'])
            with Image.open(d_copy) as d_image, Image.open(s_copy) as s_image:
                result = color_blend(d_image, s_image)
                size = list(s_image.size)
                output = os.path.join(scratch, str(i) + '-out.png')
                result.save(output, 'PNG', icc_profile=s_image.info.get('icc_profile'))
            with Image.open(output) as verified:
                verified.verify()
            target = inputs[row['s']]
            changes.append(dict(path=os.path.relpath(target, root).replace('\\', '/'),
                                before=saved['before'][row['s']], source=output))
            changes.append(dict(path=backup_root + '/' + row['s'] + '.png', before=None, source=s_copy))
            processed.append(dict(row, size=size, sha256=digest(output)))
        for row in selected:
            if digest(inputs[row['d']]) != saved['before'][row['d']]:
                raise RuntimeError('D map changed during processing: ' + row['d'])
        manifest = os.path.join(scratch, 'batch.json')
        Path(manifest).write_text(json.dumps({'processed': processed, 'skipped': skipped,
            'resize': 'Bicubic', 'blend': 'Color', 'opacity': 100, 'preserve_s_alpha': True}, indent=2), encoding='utf-8')
        changes.append(dict(path=backup_root + '/batch.json', before=None, source=manifest))
        jobs.begin_publication('Saving processed S maps…')
        publish_project_files(root, changes)
    return {'ok': True, 'processed': processed, 'skipped': skipped, 'backup': backup_root}

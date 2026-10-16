"""Restore saved asset content without removing its edit-list entry or selection."""
import json
import os
from pathlib import Path
import tempfile

from atelier import config, jobs, project_meta
from atelier.storage import atomic_json, publish_project_files
from atelier.handlers.meshreplace import digest


def revert(game_rel):
    config.validate_game_rel(game_rel)
    from atelier.web.browse import _classify_file, _imported_exists
    kind = _classify_file(os.path.basename(game_rel))
    extension = '.blend' if kind == 'mesh' else '.png' if kind == 'texture' else '.json'
    if not _imported_exists(game_rel, extension):
        raise ValueError('This asset is not in the edit list')
    root = config.get_import_root()
    if kind == 'mesh':
        from atelier.handlers.meshreplace import revert as revert_mesh
        result = revert_mesh(game_rel)
    else:
        base = config.project_base(game_rel)
        # Restore a legacy entry in place; do not create a second edit-list row.
        target = next((p for p in (base+extension, config.project_base_legacy(game_rel)+extension)
                       if os.path.isfile(p)), base+extension)
        before = digest(target)
        with tempfile.TemporaryDirectory(prefix='atelier-revert-') as temporary:
            source = Path(temporary)/('original'+extension)
            jobs.progress('Reading the original asset…')
            if kind == 'texture':
                from atelier.handlers.texture import ensure_work_base, decode_to_png
                original = ensure_work_base(game_rel)
                decoded = decode_to_png(str(source.with_suffix('')), original) if original else None
                if not decoded: raise RuntimeError('Could not decode the original texture; your edit is unchanged')
            elif kind in ('world', 'text'):
                atomic_json(str(source), {kind+'_edits': {}})
            elif kind == 'vfx' and not os.path.basename(game_rel).lower().startswith('mpc_'):
                atomic_json(str(source), {'vfx_edits': []})
            elif kind in ('material', 'curve', 'vfx'):
                from atelier.handlers.texture import ensure_work_base
                from atelier.tools import uat
                original = ensure_work_base(game_rel)
                if not original: raise RuntimeError('Could not read the original asset')
                converted = Path(temporary)/'converted'; converted.mkdir()
                response = uat(['to_json', os.path.abspath(original+'.uasset'), config.USMAP, str(converted)])
                files = list(converted.glob('*.json'))
                if response.returncode or len(files) != 1: raise RuntimeError('Could not read original parameters; your edit is unchanged')
                source = files[0]
                json.loads(source.read_text(encoding='utf-8-sig'))
            else: raise ValueError('This asset type cannot be restored')
            jobs.checkpoint(); jobs.begin_publication('Restoring the original content…')
            publish_project_files(root, [{'path':os.path.relpath(target,root), 'before':before, 'source':str(source)}])
        result = {'ok':True, 'game_rel':game_rel}
    # Export overrides also change the original appearance. Selection is separate and preserved.
    project_meta.forget_asset(root, game_rel)
    return result

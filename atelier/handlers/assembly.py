"""On-demand, outgoing VFX package references for Assembly View.

This does not scan filenames or claim to index reverse Niagara dependencies.
Opening the workspace never extracts these documents; the user requests them.
"""
import json
from pathlib import Path

from atelier import config, jobs
from atelier.unreal_refs import imported_package

EFFECT_CLASSES = frozenset(('NiagaraSystem', 'NiagaraEmitter', 'ParticleSystem'))


def effect_references(document, source):
    """Retain class and exact package provenance from a cooked import table."""
    result = {}
    for index, record in enumerate((document or {}).get('Imports', [])):
        if not isinstance(record, dict) or record.get('ClassName') not in EFFECT_CLASSES:
            continue
        package = imported_package(document, -index-1)
        if package:
            path = package[1]
            result[path.casefold()] = {'game_rel': path, 'name': path.rsplit('/', 1)[-1],
                                      'class': record['ClassName'], 'source': source}
    return list(result.values())


def references(mesh_game_rel, material_game_rel):
    from atelier.handlers import material, meshmat, texture
    result, warnings = {}, []
    for path, kind in ((mesh_game_rel, 'mesh'), (material_game_rel, 'material')):
        if not path:
            continue
        config.validate_game_rel(path)
        jobs.checkpoint()
        try:
            if kind == 'material':
                document = json.loads(Path(material.mat_json(path, out_dir=config.CACHE_3DVIEW, prefer_exact=True)).read_text(encoding='utf-8-sig'))
            else:
                base = texture.ensure_work_base(path, prefer_exact=True)
                if not base:
                    raise ValueError('The mesh import table is unavailable')
                document = meshmat._mesh_json(path, base)
                if document is None:
                    raise ValueError('The mesh import table is unavailable')
            for record in effect_references(document, path):
                key = record['game_rel'].casefold()
                if key in result:
                    result[key]['sources'].append(path)
                else:
                    result[key] = {**record, 'sources': [path]}
        except jobs.Cancelled:
            raise
        except Exception as error:
            warnings.append(f'{kind.capitalize()} references unavailable: {error}')
    return {'ok': True, 'effects': list(result.values()), 'warnings': warnings,
            'scope': 'Direct outgoing package references only; reverse VFX references are not indexed.'}

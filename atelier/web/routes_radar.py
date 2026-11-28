"""Game Patch Radar routes — scan project edits against baseline and record new baselines."""
import json
from bottle import request, response

from atelier import patch_radar


def register(app, get_import_root, list_project_rels_fn):
    @app.get('/api/patch_radar')
    def api_patch_radar():
        response.content_type = 'application/json'
        try:
            root = get_import_root()
            items = list_project_rels_fn(root)
            return json.dumps(patch_radar.scan_project(root, items))
        except Exception as exc:
            response.status = 500
            return json.dumps({'ok': False, 'error': str(exc)})

    @app.post('/api/patch_radar/baseline')
    def api_patch_radar_baseline():
        response.content_type = 'application/json'
        try:
            root = get_import_root()
            body = request.json or {}
            items = body.get('items') if isinstance(body.get('items'), list) else list_project_rels_fn(root)
            saved = patch_radar.record_baseline(root, items)
            return json.dumps({
                'ok': True,
                'recorded_at': saved.get('recorded_at', ''),
                'tracked_count': len(saved.get('targets') or {}),
            })
        except Exception as exc:
            response.status = 500
            return json.dumps({'ok': False, 'error': str(exc)})

    return {
        'api_patch_radar': api_patch_radar,
        'api_patch_radar_baseline': api_patch_radar_baseline,
    }

"""Look Presets and One-Click Hero Theme routes."""
import json
from bottle import request, response

from atelier import themes


def register(app, get_import_root, list_project_rels_fn):
    @app.get('/api/themes/looks')
    def api_themes_looks_get():
        response.content_type = 'application/json'
        return json.dumps({'ok': True, 'looks': themes.list_looks(get_import_root())})

    @app.post('/api/themes/looks')
    def api_themes_looks_save():
        response.content_type = 'application/json'
        try:
            looks = themes.save_custom_look(get_import_root(), request.json or {})
            return json.dumps({'ok': True, 'looks': looks})
        except ValueError as exc:
            response.status = 400
            return json.dumps({'ok': False, 'error': str(exc)})

    @app.post('/api/themes/looks/delete')
    def api_themes_looks_delete():
        response.content_type = 'application/json'
        body = request.json or {}
        looks = themes.delete_custom_look(get_import_root(), body.get('id', ''))
        return json.dumps({'ok': True, 'looks': looks})

    @app.post('/api/themes/propose')
    def api_themes_propose():
        response.content_type = 'application/json'
        body = request.json or {}
        try:
            root = get_import_root()
            proj_items = list_project_rels_fn(root)
            res = themes.propose_theme_targets(
                skin_id=body.get('skin_id', ''),
                hero_id=body.get('hero_id', ''),
                project_items=proj_items,
            )
            return json.dumps(res)
        except Exception as exc:
            response.status = 400
            return json.dumps({'ok': False, 'error': str(exc)})

    @app.post('/api/themes/apply')
    def api_themes_apply():
        response.content_type = 'application/json'
        body = request.json or {}
        try:
            res = themes.apply_theme(
                get_import_root(),
                body.get('targets') or [],
                body.get('theme') or {},
            )
            return json.dumps(res)
        except Exception as exc:
            response.status = 400
            return json.dumps({'ok': False, 'error': str(exc)})

    return {
        'api_themes_looks_get': api_themes_looks_get,
        'api_themes_looks_save': api_themes_looks_save,
        'api_themes_looks_delete': api_themes_looks_delete,
        'api_themes_propose': api_themes_propose,
        'api_themes_apply': api_themes_apply,
    }

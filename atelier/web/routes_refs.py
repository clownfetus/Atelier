"""Shared-asset reference inspection and 1-click Safe Fork routes."""
import json
from bottle import request, response

from atelier import asset_refs


def register(app):
    @app.get('/api/asset_refs')
    def api_asset_refs():
        response.content_type = 'application/json'
        game_rel = request.query.get('game_rel', '')
        deep = str(request.query.get('deep', '')).lower() in ('1', 'true', 'yes')
        try:
            return json.dumps(asset_refs.find_references(game_rel, deep=deep))
        except Exception as exc:
            response.status = 400
            return json.dumps({'ok': False, 'error': str(exc)})

    @app.post('/api/asset_refs/fork')
    def api_asset_refs_fork():
        response.content_type = 'application/json'
        body = request.json or {}
        try:
            return json.dumps(asset_refs.safe_fork(
                body.get('game_rel', ''),
                body.get('file_type') or None,
                folder=body.get('folder') or None,
                name=body.get('name') or None,
            ))
        except Exception as exc:
            response.status = 400
            return json.dumps({'ok': False, 'error': str(exc)})

    return {
        'api_asset_refs': api_asset_refs,
        'api_asset_refs_fork': api_asset_refs_fork,
    }

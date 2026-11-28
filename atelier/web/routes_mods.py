"""Installed mods drawer and Clean-Test sandbox routes."""
import json
import os
from bottle import request, response

from atelier import mod_sandbox


def register(app, get_mods_folder, *, game_running_fn=None, state_path=None, open_folder_fn=None, push_sse=None):
    def _is_game_running():
        if not callable(game_running_fn):
            return False
        try:
            return bool(game_running_fn())
        except Exception:
            return False

    @app.get('/api/mods/installed', skip=['project_scope'])
    def api_mods_installed():
        response.content_type = 'application/json'
        mods_dir = get_mods_folder() or ''
        current_mod = request.query.get('current_mod', '')
        data = mod_sandbox.scan_installed_mods(mods_dir, current_mod_name=current_mod, state_path=state_path)
        data['game_running'] = _is_game_running()
        data['configured'] = bool(mods_dir)
        return json.dumps(data)

    @app.post('/api/mods/toggle', skip=['project_scope'])
    def api_mods_toggle():
        response.content_type = 'application/json'
        body = request.json or {}
        mods_dir = get_mods_folder() or ''
        try:
            res = mod_sandbox.toggle_mod(
                mods_dir,
                body.get('id', ''),
                bool(body.get('enabled')),
                game_running_check=_is_game_running,
            )
            if callable(push_sse):
                push_sse({'mods_changed': True})
            return json.dumps(res)
        except (ValueError, FileNotFoundError, FileExistsError, RuntimeError, OSError) as exc:
            response.status = 409 if isinstance(exc, (RuntimeError, FileExistsError)) else 400
            return json.dumps({'ok': False, 'error': str(exc)})

    @app.post('/api/mods/clean_test', skip=['project_scope'])
    def api_mods_clean_test():
        response.content_type = 'application/json'
        body = request.json or {}
        mods_dir = get_mods_folder() or ''
        try:
            res = mod_sandbox.set_clean_test(
                mods_dir,
                enable=bool(body.get('enable')),
                keep_mod=body.get('keep_mod', ''),
                state_path=state_path,
                game_running_check=_is_game_running,
            )
            if callable(push_sse):
                push_sse({'mods_changed': True})
            return json.dumps(res)
        except (ValueError, FileNotFoundError, FileExistsError, RuntimeError, OSError) as exc:
            response.status = 409 if isinstance(exc, (RuntimeError, FileExistsError)) else 400
            return json.dumps({'ok': False, 'error': str(exc)})

    @app.post('/api/mods/open_folder', skip=['project_scope'])
    def api_mods_open_folder():
        response.content_type = 'application/json'
        mods_dir = get_mods_folder() or ''
        if not mods_dir or not os.path.isdir(mods_dir):
            response.status = 400
            return json.dumps({'ok': False, 'error': 'No mods folder is configured in Settings.'})
        try:
            if callable(open_folder_fn):
                open_folder_fn(mods_dir)
            return json.dumps({'ok': True})
        except Exception as exc:
            response.status = 500
            return json.dumps({'ok': False, 'error': str(exc)})

    return {
        'api_mods_installed': api_mods_installed,
        'api_mods_toggle': api_mods_toggle,
        'api_mods_clean_test': api_mods_clean_test,
        'api_mods_open_folder': api_mods_open_folder,
    }

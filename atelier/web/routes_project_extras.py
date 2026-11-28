"""Project trash listing/discard, colour palette, and selection profile routes."""
import json
from bottle import request, response

from atelier import operations, project_meta, project_trash


def register(app, get_import_root, *, batch_export_handler=None):
    @app.post('/api/restore_imported')
    def api_restore_imported():
        response.content_type = 'application/json'
        try:
            return json.dumps(project_trash.restore(get_import_root(), (request.json or {}).get('entry')))
        except ValueError as error:
            response.status = 400
            return json.dumps({'ok': False, 'error': str(error)})

    @app.get('/api/trash')
    def api_trash_list():
        response.content_type = 'application/json'
        root = get_import_root()
        # Listing also recovers interrupted deletes and expires old entries.
        with operations.project_use(root, write=True):
            entries = project_trash.list_entries(root)
        return json.dumps({'ok': True, 'entries': entries})

    @app.post('/api/trash/discard')
    def api_trash_discard():
        response.content_type = 'application/json'
        body = request.json or {}
        try:
            if body.get('all') is True and 'entry' not in body:
                entry = None
            elif body.get('entry') is not None and 'all' not in body:
                entry = body['entry']
            else:
                raise ValueError('Specify a trash entry or explicitly empty the project trash.')
            return json.dumps(project_trash.discard(get_import_root(), entry))
        except ValueError as error:
            response.status = 400
            return json.dumps({'ok': False, 'error': str(error)})

    @app.get('/api/project/palette')
    def api_project_palette_get():
        response.content_type = 'application/json'
        return json.dumps({'ok': True, 'palette': project_meta.get_palette(get_import_root())})

    @app.post('/api/project/palette')
    def api_project_palette_set():
        response.content_type = 'application/json'
        body = request.json or {}
        saved = project_meta.set_palette(get_import_root(), body.get('palette'))
        return json.dumps({'ok': True, 'palette': saved})

    @app.get('/api/project/profiles')
    def api_project_profiles_get():
        response.content_type = 'application/json'
        return json.dumps({'ok': True, 'profiles': project_meta.get_profiles(get_import_root())})

    @app.post('/api/project/profiles')
    def api_project_profiles_save():
        response.content_type = 'application/json'
        body = request.json or {}
        try:
            profiles = project_meta.save_profile(
                get_import_root(),
                body.get('name', ''),
                body.get('deselected') or [],
                body.get('mod_name', ''),
            )
            return json.dumps({'ok': True, 'profiles': profiles})
        except ValueError as error:
            response.status = 400
            return json.dumps({'ok': False, 'error': str(error)})

    @app.post('/api/project/profiles/delete')
    def api_project_profiles_delete():
        response.content_type = 'application/json'
        body = request.json or {}
        profiles = project_meta.delete_profile(get_import_root(), body.get('name', ''))
        return json.dumps({'ok': True, 'profiles': profiles})

    @app.post('/api/project/export_batch')
    def api_project_export_batch():
        response.content_type = 'application/json'
        if batch_export_handler is None:
            response.status = 501
            return json.dumps({'ok': False, 'error': 'Batch profile export is unavailable.'})
        body = request.json or {}
        result = batch_export_handler(body)
        if isinstance(result, str):
            return result
        return json.dumps(result)

    return {
        'api_restore_imported': api_restore_imported,
        'api_trash_list': api_trash_list,
        'api_trash_discard': api_trash_discard,
        'api_project_palette_get': api_project_palette_get,
        'api_project_palette_set': api_project_palette_set,
        'api_project_profiles_get': api_project_profiles_get,
        'api_project_profiles_save': api_project_profiles_save,
        'api_project_profiles_delete': api_project_profiles_delete,
        'api_project_export_batch': api_project_export_batch,
    }

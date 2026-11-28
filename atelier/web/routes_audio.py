"""Audio & Voice Line Studio routes (catalog, bank clips, waveform, WAV streaming, save/reset, subtitles)."""
import json
from bottle import request, response

from atelier.handlers import audio


def register(app, get_import_root):
    @app.get('/api/audio/catalog')
    def api_audio_catalog():
        response.content_type = 'application/json'
        try:
            cat = audio.scan_audio_catalog()
            edited = audio._edited_map(get_import_root())
            edited_items = [
                {
                    'game_rel': m.get('game_rel', ''),
                    'media_id': str(m.get('media_id', '')),
                    'bank_rel': m.get('bank_rel', ''),
                    'bank_stem': m.get('bank_stem', ''),
                    'hero_id': m.get('hero_id', ''),
                    'group_label': m.get('group_label', ''),
                    'label': m.get('label', ''),
                    'subtitle': m.get('subtitle', ''),
                }
                for m in edited.values() if m.get('game_rel')
            ]
            return json.dumps({
                'ok': True,
                'banks': cat['banks'],
                'streams': cat['streams'],
                'edited_count': len(edited_items),
                'edited_rels': [m['game_rel'] for m in edited_items],
                'edited_items': edited_items,
                'has_subtitles': bool(cat.get('locres_files') or cat.get('info_files')),
                'tools': cat['tools'],
            })
        except Exception as exc:
            response.status = 500
            return json.dumps({'ok': False, 'error': str(exc)})

    @app.get('/api/audio/bank')
    def api_audio_bank():
        response.content_type = 'application/json'
        bank_rel = request.query.get('bank_rel', '')
        try:
            return json.dumps(audio.list_bank_clips(bank_rel, project_dir=get_import_root()))
        except LookupError as exc:
            response.status = 404
            return json.dumps({'ok': False, 'error': str(exc)})
        except Exception as exc:
            response.status = 500
            return json.dumps({'ok': False, 'error': str(exc)})

    @app.get('/api/audio/clip')
    def api_audio_clip():
        response.content_type = 'application/json'
        gr = request.query.get('game_rel', '')
        try:
            return json.dumps(audio.inspect_clip(gr, project_dir=get_import_root()))
        except LookupError as exc:
            response.status = 404
            return json.dumps({'ok': False, 'error': str(exc)})
        except Exception as exc:
            response.status = 400
            return json.dumps({'ok': False, 'error': str(exc)})

    @app.get('/api/audio/wav')
    def api_audio_wav():
        gr = request.query.get('game_rel', '')
        version = request.query.get('version', 'original')
        try:
            wav_data = audio.clip_wav_bytes(gr, version=version, project_dir=get_import_root())
            response.content_type = 'audio/wav'
            response.headers['Cache-Control'] = 'no-store'
            return wav_data
        except Exception as exc:
            response.status = 404
            response.content_type = 'application/json'
            return json.dumps({'ok': False, 'error': str(exc)})

    @app.post('/api/audio/save')
    def api_audio_save():
        response.content_type = 'application/json'
        body = request.json or {}
        try:
            res = audio.save_audio_edit(
                body.get('game_rel', ''),
                wav_b64=body.get('wav_b64') or None,
                dsp=body.get('dsp') or None,
                label=body.get('label'),
                subtitle=body.get('subtitle'),
                project_dir=get_import_root(),
            )
            return json.dumps(res)
        except Exception as exc:
            response.status = 400
            return json.dumps({'ok': False, 'error': str(exc)})

    @app.post('/api/audio/reset')
    def api_audio_reset():
        response.content_type = 'application/json'
        body = request.json or {}
        try:
            return json.dumps(audio.reset_audio_edit(body.get('game_rel', ''), project_dir=get_import_root()))
        except Exception as exc:
            response.status = 400
            return json.dumps({'ok': False, 'error': str(exc)})

    @app.post('/api/audio/subtitle')
    def api_audio_subtitle():
        response.content_type = 'application/json'
        body = request.json or {}
        try:
            return json.dumps(audio.save_custom_subtitle(
                body.get('media_id', ''),
                subtitle=body.get('subtitle', ''),
                label=body.get('label', ''),
                event=body.get('event', ''),
                project_dir=get_import_root(),
            ))
        except Exception as exc:
            response.status = 400
            return json.dumps({'ok': False, 'error': str(exc)})

    @app.post('/api/audio/subtitles/import')
    def api_audio_subtitles_import():
        response.content_type = 'application/json'
        body = request.json or {}
        try:
            return json.dumps(audio.import_subtitles(
                body.get('content', ''),
                body.get('filename', ''),
                project_dir=get_import_root(),
            ))
        except Exception as exc:
            response.status = 400
            return json.dumps({'ok': False, 'error': str(exc)})

    @app.get('/api/audio/subtitles/search')
    def api_audio_subtitles_search():
        response.content_type = 'application/json'
        hero_id = request.query.get('hero_id', '')
        q = request.query.get('q', '')
        try:
            idx = audio.subtitle_index(project_dir=get_import_root())
            return json.dumps({'ok': True, 'lines': idx.hero_subtitles(hero_id, query=q)})
        except Exception as exc:
            response.status = 500
            return json.dumps({'ok': False, 'error': str(exc)})

    return {
        'api_audio_catalog': api_audio_catalog,
        'api_audio_bank': api_audio_bank,
        'api_audio_clip': api_audio_clip,
        'api_audio_wav': api_audio_wav,
        'api_audio_save': api_audio_save,
        'api_audio_reset': api_audio_reset,
        'api_audio_subtitle': api_audio_subtitle,
        'api_audio_subtitles_import': api_audio_subtitles_import,
        'api_audio_subtitles_search': api_audio_subtitles_search,
    }

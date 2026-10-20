"""The local API answers only this machine's own Atelier page, and Settings cannot point the
Blender launcher at another program. Both were reachable from any website the user visited."""
import atexit
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from wsgiref.util import setup_testing_defaults

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
data = tempfile.TemporaryDirectory(prefix='atelier-api-guard-')
os.environ['ATELIER_DATA_DIR'] = data.name
from atelier import config as C
from atelier.handlers import meshedit
from atelier.web import routes as R
from atelier.web.app import request_rejection


def cleanup():
    R.shutdown(5)
    data.cleanup()


atexit.register(cleanup)

BOUNDARY = 'atelier-test-boundary'


def http(path, method='GET', body=b'', content_type=None, **headers):
    env = {}
    setup_testing_defaults(env)
    env.update(PATH_INFO=path, REQUEST_METHOD=method, CONTENT_LENGTH=str(len(body)),
               **{'wsgi.input': io.BytesIO(body)})
    if content_type is not None:
        env['CONTENT_TYPE'] = content_type
    env.update({'HTTP_' + name.upper(): value for name, value in headers.items()})
    replies = []
    result = R.app(env, lambda status, headers, exc_info=None: replies.append(int(status.split()[0])))
    try:
        payload = b''.join(result)
    finally:
        if hasattr(result, 'close'):
            result.close()
    return replies[0], payload


def post_json(path, body, **headers):
    return http(path, 'POST', json.dumps(body).encode(), 'application/json', **headers)


def multipart(**fields):
    parts = [f'--{BOUNDARY}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'
             for name, value in fields.items()]
    return (''.join(parts) + f'--{BOUNDARY}--\r\n').encode()


class RequestRejection(unittest.TestCase):
    def rejection(self, path='/api/app_info', method='GET', **environ):
        return request_rejection({'PATH_INFO': path, 'REQUEST_METHOD': method, **environ})

    def test_loopback_hosts_are_accepted_on_any_port(self):
        for host in ('localhost:8767', '127.0.0.1:8774', '[::1]:8767', 'LOCALHOST', '127.0.0.1'):
            with self.subTest(host=host):
                self.assertIsNone(self.rejection(HTTP_HOST=host))

    def test_rebinding_hosts_are_refused_everywhere(self):
        for host in ('attacker.example:8767', 'localhost.attacker.example', '127.0.0.1.nip.io:8767',
                     '[::2]:8767', '0.0.0.0:8767'):
            for path in ('/api/app_info', '/', '/static/app.js'):
                with self.subTest(host=host, path=path):
                    self.assertEqual(self.rejection(path, HTTP_HOST=host)[0], 403)

    def test_fetch_metadata_must_be_same_origin_for_the_api(self):
        for site in ('cross-site', 'same-site', 'CROSS-SITE'):
            with self.subTest(site=site):
                self.assertEqual(self.rejection(HTTP_HOST='localhost:8767',
                                                HTTP_SEC_FETCH_SITE=site)[0], 403)
        for site in ('same-origin', 'none'):
            with self.subTest(site=site):
                self.assertIsNone(self.rejection(HTTP_HOST='localhost:8767', HTTP_SEC_FETCH_SITE=site))

    def test_origin_must_match_the_host(self):
        host = 'localhost:8767'
        self.assertIsNone(self.rejection(method='POST', HTTP_HOST=host,
                                         HTTP_ORIGIN='http://localhost:8767',
                                         CONTENT_TYPE='application/json'))
        for origin in ('https://attacker.example', 'http://127.0.0.1:8767', 'http://localhost:3000',
                       'null', 'https://localhost:8767'):
            with self.subTest(origin=origin):
                self.assertEqual(self.rejection(method='POST', HTTP_HOST=host, HTTP_ORIGIN=origin,
                                                CONTENT_TYPE='application/json')[0], 403)

    def test_interface_pages_ignore_fetch_metadata(self):
        # Only the API acts; a link that opens the interface itself is harmless.
        self.assertIsNone(self.rejection('/', HTTP_HOST='localhost:8767',
                                         HTTP_SEC_FETCH_SITE='cross-site'))

    def test_state_changes_must_be_json(self):
        for content_type in (None, '', 'text/plain', 'application/x-www-form-urlencoded',
                             'multipart/form-data; boundary=x'):
            with self.subTest(content_type=content_type):
                environ = {} if content_type is None else {'CONTENT_TYPE': content_type}
                self.assertEqual(self.rejection('/api/reset_data', 'POST', **environ)[0], 415)
        self.assertIsNone(self.rejection('/api/reset_data', 'POST',
                                         CONTENT_TYPE='application/json; charset=utf-8'))
        self.assertIsNone(self.rejection('/api/app_info', 'GET', CONTENT_TYPE='text/plain'))

    def test_upload_routes_keep_only_their_own_body_types(self):
        allowed = {
            '/api/assets/add': ('multipart/form-data; boundary=x', 'application/json'),
            '/api/material_custom_texture': ('multipart/form-data; boundary=x',),
            '/api/replace_texture': ('multipart/form-data; boundary=x',),
            '/api/mesh_replace': ('multipart/form-data; boundary=x',),
            '/api/showcase_webp': ('application/octet-stream',),
        }
        for path, types in allowed.items():
            for content_type in types:
                with self.subTest(path=path, content_type=content_type):
                    self.assertIsNone(self.rejection(path, 'POST', CONTENT_TYPE=content_type))
            with self.subTest(path=path, content_type='text/plain'):
                self.assertEqual(self.rejection(path, 'POST', CONTENT_TYPE='text/plain')[0], 415)
        # Cross-site uploads are still refused by origin, before their type is considered.
        self.assertEqual(self.rejection('/api/mesh_replace', 'POST', HTTP_HOST='localhost:8767',
                                        HTTP_ORIGIN='https://attacker.example',
                                        CONTENT_TYPE='multipart/form-data; boundary=x')[0], 403)


class LiveRoutes(unittest.TestCase):
    def setUp(self):
        self.marker = Path(C.ASSETS) / 'projects' / 'guarded' / 'marker.txt'
        self.marker.parent.mkdir(parents=True, exist_ok=True)
        self.marker.write_text('mod work', encoding='utf-8')
        self.addCleanup(shutil.rmtree, self.marker.parent, True)

    def test_cross_site_form_cannot_reset_data(self):
        # The exact request a hidden <form enctype="text/plain"> on any website sends.
        attacks = (
            {'HOST': 'localhost:8767', 'ORIGIN': 'https://attacker.example',
             'SEC_FETCH_SITE': 'cross-site'},
            {'HOST': 'attacker.example:8767', 'ORIGIN': 'http://attacker.example:8767',
             'SEC_FETCH_SITE': 'same-origin'},
            {},   # a browser without fetch metadata still cannot send JSON cross-site
        )
        for headers in attacks:
            with self.subTest(headers=headers):
                status, payload = http('/api/reset_data', 'POST', b'x=1', 'text/plain', **headers)
                self.assertIn(status, (403, 415))
                self.assertFalse(json.loads(payload)['ok'])
                self.assertEqual(self.marker.read_text(encoding='utf-8'), 'mod work')

    def test_rebinding_page_cannot_read_settings(self):
        status, payload = http('/api/setup_status', HOST='attacker.example:8767')
        self.assertEqual(status, 403)
        self.assertNotIn(b'aes_prefill', payload)

    def test_own_page_bodyless_post_still_reaches_routes(self):
        status, payload = http('/api/update_open_release', 'POST', b'', 'application/json',
                               HOST='localhost:8767', ORIGIN='http://localhost:8767',
                               SEC_FETCH_SITE='same-origin')
        self.assertEqual((status, json.loads(payload)), (200, {'ok': False}))

    def test_own_page_multipart_upload_still_reaches_routes(self):
        status, payload = http('/api/replace_texture', 'POST', multipart(note='no file'),
                               f'multipart/form-data; boundary={BOUNDARY}',
                               HOST='localhost:8767', ORIGIN='http://localhost:8767',
                               SEC_FETCH_SITE='same-origin')
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(payload)['error'], 'missing game_rel or file')


class BlenderPath(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(dir=data.name)
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.blender = self.root / meshedit.BLENDER_NAMES[0]
        self.blender.write_bytes(b'')
        self.other = self.root / 'whoami.exe'
        self.other.write_bytes(b'')
        self.addCleanup(lambda: Path(C.CONFIG_FILE).unlink(missing_ok=True))

    def save(self, blender_path):
        return post_json('/api/save_paks', {'path': str(self.root), 'aes_key': '0x' + 'AB' * 32,
                                            'blender_path': blender_path})

    def saved_blender_path(self):
        return C._load_config().get('blender_path')

    def test_only_existing_blender_files_qualify(self):
        self.assertTrue(meshedit.is_blender_executable(str(self.blender)))
        self.assertFalse(meshedit.is_blender_executable(str(self.other)))
        self.assertFalse(meshedit.is_blender_executable(str(self.root / 'missing' / 'blender.exe')))
        folder = self.root / 'folder' / meshedit.BLENDER_NAMES[0]
        folder.mkdir(parents=True)
        self.assertFalse(meshedit.is_blender_executable(str(folder)))
        self.assertFalse(meshedit.is_blender_executable(''))

    def test_save_refuses_another_program_before_saving_anything(self):
        status, payload = self.save(str(self.other))
        result = json.loads(payload)
        self.assertEqual(status, 200)
        self.assertFalse(result['ok'])
        self.assertIn('Blender path', result['error'])
        self.assertIsNone(self.saved_blender_path())

    def test_save_accepts_blender_and_continues_to_game_folder_checks(self):
        result = json.loads(self.save(str(self.blender))[1])
        self.assertFalse(result['ok'])
        self.assertIn('MarvelGame/Marvel/Content/Paks', result['error'])

    def test_clearing_the_path_is_still_allowed(self):
        result = json.loads(self.save('')[1])
        self.assertNotIn('Blender path', result['error'])

    def test_launcher_skips_a_configured_program_that_is_not_blender(self):
        environment = {k: v for k, v in os.environ.items() if k != 'ATELIER_BLENDER'}
        with patch.dict(os.environ, environment, clear=True), \
                patch.object(meshedit, '_scan_blender_dirs', return_value=[]):
            with patch.object(C, 'get_blender_path', return_value=str(self.other)):
                with self.assertRaisesRegex(RuntimeError, 'Blender not found'):
                    meshedit.find_blender()
                self.assertEqual(meshedit.blender_path_suggestion(), '')
            with patch.object(C, 'get_blender_path', return_value=str(self.blender)):
                self.assertEqual(meshedit.find_blender(), str(self.blender))
                self.assertEqual(meshedit.blender_path_suggestion(), str(self.blender))


@unittest.skipUnless(shutil.which('node'), 'Node is unavailable')
class FrontendRequests(unittest.TestCase):
    def test_project_fetch_sends_state_changes_as_json(self):
        script = r'''
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync(process.argv[1],'utf8');
const start=source.indexOf('function projectFetch(');
const end=source.indexOf('window.atelierProject',start);
assert.ok(start>=0 && end>start);
const calls=[];
const environment={_activeProjectName:'A',FormData,Blob,fetch:(path,opts)=>{calls.push(opts);return opts;}};
vm.createContext(environment);vm.runInContext(source.slice(start,end),environment);
const send=(opts)=>environment.projectFetch('/api/x',opts).headers;
assert.equal(send({method:'POST'})['Content-Type'],'application/json');
assert.equal(send({method:'post',body:'{}'})['Content-Type'],'application/json');
const kept=send({method:'POST',headers:{'content-type':'application/json'},body:'{}'});
assert.deepEqual(Object.keys(kept).filter(k=>k.toLowerCase()==='content-type'),['content-type']);
assert.equal(send({method:'POST',body:new FormData()})['Content-Type'],undefined);
assert.equal(send({method:'POST',body:new Blob([])})['Content-Type'],undefined);
assert.equal(send({})['Content-Type'],undefined);
assert.equal(send({method:'POST'})['X-Atelier-Project'],'A');
console.log('PASS projectFetch content types');
'''
        result = subprocess.run([shutil.which('node'), '-e', script, str(ROOT / 'gui/app.js')],
                                capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)


if __name__ == '__main__':
    unittest.main(verbosity=2)

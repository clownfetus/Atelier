"""HTTP regressions for desktop upgrades that retain an existing browser profile."""
import atexit
import io
import os
from pathlib import Path
import sys
import tempfile
import unittest
from wsgiref.util import setup_testing_defaults

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
data = tempfile.TemporaryDirectory(prefix='atelier-frontend-cache-')
os.environ['ATELIER_DATA_DIR'] = data.name
from atelier.web import routes as R


def cleanup():
    R.shutdown(5)
    data.cleanup()


atexit.register(cleanup)


def get(path, modified_since=None):
    env = {}
    setup_testing_defaults(env)
    env.update(REQUEST_METHOD='GET', PATH_INFO=path.split('?')[0],
               QUERY_STRING=path.partition('?')[2], **{'wsgi.input': io.BytesIO()})
    if modified_since:
        env['HTTP_IF_MODIFIED_SINCE'] = modified_since
    replies = []
    body = R.app(env, lambda status, headers, exc_info=None: replies.append((int(status.split()[0]), dict(headers))))
    try:
        content = b''.join(body)
    finally:
        if hasattr(body, 'close'):
            body.close()
    return *replies[0], content


class FrontendCache(unittest.TestCase):
    def test_legacy_and_versioned_page_prevent_storage(self):
        for path in ('/', '/?ui=upgraded'):
            with self.subTest(path=path):
                status, headers, body = get(path)
                self.assertEqual(status, 200)
                self.assertIn('no-store', headers['Cache-Control'])
                self.assertIn(b'/static/tokens.css', body)

    def test_conditional_page_retains_cache_invalidation(self):
        _, headers, _ = get('/')
        status, headers, body = get('/', headers['Last-Modified'])
        self.assertEqual(status, 304)
        self.assertIn('no-store', headers['Cache-Control'])
        self.assertEqual(body, b'')

    def test_stylesheets_prevent_storage(self):
        for path in ('/static/tokens.css', '/static/style.css'):
            with self.subTest(path=path):
                status, headers, body = get(path)
                self.assertEqual(status, 200)
                self.assertIn('no-store', headers['Cache-Control'])
                self.assertTrue(body)


if __name__ == '__main__':
    unittest.main(verbosity=2)

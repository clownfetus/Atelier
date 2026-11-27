"""Check port configuration and when the local server is ready for navigation."""
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def read_port(value=None):
    env = dict(os.environ)
    env.pop("ATELIER_PORT", None)
    if value is not None:
        env["ATELIER_PORT"] = value
    return subprocess.run(
        [sys.executable, "-B", "-c", "from atelier.web.app import PORT; print(PORT)"],
        cwd=ROOT, env=env, capture_output=True, text=True, timeout=10,
    )


class AppPort(unittest.TestCase):
    def test_default_remains_8767(self):
        result = read_port()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "8767")

    def test_override_selects_an_independent_port(self):
        result = read_port("8778")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "8778")

    def test_valid_boundaries(self):
        for value in ("1", "65535"):
            with self.subTest(value=value):
                result = read_port(value)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout.strip(), value)

    def test_invalid_boundaries_fail_clearly(self):
        for value in ("0", "-1", "65536"):
            with self.subTest(value=value):
                result = read_port(value)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("ATELIER_PORT must be an integer from 1 to 65535", result.stderr)
                self.assertEqual(result.stdout, "")

    def test_invalid_format_fails_clearly(self):
        for value in ("", "localhost:8778", "8778.0"):
            with self.subTest(value=value):
                result = read_port(value)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("ATELIER_PORT must be an integer from 1 to 65535", result.stderr)
                self.assertEqual(result.stdout, "")


class ServerReadiness(unittest.TestCase):
    def test_notifies_after_binding_and_before_serving(self):
        from atelier.web import app as web

        stages = []
        make_server = web.make_server

        def bind(*args, **kwargs):
            server = make_server(*args, **kwargs)
            stages.append("bound")
            return server

        adapter = web._ThreadedServer(port=0, on_listening=lambda: stages.append("ready"))
        with patch.object(web, "make_server", bind), patch.object(
            web._ThreadingWSGIServer, "serve_forever", side_effect=lambda: stages.append("serving")
        ):
            adapter.run(web.app)

        self.assertEqual(stages, ["bound", "ready", "serving"])


if __name__ == "__main__":
    unittest.main(verbosity=2)

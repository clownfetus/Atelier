"""The in-app tool updater, offline: a file:// channel and generated archives, no network."""
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from atelier import config, tool_updates as U  # noqa: E402

# A tiny "tool": a Python script started through the interpreter would need a launcher, so the
# probe is stubbed separately; the payload only has to be bytes with known hashes.
NEW = b"tool v2 payload"


def sha(data):
    return hashlib.sha256(data).hexdigest()


class ToolUpdates(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="atelier-tool-updates-")
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.tools = root / "Tools"
        (self.tools / "retoc").mkdir(parents=True)
        self.exe = self.tools / "retoc" / "retoc-rivals-cli.exe"
        self.exe.write_bytes(b"tool v1 payload")
        (self.tools / "tools.json").write_text(json.dumps({"schema": 1, "platform": U.PLATFORM, "tools": {
            "retoc": {"version": "1.0", "updatable": True, "files": {"retoc/retoc-rivals-cli.exe": sha(b"tool v1 payload")}},
            "UAssetTool": {"version": "built", "updatable": False, "files": {"UAssetTool.exe": "0" * 64}},
        }}))
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("retoc-rivals-cli.exe", NEW)
        archive = root / "retoc.zip"
        archive.write_bytes(buf.getvalue())
        self.channel = root / "channel.json"
        self.channel.write_text(json.dumps({"schema": 1, "tools": [{
            "name": "retoc", "version": "2.0",
            "assets": {U.PLATFORM: {"url": archive.as_uri(), "sha256": sha(archive.read_bytes()),
                                    "extract": {"retoc-rivals-cli.exe": {"to": "retoc/retoc-rivals-cli.exe", "sha256": sha(NEW)}}}},
            "probe": {"args": ["--help"], "expect": ["unpack"]}}]}))
        for p in (patch.object(config, "TOOLS", str(self.tools)), patch.object(config, "_CACHE", str(root / "cache")),
                  patch.object(U, "CHANNEL_URL", self.channel.as_uri()), patch.object(U, "_probe", lambda e, s: None)):
            p.start()
            self.addCleanup(p.stop)
        U._channel_cache.update(at=0.0, data=None, error=None)

    def row(self, name="retoc"):
        return next(r for r in U.status()["tools"] if r["name"] == name)

    def test_check_offers_the_channel_version(self):
        U.status(check=True)
        self.assertEqual(self.row()["available"], "2.0")
        self.assertIsNone(self.row("UAssetTool")["available"])

    def test_update_installs_verified_files_and_records_them(self):
        result = U.update_all()
        self.assertEqual(result, {"ok": True, "updated": ["retoc 2.0"], "problems": []})
        self.assertEqual(self.exe.read_bytes(), NEW)
        self.assertEqual((self.row()["version"], self.row()["state"]), ("2.0", "ok"))

    def test_a_tampered_download_is_never_installed(self):
        data = json.loads(self.channel.read_text())
        data["tools"][0]["assets"][U.PLATFORM]["extract"]["retoc-rivals-cli.exe"]["sha256"] = "f" * 64
        self.channel.write_text(json.dumps(data))
        result = U.update_all()
        self.assertFalse(result["ok"])
        self.assertEqual(self.exe.read_bytes(), b"tool v1 payload")
        self.assertEqual(self.row()["version"], "1.0")

    def test_a_tool_that_fails_its_probe_is_not_switched_in(self):
        def refuse(entry, staged):
            raise U.toolfiles.ToolFileError("the new retoc does not offer unpack; not installed")
        with patch.object(U, "_probe", refuse):
            self.assertFalse(U.update_all()["ok"])
        self.assertEqual(self.exe.read_bytes(), b"tool v1 payload")
        self.assertFalse((self.tools / ".staging" / "retoc").exists())

    def test_rollback_restores_what_the_update_replaced(self):
        U.update_all()
        U.rollback("retoc")
        self.assertEqual(self.exe.read_bytes(), b"tool v1 payload")
        self.assertEqual(self.row()["version"], "1.0")
        with self.assertRaises(U.toolfiles.ToolFileError):
            U.rollback("retoc")

    def test_repair_restores_a_missing_tool_without_losing_the_rollback(self):
        U.update_all()
        self.exe.unlink()
        self.assertEqual(self.row()["state"], "missing")
        result = U.repair()
        self.assertEqual(result["repaired"], ["retoc"])
        self.assertIn("UAssetTool is missing", " ".join(result["problems"]))
        self.assertEqual(self.exe.read_bytes(), NEW)
        U.rollback("retoc")
        self.assertEqual(self.exe.read_bytes(), b"tool v1 payload")

    def test_an_unreachable_channel_is_reported_not_raised(self):
        with patch.object(U, "CHANNEL_URL", (Path(self.tmp.name) / "nope.json").as_uri()):
            status = U.status(check=True)
        self.assertTrue(status["ok"])
        self.assertTrue(status["channel_error"])
        self.assertIsNone(self.row()["available"])


class ContainerRetoc(unittest.TestCase):
    """Container work prefers the hardened build unless an update brought a newer upstream."""

    def check(self, files, record, expected):
        from atelier import tools as T
        with tempfile.TemporaryDirectory() as tmp:
            upstream, hardened = Path(tmp, "retoc", "retoc-rivals-cli.exe"), Path(tmp, "shaders", "retoc-rivals-cli.exe")
            for path, present in ((upstream, "retoc" in files), (hardened, "shaders" in files)):
                if present:
                    path.parent.mkdir(parents=True)
                    path.write_bytes(b"x")
            if record is not None:
                Path(tmp, "tools.json").write_text(json.dumps({"tools": record}))
            with patch.object(T, "TOOLS", tmp), patch.object(T, "RETOC", str(upstream)), \
                 patch.object(T, "SHADER_RETOC", str(hardened)), patch.object(T.hostos, "native_tool", return_value=None):
                self.assertEqual(T.container_retoc(), str(upstream if expected == "retoc" else hardened))

    def test_selection(self):
        same = {"retoc": {"version": "3.10.2"}, "retoc-shaders": {"version": "3.10.2-atelier.1"}}
        newer = {"retoc": {"version": "3.11.0"}, "retoc-shaders": {"version": "3.10.2-atelier.1"}}
        self.check({"retoc", "shaders"}, same, "shaders")
        self.check({"retoc", "shaders"}, None, "shaders")
        self.check({"retoc", "shaders"}, newer, "retoc")
        self.check({"retoc"}, same, "retoc")
        self.check({"shaders"}, newer, "shaders")


if __name__ == "__main__":
    unittest.main(verbosity=2)

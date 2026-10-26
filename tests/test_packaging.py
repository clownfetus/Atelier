"""Packaging invariants: the installer never deletes user data, and always ships the native tools.

Static checks over Atelier.iss and scripts/stage_tools.py, plus the staging script run against a
fake Tools/ tree. No PyInstaller, Inno Setup or real tools needed.
"""
from pathlib import Path
import os
import re
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import stage_tools as ST  # noqa: E402

ISS = (ROOT / "packaging" / "Atelier.iss").read_text(encoding="utf-8")

# Folders the installer owns outright. Anything else under {app} may hold user data.
# AtelierNative and retoc are wholly installer/toolchain output; the others are retired layouts.
OWNED = {r"{app}\_internal", r"{app}\Tools\AtelierNative", r"{app}\Tools\retoc",
         r"{app}\Tools\AtelierMesh", r"{app}\Tools\AtelierAnimation", r"{app}\Tools\AtelierImport",
         r"{app}\Tools\retoc-rivals-cli"}


def section(name):
    m = re.search(r"^\[" + re.escape(name) + r"\]\s*$(.*?)(?=^\[|\Z)", ISS, re.M | re.S)
    if not m:
        return []
    return [line.strip() for line in m.group(1).splitlines()
            if line.strip() and not line.strip().startswith(";")]


def field(line, key):
    m = re.search(key + r':\s*"([^"]*)"', line)
    return m.group(1) if m else None


class InstallerKeepsUserData(unittest.TestCase):
    def test_install_delete_only_touches_owned_folders(self):
        for line in section("InstallDelete"):
            with self.subTest(line=line):
                self.assertIn(field(line, "Name"), OWNED)

    def test_uninstall_cleans_patched_runtime_files_only(self):
        self.assertEqual([field(line, "Name") for line in section("UninstallDelete")], [r"{app}\_internal"])

    def test_no_code_section_deletes_files(self):
        code = "\n".join(section("Code"))
        for call in ("DelTree", "DeleteFile", "RemoveDir"):
            self.assertNotIn(call, code)

    def test_project_folders_survive_uninstall(self):
        dirs = section("Dirs")
        for name in (r"{app}\assets\projects", r"{app}\assets\exported"):
            line = next((d for d in dirs if field(d, "Name") == name), "")
            self.assertIn("uninsneveruninstall", line, name)

    def test_no_wildcard_over_the_whole_dist(self):
        for line in section("Files"):
            self.assertNotEqual(field(line, "Source"), r"dist\Atelier\*", line)

    def test_files_never_land_in_user_data(self):
        for line in section("Files"):
            dest = field(line, "DestDir") or ""
            with self.subTest(line=line):
                self.assertNotRegex(dest.lower(), r"\\(assets|_cache|mappings)(\\|$)")

    def test_runtime_authored_seed_is_not_overwritten(self):
        line = next(l for l in section("Files") if "MarvelRivalsCharacterIDs.md" in l)
        self.assertIn("onlyifdoesntexist", line)


class InstallerShipsTools(unittest.TestCase):
    def test_every_windows_manifest_entry_is_in_the_installer(self):
        sources = {field(l, "Source") for l in section("Files")}
        for rel, required in ST.MANIFEST["windows"]:
            src = "dist\\Atelier\\Tools\\" + rel.replace("/", "\\")
            parent = src.rsplit("\\", 1)[0] + "\\*"
            with self.subTest(rel=rel):
                self.assertTrue(src in sources or src + "\\*" in sources or parent in sources,
                                f"{rel} is staged but not installed")

    def test_required_tools_cannot_be_silently_skipped(self):
        for line in section("Files"):
            self.assertNotIn("skipifsourcedoesntexist", line)

    def test_tools_the_code_loads_are_in_the_manifest(self):
        win = {rel for rel, _ in ST.MANIFEST["windows"]}
        sys.path.insert(0, str(ROOT))
        from atelier import tools as TL
        for rel in ("UAssetTool.exe", "UAssetGUI.exe", "AtelierNative/AtelierNative.exe",
                    "AtelierNative/CUE4Parse-Natives.dll", "AtelierNative/oo2core_9_win64.dll",
                    "retoc/retoc-rivals-cli.exe", "shaders/retoc-rivals-cli.exe",
                    "shaders/oo2core_9_win64.dll", "shaders/dxcompiler.dll", "shaders/dxil.dll",
                    "shaders/dxc.exe", "texconv.exe"):
            self.assertIn(rel, win)
        for constant in (TL.NATIVE, TL.RETOC, TL.SHADER_RETOC, TL.UAT, TL.TEXCONV):
            rel = os.path.relpath(constant, TL.TOOLS).replace(os.sep, "/")
            self.assertIn(rel, win, f"{rel} is loaded by atelier.tools but not shipped")
        lin = {rel for rel, _ in ST.MANIFEST["linux"]}
        for rel in ("UAssetTool", "liboo2corelinux64.so.9", "retoc/retoc-rivals-cli",
                    "AtelierNative/AtelierNative", "AtelierNative/CUE4Parse-Natives.so"):
            self.assertIn(rel, lin)

    def test_io_lib_loads_oodle_from_a_shipped_folder(self):
        """io_lib used to load Tools/retoc-rivals-cli/oo2core_9_win64.dll: never shipped, and the
        installer deleted that folder, so in-process pak reads failed on every installed copy."""
        sys.path.insert(0, str(ROOT))
        import io_lib
        loaded = []
        with tempfile.TemporaryDirectory() as tmp:
            dll = Path(tmp) / "shaders" / "oo2core_9_win64.dll"
            dll.parent.mkdir()
            dll.write_bytes(b"x")
            with patch.object(io_lib, "IS_WINDOWS", True), patch.object(io_lib, "_TOOLS", tmp), \
                    patch.object(io_lib.ctypes, "WinDLL", side_effect=lambda p: loaded.append(p) or Mock(),
                                 create=True):
                io_lib._load_oodle()
        # Windows runners may expose TEMP through its 8.3 path alias.
        self.assertEqual([Path(p).resolve() for p in loaded], [dll.resolve()])
        self.assertIn("shaders/oo2core_9_win64.dll", {rel for rel, _ in ST.MANIFEST["windows"]})


class StageTools(unittest.TestCase):
    def _tree(self, root, platform, skip=()):
        tools = root / "Tools"
        for rel, _ in ST.MANIFEST[platform]:
            if rel in skip or "." not in Path(rel).name:
                continue
            (tools / rel).parent.mkdir(parents=True, exist_ok=True)
            (tools / rel).write_bytes(b"x")
        # Dev/run data that must never be staged.
        (tools / "Mappings").mkdir(parents=True, exist_ok=True)
        (tools / "Mappings" / "Marvel.usmap").write_bytes(b"x")
        (tools / "AES_KEY.txt").write_text("00")
        (tools / "shaders" / "_cache").mkdir(parents=True, exist_ok=True)
        (tools / "shaders" / "_cache" / "s1.bin").write_bytes(b"x")
        (tools / "AtelierNative" / "_cache").mkdir(parents=True, exist_ok=True)
        dist = root / "dist" / "Atelier"
        (dist / "_internal").mkdir(parents=True)
        (dist / ("Atelier.exe" if platform == "windows" else "Atelier")).write_bytes(b"x")
        return tools, dist

    def _run(self, platform, tools, dist):
        return subprocess.run([sys.executable, str(ROOT / "scripts" / "stage_tools.py"),
                               "--platform", platform, "--src", str(tools), "--dist", str(dist)],
                              capture_output=True, text=True)

    def test_stages_only_the_manifest(self):
        for platform in ("windows", "linux"):
            with self.subTest(platform=platform), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                # Linux has extensionless executables; create them explicitly.
                for rel, _ in ST.MANIFEST[platform]:
                    if "." not in Path(rel).name:
                        (root / "Tools" / rel).parent.mkdir(parents=True, exist_ok=True)
                        (root / "Tools" / rel).write_bytes(b"x")
                tools, dist = self._tree(root, platform)
                r = self._run(platform, tools, dist)
                self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
                staged = {p.relative_to(dist / "Tools").as_posix() for p in (dist / "Tools").rglob("*")}
                self.assertNotIn("Mappings", staged)
                self.assertNotIn("AES_KEY.txt", staged)
                self.assertFalse(any("_cache" in s for s in staged), staged)
                for rel, required in ST.MANIFEST[platform]:
                    if required:
                        self.assertIn(rel, staged)

    def test_missing_required_tool_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            tools, dist = self._tree(Path(tmp), "windows", skip={"shaders/oo2core_9_win64.dll"})
            r = self._run("windows", tools, dist)
            self.assertNotEqual(r.returncode, 0)
            self.assertIn("shaders/oo2core_9_win64.dll", r.stdout + r.stderr)

    def test_run_data_beside_the_exe_fails_the_audit(self):
        with tempfile.TemporaryDirectory() as tmp:
            tools, dist = self._tree(Path(tmp), "windows")
            (dist / "assets" / "projects" / "Mine").mkdir(parents=True)
            (dist / "mr_config.json").write_text("{}")
            r = self._run("windows", tools, dist)
            self.assertNotEqual(r.returncode, 0)
            self.assertIn("assets", r.stdout + r.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)

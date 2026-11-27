"""Local mod pairing, confirmed repair and read-only installed checks."""
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from atelier.handlers import file_repair as repair


TOC = b"fixture toc"
BROKEN = b"needs repair"
OTHER_BROKEN = b"newly broken"
CLEAN = b"fixed asset!"
PAK = b"companion pak"


@dataclass(frozen=True)
class Scan:
    status: str
    materials: int
    fixed: int
    problems: int
    reason: str
    input_digest: str


class FakeChecker:
    """A stand-in for the byte-level checker. The real handler owns the filesystem."""
    MAX_INPUT_BYTES = 1024
    ScanResult = Scan

    class Unavailable(RuntimeError):
        pass

    class RepairError(ValueError):
        pass

    def __init__(self):
        self.count = 0
        self.version = "a" * 64
        self.output = CLEAN

    def module_digest(self):
        return self.version

    def scan_pair(self, utoc, ucas):
        self.count += 1
        digest = hashlib.sha256(utoc + ucas).hexdigest()
        if utoc == TOC and ucas in (BROKEN, OTHER_BROKEN):
            return Scan("repairable", 1, 1, 0, "", digest)
        if utoc == TOC and ucas == self.output:
            return Scan("clean", 1, 0, 0, "", digest)
        return Scan("unreadable", 0, 0, 0, "This container could not be read.", digest)

    def repair_pair(self, utoc, ucas, scan):
        if (utoc, ucas, scan.status) != (TOC, BROKEN, "repairable"):
            raise self.RepairError("This container changed.")
        return utoc, self.output


class FileRepairTests(unittest.TestCase):
    def setUp(self):
        tree = self.enterContext(tempfile.TemporaryDirectory(prefix="atelier-file-repair-test-"))
        self.root = Path(tree)
        self.cache = self.root / "cache"
        self.mods = self.root / "mods"
        self.mods.mkdir()
        self.saved = self.root / "saved"
        self.saved.mkdir()
        self.checker = FakeChecker()
        self.enterContext(patch.object(repair, "file_fixer", self.checker))
        self.enterContext(patch.object(repair.config, "_CACHE", str(self.cache)))
        self.enterContext(patch.object(repair.hostos, "installed_tool", return_value=None))

    def loose(self, folder, name="Dye", data=BROKEN):
        folder.mkdir(parents=True, exist_ok=True)
        toc = folder / (name + ".UTOC")
        toc.write_bytes(TOC)
        (folder / (name + ".ucas")).write_bytes(data)
        (folder / (name + ".pak")).write_bytes(PAK)
        return toc

    def archive(self, path, members):
        with ZipFile(path, "w") as archive:
            archive.comment = b"mod archive note"
            for name, data in members.items():
                archive.writestr(name, data)
        return path

    def token(self, source):
        scan = repair.scan_source(source)
        self.assertEqual(scan["status"], "repairable", scan["reason"])
        return scan["token"]

    def test_loose_input_saves_a_separate_complete_zip(self):
        toc = self.loose(self.mods)
        source = toc.with_suffix(".pak")
        scan = repair.scan_source(source)
        self.assertEqual(scan["status"], "repairable")
        self.assertEqual(scan["fixed"], 1)
        self.assertEqual(scan["suggested_name"], "Dye-repaired.zip")
        self.assertNotIn(str(self.mods), str(scan))
        destination = self.saved / "copy.zip"
        self.assertEqual(repair.save_repaired(scan["token"], destination)["status"], "repaired")
        with ZipFile(destination) as archive:
            self.assertEqual({name: archive.read(name) for name in archive.namelist()}, {
                "Dye.UTOC": TOC, "Dye.ucas": CLEAN, "Dye.pak": PAK,
            })
        self.assertEqual(toc.with_suffix(".ucas").read_bytes(), BROKEN)
        self.assertEqual(len(list(self.mods.iterdir())), 3)

    def test_zip_repair_preserves_unrelated_members_and_companion(self):
        members = {
            "nested/": b"", "nested/Dye.utoc": TOC, "nested/Dye.ucas": BROKEN,
            "nested/Dye.PAK": PAK, "nested/Readme.txt": b"author's notes",
            "alt/Extra.pak": b"other mod file",
        }
        source = self.archive(self.root / "mod.zip", members)
        original = source.read_bytes()
        scan = repair.scan_source(source)
        destination = self.saved / "copy.zip"
        self.assertTrue(repair.save_repaired(scan["token"], destination)["ok"])
        with ZipFile(destination) as archive:
            self.assertEqual(archive.comment, b"mod archive note")
            self.assertEqual({name: archive.read(name) for name in archive.namelist()},
                             members | {"nested/Dye.ucas": CLEAN})
        self.assertEqual(source.read_bytes(), original)

    def test_zip_refuses_multiple_or_unmatched_pairs(self):
        for members in (
            {"one/Dye.utoc": TOC, "two/Dye.ucas": BROKEN},
            {"Dye.utoc": TOC, "Dye.ucas": BROKEN, "Other.utoc": TOC, "Other.ucas": BROKEN},
            {"Dye.utoc": TOC, "Dye.ucas": BROKEN, "Dye_s1.ucas": BROKEN},
        ):
            with self.subTest(names=list(members)):
                scan = repair.scan_source(self.archive(self.root / "mod.zip", members))
                self.assertEqual(scan["status"], "review")
                self.assertIsNone(scan["token"])
                self.assertTrue(scan["reason"])

    def test_zip_refuses_unsafe_member_names(self):
        for name in ("../outside.txt", "nested\\..\\outside.txt", "C:/outside.txt", "/root.txt",
                     "nested/file:stream", "nested/CON.txt", "nested/file. ", "dye.UTOC", "Dye.utoc/file"):
            with self.subTest(name=name):
                source = self.archive(self.root / "mod.zip", {"Dye.utoc": TOC, "Dye.ucas": BROKEN, name: b"extra"})
                scan = repair.scan_source(source)
                self.assertEqual(scan["status"], "unreadable")
                self.assertIsNone(scan["token"])

    def test_zip_refuses_symbolic_link_members(self):
        link = ZipInfo("link")
        link.create_system = 3
        link.external_attr = (stat.S_IFLNK | 0o777) << 16
        source = self.archive(self.root / "mod.zip", {"Dye.utoc": TOC, "Dye.ucas": BROKEN, link: b"target"})
        self.assertEqual(repair.scan_source(source)["status"], "unreadable")

    def test_input_limit_applies_to_expanded_pair_bytes(self):
        source = self.root / "big.zip"
        with ZipFile(source, "w", ZIP_DEFLATED) as archive:
            archive.writestr("Dye.utoc", TOC)
            archive.writestr("Dye.ucas", b"x" * 1020)
        scan = repair.scan_source(source)
        self.assertEqual(scan["status"], "review")
        self.assertIsNone(scan["token"])
        self.assertEqual(self.checker.count, 0)

    def test_locked_loose_mod_does_not_get_a_repair_token(self):
        toc = self.loose(self.mods, data=BROKEN + b"UE5SCOcodeUE5SCO")
        scan = repair.scan_source(toc)
        self.assertEqual(scan["status"], "review")
        self.assertIsNone(scan["token"])
        self.assertNotIn("code", scan["reason"])

    def test_changed_archive_member_invalidates_confirmation(self):
        members = {"Dye.utoc": TOC, "Dye.ucas": BROKEN, "Readme.txt": b"old"}
        source = self.archive(self.root / "mod.zip", members)
        token = self.token(source)
        original = source.stat()
        self.archive(source, members | {"Readme.txt": b"new"})
        os.utime(source, ns=(original.st_atime_ns, original.st_mtime_ns))
        destination = self.saved / "copy.zip"
        self.assertFalse(repair.save_repaired(token, destination)["ok"])
        self.assertEqual(list(self.saved.iterdir()), [])

    def test_changed_loose_companion_invalidates_confirmation(self):
        toc = self.loose(self.mods)
        token = self.token(toc)
        pak = toc.with_suffix(".pak")
        original = pak.stat()
        pak.write_bytes(b"x" * len(PAK))
        os.utime(pak, ns=(original.st_atime_ns, original.st_mtime_ns))
        self.assertFalse(repair.save_repaired(token, self.saved / "copy.zip")["ok"])
        self.assertEqual(list(self.saved.iterdir()), [])

    def test_existing_destination_is_preserved_if_it_appears_during_publication(self):
        toc = self.loose(self.mods)
        token = self.token(toc)
        destination = self.saved / "copy.zip"
        with patch.object(repair.jobs, "begin_publication", side_effect=lambda _label: destination.write_bytes(b"keep")):
            self.assertFalse(repair.save_repaired(token, destination)["ok"])
        self.assertEqual(destination.read_bytes(), b"keep")
        self.assertEqual(list(self.saved.iterdir()), [destination])

    def test_cancellation_during_save_removes_staged_files(self):
        toc = self.loose(self.mods)
        token = self.token(toc)

        def checkpoint():
            if list(self.saved.iterdir()):
                raise repair.jobs.Cancelled()

        with self.assertRaises(repair.jobs.Cancelled):
            repair.save_repaired(token, self.saved / "copy.zip", checkpoint=checkpoint)
        self.assertEqual(list(self.saved.iterdir()), [])
        self.assertEqual(toc.with_suffix(".ucas").read_bytes(), BROKEN)

    def test_failed_output_rescan_leaves_no_copy(self):
        toc = self.loose(self.mods)
        token = self.token(toc)
        self.checker.output = BROKEN
        self.assertFalse(repair.save_repaired(token, self.saved / "copy.zip")["ok"])
        self.assertEqual(list(self.saved.iterdir()), [])

    def test_archive_growth_cannot_exceed_the_repair_limit(self):
        self.checker.output = b"new " + CLEAN * 3
        toc = self.loose(self.mods)
        with patch.object(repair, "_MAX_ARCHIVE_BYTES", 40):
            token = self.token(toc)
            result = repair.save_repaired(token, self.saved / "copy.zip")
        self.assertFalse(result["ok"])
        self.assertEqual(list(self.saved.iterdir()), [])

    def test_native_readback_failure_after_input_opens_leaves_no_copy(self):
        toc = self.loose(self.mods)
        token = self.token(toc)

        def reader(argv, **_options):
            data = Path(argv[-1]).with_suffix(".ucas").read_bytes()
            return subprocess.CompletedProcess(argv, 0 if data == BROKEN else 1)

        with (patch.object(repair.hostos, "installed_tool", return_value="reader"),
              patch.object(repair.hostos, "run_exe", side_effect=reader)):
            result = repair.save_repaired(token, self.saved / "copy.zip")
        self.assertFalse(result["ok"])
        self.assertIn("container reader", result["error"])
        self.assertEqual(list(self.saved.iterdir()), [])

    def test_installed_checks_cache_full_content_and_checker_revision(self):
        self.loose(self.mods, "Needs repair")
        clean = self.loose(self.mods / "subfolder", "Clean", CLEAN)
        self.loose(self.mods / "archive.disabled", "Disabled")
        (self.mods / "partial.utoc").write_bytes(TOC)
        self.archive(self.mods / "unused.zip", {"Dye.utoc": TOC, "Dye.ucas": BROKEN})
        first = repair.scan_installed(self.mods)
        self.assertEqual((first["checked"], first["repairable"]), (2, 1))
        self.assertEqual(len(first["repairs"]), 1)
        self.assertEqual(self.checker.count, 2)
        self.assertNotIn(str(self.mods), str(first))
        self.assertEqual(repair.scan_installed(self.mods)["repairable"], 1)
        self.assertEqual(self.checker.count, 2)

        ucas = clean.with_suffix(".ucas")
        original = ucas.stat()
        ucas.write_bytes(OTHER_BROKEN)
        os.utime(ucas, ns=(original.st_atime_ns, original.st_mtime_ns))
        self.assertEqual(repair.scan_installed(self.mods)["repairable"], 2)
        self.assertEqual(self.checker.count, 3)

        self.checker.version = "b" * 64
        self.assertEqual(repair.scan_installed(self.mods)["repairable"], 2)
        self.assertEqual(self.checker.count, 5)


if __name__ == "__main__":
    unittest.main()

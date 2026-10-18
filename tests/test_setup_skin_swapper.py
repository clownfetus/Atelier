"""Template installation failures preserve the previously installed pair."""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import stage_galacta_template as ST


class TemplateInstallation(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="atelier-template-install-")
        root = Path(self.temporary.name).resolve()
        self.source, self.destination = root / "input", root / "Tools" / "Galacta"
        self.source.mkdir()
        self.destination.mkdir(parents=True)
        for name in ST.FILES:
            (self.destination / name).write_bytes(b"previous " + name.encode())
            (self.source / name).write_bytes(b"replacement " + name.encode())

    def tearDown(self):
        self.temporary.cleanup()

    def previous_pair_intact(self):
        for name in ST.FILES:
            self.assertEqual((self.destination / name).read_bytes(), b"previous " + name.encode())

    def test_missing_second_half_does_not_change_the_first(self):
        (self.source / ST.FILES[1]).unlink()
        with self.assertRaisesRegex(ValueError, "Missing or empty"):
            ST.install_template(self.source, self.destination)
        self.previous_pair_intact()

    def test_second_copy_failure_preserves_both_previous_files(self):
        copy = ST.storage.shutil.copy2
        def fail_second(source, destination, **kwargs):
            if Path(source) == self.source / ST.FILES[1]:
                raise OSError("simulated full disk")
            return copy(source, destination, **kwargs)
        with patch.object(ST.storage.shutil, "copy2", side_effect=fail_second):
            with self.assertRaisesRegex(OSError, "full disk"):
                ST.install_template(self.source, self.destination)
        self.previous_pair_intact()

    def test_failed_second_file_publication_rolls_back_the_first(self):
        replace = ST.storage.os.replace
        failed = False
        def fail_publication(source, destination):
            nonlocal failed
            if Path(destination) == self.destination / ST.FILES[1] and not failed:
                failed = True
                raise PermissionError("simulated locked destination")
            return replace(source, destination)
        with patch.object(ST.storage.os, "replace", side_effect=fail_publication):
            with self.assertRaisesRegex(PermissionError, "locked destination"):
                ST.install_template(self.source, self.destination)
        self.previous_pair_intact()

    def test_complete_pair_is_installed_and_reruns_are_idempotent(self):
        hashes = ST.install_template(self.source, self.destination)
        self.assertEqual(ST.install_template(self.source, self.destination), hashes)
        for name in ST.FILES:
            self.assertEqual((self.destination / name).read_bytes(), (self.source / name).read_bytes())


if __name__ == "__main__":
    unittest.main()

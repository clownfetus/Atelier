"""Exercise the repair adapter through a minimal Wasmtime guest."""
import hashlib
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import wasmtime

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from atelier import file_fixer


GUEST = """
(module
  (memory (export "memory") 1)
  (global $next (mut i32) (i32.const 1024))
  (data (i32.const 256) "repaired-utocrepaired-ucas")
  (func (export "alloc") (param $size i32) (result i32)
    (local $old i32)
    (local.set $old (global.get $next))
    (global.set $next (i32.add (local.get $old) (local.get $size)))
    (local.get $old))
  (func (export "dealloc") (param i32 i32))
  (func (export "fix_mod") (param $utoc i32) (param i32 i32 i32)
      (param $assume i32) (param $check i32) (result i32)
    (local $case i32)
    (local.set $case (i32.load8_u (local.get $utoc)))
    (if (i32.eq (local.get $case) (i32.const 3)) (then (return (i32.const 65530))))
    (if (i32.eq (local.get $case) (i32.const 4)) (then unreachable))
    (i32.store offset=12 (i32.const 64) (i32.const 1))
    (i32.store offset=16 (i32.const 64)
      (i32.or (i32.eq (local.get $case) (i32.const 1))
              (i32.and (i32.eq (local.get $case) (i32.const 2)) (local.get $assume))))
    (if (i32.eqz (local.get $check))
      (then
        (i32.store offset=20 (i32.const 64) (i32.const 256))
        (i32.store offset=24 (i32.const 64) (i32.const 13))
        (i32.store offset=28 (i32.const 64) (i32.const 269))
        (i32.store offset=32 (i32.const 64) (i32.const 13))))
    (i32.const 64)))
"""


class RepairAdapterTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.module = Path(temp.name) / "file_fixer.wasm"
        self.bytes = wasmtime.wat2wasm(GUEST)
        self.module.write_bytes(self.bytes)
        self.enterContext(patch.object(file_fixer, "_WASM", self.module))
        self.enterContext(patch.object(file_fixer, "_SHA256", hashlib.sha256(self.bytes).hexdigest()))
        file_fixer._runtime.cache_clear()
        self.addCleanup(file_fixer._runtime.cache_clear)

    def test_checks_then_repairs_the_approved_pair(self):
        scan = file_fixer.scan_pair(b"\x01old", b"packages")
        self.assertEqual((scan.status, scan.materials, scan.fixed), ("repairable", 1, 1))
        self.assertEqual(file_fixer.repair_pair(b"\x01old", b"packages", scan),
                         (b"repaired-utoc", b"repaired-ucas"))
        with self.assertRaises(file_fixer.RepairError):
            file_fixer.repair_pair(b"\x01old", b"different", scan)

    def test_ambiguity_requires_review(self):
        scan = file_fixer.scan_pair(b"\x02ambiguous", b"packages")
        self.assertEqual(scan.status, "review")
        with self.assertRaises(file_fixer.RepairError):
            file_fixer.repair_pair(b"\x02ambiguous", b"packages", scan)

    def test_clean_and_unreadable_are_distinct(self):
        self.assertEqual(file_fixer.scan_pair(b"\x00clean", b"packages").status, "clean")
        for kind in (b"\x03", b"\x04"):
            with self.subTest(kind=kind):
                self.assertEqual(file_fixer.scan_pair(kind, b"packages").status, "unreadable")

    def test_rejects_changed_module_before_compiling(self):
        self.module.write_bytes(self.bytes + b"changed")
        with self.assertRaises(file_fixer.Unavailable):
            file_fixer.module_digest()

    def test_rejects_imports_even_with_a_matching_digest(self):
        guest = GUEST.replace("(module", '(module (import "env" "read" (func))', 1)
        dependency = wasmtime.wat2wasm(guest)
        self.module.write_bytes(dependency)
        with patch.object(file_fixer, "_SHA256", hashlib.sha256(dependency).hexdigest()):
            with self.assertRaises(file_fixer.Unavailable):
                file_fixer.module_digest()


class BundledModuleTests(unittest.TestCase):
    def test_bundled_module_loads_and_rejects_a_non_container(self):
        self.assertEqual(file_fixer.module_digest(), file_fixer._SHA256)
        result = file_fixer.scan_pair(b"not a container", b"package data")
        self.assertEqual(result.status, "unreadable")

    def test_frozen_app_stages_the_module_and_licences(self):
        from pathlib import Path
        spec = (Path(__file__).resolve().parents[1] / "packaging" / "Atelier.spec").read_text(encoding="utf-8")
        self.assertIn("module_digest()", spec)
        for name in ("file_fixer.wasm", "THIRD_PARTY_NOTICES.txt", "RUST-COPYRIGHT.html"):
            self.assertIn(name, spec)
            self.assertTrue(file_fixer._WASM.with_name(name).is_file())


if __name__ == "__main__":
    unittest.main()

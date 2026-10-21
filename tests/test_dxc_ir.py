"""DXIL validation must check the native operation result before claiming success."""
from contextlib import ExitStack
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from atelier.handlers import dxc_ir as D


class DxcValidation(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(D, '_dxc', object()))
        self.stack.enter_context(patch.object(D, '_dxil', object()))
        self.create = self.stack.enter_context(patch.object(D, '_create', side_effect=['utils', 'validator']))
        self.blob = self.stack.enter_context(patch.object(D, '_blob', return_value=('shader', bytearray(b'DXBC' + b'\1' * 28))))
        self.bytes = self.stack.enter_context(patch.object(D, '_bytes', return_value=b'fixture shader validation error'))

    @staticmethod
    def native(status=0, hr=0, result=True):
        def call(obj, index, _restype, _argtypes, *args):
            if obj == 'validator':
                if result:
                    args[-1]._obj.value = 123
                return hr
            if index == 3:
                args[-1]._obj.value = status
            elif index == 5:
                args[-1]._obj.value = 456
            return 0
        return call

    def test_validated_shader_returns_the_signed_container(self):
        with patch.object(D, '_call', side_effect=self.native()):
            data, signed = D._try_sign(bytearray(b'input'))
        self.assertEqual(data, b'DXBC' + b'\1' * 28)
        self.assertTrue(signed)

    def test_nonzero_hash_never_hides_a_failed_validation(self):
        with patch.object(D, '_call', side_effect=self.native(status=-1)):
            with self.assertRaisesRegex(RuntimeError, 'fixture shader validation error'):
                D._try_sign(bytearray(b'DXBC' + b'\1' * 28))

    def test_failed_native_call_and_missing_result_do_not_publish(self):
        for settings in (dict(hr=-1), dict(result=False)):
            self.create.side_effect = ['utils', 'validator']
            with self.subTest(settings=settings), patch.object(D, '_call', side_effect=self.native(**settings)):
                with self.assertRaisesRegex(RuntimeError, 'DXIL validation failed'):
                    D._try_sign(bytearray(b'input'))

    def test_unavailable_validator_retains_explicit_unsigned_fallback(self):
        self.create.side_effect = ['utils', RuntimeError('fixture validator unavailable')]
        with patch.object(D, '_call') as call:
            self.assertEqual(D._try_sign(bytearray(b'input')), (b'input', False))
            call.assert_not_called()

    def test_native_status_read_failure_is_not_treated_as_success(self):
        native = self.native()
        def call(obj, index, *args):
            if obj != 'validator' and index == 3:
                return -1
            return native(obj, index, *args)
        with patch.object(D, '_call', side_effect=call):
            with self.assertRaisesRegex(RuntimeError, 'status unavailable'):
                D._try_sign(bytearray(b'input'))


if __name__ == '__main__':
    unittest.main()

"""Check desktop game launch and status without opening Steam."""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from atelier import window_game as game


class GameControlsTests(unittest.TestCase):
    def test_detects_an_externally_started_game_and_its_exit(self):
        controls = game.GameControls()
        with patch.object(game, '_game_running', side_effect=[True, True, False]), \
                patch.object(game.hostos, 'open_path') as open_path:
            self.assertEqual(controls.game_status()['state'], 'running')
            self.assertEqual(controls.launch_game()['state'], 'running')
            self.assertEqual(controls.game_status()['state'], 'ready')
        open_path.assert_not_called()

    def test_launch_waits_for_the_game_and_ignores_duplicate_clicks(self):
        controls = game.GameControls()
        with patch.object(game, '_game_running', side_effect=[False, False, False, True, False]), \
                patch.object(game.hostos, 'open_path') as open_path:
            self.assertEqual(controls.launch_game()['state'], 'starting')
            self.assertEqual(controls.game_status()['state'], 'starting')
            self.assertEqual(controls.launch_game()['state'], 'starting')
            self.assertEqual(controls.game_status()['state'], 'running')
            self.assertEqual(controls.game_status()['state'], 'ready')
        open_path.assert_called_once_with('steam://rungameid/2767030')

    def test_expired_launch_becomes_ready_without_reporting_success(self):
        controls = game.GameControls()
        with patch.object(game, '_game_running', return_value=False), \
                patch.object(game.hostos, 'open_path'), \
                patch.object(game.time, 'monotonic', return_value=100) as monotonic:
            self.assertEqual(controls.launch_game()['state'], 'starting')
            monotonic.return_value = 200
            self.assertEqual(controls.game_status()['state'], 'ready')

    def test_steam_open_error_leaves_launch_available(self):
        controls = game.GameControls()
        with patch.object(game, '_game_running', return_value=False), \
                patch.object(game.hostos, 'open_path', side_effect=OSError):
            result = controls.launch_game()
            self.assertEqual(result['state'], 'ready')
            self.assertIn('Steam', result['error'])
            self.assertEqual(controls.game_status()['state'], 'ready')

    def test_failed_process_check_reports_unknown_and_recovers(self):
        controls = game.GameControls()
        with patch.object(game, '_game_running', side_effect=[OSError, True]):
            self.assertEqual(controls.game_status()['state'], 'unknown')
            self.assertEqual(controls.game_status()['state'], 'running')

    def test_proton_matches_the_game_executable_and_ignores_helpers(self):
        with tempfile.TemporaryDirectory() as root:
            proc = Path(root)
            process = proc / '101'
            process.mkdir()
            cmdline = process / 'cmdline'
            cmdline.write_bytes(b'MarvelRivals_Launcher.exe\0Marvel-Win64-Shipping.exe\0')
            self.assertFalse(game._proton_game_running(proc))
            cmdline.write_bytes(b'Z:\\Steam library\\Marvel-Win64-Shipping.exe\0-argument\0')
            self.assertTrue(game._proton_game_running(proc))


if __name__ == '__main__':
    unittest.main()

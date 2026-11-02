"""Automatic release selection, CI provenance and conservative hotfix coverage."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import release_automation as A
import release_browser_checks as B
import release_check_scope as S
import release_checks as C

SHA = 'a' * 40


def checks(commit=SHA, **changes):
    return dict(id=42, run_attempt=1, event='push', head_branch='main', head_sha=commit,
                path=A.CHECKS_PATH, status='completed', conclusion='success',
                repository={'full_name': A.REPOSITORY}, head_repository={'full_name': A.REPOSITORY}) | changes


class AutomaticReleases(unittest.TestCase):
    def plan(self, run=None, event=None, previous_commit='b' * 40):
        return A.automatic_plan(event or {'workflow_run': checks()}, SHA, run or checks(),
                                {'tag_name': 'v1.1.5'}, previous_commit)

    def test_assigns_next_patch_to_verified_main(self):
        plan = self.plan()
        self.assertTrue(plan['release'])
        self.assertEqual((plan['version'], plan['source_commit'], plan['checks_run']), ('1.1.6', SHA, '42'))

    def test_drafts_and_existing_tags_are_not_overwritten(self):
        self.assertEqual(A.next_patch('v1.1.5', ['v1.1.6', '1.1.7']), '1.1.8')
        with self.assertRaises(ValueError):
            A.next_patch('1.1.99')

    def test_delayed_older_event_selects_latest_green_main(self):
        plan = self.plan(event={'workflow_run': checks(commit='c' * 40, id=40)})
        self.assertEqual(plan['source_commit'], SHA)
        self.assertEqual(plan['checks_run'], '42')

    def test_webhook_repository_is_also_supported_at_top_level(self):
        run = checks()
        repository = run.pop('repository')
        self.assertTrue(self.plan(event={'workflow_run': run, 'repository': repository})['release'])

    def test_failed_in_progress_foreign_and_pr_checks_cannot_release(self):
        for change in [dict(conclusion='failure'), dict(status='in_progress'), dict(event='pull_request'),
                       dict(head_branch='feature'), dict(head_sha='f' * 40), dict(path='other.yml'),
                       dict(repository={'full_name': 'fork/Atelier'}), dict(head_repository={'full_name': 'fork/Atelier'})]:
            with self.subTest(change=change):
                self.assertFalse(self.plan(run=checks(**change))['release'])
        for change in [dict(event='pull_request'), dict(conclusion='failure'), dict(head_branch='feature'),
                       dict(head_repository={'full_name': 'fork/Atelier'})]:
            self.assertFalse(self.plan(event={'workflow_run': checks(**change)})['release'])

    def test_already_published_commit_is_a_noop(self):
        self.assertFalse(self.plan(previous_commit=SHA)['release'])

    def test_latest_failed_rerun_does_not_reuse_an_older_success(self):
        with patch.object(A, 'api', return_value={'workflow_runs': [checks(), checks(id=43, conclusion='failure')]}):
            self.assertIsNone(A.latest_checks(SHA))

    def test_publication_rechecks_main_after_building(self):
        with patch.dict(A.os.environ, {'GITHUB_EVENT_NAME': 'workflow_run'}), \
             patch.object(A.sys, 'argv', ['release_automation.py', '--publishable', SHA]), \
             patch.object(A, 'api', return_value={'object': {'sha': 'c' * 40}}), \
             patch.object(A, 'outputs') as output, patch.object(A, 'latest_checks') as current:
            A.main()
            output.assert_called_once_with({'publishable': False})
            current.assert_not_called()

    def test_invalid_manual_version_cannot_write_workflow_outputs(self):
        with patch.dict(A.os.environ, {'GITHUB_EVENT_NAME': 'workflow_dispatch', 'GITHUB_SHA': SHA,
                                       'RELEASE_VERSION': '1.1.6\nsource_commit=other'}), \
             patch.object(A.sys, 'argv', ['release_automation.py']), patch.object(A, 'outputs') as output:
            with self.assertRaises(ValueError):
                A.main()
            output.assert_not_called()


class ReuseChecks(unittest.TestCase):
    def setUp(self):
        self.packages = {'example': '1.0'}
        self.suites = ['test_one.py', 'test_two.py']
        self.report = dict(source_commit=SHA, run_id='42', run_attempt='1', platform='win32',
                           python=sys.version, packages=self.packages,
                           results=[dict(suite=name, exit_code=0) for name in self.suites])

    def valid(self, report=None, run=None):
        with patch.object(C.sys, 'platform', 'win32'):
            return C.validate_reuse(report or self.report, run or checks(), SHA, self.suites, self.packages)

    def test_exact_commit_environment_and_complete_successful_receipt_is_reusable(self):
        self.assertTrue(self.valid())

    def test_wrong_commit_attempt_environment_or_incomplete_suites_are_not_reused(self):
        for change in [dict(source_commit='b' * 40), dict(run_id='41'), dict(run_attempt='2'), dict(platform='linux'),
                       dict(python='3.14.0'), dict(packages={'example': '2.0'}), dict(results=[]),
                       dict(results=[dict(suite='test_one.py', exit_code=0)] * 2),
                       dict(results=[dict(suite=name, exit_code=1) for name in self.suites])]:
            with self.subTest(change=change):
                self.assertFalse(self.valid(report=self.report | change))
        self.assertFalse(self.valid(run=checks(event='pull_request')))

    def test_missing_ci_artifact_falls_back_to_running_all_checks(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / '_release').mkdir()
            (root / '_release/context.json').write_text(json.dumps({'checks_run': '42', 'source_commit': SHA}))
            with patch.object(C, 'ROOT', root), patch.object(C.sys, 'platform', 'win32'), \
                 patch.object(C, 'api', return_value=checks()), \
                 patch.object(C.subprocess, 'run', side_effect=subprocess.CalledProcessError(1, 'gh')):
                self.assertEqual(C.reuse_ci([], self.packages, SHA), ([], ''))

    def test_failed_test_launcher_cannot_reuse_an_old_pass(self):
        with tempfile.TemporaryDirectory() as temporary, patch.object(C, 'ROOT', Path(temporary)):
            folder = Path(temporary) / 'reports/backend-suites/test_one'
            folder.mkdir(parents=True)
            receipt = folder / 'results.json'
            receipt.write_text(json.dumps({'results': [{'suite': 'test_one.py', 'exit_code': 0}]}))
            with patch.object(C.subprocess, 'run', return_value=SimpleNamespace(returncode=1, stdout='', stderr='failed')):
                with self.assertRaisesRegex(RuntimeError, 'no report'):
                    C.run_suite(Path('test_one.py'))
            self.assertFalse(receipt.exists())


class BrowserCoverage(unittest.TestCase):
    def mode(self, changed):
        return S.browser_mode(changed, lambda _: '', lambda _: '')

    def test_known_ui_surfaces_have_focused_coverage(self):
        self.assertEqual(self.mode(['gui/viewport.css', 'gui/roster.js', 'CHANGELOG.md']), 'ui')
        names = {name for name, _ in B.suites_for({'browser_mode': 'ui', 'changed': ['gui/viewport.css', 'gui/roster.js']})}
        self.assertTrue({'updates', 'workspace', 'viewport', 'assembly', 'identity', 'find', 'library'} <= names)

    def test_shared_ui_regions_cannot_hide_changes_elsewhere(self):
        samples = {
            'gui/app.js': 'state\nfunction buildGrid(\nold\nfunction _editedDots(\nother',
            'gui/viewport.js': 'state\nfunction pickMaterial(\nold\nasync function openConnectedEditor(\nother\nfunction buildMaterialInspector(\nui\nfunction colorField(\nend',
        }
        for name, before in samples.items():
            self.assertEqual(S.browser_mode([name], lambda _: before, lambda _: before.replace('old', 'new')), 'ui')
            self.assertEqual(S.browser_mode([name], lambda _: before, lambda _: before.replace('state', 'changed')), 'full')
        self.assertEqual(self.mode(['gui/app.js']), 'full')

    def test_mixed_unknown_and_shared_infrastructure_changes_keep_full_coverage(self):
        for other in ['atelier/handlers/material.py', 'gui/style.css', 'gui/vendor/new.js', 'native/tool.cs',
                      'scripts/build.py', '.github/workflows/release.yml', 'requirements.txt', 'tests/browser_startup.py']:
            self.assertEqual(self.mode(['gui/roster.css', other]), 'full', other)
        self.assertEqual(self.mode([]), 'full')

    def test_updates_and_full_runs_still_cover_workspace_saving(self):
        for mode in ('updates', 'full'):
            names = {name for name, _ in B.suites_for({'browser_mode': mode, 'changed': []})}
            self.assertIn('workspace', names)
            self.assertIn('full' if mode == 'full' else 'updates', names)

    def test_old_receipt_cannot_mask_missing_or_failed_browser_results(self):
        with tempfile.TemporaryDirectory() as temporary, patch.object(B, 'ROOT', Path(temporary)):
            folder = Path(temporary) / 'reports/browser/workspace'
            folder.mkdir(parents=True)
            receipt = folder / 'results.json'
            receipt.write_text(json.dumps({'checks': ['old success'], 'page_errors': []}))
            with patch.object(B.subprocess, 'run', return_value=SimpleNamespace(returncode=0, stdout='', stderr='')):
                with self.assertRaises(FileNotFoundError):
                    B.run_suite(('workspace', ['--workspace-only']))
            self.assertFalse(receipt.exists())
            with patch.object(B.subprocess, 'run', return_value=SimpleNamespace(returncode=1, stdout='', stderr='failed')):
                with self.assertRaisesRegex(RuntimeError, 'Browser gate failed'):
                    B.run_suite(('workspace', ['--workspace-only']))


if __name__ == '__main__':
    unittest.main()

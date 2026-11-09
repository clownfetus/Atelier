"""Release notes move out of Unreleased and survive concurrent edits on main."""
import base64
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import prepare_release as P
import sync_release_changelog as S

INTRO = '# Changelog\n\nFull release numbers identify Atelier updates.'
OLD = '## 1.1.7 — 2026-11-02\n\n- Previous fix.'


def document(pending='', releases=OLD):
    return f'{INTRO}\n\n## Unreleased\n\n{pending}\n\n{releases}\n'


class Preparation(unittest.TestCase):
    def test_authored_notes_move_to_numbered_release_and_keep_intro_separate(self):
        notes = '### Fixes\n\n- Read the newest game patch.\n  Keep texture references consistent.\n\n- Another fix.'
        result = P.prepare_changelog(document(notes), '1.1.8', '2026-11-05', ['Commit title'])
        intro, sections = P.split_changelog(result)
        self.assertEqual(intro, INTRO)
        self.assertEqual(sections['Unreleased'], '## Unreleased')
        self.assertEqual(sections['1.1.8'], '## 1.1.8 — 2026-11-05\n\n' + notes)
        self.assertEqual(sections['1.1.7'], OLD)
        self.assertNotIn('Commit title', result)

    def test_commit_titles_fill_empty_pending_notes(self):
        result = P.prepare_changelog(document(), '1.1.8', '2026-11-05', ['Fix preview', 'Fix export'])
        self.assertIn('## 1.1.8 — 2026-11-05\n\n- Fix preview\n- Fix export', result)
        self.assertNotIn(INTRO, P.split_changelog(result)[1]['1.1.8'])

    def test_existing_authored_release_keeps_notes_for_next_version(self):
        original = document('- Next version.', '## 1.1.8\n\n- Ready to ship.\n\n' + OLD)
        result = P.prepare_changelog(original, '1.1.8', '2026-11-05', ['Fallback'])
        self.assertEqual(P.split_changelog(result)[1], P.split_changelog(original)[1])
        self.assertEqual(P.prepare_changelog(result, '1.1.8', '2026-11-06', []), result)

    def test_history_merges_numerically_and_preserves_current_corrections(self):
        current = document('- Pending.', '## 1.1.7\n\n- Corrected notes.')
        historical = document('- Stale pending.', '## 1.1.10\n\n- Newer.\n\n' + OLD)
        result = P.merge_changelog_history(current, historical)
        self.assertIn('- Pending.', result)
        self.assertIn('- Corrected notes.', result)
        self.assertNotIn('Stale pending', result)
        self.assertNotIn('Previous fix', result)
        self.assertLess(result.index('## 1.1.10'), result.index('## 1.1.7'))

    def test_history_skips_repeated_unreleased_in_published_changelog(self):
        # The published 1.1.8 changelog repeats Unreleased after every version.
        current = document('- Pending.', '## 1.1.7\n\n- Corrected notes.')
        historical = ('# Changelog\n\n## 1.1.8 — 2026-11-05\n\n- Shipped.\n\n'
                      '## Unreleased\n\n- Stale one.\n\n## 1.1.7 — 2026-11-02\n\n- Old notes.\n\n'
                      '## Unreleased\n\n- Stale two.\n')
        result = P.merge_changelog_history(current, historical)
        self.assertEqual(result.count('## Unreleased'), 1)
        self.assertIn('- Pending.', result)
        self.assertIn('- Shipped.', result)
        self.assertIn('- Corrected notes.', result)
        self.assertNotIn('Stale', result)
        with self.assertRaises(ValueError):
            P.split_changelog(historical)


class Synchronization(unittest.TestCase):
    def setUp(self):
        self.source = document('- Ship this fix.\n  With detail.\n\n- Ship another fix.')
        self.released = P.prepare_changelog(self.source, '1.1.8', '2026-11-05', [])

    def test_main_receives_published_notes_and_clears_shipped_pending_notes(self):
        result = S.synchronize(self.source, self.source, self.released)
        self.assertEqual(result, self.released)
        self.assertEqual(S.synchronize(result, self.source, self.released), result)

    def test_new_and_revised_pending_notes_and_history_corrections_survive(self):
        current = document('- New fix.\n\n- Ship this fix.\n  With revised detail.\n\n- Ship another fix.',
                           '## 1.1.7\n\n- Corrected previous notes.')
        result = S.synchronize(current, self.source, self.released)
        sections = P.split_changelog(result)[1]
        self.assertIn('- New fix.', sections['Unreleased'])
        self.assertIn('With revised detail.', sections['Unreleased'])
        self.assertNotIn('Ship another fix', sections['Unreleased'])
        self.assertIn('With detail.', sections['1.1.8'])
        self.assertIn('Corrected previous notes', sections['1.1.7'])
        self.assertEqual(S.synchronize(result, self.source, self.released), result)

    def test_pending_notes_beside_an_authored_release_are_not_consumed(self):
        source = document('- For the next release.', '## 1.1.8\n\n- Ship this.\n\n' + OLD)
        released = P.prepare_changelog(source, '1.1.8', '2026-11-05', [])
        self.assertIn('- For the next release.', S.synchronize(source, source, released))

    def test_concurrent_notes_keep_their_heading_and_empty_headings_disappear(self):
        source = document('### Added\n\n- Shipped feature.\n\n### Fixed\n\n- Shipped fix.')
        released = P.prepare_changelog(source, '1.1.8', '2026-11-05', [])
        current = source.replace('- Shipped fix.', '- New fix.\n\n- Shipped fix.')
        result = S.synchronize(current, source, released)
        self.assertEqual(P.split_changelog(result)[1]['Unreleased'], '## Unreleased\n\n### Fixed\n\n- New fix.')

    def test_sync_does_not_remove_newer_releases(self):
        current = document('- Later fix.', '## 1.1.9\n\n- Already recorded.\n\n' + OLD)
        result = S.synchronize(current, self.source, self.released)
        self.assertIn('## 1.1.9', result)
        self.assertLess(result.index('## 1.1.9'), result.index('## 1.1.8'))

    def file(self, text, sha='original'):
        return {'sha': sha, 'content': base64.b64encode(text.encode()).decode()}

    def release(self, **changes):
        return dict(draft=False, prerelease=False, published_at='2026-11-05T22:40:06Z') | changes

    def test_contents_update_targets_main_and_uses_current_blob_sha(self):
        with patch.object(S, 'api', side_effect=[self.release(), self.file(self.source), {}]) as api:
            S.sync_main('1.1.8', self.source, self.released)
        path, payload = api.call_args.args
        self.assertEqual(path, 'contents/CHANGELOG.md')
        self.assertEqual(payload['branch'], 'main')
        self.assertEqual(payload['sha'], 'original')
        self.assertIn('[skip ci]', payload['message'])
        self.assertEqual(base64.b64decode(payload['content']).decode(), self.released)

    def test_blob_conflict_refetches_main_and_preserves_the_concurrent_note(self):
        conflict = subprocess.CalledProcessError(1, 'gh', stderr='gh: SHA does not match (HTTP 409)')
        newer = self.source.replace('## Unreleased', '## Unreleased\n\n- Merged during publication.')
        with patch.object(S, 'api', side_effect=[self.release(), self.file(self.source), conflict,
                                               self.file(newer, 'new-blob'), {}]) as api:
            S.sync_main('1.1.8', self.source, self.released)
        payload = api.call_args.args[1]
        self.assertEqual(payload['sha'], 'new-blob')
        pending = P.split_changelog(base64.b64decode(payload['content']).decode())[1]['Unreleased']
        self.assertEqual(pending, '## Unreleased\n\n- Merged during publication.')

    def test_repeated_sync_does_not_create_another_commit(self):
        with patch.object(S, 'api', side_effect=[self.release(), self.file(self.released)]) as api:
            S.sync_main('1.1.8', self.source, self.released)
        self.assertEqual(api.call_count, 2)

    def test_drafts_prereleases_missing_publication_and_missing_notes_cannot_write(self):
        for release in [self.release(draft=True), self.release(prerelease=True), self.release(published_at=None)]:
            with self.subTest(release=release), patch.object(S, 'api', return_value=release) as api:
                with self.assertRaises(ValueError):
                    S.sync_main('1.1.8', self.source, self.released)
                self.assertEqual(api.call_count, 1)
        with patch.object(S, 'api', return_value=self.release()) as api, self.assertRaises(ValueError):
            S.sync_main('1.1.8', self.source, self.source)
        self.assertEqual(api.call_count, 1)

    def test_permission_failure_is_reported_without_retry(self):
        error = subprocess.CalledProcessError(1, 'gh', stderr='gh: Resource not accessible (HTTP 403)')
        with patch.object(S, 'api', side_effect=[self.release(), self.file(self.source), error]) as api:
            with self.assertRaises(subprocess.CalledProcessError):
                S.sync_main('1.1.8', self.source, self.released)
        self.assertEqual(api.call_count, 3)

    def test_continuing_conflicts_fail_after_three_attempts(self):
        error = subprocess.CalledProcessError(1, 'gh', stderr='gh: conflict (HTTP 409)')
        with patch.object(S, 'api', side_effect=[self.release()] + [self.file(self.source), error] * 3) as api:
            with self.assertRaises(subprocess.CalledProcessError):
                S.sync_main('1.1.8', self.source, self.released)
        self.assertEqual(api.call_count, 7)


if __name__ == '__main__':
    unittest.main()

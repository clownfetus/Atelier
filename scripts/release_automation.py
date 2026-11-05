"""Plan serialized patch releases from the latest verified main commit."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from atelier.update_protocol import version

REPOSITORY = 'clownfetus/Atelier'
CHECKS_PATH = '.github/workflows/checks.yml'


def api(path):
    return json.loads(subprocess.check_output(
        ['gh', 'api', f'repos/{REPOSITORY}/{path}'], text=True, encoding='utf-8'))


def trusted_checks(run, commit):
    return (run.get('event') == 'push' and run.get('head_branch') == 'main'
            and run.get('head_sha') == commit and run.get('path') == CHECKS_PATH
            and (run.get('repository') or {}).get('full_name') == REPOSITORY
            and (run.get('head_repository') or {}).get('full_name') == REPOSITORY
            and run.get('status') == 'completed' and run.get('conclusion') == 'success')


def latest_checks(commit):
    # Check the latest attempt, not an earlier green run followed by a failed rerun.
    runs = api(f'actions/workflows/checks.yml/runs?branch=main&event=push&head_sha={commit}&per_page=100')['workflow_runs']
    runs = [run for run in runs if run.get('head_sha') == commit]
    if not runs:
        return None
    run = max(runs, key=lambda row: (row['id'], row.get('run_attempt', 1)))
    return run if trusted_checks(run, commit) else None


def next_patch(previous, tags=()):
    major, minor, patch = version(previous.removeprefix('v'))
    # A deliberately retained draft/tag must never be overwritten by automation.
    occupied = {tag.removeprefix('v') for tag in tags}
    while patch < 99:
        patch += 1
        candidate = f'{major}.{minor}.{patch}'
        if candidate not in occupied:
            return candidate
    raise ValueError('Patch numbers exhausted; choose the next minor release explicitly.')


def event_checks(event):
    trigger = event.get('workflow_run', {})
    return trigger | {'repository': event.get('repository', trigger.get('repository', {}))}


def automatic_plan(event, main_commit, checks, previous, previous_commit, tags=()):
    trigger = event_checks(event)
    if not trusted_checks(trigger, trigger.get('head_sha')):
        return {'release': False, 'reason': 'Only successful main push checks may release.'}
    if not re.fullmatch(r'[0-9a-f]{40}', main_commit) or not trusted_checks(checks or {}, main_commit):
        return {'release': False, 'reason': 'Latest main has not passed Checks yet.'}
    if previous.get('draft') or previous.get('prerelease'):
        raise ValueError('Automatic releases require a stable published baseline.')
    if main_commit == previous_commit:
        return {'release': False, 'reason': 'Latest main is already published.'}
    return {'release': True, 'source_commit': main_commit, 'checks_run': str(checks['id']),
            'version': next_patch(previous['tag_name'], tags), 'reason': 'Release latest verified main.'}


def outputs(values):
    print(json.dumps(values, indent=2))
    if os.environ.get('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'], 'a', encoding='utf-8') as handle:
            for key, value in values.items():
                handle.write(f'{key}={str(value).lower() if isinstance(value, bool) else value}\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--publishable', help='Recheck automatic publication against the current main head')
    args = parser.parse_args()
    if os.environ.get('GITHUB_REPOSITORY', REPOSITORY) != REPOSITORY:
        raise ValueError('Release automation only runs in ' + REPOSITORY)
    automatic = os.environ.get('GITHUB_EVENT_NAME') == 'workflow_run'
    if args.publishable:
        allowed = True
        if automatic:
            current = api('git/ref/heads/main')['object']['sha']
            allowed = current == args.publishable and latest_checks(current) is not None
        outputs({'publishable': allowed})
        return
    if not automatic:
        commit = os.environ['GITHUB_SHA']
        release_version = os.environ['RELEASE_VERSION'].removeprefix('v')
        version(release_version)
        outputs({'release': True, 'source_commit': commit, 'checks_run': '',
                 'version': release_version})
        return
    event = json.loads(Path(os.environ['GITHUB_EVENT_PATH']).read_bytes())
    trigger = event_checks(event)
    if not trusted_checks(trigger, trigger.get('head_sha')):
        outputs({'release': False, 'reason': 'Not a successful main push.'})
        return
    # Resolve main AFTER acquiring the release lock. Even a late, older completion
    # event can release the latest green head instead of displacing its pending run.
    commit = api('git/ref/heads/main')['object']['sha']
    previous = api('releases/latest')
    previous_commit = subprocess.check_output(
        ['git', 'rev-parse', previous['tag_name'] + '^{commit}'], cwd=ROOT, text=True).strip()
    tags = subprocess.check_output(['git', 'tag', '--list'], cwd=ROOT, text=True).splitlines()
    # Draft releases can reserve a version before GitHub creates its git tag.
    tags.extend(release['tag_name'] for release in api('releases?per_page=100'))
    plan = automatic_plan(event, commit, latest_checks(commit), previous, previous_commit, tags)
    if plan['release']:
        # Do not automatically downgrade to an unrelated or force-rewound history.
        subprocess.run(['git', 'fetch', '--no-tags', 'origin', commit], cwd=ROOT, check=True)
        subprocess.run(['git', 'merge-base', '--is-ancestor', previous_commit, commit], cwd=ROOT, check=True)
        changed = subprocess.check_output(['git', 'diff', '--name-only', previous_commit, commit],
                                          cwd=ROOT, text=True).splitlines()
        if not set(changed) - {'CHANGELOG.md'}:
            plan = {'release': False, 'reason': 'Only the published changelog changed.'}
    outputs(plan)


if __name__ == '__main__':
    main()

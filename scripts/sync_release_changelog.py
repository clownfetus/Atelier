"""Record a published release on main without losing notes added during its build."""
import argparse
import base64
from collections import Counter
import json
import os
from pathlib import Path
import re
import subprocess

from prepare_release import REPOSITORY, git, merge_changelog_history, render_changelog, split_changelog
from atelier.update_protocol import version


def pending_blocks(sections):
    body = sections.get('Unreleased', '').partition('\n')[2].strip()
    return [block.strip() for block in re.split(r'\n(?=- |### )', body) if block.strip()]


def synchronize(current, source, released):
    intro, sections = split_changelog(merge_changelog_history(current, released))
    # Remove only unchanged notes that this release consumed. New and revised
    # notes on main survive, as do pending notes alongside an authored release.
    consumed = Counter(pending_blocks(split_changelog(source)[1]))
    consumed.subtract(pending_blocks(split_changelog(released)[1]))
    remaining = []
    heading = None
    heading_kept = False
    for block in pending_blocks(sections):
        if block.startswith('### '):
            heading, heading_kept = block, False
            continue
        if consumed[block] > 0:
            consumed[block] -= 1
        else:
            if heading and not heading_kept:
                remaining.append(heading)
                heading_kept = True
            remaining.append(block)
    sections['Unreleased'] = ('## Unreleased\n\n' + '\n\n'.join(remaining)).strip()
    return render_changelog(intro, sections)


def api(path, payload=None):
    command = ['gh', 'api', f'repos/{REPOSITORY}/{path}']
    if payload is not None:
        command += ['--method', 'PUT', '--input', '-']
    return json.loads(subprocess.check_output(command, text=True, encoding='utf-8',
                      input=json.dumps(payload) if payload is not None else None, stderr=subprocess.PIPE))


def sync_main(release_version, source, released):
    version(release_version)
    release = api('releases/tags/v' + release_version)
    if release['draft'] or release['prerelease'] or not release.get('published_at'):
        raise ValueError('Only a published stable release may update main.')
    if release_version not in split_changelog(released)[1]:
        raise ValueError('Published changelog is missing this release.')
    for attempt in range(3):
        file = api('contents/CHANGELOG.md?ref=main')
        current = base64.b64decode(file['content']).decode('utf-8')
        updated = synchronize(current, source, released)
        if updated == current:
            print('Main already records Atelier ' + release_version)
            return
        try:
            api('contents/CHANGELOG.md', {
                'branch': 'main', 'sha': file['sha'],
                'message': f'docs: record Atelier {release_version} release in changelog [skip ci]',
                'content': base64.b64encode(updated.encode('utf-8')).decode('ascii'),
            })
            print('Recorded Atelier ' + release_version + ' in main changelog')
            return
        except subprocess.CalledProcessError as error:
            # A concurrent changelog edit invalidates the contents API's SHA.
            # Read main again and recompute; never force or replace its history.
            if attempt == 2 or '(HTTP 409)' not in (error.stderr or ''):
                raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--version', required=True)
    parser.add_argument('--source', required=True)
    parser.add_argument('--changelog', type=Path, required=True)
    args = parser.parse_args()
    if os.environ.get('GITHUB_REPOSITORY', REPOSITORY) != REPOSITORY:
        raise ValueError('Release changelog updates only run in ' + REPOSITORY)
    if not re.fullmatch(r'[0-9a-f]{40}', args.source):
        raise ValueError('Expected the exact release source commit.')
    sync_main(args.version, git('show', args.source + ':CHANGELOG.md'),
              args.changelog.read_text(encoding='utf-8'))


if __name__ == '__main__':
    main()

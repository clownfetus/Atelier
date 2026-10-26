"""Resolve release inputs once, using the published release as the upgrade baseline."""
import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from atelier.update_protocol import atomic_json, digest, version

REPOSITORY = 'clownfetus/Atelier'


def git(*args):
    return subprocess.check_output(['git', *args], cwd=ROOT, text=True, encoding='utf-8').strip()


def asset_digest(asset):
    value = asset.get('digest', '')
    if not isinstance(value, str) or not value.startswith('sha256:') or len(value) != 71:
        raise ValueError('Published asset has no SHA-256 digest: ' + asset['name'])
    return value[7:]


def merge_changelog_history(current, historical):
    pattern = r'(?m)(?=^## [0-9]{1,2}\.[0-9]{1,2}\.[0-9]{1,2}(?:\s|$))'
    current_parts = re.split(pattern, current)
    releases = {}
    for document in (historical, current):
        for section in re.split(pattern, document)[1:]:
            number = re.match(r'## ([0-9]+\.[0-9]+\.[0-9]+)', section)[1]
            releases[number] = section.strip()
    return current_parts[0].rstrip() + '\n\n' + '\n\n'.join(releases[number] for number in sorted(releases, key=version, reverse=True)) + '\n'


def release_summaries(log, previous_tree):
    entries = []
    for record in log.split('\x1e'):
        if not record.strip():
            continue
        tree, subject, body = record.strip('\r\n').split('\x1f', 2)
        if tree == previous_tree:
            continue
        title = body.strip().splitlines()[0] if subject.startswith('Merge pull request ') and body.strip() else subject
        if title.startswith('Merge '):
            continue
        title = re.sub(r'\s*\[verify release\]', '', title).strip()
        if title and title not in entries:
            entries.append(title)
    return entries


def needs_full_checks(changed):
    prefixes = ('native/', 'toolchain/', 'packaging/', '.github/', 'scripts/', 'atelier/update',
                'atelier/storage', 'atelier/jobs', 'atelier/config', 'atelier/hostos',
                'atelier/handlers/', 'atelier/vendor/')
    names = {'Atelier.iss', 'Atelier.spec', 'window.py', 'main.py', 'io_lib.py', 'update_keys.json'}
    return not changed or any(name in names or name.startswith(prefixes) or name.startswith('requirements') for name in changed)


def can_reuse_native(changed):
    recipes = {'scripts/toolchain.py', 'scripts/build_shader_tool.py'}
    return bool(changed) and not any(name.startswith(('native/', 'toolchain/', 'requirements')) or name in recipes for name in changed)


def native_cache_key(config):
    paths = list((ROOT / 'native').rglob('*')) + list((ROOT / 'toolchain').rglob('*'))
    paths += [ROOT / 'scripts' / name for name in ('toolchain.py', 'release_config.json', 'build_shader_tool.py')]
    paths.append(ROOT / '.github/workflows/release.yml')
    # bin/obj/target output is not a source input and is absent on clean runners.
    rows = [(path.relative_to(ROOT).as_posix(), digest(path)) for path in sorted(paths)
            if path.is_file() and not {'bin', 'obj', 'target', '__pycache__'}.intersection(path.relative_to(ROOT).parts)]
    return hashlib.sha256(json.dumps([config, rows], sort_keys=True).encode()).hexdigest()


def prepare(release_version, previous):
    version(release_version)
    if previous.get('draft') or previous.get('prerelease'):
        raise ValueError('Upgrade baseline must be a stable published release.')
    previous_version = previous['tag_name'].removeprefix('v')
    if version(release_version) <= version(previous_version):
        raise ValueError('Release version must be higher than published ' + previous_version)
    config = json.loads((ROOT / 'scripts/release_config.json').read_bytes())
    assets = {item['name']: item for item in previous['assets']}
    installer = assets['AtelierSetup.exe']
    image = assets[f'Atelier-{previous_version}-x86_64.AppImage']
    commit = git('rev-parse', 'HEAD')
    try:
        changed = git('diff', '--name-only', previous['tag_name'], commit).splitlines()
    except subprocess.CalledProcessError:
        changed = []
    inputs = config | {'version': release_version,
                       'previous_windows_url': installer['browser_download_url'],
                       'previous_windows_sha256': asset_digest(installer),
                       'previous_windows_bytes': installer['size'],
                       'previous_linux_url': image['browser_download_url'],
                       'previous_linux_sha256': asset_digest(image)}
    context = {'version': release_version, 'tag': 'v' + release_version, 'source_commit': commit,
               'previous_tag': previous['tag_name'], 'previous_version': previous_version,
               'full_checks': needs_full_checks(changed), 'changed': changed,
               'reuse_native': can_reuse_native(changed),
               'native_key': native_cache_key(config), 'previous_assets': assets}
    return context, inputs


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--version', default='')
    args = parser.parse_args()
    if os.environ.get('GITHUB_REPOSITORY', REPOSITORY) != REPOSITORY:
        raise ValueError('Official releases must run in ' + REPOSITORY)
    release_version = args.version.removeprefix('v') or (ROOT / 'version').read_text().strip()
    previous = json.loads(subprocess.check_output(['gh', 'api', f'repos/{REPOSITORY}/releases/latest'], text=True))
    context, inputs = prepare(release_version, previous)
    from release_check_scope import select
    context['browser_mode'] = 'full' if os.environ.get('ATELIER_FULL_BROWSER') == 'true' else select(context)
    directory = ROOT / '_release'
    atomic_json(directory / 'context.json', context)
    atomic_json(directory / 'inputs.json', inputs)
    (ROOT / 'version').write_text(release_version + '\n', encoding='utf-8')
    changelog = (ROOT / 'CHANGELOG.md').read_text(encoding='utf-8')
    previous_changelog = context['previous_assets'].get('CHANGELOG.md')
    if previous_changelog:
        with urllib.request.urlopen(previous_changelog['browser_download_url'], timeout=30) as response:
            raw = response.read(4 * 1024 * 1024 + 1)
        if len(raw) > 4 * 1024 * 1024 or hashlib.sha256(raw).hexdigest() != asset_digest(previous_changelog):
            raise ValueError('Published changelog failed its release digest.')
        changelog = merge_changelog_history(changelog, raw.decode('utf-8'))
    heading = '## ' + release_version
    if not any(line == heading or line.startswith(heading + ' ') for line in changelog.splitlines()):
        log = subprocess.check_output(['git', 'log', '--first-parent', '--format=%T%x1f%s%x1f%b%x1e',
                                       f"{context['previous_tag']}..HEAD"], cwd=ROOT, text=True, encoding='utf-8')
        entries = release_summaries(log, git('rev-parse', context['previous_tag'] + '^{tree}'))
        today = datetime.datetime.now(datetime.timezone.utc).date().isoformat()
        section = f'## {release_version} — {today}\n\n' + '\n'.join('- ' + entry for entry in entries) + '\n\n'
        first, separator, remainder = changelog.partition('\n')
        changelog = first + '\n\n' + section + remainder.lstrip() if first.startswith('# ') else section + changelog
        (ROOT / 'CHANGELOG.md').write_text(changelog, encoding='utf-8')
    else:
        (ROOT / 'CHANGELOG.md').write_text(changelog, encoding='utf-8')
    # The prepared metadata is identical in both build jobs and the source ZIP.
    (directory / 'version').write_text(release_version + '\n', encoding='utf-8')
    (directory / 'CHANGELOG.md').write_text(changelog, encoding='utf-8')
    name = f"Atelier-Windows-{context['previous_version']}-inventory.json"
    previous_inventory = context['previous_assets'].get(name)
    if previous_inventory:
        with urllib.request.urlopen(previous_inventory['browser_download_url'], timeout=30) as response:
            raw = response.read(4 * 1024 * 1024 + 1)
        if len(raw) > 4 * 1024 * 1024 or hashlib.sha256(raw).hexdigest() != asset_digest(previous_inventory):
            raise ValueError('Previous installation inventory failed its release digest.')
        (directory / 'previous-inventory.json').write_bytes(raw)
    if os.environ.get('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'], 'a', encoding='utf-8') as output:
            for key in ('version', 'tag', 'native_key'):
                output.write(f'{key}={context[key]}\n')
            output.write(f"full_checks={str(context['full_checks']).lower()}\n")
    print('Prepared ' + context['tag'] + ' against ' + context['previous_tag'])
    print('Browser coverage: ' + context['browser_mode'])


if __name__ == '__main__':
    main()

"""Offline release notes and the last version acknowledged by this installation."""
from pathlib import Path
import re

from atelier import config


def _version(value):
    if not isinstance(value, str) or not re.fullmatch(r'\d+(?:\.\d+){1,3}', value):
        return None
    parts = tuple(int(part) for part in value.split('.'))
    return parts + (0,) * (4 - len(parts))


def current_version(version_file):
    try:
        value = Path(version_file).read_text(encoding='utf-8').strip()
    except OSError:
        return None
    return value if _version(value) is not None else None


def _blocks(lines):
    blocks = []
    for line in lines:
        text = line.strip()
        if not text:
            if blocks and blocks[-1]['type'] == 'paragraph':
                blocks.append({'type': 'break'})
            continue
        if text.startswith('### '):
            blocks.append({'type': 'heading', 'text': text.lstrip('#').strip()})
        elif text.startswith('- '):
            if not blocks or blocks[-1]['type'] != 'list':
                blocks.append({'type': 'list', 'items': []})
            blocks[-1]['items'].append(text[2:])
        elif line[:1].isspace() and blocks and blocks[-1]['type'] == 'list':
            blocks[-1]['items'][-1] += ' ' + text
        elif blocks and blocks[-1]['type'] == 'paragraph':
            blocks[-1]['text'] += ' ' + text
        else:
            blocks.append({'type': 'paragraph', 'text': text})
    return [block for block in blocks if block['type'] != 'break']


def release_notes(version_file, current, previous=None):
    """Include skipped releases, but never Unreleased or a version newer than this build."""
    try:
        source = Path(version_file).with_name('CHANGELOG.md').read_text(encoding='utf-8')
    except OSError:
        source = ''
    releases = []
    for section in re.split(r'(?m)^##\s+', source)[1:]:
        heading, _, body = section.partition('\n')
        match = re.fullmatch(r'(\d+(?:\.\d+){1,3})(?:\s+[—–-]\s+(.+))?', heading.strip())
        if not match:
            continue
        version, date = match.groups()
        number = _version(version)
        if number > _version(current):
            continue
        if previous is None and number != _version(current):
            continue
        if previous is not None and number <= _version(previous):
            continue
        releases.append({'version': version, 'date': date or '', 'blocks': _blocks(body.splitlines())})
    releases.sort(key=lambda release: _version(release['version']), reverse=True)
    if not releases or releases[0]['version'] != current:
        releases.insert(0, {'version': current, 'date': '', 'blocks': [{
            'type': 'paragraph',
            'text': 'Release notes for this version are available in the full changelog.',
        }]})
    return releases


def status(version_file):
    current = current_version(version_file)
    if current is None:
        return {'ok': True, 'version': 'development', 'available': False, 'releases': []}
    saved = config._load_config()
    previous = saved.get('changelog_version')
    previous_number = _version(previous)
    # A fresh installation establishes its baseline during setup. Existing installations
    # predate this key, so they receive the current release's notes once.
    if previous_number is None and not saved.get('paks'):
        config._save_config(changelog_version=current)
        previous = current
        previous_number = _version(current)
    available = previous_number is None or previous_number < _version(current)
    return {'ok': True, 'version': current, 'previous_version': previous,
            'available': available,
            'releases': release_notes(version_file, current,
                                      previous if available and previous_number is not None else None)}


def acknowledge(version_file, version):
    current = current_version(version_file)
    if current is None or version != current:
        raise ValueError('The changelog version does not match this installation.')
    # Opening an older build must not make a newer, already acknowledged build pop up again.
    previous = _version(config._load_config().get('changelog_version'))
    if previous is None or previous < _version(current):
        config._save_config(changelog_version=current)
    return {'ok': True}

"""Release/update format shared by the publisher and the standalone updater.

Only distribution-owned files can be replaced. Projects, configuration, cached
game data and the mutable character-name seed are deliberately outside it.
"""
import base64
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import zipfile

SCHEMA = 1
INVENTORY = 'Atelier.update.json'
FEED = 'Atelier-Update.json'
SEED = 'Tools/MarvelRivalsCharacterIDs.md'
PLATFORMS = {'windows-x64', 'linux-x64'}


class InstallerRequired(ValueError):
    """A structural/runtime change needs the installer's complete owned-folder reset."""


def version(value):
    if not isinstance(value, str) or not re.fullmatch(r'[0-9]{1,2}\.[0-9]{1,2}\.[0-9]{1,2}', value):
        raise ValueError('Expected a version such as 1.2.3.')
    return tuple(map(int, value.split('.')))


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode('utf-8')


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.tmp')
    with temporary.open('wb') as stream:
        stream.write(canonical(value))
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def relative_name(name):
    if not isinstance(name, str) or not name or '\\' in name or ':' in name or '\x00' in name:
        raise ValueError('Unsafe update filename.')
    parts = name.split('/')
    if any(part in {'', '.', '..'} or part.endswith((' ', '.')) or
           re.match(r'(?i)^(con|prn|aux|nul|com[0-9]|lpt[0-9])(?:\.|$)', part) or
           any(ord(char) < 32 or char in '<>"|?*' for char in part) for part in parts):
        raise ValueError('Unsafe update filename: ' + name)
    if PurePosixPath(name).is_absolute():
        raise ValueError('Absolute update filename.')
    return name


def managed(name):
    relative_name(name)
    if name in {'Atelier.exe', 'LICENSE', INVENTORY}:
        return True
    if name.startswith(('_internal/', 'licenses/')):
        return True
    if name in {'Tools/UAssetTool.exe', 'Tools/UAssetGUI.exe', 'Tools/texconv.exe',
                'Tools/retoc/retoc-rivals-cli.exe', 'Tools/tools.json', 'Tools/THIRD_PARTY_TOOLS.md'}:
        return True
    return name.startswith(('Tools/AtelierNative/', 'Tools/AtelierMesh/', 'Tools/AtelierAnimation/',
                            'Tools/AtelierImport/', 'Tools/shaders/licenses/')) or name in {
        'Tools/shaders/retoc-rivals-cli.exe', 'Tools/shaders/build-inputs.json',
        'Tools/shaders/oo2core_9_win64.dll', 'Tools/shaders/dxc.exe',
        'Tools/shaders/dxcompiler.dll', 'Tools/shaders/dxil.dll',
        'Tools/Galacta/GAL_ConfigTemplate.uasset', 'Tools/Galacta/GAL_ConfigTemplate.uexp',
    }


def safe_path(root, name):
    relative_name(name)
    root = Path(root).absolute()
    path = root / name
    # resolve() alone would follow a junction into a user's unrelated folder.
    for part in [root, *list(path.relative_to(root).parents)[:-1]]:
        candidate = part if part == root else root / part
        if candidate.is_symlink() or candidate.is_junction():
            raise ValueError('Update paths cannot contain links: ' + name)
    if path.is_symlink() or path.is_junction():
        raise ValueError('Update paths cannot contain links: ' + name)
    if not path.resolve().is_relative_to(root.resolve()):
        raise ValueError('Update path escapes the installation.')
    return path


def validate_inventory(data):
    if data.get('schema') != SCHEMA or data.get('platform') != 'windows-x64':
        raise ValueError('Unsupported installation inventory.')
    version(data.get('version'))
    seen = set()
    files = data.get('files')
    if not isinstance(files, list) or not files:
        raise ValueError('Empty installation inventory.')
    for row in files:
        name = row.get('path')
        if not managed(name) or name == INVENTORY or name.casefold() in seen:
            raise ValueError('Invalid or duplicate managed file: ' + str(name))
        seen.add(name.casefold())
        if type(row.get('bytes')) is not int or row['bytes'] < 0 or not re.fullmatch(r'[a-f0-9]{64}', str(row.get('sha256'))):
            raise ValueError('Invalid update file digest or size.')
    if 'atelier.exe' not in seen or '_internal/version' not in seen:
        raise ValueError('Installation inventory has no application or version.')
    # File/directory collisions must be rejected before any filesystem changes.
    for name in seen:
        if any(parent.as_posix() in seen for parent in PurePosixPath(name).parents if parent.as_posix() != '.'):
            raise ValueError('Update file/directory collision.')
    return data


def make_inventory(root, release_version, commit):
    version(release_version)
    root = Path(root)
    files = []
    for path in sorted(root.rglob('*')):
        if not path.is_file():
            continue
        name = path.relative_to(root).as_posix()
        if name in {INVENTORY, SEED}:
            continue
        if not managed(name):
            raise ValueError('Unmanaged data in release: ' + name)
        safe_path(root, name)
        files.append({'path': name, 'bytes': path.stat().st_size, 'sha256': digest(path)})
    application_data = ('_internal/gui/', '_internal/atelier/blender/', '_internal/atelier/models/',
                        '_internal/extensions/', '_internal/updates/')
    application_files = {'_internal/version', '_internal/CHANGELOG.md', '_internal/update_keys.json'}
    runtime = [row for row in files if row['path'].startswith('_internal/') and
               row['path'] not in application_files and not row['path'].startswith(application_data)]
    data = {'schema': SCHEMA, 'platform': 'windows-x64', 'version': release_version,
            'source_commit': commit, 'files': files,
            'runtime_id': hashlib.sha256(canonical(runtime)).hexdigest()}
    validate_inventory(data)
    atomic_json(root / INVENTORY, data)
    return data


def load_inventory(root):
    return validate_inventory(json.loads((Path(root) / INVENTORY).read_bytes()))


def verify_files(root, rows):
    for row in rows:
        path = safe_path(root, row['path'])
        if not path.is_file() or path.stat().st_size != row['bytes'] or digest(path) != row['sha256']:
            raise ValueError('Installed file differs from its release: ' + row['path'])


def sign_feed(data, private_key, key_id):
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    key = Ed25519PrivateKey.from_private_bytes(base64.b64decode(private_key, validate=True))
    return {'signed': data, 'key_id': key_id,
            'signature': base64.b64encode(key.sign(canonical(data))).decode('ascii')}


def verify_feed(envelope, keys):
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    key = keys.get(envelope.get('key_id'))
    if not key:
        raise ValueError('Unknown release signing key.')
    try:
        Ed25519PublicKey.from_public_bytes(base64.b64decode(key, validate=True)).verify(
            base64.b64decode(envelope['signature'], validate=True), canonical(envelope['signed']))
    except Exception as error:
        raise ValueError('Release signature could not be verified.') from error
    data = envelope['signed']
    if data.get('schema') != SCHEMA:
        raise ValueError('Unsupported update feed.')
    version(data.get('version'))
    return data


def file_record(path):
    path = Path(path)
    return {'name': path.name, 'bytes': path.stat().st_size, 'sha256': digest(path)}


def make_patch(root, previous, output):
    target = load_inventory(root)
    validate_inventory(previous)
    if version(target['version']) <= version(previous['version']):
        raise ValueError('Patch must increase the version.')
    if target.get('runtime_id') != previous.get('runtime_id'):
        raise InstallerRequired('A changed Python runtime requires the installer.')
    old = {row['path']: row for row in previous['files']}
    new = {row['path']: row for row in target['files']}
    changed = [name for name, row in new.items() if row != old.get(name)]
    removed = sorted(set(old) - set(new))
    # A case-only rename on Windows cannot be safely treated as two files.
    if any(name.casefold() == other.casefold() and name != other for name in new for other in removed):
        raise InstallerRequired('Case-only rename requires the installer.')
    metadata = {'schema': SCHEMA, 'base': previous, 'target': target,
                'changed': changed, 'removed': removed}
    with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('patch.json', canonical(metadata))
        for name in changed:
            archive.write(safe_path(root, name), 'payload/' + name)
    return file_record(output) | {'from_version': previous['version']}


def _members(archive):
    result = {}
    seen = set()
    for entry in archive.infolist():
        name = entry.filename.rstrip('/')
        relative_name(name)
        if name.casefold() in seen or stat.S_ISLNK(entry.external_attr >> 16) or entry.flag_bits & 1:
            raise ValueError('Duplicate, encrypted or linked update archive entry.')
        seen.add(name.casefold())
        if not entry.is_dir():
            result[name] = entry
    return result


def stage_windows(installation, package, staging, kind):
    """Validate the complete archive and base before extracting any replacements."""
    installation, staging = Path(installation), Path(staging)
    previous = load_inventory(installation)
    old = {row['path']: row for row in previous['files']}
    with zipfile.ZipFile(package) as archive:
        members = _members(archive)
        if kind == 'patch':
            if 'patch.json' not in members or members['patch.json'].file_size > 4 * 1024 * 1024:
                raise ValueError('Patch metadata is missing or too large.')
            patch = json.loads(archive.read('patch.json'))
            if patch.get('schema') != SCHEMA or patch['base'] != previous:
                raise ValueError('Patch does not match this installed version.')
            target = validate_inventory(patch['target'])
            new = {row['path']: row for row in target['files']}
            changed = [name for name, row in new.items() if row != old.get(name)]
            removed = sorted(set(old) - set(new))
            if patch.get('changed') != changed or patch.get('removed') != removed:
                raise ValueError('Patch operations differ from its inventories.')
            if set(members) != {'patch.json', *('payload/' + name for name in changed)}:
                raise ValueError('Unexpected file in patch archive.')
            verify_files(installation, previous['files'])
            prefix = 'payload/'
        elif kind == 'full':
            inventory_name = 'Atelier/' + INVENTORY
            if inventory_name not in members or members[inventory_name].file_size > 4 * 1024 * 1024:
                raise ValueError('Full update has no installation inventory.')
            target = validate_inventory(json.loads(archive.read(inventory_name)))
            new = {row['path']: row for row in target['files']}
            expected = {'Atelier/' + name for name in new} | {inventory_name}
            if set(members) - expected - {'Atelier/' + SEED} or expected - set(members):
                raise ValueError('Full update archive membership differs from its inventory.')
            changed = list(new)
            removed = sorted(set(old) - set(new))
            prefix = 'Atelier/'
        else:
            raise ValueError('Unknown package kind.')
        if version(target['version']) <= version(previous['version']):
            raise ValueError('Refusing an update that does not increase the version.')
        if target.get('runtime_id') != previous.get('runtime_id'):
            raise InstallerRequired('A changed Python runtime requires the installer.')
        old_names = {name.casefold(): name for name in old}
        for name in new:
            if name.casefold() in old_names and old_names[name.casefold()] != name:
                raise InstallerRequired('Case-only rename requires the installer.')
            destination = safe_path(installation, name)
            if destination.is_dir() or any(parent.is_file() for parent in destination.parents if parent.is_relative_to(installation)):
                raise InstallerRequired('A changed file/directory layout requires the installer.')
        # Preflight every destination, including unchanged paths and removals.
        for name in set(old) | set(new) | {INVENTORY}:
            safe_path(installation, name)
        for name in changed:
            row = new[name]
            member = members[prefix + name]
            if member.file_size != row['bytes']:
                raise ValueError('Archive file size differs from inventory: ' + name)
        staging.mkdir(parents=True, exist_ok=False)
        for name in changed:
            path = safe_path(staging, name)
            path.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(members[prefix + name]) as source, path.open('xb') as destination:
                shutil.copyfileobj(source, destination)
            if digest(path) != new[name]['sha256']:
                raise ValueError('Corrupted update file: ' + name)
        atomic_json(staging / INVENTORY, target)
    return {'target': target, 'replace': [*changed, INVENTORY], 'remove': removed}


def _replace_file(source, target):
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + '.atelier-update-tmp')
    if temporary.exists() or temporary.is_symlink():
        raise ValueError('An update temporary file already exists: ' + str(temporary))
    try:
        shutil.copy2(source, temporary)
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


def apply_windows(installation, staging, plan, transaction):
    """Journal backups before mutation; a helper can restore them after a crash."""
    installation, staging, transaction = Path(installation), Path(staging), Path(transaction)
    transaction.mkdir(parents=True, exist_ok=True)
    journal_path = transaction / 'journal.json'
    if journal_path.exists():
        raise ValueError('An update transaction already exists.')
    operations = []
    names = [*plan['remove'], *plan['replace']]
    if len({name.casefold() for name in names}) != len(names):
        raise ValueError('Update operations overlap.')
    for name in names:
        if not managed(name):
            raise ValueError('Unmanaged update destination.')
        path = safe_path(installation, name)
        existed = path.is_file()
        if path.exists() and not existed:
            raise ValueError('An update file is a directory: ' + name)
        if existed:
            backup = safe_path(transaction / 'backup', name)
            backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, backup)
        operations.append({'path': name, 'existed': existed})
    journal = {'installation': str(installation.absolute()), 'operations': operations, 'state': 'applying'}
    atomic_json(journal_path, journal)
    try:
        for name in plan['remove']:
            safe_path(installation, name).unlink(missing_ok=True)
        for name in plan['replace']:
            _replace_file(safe_path(staging, name), safe_path(installation, name))
        verify_files(installation, plan['target']['files'])
        journal['state'] = 'awaiting_health'
        atomic_json(journal_path, journal)
    except BaseException:
        rollback_windows(transaction)
        raise


def rollback_windows(transaction):
    transaction = Path(transaction)
    journal_path = transaction / 'journal.json'
    journal = json.loads(journal_path.read_bytes())
    if journal['state'] in {'rolled_back', 'committed'}:
        return
    installation = Path(journal['installation'])
    for operation in reversed(journal['operations']):
        name = operation['path']
        if not managed(name):
            raise ValueError('Unmanaged rollback destination.')
        path = safe_path(installation, name)
        if operation['existed']:
            _replace_file(safe_path(transaction / 'backup', name), path)
        else:
            path.unlink(missing_ok=True)
    journal['state'] = 'rolled_back'
    atomic_json(journal_path, journal)

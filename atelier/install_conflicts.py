"""Compare the package paths in a built export and the enabled mods on disk.

The single-mod case-insensitive intersection and path normalisation are adapted from
Repak-X by X-zant and contributors (GPL-3.0), revision 1bb9c9398305673bb8426f32ca191394257a9ed5.
https://github.com/X-zant/Repak-X/blob/1bb9c9398305673bb8426f32ca191394257a9ed5/repak-x/src/main_tauri.rs#L8970
https://github.com/X-zant/Repak-X/blob/1bb9c9398305673bb8426f32ca191394257a9ed5/repak-x/src/asset_explorer.rs#L70
"""
import os
from pathlib import Path
import re

from atelier import config  # sets MR_TOOLS before the container readers are imported
import io_lib
from atelier import jobs, legacy_pak


_CONTAINERS = ('.pak', '.utoc', '.ucas')
_DISABLED = ('.bak_repak', '.pak_disabled', '.pak.disabled', '.utoc_disabled', '.utoc.disabled')
_METADATA = {'chunknames', 'patched_files'}
_HEADS = ('.uasset', '.umap')
_COMPANIONS = ('.uexp', '.m.ubulk', '.ubulk', '.uptnl', '.upayload')


def _path_key(raw):
    parts = []
    for part in raw.replace('\\', '/').casefold().split('/'):
        if part == '..':
            if parts:
                parts.pop()
        elif part and part != '.':
            parts.append(part)
    if not parts or _METADATA.intersection(parts):
        return None

    # Disk paths and virtual mount paths can name the same package. Engine and plugin
    # mounts have independent namespaces, even when their content paths are identical.
    if parts[0] != 'game' and 'content' in parts:
        content = parts.index('content')
        mount = parts[:content]
        root = mount[-1] if mount and ('plugins' in mount[:-1] or mount[-1] == 'engine') else 'game'
        parts = [root] + parts[content + 1:]
    path = '/'.join(parts)
    for suffix in _HEADS + _COMPANIONS:
        if path.endswith(suffix):
            return 'package', path[:-len(suffix)]
    return 'file', path


def _combine_paths(entries, paths):
    for raw in entries:
        key = _path_key(raw)
        if key is None:
            continue
        previous = paths.get(key)
        if previous is None or (raw.lower().endswith(_HEADS) and not previous.lower().endswith(_HEADS)):
            paths[key] = raw


def _groups(paths):
    groups = {}
    for path in paths:
        lower = path.name.casefold()
        for suffix in _CONTAINERS + _DISABLED:
            if lower.endswith(suffix):
                members = groups.setdefault((path.parent, lower[:-len(suffix)]), {})
                members.setdefault(suffix, path)
                break
    return groups


def _read_bundle(members, root, unreadable, *, source, replaced=()):
    paths = {}

    def bad(path, reason):
        unreadable.append({'file': path.relative_to(root).as_posix(), 'source': source, 'reason': reason})

    pak, toc, ucas = (members.get(ext) for ext in _CONTAINERS)
    if toc and toc not in replaced:
        try:
            header = io_lib.parse_toc(toc)
            entries = io_lib.parse_dir_index(header)
            if not entries and header.entry_count:
                bad(toc, 'The IoStore table has no readable file names.')
            else:
                _combine_paths((name for name, _index in entries), paths)
            if not ucas:
                bad(toc, 'The companion .ucas file is missing.')
        except Exception as error:
            bad(toc, str(error) or 'Atelier could not read the IoStore table.')
    elif ucas and not toc and ucas not in replaced:
        bad(ucas, 'The companion .utoc file is missing.')

    if pak and pak not in replaced:
        try:
            index = legacy_pak.Pak(pak)
            if index.count and not index.names:
                bad(pak, 'The PAK index has no readable file names.')
            else:
                mount = index.mount.rstrip('/\\')
                _combine_paths((mount + '/' + name for name in index.names), paths)
        except Exception as error:
            bad(pak, str(error) or 'Atelier could not read the PAK index.')
    return paths


def scan(artifacts, destination):
    """Return overlaps and unreadable entries without unpacking or modifying any container."""
    sources = [Path(path) for path in artifacts]
    mods = Path(destination)
    unreadable, conflicts = [], []
    target_paths = {}
    for (folder, _stem), bundle in _groups(sources).items():
        target_paths.update(_read_bundle(bundle, folder, unreadable, source='export'))

    def inaccessible(error):
        path = Path(error.filename or mods)
        if path == mods and isinstance(error, FileNotFoundError):
            return  # The configured folder can be created by the first install.
        unreadable.append({'file': path.relative_to(mods).as_posix(), 'source': 'installed',
                           'reason': str(error)})

    candidates = []
    for folder, dirs, names in os.walk(mods, onerror=inaccessible):
        jobs.checkpoint()
        dirs[:] = sorted((name for name in dirs if not name.startswith('.atelier-publish-')), key=str.casefold)
        candidates.extend(Path(folder) / name for name in sorted(names, key=str.casefold))
    groups = _groups(candidates)
    replacements = {mods / path.name for path in sources}
    for (folder, stem), bundle in groups.items():
        jobs.checkpoint()
        if '.pak' not in bundle and any(suffix in bundle for suffix in _DISABLED):
            continue
        partition = re.fullmatch(r'(.+)_s[1-9]\d*', stem)
        if set(bundle) == {'.ucas'} and partition and (folder, partition[1]) in groups:
            continue  # These payload partitions share the main TOC's directory index.
        primary = next((bundle[ext] for ext in _CONTAINERS if ext in bundle), None)
        if not primary:
            continue
        other_paths = _read_bundle(bundle, mods, unreadable, source='installed', replaced=replacements)
        overlap = sorted(target_paths.keys() & other_paths.keys())
        if overlap:
            conflicts.append({'mod': primary.relative_to(mods).as_posix(),
                              'paths': [target_paths[key] for key in overlap]})
    conflicts.sort(key=lambda item: item['mod'].casefold())
    unreadable.sort(key=lambda item: (item['source'], item['file'].casefold(), item['reason']))
    return {'conflicts': conflicts, 'unreadable': unreadable}

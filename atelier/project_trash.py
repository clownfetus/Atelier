"""Recoverable removal of project edits. Work copies remain disposable.

Each request owns a manifest and mirrors both project layouts beneath files/.
Manifests are written before moving anything, so interrupted deletes can be
recovered on project open rather than silently losing half an edit. Earlier
files that a newer edit has replaced stay in a 'kept' entry, which is never
rolled back again or aged out.
"""
import json
import os
from pathlib import Path
import re
import shutil
import time
import uuid

from atelier import asset_cache, config, project_meta
from atelier.storage import atomic_json

DIRECTORY = '.atelier-trash'
EDIT_EXTS = ('.png', '.json', '.blend', '.blend.mat.json', '.blend1', '.mesh.json', '.mesh.glb', '.asset.json')
MAX_AGE = 7 * 24 * 3600
MAX_ENTRIES = 20
_ENTRY_ID = re.compile(r'[0-9a-f]{32}')
_RECOVERABLE = ('ready', 'kept')


class Interrupted(RuntimeError):
    """A delete stopped part-way and newer edits kept some earlier files in the trash."""


def _inside(root, relative):
    path = Path(root, *config.validate_game_rel(relative)).resolve()
    if os.path.commonpath([str(Path(root).resolve()), str(path)]) != str(Path(root).resolve()):
        raise ValueError('Trash path must stay inside its project.')
    return path


def _trash_root(root):
    base = Path(root, DIRECTORY)
    if base.is_symlink() or base.is_junction():
        raise ValueError('The project trash folder cannot be a link.')
    return _inside(root, DIRECTORY)


def _entry(root, entry):
    if not isinstance(entry, str) or not _ENTRY_ID.fullmatch(entry):
        raise ValueError('Invalid trash entry.')
    folder = _trash_root(root) / entry
    if folder.is_symlink() or folder.is_junction():
        raise ValueError('A project trash entry cannot be a link.')
    return folder


def _entries(root):
    base = _trash_root(root)
    if not base.is_dir():
        return
    for folder in base.iterdir():
        if not _ENTRY_ID.fullmatch(folder.name) or folder.is_symlink() or folder.is_junction():
            continue
        manifest = _read_manifest(folder)
        if manifest is not None:
            yield folder, manifest


def _read_manifest(folder):
    try:
        manifest = json.loads((folder / 'manifest.json').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None
    if isinstance(manifest, dict) and manifest.get('version') == 1 and isinstance(manifest.get('assets'), list):
        return manifest
    return None


def _files(root, game_rel):
    from atelier.added_assets import source_files
    try:
        originals = source_files(game_rel, root)
    except (ValueError, OSError):
        originals = []  # A damaged source record must still be removable/recoverable as an edit.
    return sorted({Path(base + ext) for base in
                   (config.project_base(game_rel, root), config.project_base_legacy(game_rel, root))
                   for ext in EDIT_EXTS if Path(base + ext).is_file()} | set(originals))


def remove(root, game_rels):
    root = str(Path(root).resolve())
    purge(root)
    metadata = project_meta.load(root)
    assets = []
    for gr in dict.fromkeys(game_rels):
        config.validate_game_rel(gr)
        files = _files(root, gr)
        if not files:
            continue
        assets.append({'game_rel': gr, 'files': [p.relative_to(root).as_posix() for p in files],
                       'project_meta': {'opts': metadata['asset_opts'].get(gr, {}),
                                        'recolour': metadata['recolours'].get(gr),
                                        'deselected': gr in metadata['deselected']},
                       'cache': dict(asset_cache.get(gr) or {})})
    if not assets:
        return {'ok': True, 'deleted': 0, 'entry': None}
    entry = uuid.uuid4().hex
    folder = _entry(root, entry)
    manifest = {'version': 1, 'deleted_at': time.time(), 'state': 'moving', 'assets': assets}
    atomic_json(folder / 'manifest.json', manifest)
    moved = []
    try:
        for asset in assets:
            for relative in asset['files']:
                source, target = _inside(root, relative), _inside(folder / 'files', relative)
                target.parent.mkdir(parents=True, exist_ok=True)
                os.replace(source, target)
                moved.append((source, target))
        for asset in assets:
            project_meta.forget_asset(root, asset['game_rel'], selection=True)
        manifest['state'] = 'ready'
        atomic_json(folder / 'manifest.json', manifest)
    except BaseException:
        for source, target in reversed(moved):
            if target.exists() and not source.exists():
                source.parent.mkdir(parents=True, exist_ok=True)
                os.replace(target, source)
        for asset in assets:
            project_meta.restore_asset(root, asset['game_rel'], asset['project_meta'])
        if any(target.exists() for _, target in moved):
            raise Interrupted(f'Delete interrupted by newer edits. The earlier files remain in {folder}.')
        shutil.rmtree(folder)
        raise
    for asset in assets:
        cached = asset['cache'].get('cache_path')
        if cached:
            for ext in ('.uasset', '.uexp', '.ubulk'):
                try:
                    os.remove(cached + ext)
                except OSError:
                    pass
        asset_cache.remove(asset['game_rel'])
    purge(root)
    return {'ok': True, 'deleted': len(assets), 'entry': entry}


def restore(root, entry):
    folder = _entry(root, entry)
    manifest = _read_manifest(folder)
    if manifest is None or manifest.get('state') not in _RECOVERABLE:
        raise ValueError('This trash entry is no longer available.')
    kept = manifest['state'] == 'kept'
    restored, conflicts, missing = [], [], []
    for asset in list(manifest['assets']):
        gr = asset['game_rel']
        config.validate_game_rel(gr)
        pairs = [(_inside(folder / 'files', rel), _inside(root, rel)) for rel in asset['files']]
        # Interrupted deletes may have saved only part of an asset.
        if kept:
            pairs = [(source, target) for source, target in pairs if source.is_file()]
        # Check every layout and sidecar so a fresh import stays untouched.
        if _files(root, gr) or any(target.exists() for _, target in pairs):
            conflicts.append(gr)
            continue
        if not pairs or any(not source.is_file() for source, _ in pairs):
            missing.append(gr)
            continue
        moved = []
        try:
            for source, target in pairs:
                target.parent.mkdir(parents=True, exist_ok=True)
                os.replace(source, target)
                moved.append((source, target))
            project_meta.restore_asset(root, gr, asset['project_meta'])
            cached = asset.get('cache') or {}
            if cached:
                asset_cache.record(gr, cached['cache_path'], cached.get('pak', ''), cached.get('pfx', ''))
            manifest['assets'].remove(asset)
            atomic_json(folder / 'manifest.json', manifest)
        except BaseException:
            for source, target in reversed(moved):
                if target.exists() and not source.exists():
                    os.replace(target, source)
            project_meta.forget_asset(root, gr, selection=True)
            asset_cache.remove(gr)
            raise
        restored.append(gr)
    if not manifest['assets']:
        shutil.rmtree(folder)
    errors = []
    if conflicts:
        errors.append('New edits already exist. Those assets remain in the project trash.')
    if missing:
        errors.append('Some edit files are missing from the project trash.')
    return {'ok': not errors, 'game_rels': restored, 'conflicts': conflicts + missing,
            'error': ' '.join(errors) or None}


def purge(root, now=None):
    now = time.time() if now is None else now
    entries = []
    for folder, manifest in _entries(root):
        try:
            deleted = float(manifest['deleted_at'])
        except (ValueError, KeyError, TypeError):
            continue  # Unknown data is never silently discarded.
        if manifest.get('state') == 'moving':
            # Roll back an interrupted delete; existing edits always win.
            kept = []
            for asset in manifest['assets']:
                pairs = [(_inside(folder / 'files', rel), _inside(root, rel)) for rel in asset['files']]
                pending = [(source, target) for source, target in pairs if source.is_file()]
                targets = {target for _, target in pairs}
                live = _files(root, asset['game_rel'])
                if any(target.exists() for _, target in pending) or any(p.resolve() not in targets for p in live):
                    # Keep the older files together and leave the newer asset and its metadata alone.
                    if pending:
                        kept.append(asset)
                    continue
                for source, target in pending:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    os.replace(source, target)
                project_meta.restore_asset(root, asset['game_rel'], asset['project_meta'])
                cached = asset.get('cache') or {}
                if cached:
                    asset_cache.record(asset['game_rel'], cached['cache_path'], cached.get('pak', ''), cached.get('pfx', ''))
            if not kept and not any(p.is_file() for p in (folder / 'files').rglob('*')):
                shutil.rmtree(folder)
                continue
            # Keep conflicting files rather than deleting the only saved copy, but never roll them
            # back again: every replay would reset the newer edit's options and selection.
            manifest.update(state='kept', assets=kept)
            atomic_json(folder / 'manifest.json', manifest)
            continue
        if manifest.get('state') == 'ready':
            entries.append((deleted, folder))
    entries.sort(key=lambda item: item[0], reverse=True)
    for index, (deleted, folder) in enumerate(entries):
        if index >= MAX_ENTRIES or now - deleted > MAX_AGE:
            shutil.rmtree(folder)


def list_entries(root):
    """Return recoverable trash batches for a project, newest first."""
    root = str(Path(root).resolve())
    purge(root)
    entries = []
    for folder, manifest in _entries(root):
        try:
            deleted_at = float(manifest['deleted_at'])
        except (ValueError, KeyError, TypeError):
            continue
        state = manifest.get('state')
        if state not in _RECOVERABLE:
            continue
        assets = []
        for asset in manifest['assets']:
            gr = asset['game_rel']
            files = asset['files']
            if state == 'kept':
                files = [rel for rel in files if _inside(folder / 'files', rel).is_file()]
            if not files:
                continue
            assets.append({
                'game_rel': gr,
                'name': gr.rsplit('/', 1)[-1],
                'files': len(files),
            })
        if not assets:
            continue
        entries.append({
            'entry': folder.name,
            'deleted_at': deleted_at,
            'expires_at': None if state == 'kept' else deleted_at + MAX_AGE,
            'state': state,
            'count': len(assets),
            'assets': assets,
        })
    entries.sort(key=lambda item: item['deleted_at'], reverse=True)
    return entries


def discard(root, entry=None):
    """Permanently delete one trash entry, or all ready entries when entry is None."""
    root = str(Path(root).resolve())
    purge(root)
    if entry is not None:
        folder = _entry(root, entry)
        manifest = _read_manifest(folder)
        if manifest is None or manifest.get('state') not in _RECOVERABLE:
            return {'ok': False, 'removed': 0, 'error': 'This trash entry is no longer available.'}
        shutil.rmtree(folder)
        return {'ok': True, 'removed': 1}
    removed = 0
    for folder, manifest in _entries(root):
        if manifest.get('state') != 'ready':
            continue
        shutil.rmtree(folder)
        removed += 1
    return {'ok': True, 'removed': removed}

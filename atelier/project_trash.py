"""Recoverable removal of project edits. Work copies remain disposable.

Each request owns a manifest and mirrors both project layouts beneath files/.
Manifests are written before moving anything, so interrupted deletes can be
recovered on project open rather than silently losing half an edit.
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
EDIT_EXTS = ('.png', '.json', '.blend', '.blend.mat.json', '.blend1', '.mesh.json', '.mesh.glb')
MAX_AGE = 7 * 24 * 3600
MAX_ENTRIES = 20


def _inside(root, relative):
    path = Path(root, *config.validate_game_rel(relative)).resolve()
    if os.path.commonpath([str(Path(root).resolve()), str(path)]) != str(Path(root).resolve()):
        raise ValueError('Trash path must stay inside its project.')
    return path


def _entry(root, entry):
    if not isinstance(entry, str) or not re.fullmatch(r'[0-9a-f]{32}', entry):
        raise ValueError('Invalid trash entry.')
    return _inside(root, DIRECTORY + '/' + entry)


def _files(root, game_rel):
    return sorted({Path(base + ext) for base in
                   (config.project_base(game_rel, root), config.project_base_legacy(game_rel, root))
                   for ext in EDIT_EXTS if Path(base + ext).is_file()})


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
            raise RuntimeError(f'Delete interrupted by newer edits. The earlier files remain in {folder}.')
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
    try:
        manifest = json.loads((folder / 'manifest.json').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        raise ValueError('This trash entry is no longer available.')
    restored, conflicts = [], []
    for asset in list(manifest['assets']):
        gr = asset['game_rel']
        config.validate_game_rel(gr)
        pairs = [(_inside(folder / 'files', rel), _inside(root, rel)) for rel in asset['files']]
        # Check every layout and sidecar: a fresh import must never be overwritten.
        if _files(root, gr) or any(target.exists() for _, target in pairs):
            conflicts.append(gr)
            continue
        if any(not source.is_file() for source, _ in pairs):
            conflicts.append(gr)
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
    return {'ok': not conflicts, 'game_rels': restored, 'conflicts': conflicts,
            'error': 'New edits already exist; those assets remain in the project trash.' if conflicts else None}


def purge(root, now=None):
    now = time.time() if now is None else now
    base = _inside(root, DIRECTORY)
    if not base.is_dir():
        return
    entries = []
    for folder in base.iterdir():
        if not re.fullmatch(r'[0-9a-f]{32}', folder.name):
            continue
        folder = _entry(root, folder.name)
        try:
            manifest = json.loads((folder / 'manifest.json').read_text(encoding='utf-8'))
            deleted = float(manifest['deleted_at'])
        except (OSError, ValueError, KeyError, TypeError):
            continue  # Unknown data is never silently discarded.
        if manifest.get('state') == 'moving':
            # Roll back an interrupted delete; existing edits always win.
            for asset in manifest['assets']:
                for relative in asset['files']:
                    source, target = _inside(folder / 'files', relative), _inside(root, relative)
                    if source.is_file() and not target.exists():
                        target.parent.mkdir(parents=True, exist_ok=True)
                        os.replace(source, target)
                project_meta.restore_asset(root, asset['game_rel'], asset['project_meta'])
                cached = asset.get('cache') or {}
                if cached:
                    asset_cache.record(asset['game_rel'], cached['cache_path'], cached.get('pak', ''), cached.get('pfx', ''))
            # Keep any conflicting files rather than deleting the only saved copy.
            if any(p.is_file() for p in (folder / 'files').rglob('*')):
                continue
            shutil.rmtree(folder)
            continue
        if manifest.get('state') == 'ready':
            entries.append((deleted, folder))
    entries.sort(key=lambda item: item[0], reverse=True)
    for index, (deleted, folder) in enumerate(entries):
        if index >= MAX_ENTRIES or now - deleted > MAX_AGE:
            shutil.rmtree(folder)

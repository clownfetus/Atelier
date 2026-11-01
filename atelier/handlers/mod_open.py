"""Open a mod: read a cooked mod into assets you can understand and keep.

The mod's containers (.utoc/.ucas, a legacy .pak, or a .zip of them) are unpacked with retoc and
every package is decoded to JSON with UAssetTool. Each asset is described by what it really is (its
top-level export's class, not its filename prefix), where it lives in the game, whether the game has
it, and which packages it references. Textures and material instances can then be added to the Mod
tray: one that overrides a game asset becomes an ordinary edit of it, and one that is new in the mod
becomes an added asset at the same path. Everything else is read only for now, with its JSON
available to save.

A read is cached per mod file (path, size and modification time, plus the mapping file it was decoded
with), so reopening a mod is instant and adding its assets reuses the decoded files. Only add_to_tray
writes the project, and it runs as a project job like any other import.
"""
import contextvars
from concurrent.futures import ThreadPoolExecutor
import datetime
import hashlib
import json
import os
import re
import shutil
import tempfile
import zipfile

from atelier import config, hostos, jobs
from atelier.storage import atomic_json
from atelier.tools import uat

VERSION = 1
_KEEP = 8                  # cached reads; older ones are removed when another mod is read
_DECODERS = 4              # UAssetTool processes decoding at once
_CONTAINERS = ('.pak', '.ucas', '.utoc')
_COMPANIONS = ('.uasset', '.uexp', '.ubulk', '.uptnl')

CLASS_KINDS = {
    'Texture2D': 'texture', 'TextureCube': 'texture', 'TextureRenderTarget2D': 'texture',
    'MaterialInstanceConstant': 'material', 'Material': 'material', 'MaterialFunction': 'material',
    'SkeletalMesh': 'mesh', 'StaticMesh': 'mesh', 'Skeleton': 'mesh', 'PhysicsAsset': 'mesh',
    'AnimSequence': 'animation', 'AnimMontage': 'animation', 'BlendSpace': 'animation',
    'BlendSpace1D': 'animation', 'AnimBlueprintGeneratedClass': 'animation',
    'AkAudioEvent': 'sound', 'AkAudioBank': 'sound', 'AkMediaAsset': 'sound',
    'SoundWave': 'sound', 'SoundCue': 'sound',
    'NiagaraSystem': 'effect', 'NiagaraEmitter': 'effect', 'ParticleSystem': 'effect',
    'CurveFloat': 'data', 'CurveLinearColor': 'data', 'CurveVector': 'data', 'DataTable': 'data',
    'StringTable': 'data', 'MaterialParameterCollection': 'data',
}
FILE_KINDS = {'.bnk': 'sound', '.wem': 'sound', '.ini': 'config', '.json': 'data', '.locres': 'data'}
_TEXT_FILES = ('.ini', '.json', '.txt')
# Bookkeeping that packers and mod managers leave in a pak's root; not part of the mod's content.
_ARTIFACTS = {'chunknames', 'patched_files'}
WHERE_LABELS = {'mod': 'in this mod', 'game': 'in the game', 'missing': 'not found in the game'}


# ── cache ────────────────────────────────────────────────────────────────────────────────────────

def mod_key(path):
    """A read's identity: the file, its size and time, and the mapping file it is decoded with."""
    st = os.stat(path)
    seed = '\n'.join((str(VERSION), os.path.normcase(os.path.realpath(path)), str(st.st_size),
                      str(st.st_mtime_ns), str(config.USMAP or '')))
    return hashlib.sha256(seed.encode('utf-8')).hexdigest()[:24]


def _long(path):
    """Windows' verbatim form, so deep game paths inside the cache never hit the 260-character
    limit: retoc otherwise writes only the files whose paths happen to fit, and says nothing."""
    path = os.path.abspath(path)
    return '\\\\?\\' + path if hostos.IS_WINDOWS and not path.startswith('\\\\') else path


def _root():
    return _long(os.path.join(config._CACHE, 'mod-open'))


def _work(key):
    if not isinstance(key, str) or not re.fullmatch(r'[0-9a-f]{24}', key):
        raise ValueError('Open the mod again.')
    return os.path.join(_root(), key)


def load(key):
    """The saved read for key, or ValueError when it is gone (a cleared cache, a newer read)."""
    path = os.path.join(_work(key), 'manifest.json')
    try:
        with open(path, encoding='utf-8') as stream:
            manifest = json.load(stream)
    except (OSError, ValueError):
        raise ValueError('Open the mod again; Atelier no longer has this read.') from None
    if manifest.get('version') != VERSION or manifest.get('key') != key:
        raise ValueError('Open the mod again; Atelier no longer has this read.')
    return manifest


def _prune(keep):
    root = _root()
    try:
        entries = [os.path.join(root, name) for name in os.listdir(root) if name != keep]
    except OSError:
        return
    entries = sorted((p for p in entries if os.path.isdir(p)), key=os.path.getmtime, reverse=True)
    for path in entries[_KEEP - 1:]:
        shutil.rmtree(path, ignore_errors=True)


# ── reading ──────────────────────────────────────────────────────────────────────────────────────

def _copy_containers(source, src):
    """Copy the mod's containers into src. A zip's members are copied by name, never by its paths."""
    found = []
    if source.lower().endswith('.zip'):
        with zipfile.ZipFile(source) as archive:
            folders = {}
            for info in archive.infolist():
                name = info.filename.replace('\\', '/')
                base = name.rsplit('/', 1)[-1]
                if info.is_dir() or not base.lower().endswith(_CONTAINERS):
                    continue
                # One folder per zip folder, so two mods in one zip keep their own trios.
                folder = os.path.join(src, str(folders.setdefault(name.rsplit('/', 1)[0] if '/' in name else '', len(folders))))
                os.makedirs(folder, exist_ok=True)
                target = os.path.join(folder, base)
                with archive.open(info) as data, open(target, 'wb') as out:
                    shutil.copyfileobj(data, out, 1024 * 1024)
                found.append(target)
    else:
        stem = source.rsplit('.', 1)[0]
        for ext in _CONTAINERS:
            if os.path.isfile(stem + ext):
                target = os.path.join(src, os.path.basename(stem) + ext)
                shutil.copyfile(stem + ext, target)
                found.append(target)
    return found


def _walk(folder):
    return [os.path.join(d, name) for d, _dirs, names in os.walk(folder) for name in names]


def _retoc(tool, args):
    result = hostos.run_exe([tool, '-a', '0x' + config.get_aes_key()] + args, capture_output=True, timeout=900)
    text = b'\n'.join(x for x in (result.stdout, result.stderr) if x).decode('utf-8', 'replace')
    failed = sum(int(n) for n in re.findall(r'\((\d+) failed\)', text))
    return result.returncode, failed, text.strip()[-400:]


def _unpack(container, out):
    """(files, problem). IoStore goes through Atelier's hardened retoc. A legacy pak is listed
    first and extracted only when every name stays inside out; whatever it writes must match."""
    os.makedirs(out, exist_ok=True)
    if container.lower().endswith('.utoc'):
        from atelier.tools import container_retoc
        code, failed, detail = _retoc(container_retoc(), ['unpack', container, '--game-paks-dir', config.PAKS, '-o', out])
        files = _walk(out)
        if code:
            return files, 'retoc could not unpack it: ' + (detail.splitlines()[-1] if detail else 'no details')
        if failed:
            return files, '%d files could not be unpacked.' % failed
        return files, None
    from atelier import legacy_pak, tools
    try:
        names, problem = legacy_pak.check(container)
    except legacy_pak.PakError as exc:
        return [], str(exc)
    if problem or not names:
        return [], problem
    tool = hostos.native_tool(tools.RETOC) or (tools.RETOC if os.path.isfile(tools.RETOC) else None)
    if not tool:
        return [], 'The pak reader is missing. Repair the container tool in Settings → Tools.'
    code, failed, detail = _retoc(tool, ['unpack', container, '-o', out])
    files = _walk(out)
    expected = {'/'.join(legacy_pak.safe_parts(n)).lower() for n in names}
    written = {os.path.relpath(p, out).replace('\\', '/').lower() for p in files}
    if written - expected:
        for path in files:
            os.remove(path)
        return [], 'The pak wrote files its index does not list, so Atelier removed them.'
    if code or len(written) < len(expected):
        return files, '%d of %d files could not be unpacked.' % (len(expected) - len(written), len(expected))
    return files, None


def package_path(raw):
    """Unpacked path (from its mount) to its Unreal package path, the path FModel and the JSON use."""
    raw = raw.replace('\\', '/')
    stem = re.sub(r'\.[^./]+$', '', raw)
    low = stem.lower()
    if low.startswith('marvel/content/'):
        return '/Game/' + stem[len('marvel/content/'):]
    plugin = re.match(r'(?i)marvel/plugins/(?:.+/)?([^/]+)/content/(.*)$', stem)
    if plugin:
        return '/' + plugin.group(1) + '/' + plugin.group(2)
    if low.startswith('engine/content/'):
        return '/Engine/' + stem[len('engine/content/'):]
    return '/' + stem


def _virtual(raw):
    from atelier.index import _virtual_path
    vp, _prefix = _virtual_path(raw)
    return vp


def _game_rel_of(path):
    """Unreal package path to the index's virtual path (no extension), or None outside /Game/."""
    if path.startswith('/Game/'):
        vp = _virtual('Marvel/Content/' + path[len('/Game/'):] + '.uasset')
    elif path.startswith('/Engine/'):
        vp = _virtual('Engine/Content/' + path[len('/Engine/'):] + '.uasset')
    else:
        return None
    return vp[:-len('.uasset')] if vp and vp.lower().endswith('.uasset') else None


def describe_package(doc, name):
    """(class, references, parent) from a package's UAssetTool JSON."""
    imports = doc.get('Imports') or []
    exports = doc.get('Exports') or []

    def imported(index):
        return imports[-index - 1] if isinstance(index, int) and index < 0 and -index <= len(imports) else None

    def package_of(index):
        for _ in range(64):
            entry = imported(index)
            if entry is None:
                return None
            if not entry.get('OuterIndex'):
                return entry.get('ObjectName')
            index = entry['OuterIndex']
        return None

    tops = [e for e in exports if not e.get('OuterIndex')]
    main = next((e for e in tops if e.get('ObjectName') == name), tops[0] if tops else None)
    cls = None
    if main:
        index = main.get('ClassIndex')
        entry = imported(index)
        if entry:
            cls = entry.get('ObjectName')
        elif isinstance(index, int) and 0 < index <= len(exports):
            cls = exports[index - 1].get('ObjectName')
    references = []
    for entry in imports:
        path = entry.get('ObjectName') or ''
        if (entry.get('ClassName') == 'Package' and not entry.get('OuterIndex') and path.startswith('/')
                and not path.startswith('/Script/') and path not in references):
            references.append(path)
    parent = None
    for prop in (main or {}).get('Data') or []:
        if isinstance(prop, dict) and prop.get('Name') == 'Parent' and isinstance(prop.get('Value'), int):
            parent = package_of(prop['Value'])
    return cls, references, parent


def _editability(kind, cls, game_rel, in_game):
    """(editable, how, reason). how is 'edit' (overrides a game asset) or 'add' (new at its path)."""
    if kind == 'texture' and cls != 'Texture2D':
        return False, None, 'Only 2D textures can be added. Cubemaps and render targets stay read only.'
    if kind == 'material' and cls != 'MaterialInstanceConstant':
        return False, None, 'Only material instances can be added. Base materials and functions stay read only.'
    if kind not in ('texture', 'material'):
        return False, None, None
    if not game_rel:
        return False, None, 'This asset is outside the game content Atelier edits.'
    if in_game:
        return True, 'edit', None
    from atelier import added_assets
    folder, name = game_rel.rsplit('/', 1) if '/' in game_rel else ('', game_rel)
    try:
        added_assets.asset_path(kind, folder, name)
    except ValueError as exc:
        return False, None, 'New in this mod, at a path Atelier cannot add assets to: ' + str(exc)
    return True, 'add', None


def read_mod(source, unlock=None):
    """Read one mod file. Returns {ok, manifest} or {ok: False, error, locked?}."""
    from atelier.handlers import modlock
    from atelier.inflight import key_lock
    if not source or not os.path.isfile(source):
        return {'ok': False, 'error': 'Choose a mod file first.'}
    if not source.lower().endswith(_CONTAINERS + ('.zip',)):
        return {'ok': False, 'error': 'Choose a .pak, .utoc, .ucas or .zip mod file.'}
    if modlock.is_locked(source) and not modlock.unlock(source, unlock):
        return {'ok': False, 'locked': True,
                'error': 'This mod is password-protected. Enter its password to open it.'}
    key = mod_key(source)
    work = _work(key)
    with key_lock('mod-open', key):
        try:
            return {'ok': True, 'manifest': load(key)}
        except ValueError:
            pass
        shutil.rmtree(work, ignore_errors=True)
        os.makedirs(work)
        _prune(key)
        manifest = _read_into(source, key, work)
        atomic_json(os.path.join(work, 'manifest.json'), manifest)
        return {'ok': True, 'manifest': manifest}


def _read_into(source, key, work):
    jobs.progress('Unpacking the mod…')
    src = os.path.join(work, 'src')
    os.makedirs(src)
    containers = _copy_containers(source, src)
    stems = {c.rsplit('.', 1)[0].lower() for c in containers if c.lower().endswith('.utoc')}
    targets = [c for c in containers if c.lower().endswith('.utoc') or
               (c.lower().endswith('.pak') and c.rsplit('.', 1)[0].lower() not in stems)]
    # An IoStore mod's .pak is usually a stub, but unpack it too: it can carry loose files.
    targets += [c for c in containers if c.lower().endswith('.pak') and c not in targets]
    report, files = [], {}
    for n, container in enumerate(targets):
        jobs.checkpoint()
        out = os.path.join(work, 'unpacked', str(n))
        found, problem = _unpack(container, out)
        stub = container.lower().endswith('.pak') and container.rsplit('.', 1)[0].lower() in stems
        found = [p for p in found if os.path.relpath(p, out).replace('\\', '/').lower() not in _ARTIFACTS]
        entry = {'name': os.path.basename(container), 'files': len(found)}
        if problem and not (stub and not found):
            entry['problem'] = problem
        elif not found and not stub:
            entry['problem'] = 'This container lists no files. Its author may have protected it.'
        report.append(entry)
        for path in found:
            raw = os.path.relpath(path, out).replace('\\', '/')
            files[raw.lower()] = (raw, path)          # a later container wins, as in the game
    if not containers:
        raise ValueError('There is no .pak, .ucas or .utoc in this file.')

    packages, loose = {}, []
    for low, (raw, path) in files.items():
        stem, ext = os.path.splitext(low)
        if ext in _COMPANIONS:
            packages.setdefault(stem, {})[ext] = (raw, path)
        else:
            loose.append((raw, path))

    from atelier.index import index_lookup
    lookup = index_lookup()
    mod_paths = {package_path(parts['.uasset'][0]).lower() for parts in packages.values() if '.uasset' in parts}
    assets, decode = [], []
    for stem in sorted(packages, key=lambda s: s.rsplit('/', 1)[-1]):
        parts = packages[stem]
        if '.uasset' not in parts:
            continue
        raw, path = parts['.uasset']
        vp = _virtual(raw)
        game_rel = vp[:-len('.uasset')] if vp and vp.lower().endswith('.uasset') else None
        asset = {'id': 'a%d' % len(assets), 'name': os.path.basename(raw)[:-len('.uasset')],
                 'path': package_path(raw), 'game_rel': game_rel,
                 'in_game': bool(vp and vp.lower() in lookup),
                 'files': [os.path.relpath(p, work).replace('\\', '/') for _r, p in parts.values()],
                 'size': sum(os.path.getsize(p) for _r, p in parts.values())}
        assets.append(asset)
        decode.append((asset, path))
    for raw, path in sorted(loose):
        ext = os.path.splitext(raw)[1].lower()
        vp = _virtual(raw)
        assets.append({'id': 'a%d' % len(assets), 'name': os.path.basename(raw), 'path': '/' + raw,
                       'game_rel': None, 'in_game': bool(vp and vp.lower() in lookup), 'kind': FILE_KINDS.get(ext, 'other'),
                       'class': ext.lstrip('.').upper() + ' file' if ext else 'File', 'references': [],
                       'parent': None, 'editable': False, 'how': None, 'reason': None, 'json': False,
                       'text': ext in _TEXT_FILES and os.path.getsize(path) <= 4 * 1024 * 1024,
                       'files': [os.path.relpath(path, work).replace('\\', '/')], 'size': os.path.getsize(path)})

    os.makedirs(os.path.join(work, 'json'))
    done = 0
    jobs.progress('Reading assets…', 0, len(decode))

    def task(item):
        asset, path = item
        return asset, _decode(path, asset['name'], os.path.join(work, 'decode', asset['id']))

    with ThreadPoolExecutor(max_workers=_DECODERS) as pool:
        # Each task runs in a copy of this context, so cancelling the job stops its tools too.
        futures = [pool.submit(contextvars.copy_context().run, task, item) for item in decode]
        for future in futures:
            asset, (doc, error) = future.result()
            done += 1
            jobs.checkpoint()
            jobs.progress('Reading ' + asset['name'], done, len(decode))
            _describe(asset, doc, error, work, mod_paths, lookup)
    shutil.rmtree(os.path.join(work, 'decode'), ignore_errors=True)
    return {'version': VERSION, 'key': key, 'name': re.sub(r'\.[^.]+$', '', os.path.basename(source)),
            'source': source.replace('\\', '/'), 'read_at': datetime.datetime.now().isoformat(timespec='seconds'),
            'containers': report, 'assets': assets}


def _decode(uasset, name, out):
    os.makedirs(out, exist_ok=True)
    result = uat(['to_json', os.path.abspath(uasset), config.USMAP, os.path.abspath(out)])
    path = os.path.join(out, name + '.json')
    if not os.path.isfile(path):
        return None, (result.stderr or result.stdout or 'UAssetTool produced no JSON').strip()[-300:]
    try:
        with open(path, encoding='utf-8-sig') as stream:
            return json.load(stream), None
    except ValueError as exc:
        return None, 'UAssetTool wrote JSON Atelier could not read: ' + str(exc)


def _describe(asset, doc, error, work, mod_paths, lookup):
    if doc is None:
        asset.update(kind='other', **{'class': None}, references=[], parent=None, editable=False,
                     how=None, json=False, reason='Atelier could not read this package: ' + error)
        return
    atomic_json(os.path.join(work, 'json', asset['id'] + '.json'), doc)
    cls, references, parent = describe_package(doc, asset['name'])
    if isinstance(doc.get('FolderName'), str) and doc['FolderName'].startswith('/'):
        asset['path'] = doc['FolderName']
    kind = CLASS_KINDS.get(cls, 'other')
    refs = []
    for path in references:
        game_rel = _game_rel_of(path)
        where = ('mod' if path.lower() in mod_paths else
                 'game' if game_rel and (game_rel + '.uasset').lower() in lookup else
                 'missing' if game_rel else None)
        refs.append({'path': path, 'where': where})
    editable, how, reason = _editability(kind, cls, asset['game_rel'], asset['in_game'])
    asset.update(kind=kind, **{'class': cls}, references=refs, parent=parent, editable=editable,
                 how=how, reason=reason, json=True)


def present(manifest):
    """The read as the page shows it: no cache paths, plus whether each asset is in the Mod tray."""
    def in_tray(game_rel):
        if not game_rel:
            return False
        try:
            bases = (config.project_base(game_rel), config.project_base_legacy(game_rel))
        except ValueError:
            return False
        return any(os.path.exists(base + ext) for base in bases for ext in ('.png', '.json', '.asset.json'))
    assets = [{**{k: v for k, v in asset.items() if k != 'files'}, 'in_tray': in_tray(asset['game_rel'])}
              for asset in manifest['assets']]
    return {**{k: v for k, v in manifest.items() if k != 'assets'}, 'assets': assets}


# ── adding to the Mod tray ───────────────────────────────────────────────────────────────────────

def _package_base(work, asset):
    uasset = next(f for f in asset['files'] if f.lower().endswith('.uasset'))
    return os.path.join(work, *uasset.split('/'))[:-len('.uasset')]


def _project_target(game_rel, ext):
    """The project file to write: an existing legacy flat file keeps its place, as _import_base does."""
    new, legacy = config.project_base(game_rel), config.project_base_legacy(game_rel)
    return legacy + ext if os.path.exists(legacy + ext) and not os.path.exists(new + ext) else new + ext


def _decode_png(work, asset, temporary):
    base = _package_base(work, asset)
    png = os.path.join(temporary, asset['name'] + '.png')
    result = uat(['extract_texture', base + '.uasset', png, '--usmap', config.USMAP])
    if not os.path.isfile(png):
        raise ValueError('Atelier could not decode this texture: ' +
                         (result.stderr or result.stdout or 'no image was written').strip()[-300:])
    return png


def _add_texture(work, asset):
    with tempfile.TemporaryDirectory(prefix='mod-texture-', dir=work) as temporary:
        png = _decode_png(work, asset, temporary)
        target = _project_target(asset['game_rel'], '.png')
        os.makedirs(os.path.dirname(target), exist_ok=True)
        staged = target + '.mod-open.tmp'
        shutil.copyfile(png, staged)
        os.replace(staged, target)
    return None


def _template(name):
    """The game texture a new mod texture was most likely made from: its name with trailing parts
    removed one at a time (T_X_D_Brown, then T_X_D), in the main game content."""
    from atelier.index import by_basename
    parts = name.split('_')
    for end in range(len(parts) - 1, 1, -1):
        found = [gr for gr in by_basename('_'.join(parts[:end]))
                 if not gr.lower().startswith(('marvel_lq/', 'plugins/'))]
        if found:
            return found[0]
    return None


def _add_material(work, asset):
    from atelier.handlers.material import _mat_params, save_material
    with open(os.path.join(work, 'json', asset['id'] + '.json'), encoding='utf-8') as stream:
        doc = json.load(stream)
    colors, scalars = _mat_params(doc)
    save_material(asset['game_rel'], {c['name']: c['rgba'] for c in colors},
                  {s['name']: s['value'] for s in scalars})
    if any(ref['where'] == 'mod' and ref['path'].rsplit('/', 1)[-1].upper().startswith('T_')
           for ref in asset['references']):
        return ("Its colours and numbers were added. Its texture slots keep the game's textures, "
                "so the textures this mod points them at are not connected.")
    return None


def _add_new(work, asset):
    from atelier import added_assets
    base = _package_base(work, asset)
    folder, name = asset['game_rel'].rsplit('/', 1) if '/' in asset['game_rel'] else ('', asset['game_rel'])
    files = [base + ext for ext in _COMPANIONS if os.path.isfile(base + ext)]
    try:
        added_assets.add(asset['kind'], folder, name, files=files)
        return 'New in this mod, so it was added as your own asset at the same path.'
    except (ValueError, RuntimeError) as exc:
        template = _template(name) if asset['kind'] == 'texture' else None
        if not template:
            raise ValueError('New in this mod, and Atelier could not add it as your own asset: ' + str(exc)) from None
    # Some cooked textures can't be copied as they are; their image can be, on the game texture
    # they were made from.
    with tempfile.TemporaryDirectory(prefix='mod-texture-', dir=work) as temporary:
        png = _decode_png(work, asset, temporary)
        added_assets.add('texture', folder, name, source=template, files=[png])
    return ('New in this mod, so it was added as your own asset at the same path, from its image '
            'on the game texture %s.' % template.rsplit('/', 1)[-1])


def add_to_tray(key, ids):
    """Add the chosen assets to the active project. Returns {ok, added, skipped}."""
    manifest = load(key)
    work = _work(key)
    wanted = set(ids or ())
    chosen = [a for a in manifest['assets'] if a['id'] in wanted]
    if not chosen:
        return {'ok': False, 'error': 'Choose at least one asset to add.', 'added': [], 'skipped': []}
    added, skipped = [], []
    for n, asset in enumerate(chosen):
        jobs.checkpoint()
        jobs.progress('Adding ' + asset['name'], n, len(chosen))
        row = {'id': asset['id'], 'name': asset['name'], 'kind': asset['kind'], 'game_rel': asset['game_rel']}
        if not asset.get('editable'):
            skipped.append({**row, 'reason': asset.get('reason') or 'Atelier cannot add this kind of asset yet.'})
            continue
        try:
            if asset['how'] == 'add':
                note = _add_new(work, asset)
            elif asset['kind'] == 'texture':
                note = _add_texture(work, asset)
            else:
                note = _add_material(work, asset)
            added.append({**row, **({'note': note} if note else {})})
        except jobs.Cancelled:
            raise
        except Exception as exc:
            skipped.append({**row, 'reason': str(exc) or exc.__class__.__name__})
    jobs.progress('Finished', len(chosen), len(chosen))
    result = {'ok': bool(added), 'added': added, 'skipped': skipped, 'mod': manifest['name']}
    if not added:
        result['error'] = 'Nothing was added to the Mod tray.'
    return result


# ── saving JSON ──────────────────────────────────────────────────────────────────────────────────

def _safe(name):
    return re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', name).strip(' .') or 'mod'


def _unique(path):
    stem, ext = os.path.splitext(path)
    n = 2
    while os.path.exists(path):
        path = '%s (%d)%s' % (stem, n, ext)
        n += 1
    return path


def summary(manifest, assets):
    """A Markdown guide to the saved files: what each asset is and what it references."""
    lines = ['# ' + manifest['name'], '',
             'Read by Atelier from `%s` on %s.' % (os.path.basename(manifest['source']), manifest['read_at'][:10]),
             '', 'Paths are Unreal package paths. In FModel, `/Game/` is `Marvel/Content/` and each '
             'JSON file is the package as UAssetTool reads it.', '',
             '| Asset | Class | Path | In the game |', '| --- | --- | --- | --- |']
    for a in assets:
        lines.append('| %s | %s | `%s` | %s |' % (a['name'], a.get('class') or a['kind'], a['path'],
                                                  'yes, this mod replaces it' if a['in_game'] else 'no, new in this mod'))
    for a in assets:
        lines += ['', '## ' + a['name'], '', '- Class: ' + (a.get('class') or a['kind']), '- Path: `%s`' % a['path']]
        if a.get('parent'):
            lines.append('- Parent material: `%s`' % a['parent'])
        if a.get('references'):
            lines.append('- References:')
            lines += ['  - `%s` (%s)' % (r['path'], WHERE_LABELS.get(r['where'], 'outside the game content'))
                      for r in a['references']]
    return '\n'.join(lines) + '\n'


def save_json(key, dest, ids=None):
    """Save JSON for the chosen assets (all when ids is None) under dest. One asset saves one file;
    several save a folder mirroring the game paths, with a summary and the mod's text files."""
    manifest = load(key)
    work = _work(key)
    if not dest or not os.path.isdir(dest):
        raise ValueError('Choose a folder to save into.')
    wanted = None if ids is None else set(ids)
    assets = [a for a in manifest['assets'] if (wanted is None or a['id'] in wanted) and (a.get('json') or a.get('text'))]
    if not assets:
        raise ValueError('There is nothing to save as JSON.')

    def source(asset):
        if asset.get('json'):
            return os.path.join(work, 'json', asset['id'] + '.json'), '.json'
        return os.path.join(work, *asset['files'][0].split('/')), ''

    if wanted is not None and len(assets) == 1:
        path, ext = source(assets[0])
        target = _unique(os.path.join(dest, _safe(assets[0]['name']) + ext))
        shutil.copyfile(path, target)
        return {'ok': True, 'path': target, 'saved': 1}
    folder = _unique(os.path.join(dest, _safe(manifest['name']) + ' (JSON)'))
    os.makedirs(folder)
    for asset in assets:
        path, ext = source(asset)
        parts = [_safe(p) for p in asset['path'].strip('/').split('/') if p not in ('', '.', '..')]
        target = _long(os.path.join(folder, *parts) + ext)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        shutil.copyfile(path, target)
    with open(os.path.join(folder, 'README.md'), 'w', encoding='utf-8') as stream:
        stream.write(summary(manifest, [a for a in assets if a.get('json')]))
    return {'ok': True, 'path': folder, 'saved': len(assets)}

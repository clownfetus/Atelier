"""Add independent, named packages to a project and its normal editing/export workflows."""
import copy
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
import uuid

from atelier import config, jobs
from atelier.index import ensure_index
from atelier.storage import atomic_json, publish_project_files
from atelier.tools import uat
from atelier.unreal_names import add_names

PACKAGE_EXTS = ('.uasset', '.uexp', '.ubulk', '.uptnl')
IMAGE_EXTS = {'.png', '.tga', '.jpg', '.jpeg', '.webp', '.bmp', '.dds', '.hdr'}
CLASSES = {'texture': {'Texture2D', 'TextureCube'}, 'material': {'MaterialInstanceConstant'},
           'mesh': {'SkeletalMesh', 'StaticMesh'}}
PREFIXES = {'texture': 'T_', 'material': 'MI_', 'mesh': 'SK_'}
GAME_ROOT = '/Game/Marvel/'


def folder_path(value):
    if not isinstance(value, str):
        raise ValueError('Choose a game folder.')
    value = value.strip().replace('\\', '/')
    if value.rstrip('/') == GAME_ROOT.rstrip('/'):
        return ''
    if value.startswith(GAME_ROOT):
        value = value[len(GAME_ROOT):]
    value = value.rstrip('/')
    if value:
        parts = config.validate_game_rel(value)
        if any(not re.fullmatch(r'[A-Za-z0-9_]+', part) for part in parts):
            raise ValueError('Folder names can contain letters, numbers and underscores.')
        if any(re.fullmatch(r'CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9]', part, re.IGNORECASE) for part in parts):
            raise ValueError('Choose folder names that can be saved on Windows.')
        if parts[0].lower() in ('plugins', 'marvel_lq'):
            raise ValueError('Choose a folder in the main game content (/Game/Marvel/).')
        config.project_base(value)
    return value


def asset_path(file_type, folder, name):
    if file_type not in CLASSES:
        raise ValueError('Choose a texture, mesh or material.')
    if not isinstance(name, str) or not re.fullmatch(r'[A-Za-z0-9_]{1,80}', name.strip()):
        raise ValueError('Enter an asset name using letters, numbers and underscores (up to 80 characters).')
    name = name.strip()
    prefixes = ('SK_', 'SM_') if file_type == 'mesh' else (PREFIXES[file_type],)
    if not name.upper().startswith(prefixes):
        name = PREFIXES[file_type] + name
    from atelier.web.browse import _classify_file
    if _classify_file(name) != file_type:
        raise ValueError('Choose a name for this asset type (T_, MI_, SK_ or SM_).')
    folder = folder_path(folder)
    return (folder + '/' if folder else '') + name


def record(game_rel, root=None):
    path = config.project_base(game_rel, root) + '.asset.json'
    if not os.path.isfile(path):
        return None
    with open(path, encoding='utf-8') as stream:
        data = json.load(stream)
    if (not isinstance(data, dict) or data.get('version') != 1 or
            data.get('file_type') not in CLASSES or
            not re.fullmatch(r'[0-9a-f]{32}', str(data.get('id', '')))):
        raise ValueError('This added asset has an invalid source record: ' + game_rel)
    return data


def source_base(game_rel, root=None):
    """An added package's original travels with the project, independent of game caches."""
    data = record(game_rel, root)
    if data is None:
        return None
    base = config.project_base('.atelier/added-assets/' + data['id'] + '/' + game_rel.rsplit('/', 1)[-1], root)
    if not os.path.isfile(base + '.uasset'):
        raise ValueError('The added asset source is missing from this project: ' + game_rel)
    return base


def source_files(game_rel, root=None):
    base = source_base(game_rel, root)
    return [Path(base + ext) for ext in PACKAGE_EXTS if os.path.isfile(base + ext)] if base else []


def added_items(root=None):
    root = root or config.get_import_root()
    if not os.path.isdir(root):
        return []
    items = []
    for directory, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in ('.atelier', '.atelier-trash')]
        for name in files:
            if not name.endswith('.asset.json'):
                continue
            gr = os.path.relpath(os.path.join(directory, name[:-len('.asset.json')]), root).replace('\\', '/')
            data = record(gr, root)
            items.append({'game_rel': gr, 'file_type': data['file_type'], 'name': gr.rsplit('/', 1)[-1]})
    return items


def library_items(path):
    """Immediate project-only folders/assets, with the same shape as game-library items."""
    from atelier.web.browse import token
    prefix = path.rstrip('/') + '/' if path else ''
    result = {}
    for item in added_items():
        gr = item['game_rel']
        if not gr.casefold().startswith(prefix.casefold()):
            continue
        rest = gr[len(prefix):]
        if '/' in rest:
            name = rest.split('/')[0]
            result.setdefault(name.casefold(), {'type': 'folder', 'name': name, 'label': name,
                                               'rel_path': prefix + name})
        else:
            result[rest.casefold()] = {**item, 'type': 'asset', 'label': item['name'],
                                      'rel_path': gr, 'imported': True, 'token': token(gr)}
    return list(result.values())


def browse(path='', file_type=None):
    """Browse actual content folders, including folders introduced by this project."""
    path = folder_path(path)
    if file_type is not None and file_type not in CLASSES:
        raise ValueError('Choose a texture, mesh or material.')
    from atelier.web.browse import _classify_file
    prefix = path + '/' if path else ''
    children = {}
    from atelier.index import prefix_entries
    for entry in prefix_entries(prefix):
        gr = entry[0]
        rest = gr[len(prefix):]
        if '/' in rest:
            name = rest.split('/')[0]
            if not path and name.lower() in ('plugins', 'marvel_lq'):
                continue
            children.setdefault(name.casefold(), {'type': 'folder', 'name': name, 'rel_path': prefix + name})
        elif rest.lower().endswith('.uasset'):
            name = rest[:-7]
            kind = _classify_file(name, path)
            if kind == file_type:
                children[name.casefold()] = {'type': 'asset', 'name': name, 'game_rel': prefix + name}
    for item in library_items(path):
        if item['type'] == 'folder' or item['file_type'] == file_type:
            children.setdefault(item['name'].casefold(), item)
    from atelier.catalogue import catalogue
    return {'ok': True, 'path': path,
            'items': [catalogue.decorate(item) for item in sorted(children.values(),
                      key=lambda item: (item['type'] != 'folder', item['name'].casefold()))]}


def _read_package(base, directory):
    os.makedirs(directory, exist_ok=True)
    result = uat(['to_json', os.path.abspath(base + '.uasset'), config.USMAP, os.path.abspath(directory)])
    path = os.path.join(directory, os.path.basename(base) + '.json')
    if result.returncode != 0 or not os.path.isfile(path):
        raise ValueError('Could not read the Unreal asset: ' + (result.stderr or result.stdout or 'conversion failed')[-500:])
    with open(path, encoding='utf-8-sig') as stream:
        return json.load(stream)


def _export(doc, name, file_type):
    tops = [e for e in doc.get('Exports', []) if not e.get('OuterIndex') and e.get('ObjectName') == name]
    if len(tops) != 1:
        raise ValueError('The source must have one top-level asset matching its filename.')
    index = tops[0].get('ClassIndex')
    imports = doc.get('Imports', [])
    if (not isinstance(index, int) or index >= 0 or -index > len(imports) or
            imports[-index - 1].get('ObjectName') not in CLASSES[file_type]):
        raise ValueError('The source is not a supported ' + file_type + ' asset.')
    return tops[0]


def _mesh_lods(base):
    """Reject incomplete cooked skeletal packages before publishing a new asset."""
    from atelier.handlers.meshsurvey import probe
    report = probe(base, read_tails=False, include_layout=True)
    layout = report.get('_layout', [])
    if report['status'] == 'error' or not layout or any(lod['blob'] == 'missing' for lod in layout):
        raise ValueError('The skeletal mesh is missing geometry. Include every companion file and streamed LOD.')
    # Renaming can move the serialized properties without changing the geometry.
    # Compare section meaning, excluding parser byte-offset bookkeeping.
    return [{'num_verts': lod['num_verts'], 'n_indices': lod['n_indices'],
             'sections': [{key: value for key, value in section.items()
                           if key not in ('off', 'bm', 'after') and not key.endswith('_off')}
                          for section in lod['sections']]} for lod in layout]


def _retarget(doc, old_name, target, file_type, source_path=None):
    doc = copy.deepcopy(doc)
    original_names = list(doc.get('NameMap', []))
    _export(doc, old_name, file_type)['ObjectName'] = target.rsplit('/', 1)[-1]
    old_package = GAME_ROOT + source_path if source_path else doc.get('FolderName', '')
    new_package = GAME_ROOT + target
    new_name = target.rsplit('/', 1)[-1]
    def visit(value):
        if isinstance(value, str) and isinstance(old_package, str) and old_package.startswith('/'):
            if value == old_package:
                return new_package
            old_object = old_package + '.' + old_name
            if value == old_object or value.startswith(old_object + ':'):
                return new_package + '.' + new_name + value[len(old_object):]
        if isinstance(value, list):
            return [visit(v) for v in value]
        if isinstance(value, dict):
            return {k: visit(v) for k, v in value.items()}
        return value
    doc = visit(doc)
    # Opaque cooked payloads can address existing FNames by index. Keep their entries stable.
    doc['NameMap'] = original_names
    doc['FolderName'] = new_package
    add_names(doc, new_name, new_package)
    return doc


def _available(target):
    from atelier.index import index_lookup
    if (target + '.uasset').lower() in index_lookup():
        raise ValueError('An asset already exists in the game at this location. Choose another name or folder.')
    base = config.project_base(target)
    if any(os.path.exists(base + ext) for ext in ('.png', '.dds', '.json', '.blend', '.mesh.json', '.asset.json')):
        raise ValueError('An asset already exists in this project at this location. Choose another name or folder.')
    if any(item['game_rel'].casefold() == target.casefold() for item in added_items()):
        raise ValueError('An added asset already uses this name and folder.')


def add(file_type, folder, name, source='', files=()):
    """Prepare and verify privately; publish the package, editor files and record together."""
    from atelier.handlers import texture, custom_texture
    from atelier.web.browse import token
    target = asset_path(file_type, folder, name)
    _available(target)
    root = config.get_import_root()
    files = [Path(p) for p in files]
    images = [p for p in files if p.suffix.lower() in IMAGE_EXTS]
    packages = [p for p in files if p.suffix.lower() == '.uasset']
    if files and not (len(images) == 1 and len(files) == 1 and file_type == 'texture' or
                      len(packages) == 1 and all(p.suffix.lower() in PACKAGE_EXTS and p.stem == packages[0].stem for p in files)):
        raise ValueError('Choose one image for a texture, or one cooked .uasset and its matching companion files.')
    source_gr = None
    if packages:
        original = str(packages[0].with_suffix(''))
    else:
        if not isinstance(source, str):
            raise ValueError('Choose a game asset as the source.')
        source = re.sub(r'\.uasset$', '', source.strip(), flags=re.IGNORECASE)
        source_gr = folder_path(source)
        if not source_gr:
            raise ValueError('Choose a game asset to copy, or a game texture as the image template.')
        original = texture.ensure_work_base(source_gr)
        if not original or not os.path.isfile(original + '.uasset'):
            raise ValueError('The source asset could not be found: ' + source_gr)
    jobs.progress('Reading the source ' + file_type + '…')
    with tempfile.TemporaryDirectory(prefix='atelier-add-asset-') as temporary:
        work = Path(temporary)
        doc = _read_package(original, str(work / 'source-json'))
        export = _export(doc, os.path.basename(original), file_type)
        skeletal = file_type == 'mesh' and doc['Imports'][-export['ClassIndex'] - 1]['ObjectName'] == 'SkeletalMesh'
        original_lods = None
        if skeletal:
            if source_gr:
                # Patch packages may store their streamed geometry in a base container.
                # Complete that source before making the independent project copy.
                from atelier.handlers.meshstudio import complete_mesh_source
                original = complete_mesh_source(source_gr)
                doc = _read_package(original, str(work / 'source-json'))
                _export(doc, os.path.basename(original), file_type)
            original_lods = _mesh_lods(original)
        image = None
        from atelier.handlers import hdr_texture
        is_cube = file_type == 'texture' and hdr_texture.texture_class(doc) == 'TextureCube'
        hdr_cube = None
        if is_cube:
            hdr_cube, _, _ = hdr_texture.read_cooked(doc, original)
        if images:
            if is_cube:
                hdr_cube = hdr_texture.prepare(images[0].read_bytes(), images[0].name, hdr_cube.format,
                                               len(hdr_cube.mips), work/'hdr-prepare')
                png = hdr_texture.preview_png(hdr_cube, work/'hdr-preview')
            else:
                if images[0].suffix.lower() == '.hdr':
                    raise ValueError('Choose a TextureCube game template for an HDR cubemap.')
                payload = images[0].read_bytes()
                if payload[:4] == b'DDS ' and len(payload) >= 128 and int.from_bytes(payload[112:116], 'little') & 0x200:
                    raise ValueError('Choose a TextureCube game template for a six-face cubemap DDS.')
                png, _size = custom_texture._normalized_png(payload)
            image = work / 'image.png'; image.write_bytes(png)
        elif file_type == 'texture':
            if is_cube:
                image = work/'image.png'; image.write_bytes(hdr_texture.preview_png(hdr_cube, work/'hdr-preview'))
            else:
                preview = work / 'preview' / 'source'
                texture.decode_to_png(str(preview), original)
                image = preview.with_suffix('.png')
            if not image.is_file():
                raise ValueError('The texture could not be decoded for editing.')
        # The typed UE5 texture JSON writer can append a second None terminator.
        # A rename needs only the header: preserve the original cooked bytes.
        trim = custom_texture._duplicate_none_bytes(doc, original + '.uasset') if file_type == 'texture' else 0
        opaque = custom_texture._preserve_export_bytes(doc, original + '.uasset', trim_tail=trim) if file_type == 'texture' else False
        doc = _retarget(doc, os.path.basename(original), target, file_type, source_gr)
        compiled = work / 'compiled' / (target.rsplit('/', 1)[-1] + '.uasset')
        compiled.parent.mkdir()
        document = work / (compiled.stem + '.json'); atomic_json(document, doc)
        jobs.checkpoint(); jobs.progress('Building ' + target.rsplit('/', 1)[-1] + '…')
        result = uat(['from_json', str(document), str(compiled), config.USMAP])
        if result.returncode != 0 or not compiled.is_file():
            raise ValueError('Could not build the new asset: ' + (result.stderr or result.stdout or 'conversion failed')[-500:])
        if opaque:
            payload = Path(original + '.uexp').read_bytes()
            expected = payload[:-4-trim] + payload[-4:] if trim else payload
            if compiled.with_suffix('.uexp').read_bytes() != expected:
                raise ValueError('Renaming the texture altered its cooked payload; the asset was not added.')
        for ext in ('.ubulk', '.uptnl'):
            if os.path.isfile(original + ext):
                shutil.copyfile(original + ext, compiled.with_suffix(ext))
        if file_type == 'texture':
            # Rename the template before encoding: JSON conversion can drop inline mip data.
            # Injection writes a fresh, complete payload under the new package identity.
            baseline = work / 'baseline' / (os.path.basename(original) + '.uasset')
            encoded = work / 'encoded' / compiled.name
            for template, output in ((Path(original + '.uasset'), baseline), (compiled, encoded)):
                output.parent.mkdir()
                if is_cube:
                    hdr_texture.inject(str(template.with_suffix('')), output, hdr_cube, work/('hdr-'+output.parent.name))
                else:
                    result = uat(['inject_texture', str(template), str(image), str(output), '--usmap', config.USMAP])
                    if result.returncode != 0 or not output.is_file():
                        raise ValueError('Could not encode this image: ' + (result.stderr or result.stdout or 'injection failed')[-500:])
            custom_texture.repair_export_tail(str(encoded), str(work / 'texture-tail'))
            custom_texture._verify_rename(str(work), str(baseline), str(encoded), compiled.stem)
            compiled = encoded
        verified = _read_package(str(compiled.with_suffix('')), str(work / 'readback'))
        _export(verified, compiled.stem, file_type)
        if skeletal and _mesh_lods(str(compiled.with_suffix(''))) != original_lods:
            raise ValueError('The renamed skeletal mesh did not retain every original LOD and section.')
        if file_type == 'texture':
            editor_file = image; editor_ext = '.png'
        elif file_type == 'material':
            editor_file = work / 'material.json'; atomic_json(editor_file, verified); editor_ext = '.json'
        else:
            editor_file = work / 'mesh.json'
            atomic_json(editor_file, {'version': 1, 'game_rel': target, 'state': 'original'})
            editor_ext = '.mesh.json'
        identity = uuid.uuid4().hex
        package_path = '.atelier/added-assets/' + identity + '/' + compiled.stem
        marker = work / 'record.json'
        atomic_json(marker, {'version': 1, 'id': identity, 'file_type': file_type,
                             'source': source_gr or packages[0].name,
                             **({'texture_class': 'TextureCube', 'hdr': True} if is_cube else {})})
        changes = [{'path': package_path + ext, 'before': None, 'source': str(compiled.with_suffix(ext))}
                   for ext in PACKAGE_EXTS if compiled.with_suffix(ext).is_file()]
        changes += [{'path': target + editor_ext, 'before': None, 'source': str(editor_file)},
                    {'path': target + '.asset.json', 'before': None, 'source': str(marker)}]
        if is_cube:
            dds = work/'image.dds'; dds.write_bytes(hdr_texture.write_dds(hdr_cube))
            changes.append({'path': target+'.dds', 'before': None, 'source': str(dds)})
        jobs.checkpoint(); _available(target); jobs.begin_publication('Adding the asset to your project…')
        publish_project_files(root, changes)
    return {'ok': True, 'game_rel': target, 'file_type': file_type, 'name': target.rsplit('/', 1)[-1], 'token': token(target)}

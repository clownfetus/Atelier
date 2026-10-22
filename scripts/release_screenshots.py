"""Verify that release screenshots belong to the current interface and version."""
import hashlib
import json
from pathlib import Path
import re
import zipfile


def source_hashes(root):
    root = Path(root)
    paths = [root / 'version']
    paths += [p for p in (root / 'gui').rglob('*') if p.is_file()]
    paths += list((root / 'atelier').rglob('*.py'))
    def digest(path):
        data = path.read_bytes()
        # Git checks these sources out as LF. Older Windows working files may
        # still have CRLF despite the current .gitattributes rule.
        if path.suffix.lower() in {'.py', '.js', '.mjs', '.css', '.html', '.svg', '.md', '.json', '.txt'} or path.name in {'version', 'LICENSE', 'NOTICE'}:
            data = data.replace(b'\r\n', b'\n')
        return hashlib.sha256(data).hexdigest()
    return {p.relative_to(root).as_posix(): digest(p)
            for p in sorted(paths) if '__pycache__' not in p.parts}


def verify(root, version):
    root = Path(root)
    folder = root / 'images'
    receipt = json.loads((folder / 'screenshots.json').read_text(encoding='utf-8'))
    if receipt.get('version') != version or receipt.get('page_errors') != []:
        raise RuntimeError('Screenshot version or browser error gate failed')
    if receipt.get('source_files') != source_hashes(root):
        raise RuntimeError('Screenshots came from a different interface source; recapture them')
    rows = receipt.get('files', [])
    names = [row['path'] for row in rows]
    required = {'studio-dark.png', 'studio-light.png', 'material-editor.png',
                'model-studio.png', 'showcase.png'}
    if len(names) != len(set(names)) or not required.issubset(names):
        raise RuntimeError('Screenshot inventory is incomplete or contains duplicates')
    for row in rows:
        name = row['path']
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]*\.png', name):
            raise RuntimeError('Unsafe screenshot path: ' + name)
        path = folder / name
        if hashlib.sha256(path.read_bytes()).hexdigest() != row['sha256']:
            raise RuntimeError('Screenshot hash mismatch: ' + name)
    return receipt


def archive(root, version, destination):
    receipt = verify(root, version)
    folder = Path(root) / 'images'
    with zipfile.ZipFile(destination, 'w', compression=zipfile.ZIP_DEFLATED) as output:
        for name in ['README.md', 'screenshots.json', *[row['path'] for row in receipt['files']]]:
            output.write(folder / name, name)
    return receipt

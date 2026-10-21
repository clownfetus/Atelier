"""Verify the portable archive against the exact installer payload inventory."""
import argparse,hashlib,json,zipfile
from pathlib import Path

def verify(archive_path, manifest):
    expected={'Atelier/'+item['path']:item for item in manifest['files']}
    if len(expected) != len(manifest['files']):
        raise RuntimeError('Installer payload inventory has duplicate paths')
    with zipfile.ZipFile(archive_path) as archive:
        files=[info for info in archive.infolist() if not info.is_dir()]
        if len(files)!=len(expected) or {info.filename for info in files}!=set(expected):
            raise RuntimeError('Portable archive file membership differs from the installer payload')
        for info in files:
            item=expected[info.filename]
            with archive.open(info) as stream:digest=hashlib.file_digest(stream,'sha256').hexdigest()
            if info.file_size!=item['bytes'] or digest!=item['sha256']:
                raise RuntimeError('Portable archive has a stale or corrupted file: '+info.filename)
    return len(expected)

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive',type=Path,required=True)
    parser.add_argument('--manifest',type=Path,required=True)
    args=parser.parse_args();manifest=json.loads(args.manifest.read_text(encoding='utf-8'))
    count=verify(args.archive,manifest)
    print(f'Verified {count} portable files against the installer payload SHA-256 inventory')

if __name__=='__main__':main()

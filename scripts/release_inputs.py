"""Stage hash-pinned tool seeds for native release builds; no game/user data."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile

ROOT=Path(__file__).resolve().parents[1]

def download(url,path,sha,authenticated=False):
    headers={'User-Agent':'Atelier-release','Accept':'application/octet-stream'}
    if authenticated:headers['Authorization']='Bearer '+os.environ['GH_TOKEN']
    with urllib.request.urlopen(urllib.request.Request(url,headers=headers),timeout=180) as response,path.open('wb') as output:
        shutil.copyfileobj(response,output)
    with path.open('rb') as stream:actual=hashlib.file_digest(stream,'sha256').hexdigest()
    if actual!=sha:raise RuntimeError('Release input hash mismatch: '+path.name)

def main():
    inputs=json.loads((ROOT/'tests/fixtures/installer'/f"release-{(ROOT/'version').read_text().strip()}-inputs.json").read_text())
    with tempfile.TemporaryDirectory(prefix='atelier-release-inputs-') as folder:
        work=Path(folder);seed=work/'windows-tools.zip'
        download(inputs['tools_seed_api_url'],seed,inputs['tools_seed_sha256'],True)
        with zipfile.ZipFile(seed) as archive:
            for name in archive.namelist():
                parts=Path(name).parts
                if not parts or parts[0]!='Tools' or '..' in parts or Path(name).is_absolute():raise ValueError('Invalid tools seed path')
            archive.extractall(ROOT)
        if sys.platform=='linux':
            image=work/'previous.AppImage';download(inputs['linux_seed_url'],image,inputs['linux_seed_sha256'])
            image.chmod(0o755)
            if os.environ.get('RUNNER_TEMP'):
                shutil.copy2(image, Path(os.environ['RUNNER_TEMP'])/'atelier-previous.AppImage')
            subprocess.run([str(image),'--appimage-extract'],cwd=work,check=True,stdout=subprocess.DEVNULL)
            tools=next((work/'squashfs-root').rglob('Tools/UAssetTool')).parent
            for name in ('UAssetTool','liboo2corelinux64.so.9','libooz.so','shaders/retoc-rivals-cli','shaders/liboo2corelinux64.so.9'):
                source=tools/name
                if not source.exists() and name=='libooz.so':continue
                target=ROOT/'Tools'/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,target)
            for name in ('UAssetTool','shaders/retoc-rivals-cli'):(ROOT/'Tools'/name).chmod(0o755)
    print('Hash-pinned release tools staged')

if __name__=='__main__':main()

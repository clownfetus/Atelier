"""Reuse the last published tools only when source, SDK and lock verification agree."""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def previous_recipe(context, sdk):
    for name in ('.github/workflows/release.yml', '.github/workflows/release-candidate.yml'):
        result = subprocess.run(['git', 'show', context['previous_tag'] + ':' + name], cwd=ROOT,
                                capture_output=True, text=True, encoding='utf-8')
        if result.returncode:
            continue
        match = re.search(r"DOTNET_VERSION:\s*['\"]?([0-9.]+)", result.stdout)
        if not match or match[1] != sdk:
            return False
        if name.endswith('/release.yml'):
            # Workflow changes may also change the compiler/build environment.
            changed = subprocess.check_output(['git', 'diff', '--name-only', context['previous_tag'], 'HEAD', '--', name], cwd=ROOT, text=True)
            if changed.strip():
                return False
        return True
    return False


def reuse(context, platform):
    destination = ROOT / 'Tools'
    if not context['reuse_native'] or destination.exists():
        return False
    config = json.loads((ROOT / 'scripts/release_config.json').read_bytes())
    if not previous_recipe(context, config['dotnet_sdk']):
        return False
    import stage_tools
    names = {name for name, _ in stage_tools.MANIFEST[platform] if not name.startswith('Galacta/')}
    names.update({'tools.json', 'THIRD_PARTY_TOOLS.md'})
    assets = context['previous_assets']
    previous = context['previous_version']
    asset = assets.get(f'Atelier-Windows-{previous}.zip' if platform == 'windows' else f'Atelier-{previous}-x86_64.AppImage')
    if not asset or not isinstance(asset.get('digest'), str) or not asset['digest'].startswith('sha256:'):
        return False
    with tempfile.TemporaryDirectory(prefix='atelier-native-reuse-') as folder:
        folder = Path(folder)
        archive_path = folder / ('previous.zip' if platform == 'windows' else 'previous.AppImage')
        request = urllib.request.Request(asset['browser_download_url'], headers={'User-Agent': 'Atelier-release'})
        with urllib.request.urlopen(request, timeout=180) as source, archive_path.open('wb') as output:
            shutil.copyfileobj(source, output)
        with archive_path.open('rb') as stream:
            if hashlib.file_digest(stream, 'sha256').hexdigest() != asset['digest'][7:]:
                raise ValueError('Previous release failed its GitHub asset digest.')
        staged = folder / 'Tools'
        staged.mkdir()
        if platform == 'windows':
            with zipfile.ZipFile(archive_path) as archive:
                for name in names:
                    member = 'Atelier/Tools/' + name
                    if member not in archive.namelist():
                        continue
                    target = staged / name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with archive.open(member) as source, target.open('xb') as output:
                        shutil.copyfileobj(source, output)
        else:
            archive_path.chmod(0o755)
            subprocess.run([str(archive_path), '--appimage-extract'], cwd=folder, check=True, stdout=subprocess.DEVNULL)
            tools = folder / 'squashfs-root/usr/Atelier/Tools'
            for name in names:
                source = tools / name
                if source.is_file():
                    target = staged / name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, target)
        result = subprocess.run([sys.executable, str(ROOT / 'scripts/toolchain.py'), 'verify', '--platform', platform, '--dest', str(staged)], cwd=ROOT)
        if result.returncode:
            return False
        shutil.copytree(staged, destination)
    return True


if __name__ == '__main__':
    context = json.loads((ROOT / '_release/context.json').read_bytes())
    platform = 'windows' if os.name == 'nt' else 'linux'
    try:
        reused = reuse(context, platform)
    except (OSError, ValueError, subprocess.SubprocessError, zipfile.BadZipFile) as error:
        print('Previous tools could not be reused; building from the lockfile: ' + str(error))
        reused = False
    if os.environ.get('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'], 'a', encoding='utf-8') as output:
            output.write('reused=' + str(reused).lower() + '\n')
    print('Verified previous-release tools reused.' if reused else 'Native build required.')

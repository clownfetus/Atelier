"""Build the small independent updater; it must not hold installed DLLs open."""
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def build(destination):
    destination = Path(destination).absolute()
    executable = destination / ('AtelierUpdater.exe' if sys.platform == 'win32' else 'AtelierUpdater')
    command = [sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean', '--onefile',
               '--name', 'AtelierUpdater', '--paths', str(ROOT),
               '--distpath', str(destination), '--workpath', str(destination / 'work'),
               '--specpath', str(destination), '--add-data', str(ROOT / 'update_keys.json') + ':.',
               '--hidden-import', 'cryptography.hazmat.primitives.asymmetric.ed25519']
    if sys.platform == 'win32':
        command.append('--noconsole')
    command.append(str(ROOT / 'atelier' / 'update_helper.py'))
    subprocess.run(command, cwd=ROOT, check=True)
    return executable


if __name__ == '__main__':
    build(ROOT / 'build' / 'updater')

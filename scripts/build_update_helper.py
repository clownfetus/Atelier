"""Build the small independent updater; it must not hold installed DLLs open."""
from pathlib import Path
import subprocess
import sys
import sysconfig

ROOT = Path(__file__).resolve().parents[1]


def compatibility_binaries():
    """PyInstaller does not yet find CPython 3.15's abi3t compatibility shim."""
    if sys.platform != 'win32' or sys.version_info < (3, 15):
        return []
    prefix = Path(sys.base_prefix)
    candidates = []
    if not sysconfig.get_config_var('Py_GIL_DISABLED'):
        candidates.append(prefix / 'abi3t-compat/python3t.dll')
    candidates.append(prefix / 'python3t.dll')
    for path in candidates:
        if path.is_file():
            return [(str(path), '.')]
    raise RuntimeError('The Python 3.15 installation is missing its python3t.dll compatibility shim.')


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
    for path, target in compatibility_binaries():
        command.extend(['--add-binary', path + ':' + target])
    command.append(str(ROOT / 'atelier' / 'update_helper.py'))
    subprocess.run(command, cwd=ROOT, check=True)
    # Importing and using the frozen signature library catches missing native
    # dependencies that --help alone cannot detect.
    subprocess.run([str(executable), '--self-test'], cwd=ROOT, check=True, timeout=60)
    return executable


if __name__ == '__main__':
    build(ROOT / 'build' / 'updater')

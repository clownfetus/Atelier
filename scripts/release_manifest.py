"""Create the installer smoke-test manifest and collect distribution licenses."""
import hashlib,json,shutil,subprocess,sys
from pathlib import Path
from package_release import collect_licenses

ROOT=Path(__file__).resolve().parents[1]
bundle=ROOT/'dist/Atelier'
shutil.copy2(ROOT/'LICENSE',bundle/'LICENSE')
(bundle/'licenses').mkdir(exist_ok=True)
collect_licenses(bundle/'licenses')
if '--manifest' in sys.argv:
    inputs=json.loads((ROOT/'tests/fixtures/installer/release-0.4.0-inputs.json').read_text())
    def sha(path):
        with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()
    commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    data={'source_commit':commit,'application_source_commit':commit,'application_version':(ROOT/'version').read_text().strip(),
          'previous_installer_url':inputs['previous_windows_url'],'previous_installer_sha256':inputs['previous_windows_sha256'],'previous_installer_bytes':inputs['previous_windows_bytes'],
          'files':[{'path':p.relative_to(bundle).as_posix(),'bytes':p.stat().st_size,'sha256':sha(p)} for p in sorted(bundle.rglob('*')) if p.is_file()]}
    installer=ROOT/'dist/AtelierSetup.exe'
    data.update(installer_bytes=installer.stat().st_size,installer_sha256=sha(installer))
    (ROOT/'dist/installer-manifest.json').write_text(json.dumps(data,indent=2),encoding='utf-8')

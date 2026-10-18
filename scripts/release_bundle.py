"""Assemble a release only from artifacts that passed every platform gate."""
import argparse,hashlib,json,os,shutil,subprocess,zipfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

def sha(path):
    with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()

def one(root,suffix):
    found=[p for p in root.rglob('*') if p.is_file() and p.as_posix().endswith(suffix)]
    if len(found)!=1:raise RuntimeError(f'Expected one {suffix} beneath {root}, got {len(found)}')
    return found[0]

def load(path):return json.loads(path.read_text(encoding='utf-8'))

def backend(path):
    data=load(path);rows=data['results']
    if not rows or any(row['exit_code'] for row in rows):raise RuntimeError(f'Backend gate failed: {path}')
    return {'suites':len(rows),'results':rows,'platform':data['platform'],'python':data['python']}

def browser(path):
    data=load(path)
    if not data.get('checks') or data.get('page_errors'):raise RuntimeError(f'UI gate failed: {path}')
    return data

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--artifacts',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();art=args.artifacts.resolve();out=args.output.resolve()
    if out.exists():raise RuntimeError('Use a new release output directory')
    version=(ROOT/'version').read_text().strip()
    commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    manifest=load(one(art/'windows-installer','installer-manifest.json'))
    if manifest['source_commit']!=commit or manifest['application_version']!=version:
        raise RuntimeError('Windows payload came from another source commit/version')
    installer=one(art/'windows-installer','AtelierSetup.exe')
    if sha(installer)!=manifest['installer_sha256'] or installer.stat().st_size!=manifest['installer_bytes']:
        raise RuntimeError('Windows installer does not match the verified manifest')
    linux=one(art/'linux-appimage',f'Atelier-{version}-x86_64.AppImage')
    checks={
        'windows_backend':backend(one(art/'windows-backend-report','backend/results.json')),
        'windows_browser':browser(one(art/'windows-backend-report','browser/results.json')),
        'windows_frozen':browser(one(art/'windows-backend-report','frozen/results.json')),
        'linux_backend':backend(one(art/'linux-reports','backend/results.json')),
    }
    for os_name in ['windows-2022','windows-2025']:
        data=load(one(art/f'installer-report-{os_name}','results.json'))
        if not data.get('ok') or data.get('page_errors') or data['installer_sha256']!=sha(installer):
            raise RuntimeError(f'Installer gate failed: {os_name}')
        checks[f'installer_{os_name}']=data
    data=load(one(art/'linux-reports','appimage-smoke/results.json'))
    if not data.get('ok') or data['appimage_sha256']!=sha(linux):raise RuntimeError('Linux desktop gate failed')
    inputs=load(ROOT/'tests/fixtures/installer'/f'release-{version}-inputs.json')
    if data.get('previous_appimage_sha256')!=inputs['linux_seed_sha256']:
        raise RuntimeError('Linux upgrade gate did not use the pinned previous release')
    checks['linux_appimage']=data
    out.mkdir(parents=True)
    for path in [installer,linux]:shutil.copy2(path,out/path.name)
    source=out/f'Atelier-{version}-source.zip'
    subprocess.run(['git','archive','--format=zip','--prefix=Atelier-source/','--output',str(source),commit],cwd=ROOT,check=True)
    with zipfile.ZipFile(source) as archive:
        if archive.testzip():raise RuntimeError('Source archive failed integrity verification')
    files=[{'name':p.name,'bytes':p.stat().st_size,'sha256':sha(p)} for p in [out/installer.name,out/linux.name,source]]
    info={'version':version,'source_commit':commit,'workflow_url':f"https://github.com/{os.environ.get('GITHUB_REPOSITORY','clownfetus/Atelier')}/actions/runs/{os.environ.get('GITHUB_RUN_ID','local')}",
          'files':files,'checks':checks,'game_appearance_verified':False,
          'linux_wine_workflows_verified':False,'release_state_at_build':'candidate'}
    verification=out/'VERIFICATION.json';verification.write_text(json.dumps(info,indent=2)+'\n',encoding='utf-8')
    (out/'SHA256SUMS.txt').write_text(''.join(f'{sha(p)}  {p.name}\n' for p in [out/installer.name,out/linux.name,source,verification]),encoding='utf-8')
    print(json.dumps({'version':version,'source_commit':commit,'files':files,'passed_gates':list(checks)},indent=2))

if __name__=='__main__':main()

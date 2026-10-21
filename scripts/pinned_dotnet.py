"""Build a managed helper from locked source, bundle dependencies and NuGet archives."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import urllib.request

from dotnet_bundle import extract_assemblies
from native_inputs import LOCK_PATH, ROOT, digest, load_lock, verify_files, verify_mesh


def prepare_feed(folder, packages, cache=None):
    """Use verified archives only; restore extracts them into a fresh private cache."""
    folder = Path(folder)
    folder.mkdir()
    cache = Path(cache or os.environ.get('NUGET_PACKAGES', Path.home() / '.nuget/packages'))
    for package in packages:
        name, version = package['name'].lower(), package['version']
        archive = folder / f'{name}.{version}.nupkg'
        cached = cache / name / version / archive.name
        if cached.is_file():
            shutil.copyfile(cached, archive)
        else:
            url = f'https://api.nuget.org/v3-flatcontainer/{name}/{version}/{archive.name}'
            with urllib.request.urlopen(url, timeout=60) as response, archive.open('wb') as output:
                shutil.copyfileobj(response, output)
        if digest(archive, 'sha512') != package['sha512']:
            raise ValueError(f'Pinned NuGet archive SHA-512 mismatch: {name}/{version}')


def checked_run(command, **kwargs):
    flags = {'creationflags': subprocess.CREATE_NO_WINDOW} if hasattr(subprocess, 'CREATE_NO_WINDOW') else {}
    result = subprocess.run(command, capture_output=True, text=True, encoding='utf-8',
                            errors='replace', timeout=300, **flags, **kwargs)
    if result.returncode:
        raise RuntimeError('Native build failed:\n' + (result.stdout + result.stderr)[-10000:])
    return result.stdout.strip()


def build(tool, tools, output, dotnet='dotnet'):
    lock_hash = digest(LOCK_PATH)
    lock = load_lock()
    if digest(LOCK_PATH) != lock_hash:
        raise ValueError('Native input lock changed while being read; retry the build')
    output = Path(output).resolve()
    if output.exists():
        raise ValueError(f'Output exists; choose a fresh folder: {output}')
    recipe = verify_files(ROOT, lock['recipe'])
    mesh_files = verify_mesh(tools, lock)
    project = lock['managed'][tool]
    sources = verify_files(ROOT / 'tools-src', project['sources'])
    version = checked_run([str(dotnet), '--version'], cwd=ROOT / 'tools-src')
    if version != lock['dotnet']['sdk']:
        raise ValueError(f"Build requires exactly .NET SDK {lock['dotnet']['sdk']}; found {version}")
    output.parent.mkdir(parents=True, exist_ok=True)
    # All writes before publication belong to this newly created scratch directory.
    with tempfile.TemporaryDirectory(prefix='.atelier-native-build-', dir=output.parent) as folder:
        work = Path(folder)
        for name in sources:
            target = work / 'source' / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / 'tools-src' / name, target)
        verify_files(work / 'source', sources)
        mesh_snapshot = work / 'mesh'
        mesh_snapshot.mkdir()
        for name in mesh_files:
            shutil.copyfile(Path(tools) / 'AtelierMesh' / name, mesh_snapshot / name)
        verify_files(mesh_snapshot, lock['mesh']['files'])
        libraries = work / 'libraries'
        libraries.mkdir()
        extract_assemblies(mesh_snapshot / 'AtelierMesh.exe', libraries)
        verify_files(libraries, lock['mesh']['assemblies'])
        prepare_feed(work / 'feed', lock['dotnet']['packages'])
        config = work / 'NuGet.Config'
        config.write_text('<configuration><packageSources><clear/></packageSources>'
                          '<fallbackPackageFolders><clear/></fallbackPackageFolders></configuration>',
                          encoding='utf-8')
        csproj = work / 'source' / project['project']
        properties = [f'-p:MeshAssemblies={libraries}', '-p:PublishSingleFile=true',
                      '-p:SelfContained=true', '-p:RuntimeIdentifier=win-x64',
                      '-p:Configuration=Release', f'-p:PathMap={work}=/_/atelier-native']
        env = dict(os.environ, DOTNET_CLI_TELEMETRY_OPTOUT='1', DOTNET_SKIP_FIRST_TIME_EXPERIENCE='1',
                   NUGET_PACKAGES=str(work / 'packages'))
        checked_run([str(dotnet), 'restore', str(csproj), '--locked-mode',
                     '--configfile', str(config), '--source', str(work / 'feed'), *properties],
                    cwd=work / 'source', env=env)
        stage = work / 'publish'
        checked_run([str(dotnet), 'publish', str(csproj), '--no-restore',
                     '-o', str(stage), *properties], cwd=work / 'source', env=env)
        for name in ('CUE4Parse-Natives.dll', 'oo2core_9_win64.dll'):
            shutil.copyfile(mesh_snapshot / name, stage / name)
        record = dict(schema=1, tool=tool, lock_sha256=lock_hash,
                      sdk=version, runtime=lock['dotnet']['runtime'], rid='win-x64',
                      sdk_archive=lock['dotnet']['sdk_archive'], recipe=recipe,
                      configuration='Release', self_contained=True, single_file=True,
                      sources=sources, mesh=mesh_files, assemblies=lock['mesh']['assemblies'],
                      packages=lock['dotnet']['packages'],
                      outputs={p.name: digest(p) for p in sorted(stage.iterdir()) if p.is_file()})
        (stage / 'build-inputs.json').write_text(json.dumps(record, indent=2) + '\n', encoding='utf-8')
        created = False
        try:
            output.mkdir()  # Exclusive publication: never overwrite another build or install.
            created = True
            for path in stage.iterdir():
                shutil.copyfile(path, output / path.name)
        except BaseException:
            if created:
                shutil.rmtree(output)
            raise
    print(f'Built {tool} from verified inputs: {output}')
    return record

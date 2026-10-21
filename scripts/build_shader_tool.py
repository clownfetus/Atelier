"""Build Atelier's shader fork from verified upstream, compiler and Cargo inputs.

Windows x64 only. Installs no system tools and never overwrites an existing output.
Only downloaded archives are cached; extracted compilers and Cargo caches are private
to each build, so an altered global package cache cannot become a build input.
"""
import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import tarfile
import tempfile
import time
import tomllib
import urllib.request
import zipfile

from native_inputs import ROOT, digest, verify_files

SOURCE = ROOT / 'tools-src/AtelierShader'
LOCK = SOURCE / 'build.lock.json'


def load_shader_lock(raw=None):
    lock = json.loads(raw if raw is not None else LOCK.read_bytes())
    if lock['schema'] != 1:
        raise ValueError('Unsupported shader build input lock')
    verify_files(ROOT, lock['recipe'])
    verify_files(SOURCE, lock['sources'])
    cargo = tomllib.loads((SOURCE / 'Cargo.lock').read_text(encoding='utf-8'))
    git_inputs = {p['name']: p['source'] for p in cargo['package'] if p.get('source', '').startswith('git+')}
    if git_inputs != lock['git_dependencies']:
        raise ValueError('Shader Cargo git revisions differ from the input lock')
    return lock


def archive_input(pin, cache):
    cache.mkdir(parents=True, exist_ok=True)
    suffix = '.zip' if pin['url'].endswith('.zip') else '.tar'
    path = cache / (pin['sha256'] + suffix)
    if not path.exists():
        with tempfile.NamedTempFile(dir=cache, delete=False) as stream:
            temporary = Path(stream.name)
            try:
                request = urllib.request.Request(pin['url'], headers={'User-Agent': 'Atelier-source-build'})
                with urllib.request.urlopen(request, timeout=90) as response:
                    shutil.copyfileobj(response, stream)
            except BaseException:
                stream.close()
                temporary.unlink(missing_ok=True)
                raise
        if digest(temporary) != pin['sha256']:
            temporary.unlink()
            raise ValueError('Downloaded shader build archive SHA-256 mismatch')
        try:
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)
    if digest(path) != pin['sha256']:
        raise ValueError('Cached shader build archive SHA-256 mismatch')
    return path


def safe_member(name):
    normalized = name.replace('\\', '/')
    if not normalized or normalized.startswith('/') or ':' in normalized or '..' in normalized.split('/'):
        raise ValueError('Unsafe path in shader build archive')
    return normalized


def extract_archive(archive, output):
    output.mkdir(parents=True, exist_ok=False)
    if zipfile.is_zipfile(archive):
        with zipfile.ZipFile(archive) as source:
            for member in source.infolist():
                name = safe_member(member.filename)
                if (member.external_attr >> 16) & 0o170000 == 0o120000:
                    raise ValueError('Symbolic link in shader build ZIP')
                target = output / name
                if member.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with source.open(member) as stream, target.open('xb') as destination:
                        shutil.copyfileobj(stream, destination)
    else:
        with tarfile.open(archive) as source:
            for member in source.getmembers():
                safe_member(member.name)
                if member.issym() or member.islnk():
                    safe_member(member.linkname)
            source.extractall(output, filter='data')
    children = list(output.iterdir())
    if len(children) != 1 or not children[0].is_dir():
        raise ValueError('Unexpected shader input archive root')
    return children[0]


def replace_exact(path, old, new):
    content = path.read_text(encoding='utf-8')
    if content.count(old) != 1:
        raise ValueError(f'Upstream patch anchor changed: {path.name}')
    path.write_text(content.replace(old, new), encoding='utf-8', newline='\n')


def remove_upstream_key_defaults(library):
    path = library / 'src/lib.rs'
    original = path.read_text(encoding='utf-8')
    defaults = re.findall(r'(?m)^        default_value = "([A-Fa-f0-9]{64})"\n', original)
    if len(defaults) != 1:
        raise ValueError('Upstream standalone key-default anchor changed')
    content, count = re.subn(r'(?m)^        default_value = "[A-Fa-f0-9]{64}"\n', '', original)
    if count != 1:
        raise ValueError('Upstream standalone key-default anchor changed')
    path.write_text(content, encoding='utf-8', newline='\n')
    path = library / 'src/iostore_writer.rs'
    content = path.read_text(encoding='utf-8')
    start = content.index('                const DEFAULT_AES_KEY: &str =')
    end = content.index('                let padded_len =', start)
    fallback = content[start:end]
    if len(re.findall(r'"[A-Fa-f0-9]{64}"', fallback)) != 1 or 'self.aes_key.as_ref()' not in fallback:
        raise ValueError('Upstream writer key-default anchor changed')
    content = content[:start] + '''                let key = self.aes_key.as_ref()
                    .ok_or_else(|| anyhow::anyhow!("Obfuscated containers require an explicit key"))?;
''' + content[end:]
    content, count = re.subn('"' + re.escape(defaults[0]) + r'"\.parse\(\)\?',
                            '"11".repeat(32).parse()?', content, flags=re.I)
    if count != 1:
        raise ValueError('Upstream key test-fixture anchor changed')
    path.write_text(content, encoding='utf-8', newline='\n')


def prepare_source(work, lock, cache, native):
    project = work / 'source'
    project.mkdir()
    for name in lock['sources']:
        target = project / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(SOURCE / name, target)
    verify_files(project, lock['sources'])
    extracted = {}
    for name, pin in lock['upstream'].items():
        extracted[name] = extract_archive(archive_input(pin, cache), work / ('extract-' + name))
    upstream = project / 'upstream'
    for name in ('repak', 'oodle_loader'):
        shutil.copytree(extracted['repak-rivals'] / name, upstream / name)
    shutil.copytree(extracted['retoc-rivals'], upstream / 'retoc-rivals')
    # The pinned parent archive includes this DLL too. Use the explicitly verified
    # app dependency as the embedded payload and record its own digest.
    shutil.copyfile(native, upstream / 'oo2core_9_win64.dll')
    verify_files(upstream, lock['native_files'])
    library = upstream / 'retoc-rivals'
    remove_upstream_key_defaults(library)
    replace_exact(library / 'src/lib.rs', 'mod shader_library;', 'pub mod shader_library;')
    replace_exact(library / 'src/lib.rs', 'use iostore::{IoStoreTrait, PackageInfo};',
                  'pub use iostore::IoStoreTrait;\nuse iostore::PackageInfo;')
    for package, source in lock['git_dependencies'].items():
        url, revision = source.removeprefix('git+').split('#')
        url = url.split('?')[0]
        replace_exact(library / 'Cargo.toml', f'git = "{url}",', f'git = "{url}", rev = "{revision}",')
    shader = library / 'src/shader_library.rs'
    shader.write_text(shader.read_text(encoding='utf-8') + '\ninclude!("atelier_shader_commands.rs");\n',
                      encoding='utf-8', newline='\n')
    shutil.copyfile(project / 'src/shader_commands.rs', shader.with_name('atelier_shader_commands.rs'))
    # Load only the exact embedded Oodle dependency, including when a sidecar exists.
    loader = upstream / 'oodle_loader/src/lib.rs'
    replace_exact(loader, '    Ok(oodle_path)\n}', '''    use sha2::{Digest, Sha256};
    let expected = hex::encode(Sha256::digest(OODLE_PLATFORM.bytes));
    let found = hex::encode(Sha256::digest(std::fs::read(&oodle_path)?));
    if found != expected { return Err(Error::HashMismatch { expected, found }); }
    Ok(oodle_path)
}''')
    # Prevent archive paths or existing junctions from redirecting extraction writes.
    replace_exact(library / 'src/lib.rs', '        let path = self.dir.join(path);\n        let dir = path.parent().unwrap();\n        fs::create_dir_all(dir)?;\n        Ok(fs::write(path, &data)?)',
                  '''        let relative = shader_library::atelier_safe_relative_path(&path)?;
        let root = self.dir.canonicalize()?;
        let path = root.join(&relative);
        let mut dir = root.clone();
        for component in relative.parent().context("Missing asset output parent")?.components() {
            dir.push(component);
            match fs::create_dir(&dir) {
                Ok(()) => (),
                Err(error) if error.kind() == std::io::ErrorKind::AlreadyExists && dir.is_dir() => (),
                Err(error) => return Err(error.into()),
            }
            if !dir.canonicalize()?.starts_with(&root) {
                bail!("Asset output escapes the extraction directory");
            }
        }
        if path.symlink_metadata().is_ok_and(|m| m.file_type().is_symlink()) {
            bail!("Asset output escapes the extraction directory");
        }
        Ok(fs::write(path, &data)?)''')
    replace_exact(library / 'src/lib.rs',
                  '            prog_ref.inspect(|p| p.println(format!("FAILED: {path} - {err:#}")));',
                  '            emit_log(&format!("FAILED: {path} - {err:#}"));')
    replace_exact(library / 'src/lib.rs',
                  '''        args.output
    );
    Ok(())
}

fn action_to_legacy_shaders(''',
                  '''        args.output
    );
    if failed_count != 0 { bail!("Failed to extract {failed_count} of {count} selected assets"); }
    Ok(())
}

fn action_to_legacy_shaders(''')
    licenses = project / 'licenses'
    licenses.mkdir()
    for name in ('MIT', 'APACHE'):
        shutil.copyfile(extracted['repak-rivals'] / ('LICENSE-' + name), licenses / ('repak-' + name + '.txt'))
    shutil.copyfile(library / 'LICENSE', licenses / 'retoc-MIT.txt')
    return project


def prepare_compiler(work, lock, cache):
    rust = work / 'rust'
    for name, pin in lock['compiler']['rust_archives'].items():
        component = extract_archive(archive_input(pin, cache), work / ('extract-' + name))
        for path in component.iterdir():
            if path.is_dir():
                shutil.copytree(path, rust, dirs_exist_ok=True)
    llvm = extract_archive(archive_input(lock['compiler']['llvm_archive'], cache), work / 'extract-llvm')
    return rust / 'bin', llvm / 'bin'


def compiler_environment(work, rust, llvm):
    # Do not inherit build flags, wrappers, global Cargo configuration or compilers.
    system = Path(os.environ.get('SystemRoot', 'C:/Windows'))
    env = {key: value for key, value in os.environ.items() if not re.match(
        r'^(CARGO|RUST|CC|CXX|AR|CFLAGS|CXXFLAGS|CPPFLAGS|LDFLAGS|LIBRARY_PATH|CPATH|C_INCLUDE_PATH|CPLUS_INCLUDE_PATH|PKG_CONFIG|RETOC|ATELIER_RETOC)', key, re.I)}
    flags = [f'--remap-path-prefix={work}=/atelier-shader', '-Clink-self-contained=yes',
             '-Clink-arg=-Wl,--no-insert-timestamp']
    env.update(PATH=os.pathsep.join(map(str, [rust, llvm, system / 'System32', system])),
               RUSTC=str(rust / 'rustc.exe'), CARGO_HOME=str(work / 'cargo-home'),
               CARGO_TARGET_DIR=str(work / 'target'), CARGO_INCREMENTAL='0',
               CARGO_ENCODED_RUSTFLAGS='\x1f'.join(flags), RETOC_SKIP_KAWAII_BINDING_BUILD='1',
               CC=str(llvm / 'x86_64-w64-mingw32-gcc.exe'), CXX=str(llvm / 'x86_64-w64-mingw32-g++.exe'),
               AR=str(llvm / 'llvm-ar.exe'), CARGO_TARGET_X86_64_PC_WINDOWS_GNU_LINKER=str(llvm / 'x86_64-w64-mingw32-gcc.exe'),
               CFLAGS=f'-ffile-prefix-map={work}=/atelier-shader -g0',
               CXXFLAGS=f'-ffile-prefix-map={work}=/atelier-shader -g0', SOURCE_DATE_EPOCH='0')
    return env, ['--remap-path-prefix=<private-build>=/atelier-shader', *flags[1:]]


def checked_run(arguments, project, env, log):
    flags = dict(creationflags=subprocess.CREATE_NO_WINDOW) if os.name == 'nt' else {}
    result = subprocess.run(list(map(str, arguments)), cwd=project, env=env, capture_output=True,
                            text=True, errors='replace', timeout=1800, **flags)
    log.write(result.stdout + result.stderr)
    log.flush()
    if result.returncode:
        raise RuntimeError(f'Shader build step failed ({Path(arguments[0]).name}); see the isolated build log')
    return result.stdout.strip()


@contextmanager
def build_workspace(parent):
    parent = Path(parent).resolve()
    work = Path(tempfile.mkdtemp(prefix='.atelier-shader-build-', dir=parent))
    try:
        yield work
    finally:
        # Cargo can create paths longer than MAX_PATH. Use the extended path only
        # for Python cleanup, after checking the absolute target we created.
        resolved = work.resolve()
        if resolved.parent != parent or not resolved.name.startswith('.atelier-shader-build-'):
            raise ValueError('Refusing to remove a shader workspace outside its intended parent')
        target = str(resolved)
        if os.name == 'nt' and not target.startswith('\\\\?\\'):
            target = '\\\\?\\' + target
        def remove_readonly(function, path, error):
            if not isinstance(error, PermissionError):
                raise error
            os.chmod(path, stat.S_IWRITE)
            function(path)
        for attempt in range(3):
            try:
                shutil.rmtree(target, onexc=remove_readonly)
                break
            except FileNotFoundError:
                break
            except OSError:
                if attempt == 2:
                    raise
                time.sleep(0.5)


def build(tools, output, cache, log_path):
    if os.name != 'nt':
        raise ValueError('The portable pinned compiler recipe currently supports Windows x64')
    output = Path(output).resolve()
    if output.exists():
        raise ValueError('Output exists; choose a fresh shader-tool directory')
    lock_bytes = LOCK.read_bytes()
    lock = load_shader_lock(lock_bytes)
    lock_sha256 = hashlib.sha256(lock_bytes).hexdigest()
    native = Path(tools).resolve() / 'shaders/oo2core_9_win64.dll'
    verify_files(native.parent, lock['native_files'])
    output.parent.mkdir(parents=True, exist_ok=True)
    log_path = Path(log_path).resolve()
    if log_path.is_relative_to(output) or Path(cache).resolve().is_relative_to(output):
        raise ValueError('Keep the build log and archive cache outside the fresh output')
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with build_workspace(output.parent) as work, log_path.open('w', encoding='utf-8') as log:
        project = prepare_source(work, lock, Path(cache), native)
        rust, llvm = prepare_compiler(work, lock, Path(cache))
        env, flags = compiler_environment(work, rust, llvm)
        rust_version = checked_run([rust / 'rustc.exe', '--version', '--verbose'], project, env, log)
        if 'commit-hash: ' + lock['compiler']['rust_commit'] not in rust_version:
            raise ValueError('Unexpected Rust compiler revision')
        cargo_version = checked_run([rust / 'cargo.exe', '--version'], project, env, log)
        cc_version = checked_run([llvm / 'x86_64-w64-mingw32-gcc.exe', '--version'], project, env, log).splitlines()[0]
        linker_version = checked_run([llvm / 'ld.lld.exe', '--version'], project, env, log)
        cargo = rust / 'cargo.exe'
        print('Fetching checksum-locked Rust dependencies into a private cache...', flush=True)
        checked_run([cargo, 'fetch', '--locked'], project, env, log)
        print('Compiling the shader fork with pinned Rust and native compilers...', flush=True)
        checked_run([cargo, 'build', '--frozen', '--release', '-p', 'atelier-shader', '-j', '3'], project, env, log)
        print('Running native shader-format and command safety tests...', flush=True)
        checked_run([cargo, 'test', '--frozen', '--release', '-p', 'retoc', '--lib', 'atelier_tests', '-j', '3'], project, env, log)
        checked_run([cargo, 'test', '--frozen', '--release', '-p', 'atelier-shader', '-j', '3'], project, env, log)
        stage = work / 'publish'
        stage.mkdir()
        shutil.copyfile(work / 'target/release/retoc-rivals-cli.exe', stage / 'retoc-rivals-cli.exe')
        shutil.copyfile(project / 'upstream/oo2core_9_win64.dll', stage / native.name)
        shutil.copytree(project / 'licenses', stage / 'licenses')
        record = dict(schema=1, tool='AtelierShader', target='x86_64-pc-windows-gnu',
                      build_lock_sha256=lock_sha256, sources=lock['sources'], recipe=lock['recipe'],
                      upstream=lock['upstream'], compiler=lock['compiler'], rustc=rust_version,
                      cargo=cargo_version, cc=cc_version, linker=linker_version, rustflags=flags,
                      native_flags=['-ffile-prefix-map=<private-build>=/atelier-shader', '-g0'],
                      cargo_mode='fetch --locked, then build/test --frozen; fresh private CARGO_HOME',
                      git_dependencies=lock['git_dependencies'], native_files=lock['native_files'],
                      outputs={p.relative_to(stage).as_posix(): digest(p) for p in sorted(stage.rglob('*')) if p.is_file()})
        (stage / 'build-inputs.json').write_text(json.dumps(record, indent=2) + '\n', encoding='utf-8', newline='\n')
        if not stage.resolve().is_relative_to(work.resolve()) or output.exists():
            raise ValueError('Shader publication target changed during the build')
        stage.rename(output)
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tools', type=Path, required=True, help='Verified seed Tools with the pinned Oodle DLL')
    parser.add_argument('--output', type=Path, required=True, help='Fresh directory; no existing install is overwritten')
    parser.add_argument('--cache', type=Path, required=True, help='Download archive cache, verified before each use')
    parser.add_argument('--log', type=Path, required=True, help='Build log outside the release payload')
    args = parser.parse_args()
    record = build(args.tools, args.output, args.cache, args.log)
    print('Built source-verified shader tool: ' + record['outputs']['retoc-rivals-cli.exe'])


if __name__ == '__main__':
    main()

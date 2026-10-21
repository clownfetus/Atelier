"""Read real shaders, round-trip DXIL and repack only into a new report directory.

Never installs a mod. Requires Windows, configured game files and the pinned tools.
All extracted shader data stays outside source/release artifacts.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import struct
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
sys.path.insert(0, str(ROOT))
from native_inputs import digest, load_lock, verify_shaders


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tools', type=Path, required=True)
    parser.add_argument('--paks', type=Path, required=True)
    parser.add_argument('--report-dir', type=Path, required=True)
    parser.add_argument('--validator', type=Path, help='Optional pinned DXV executable for independent DXIL validation')
    parser.add_argument('--reuse-index-from', type=Path,
                        help='Reuse a successful probe report with the exact same tool and game-container stamps')
    args = parser.parse_args()
    tools, paks, report = args.tools.resolve(strict=True), args.paks.resolve(strict=True), args.report_dir.resolve()
    if report == ROOT or report.is_relative_to(ROOT) or report == paks or report.is_relative_to(paks):
        raise SystemExit('Use a fresh report directory outside the checkout and game folders.')
    record = dict(tool=verify_shaders(tools), checks=[], commands=[])
    containers = [paks / name for name in ('pakchunkShaderAsset-Windows.utoc', 'global.utoc')]
    if any(not path.is_file() for path in containers):
        raise SystemExit('Both original shader containers are required.')
    report.mkdir(parents=True, exist_ok=False)
    retoc, dxc = tools / 'shaders/retoc-rivals-cli.exe', tools / 'shaders/dxc.exe'
    source_files = containers + [path.with_suffix('.ucas') for path in containers]
    def stamps():
        return {p.name: dict(size=p.stat().st_size, mtime_ns=p.stat().st_mtime_ns,
                            sha256=digest(p) if p.suffix == '.utoc' else None) for p in source_files}
    before = stamps()

    def run(executable, command, *arguments, expect_success=True):
        started = time.monotonic()
        result = subprocess.run([str(executable), command, *map(str, arguments)], cwd=executable.parent,
            capture_output=True, text=True, errors='replace', timeout=600,
            creationflags=subprocess.CREATE_NO_WINDOW)
        # Never retain raw help or embedded defaults, including on a native failure.
        log = re.sub(r'(?i)(?:0x)?[a-f0-9]{64}', '<redacted-key-or-hash>', result.stdout + result.stderr)
        label = Path(command).name.lstrip('-')
        (report / f'{len(record["commands"]):02}-{label}.log').write_text(log, encoding='utf-8')
        record['commands'].append(dict(command=command, returncode=result.returncode,
                                       seconds=round(time.monotonic() - started, 3)))
        if expect_success != (result.returncode == 0):
            raise RuntimeError(f'{command}: unexpected exit status {result.returncode}; see isolated native log')
        return result.stdout

    def entries(path):
        with path.open(encoding='utf-8') as stream:
            for line in stream:
                line = line.strip().rstrip(',')
                if line.startswith('{"index"'):
                    yield json.loads(line)

    def extract(inputs, library, index, target):
        run(retoc, 'extract-shader', *inputs, '-l', library, '-s', index, '-o', target)
        return target.read_bytes()

    def dxbc(data):
        offset = data.find(b'DXBC')
        if offset < 0 or offset + 32 > len(data):
            raise ValueError('Extracted shader has no bounded DXBC container')
        size = struct.unpack_from('<I', data, offset + 24)[0]
        if size < 32 or offset + size > len(data):
            raise ValueError('Extracted DXBC size is invalid')
        return offset, size

    try:
        print('Verifying the previous real shader index...' if args.reuse_index_from
              else 'Building the real shader index in an isolated folder...', flush=True)
        if args.reuse_index_from:
            previous = args.reuse_index_from.resolve(strict=True)
            verified = json.loads((previous / 'results.json').read_text(encoding='utf-8'))
            assert verified.get('ok') and verified['tool']['files'] == record['tool']['files']
            assert verified['game_containers'] == before, 'Original containers changed since the previous index probe'
            index = previous / 'index'
            record['index_reused_from'] = str(previous)
        else:
            index = report / 'index'
            run(retoc, 'dump-shaders', *containers, '-o', index, '--index-only')
        libraries = {}
        for path in index.glob('*/index.json'):
            count = sum(1 for _ in entries(path))
            if count:
                libraries[path.parent.name] = count
        assert libraries, 'No shader index entries produced'
        record['libraries'] = libraries
        record['index_sha256'] = {path.parent.name: digest(path) for path in index.glob('*/index.json')}
        if args.reuse_index_from:
            assert libraries == verified['libraries'], 'Reused index totals changed'
            if verified.get('index_sha256'):
                assert record['index_sha256'] == verified['index_sha256'], 'Reused index contents changed'
        record['checks'].append(f'Original containers indexed: {sum(libraries.values())} shaders in {len(libraries)} libraries')
        library = min(libraries, key=libraries.get)
        choices = []
        for entry in entries(index / library / 'index.json'):
            choices.append(entry)
            if len(choices) > 21:
                break
        chosen = choices[min(20, len(choices) - 1)]
        untouched = next(item for item in choices if item['index'] != chosen['index'])
        record['selection'] = dict(library=library, index=chosen['index'], untouched_index=untouched['index'])
        original = extract(containers, library, chosen['index'], report / 'original.bin')
        offset, size = dxbc(original)
        (report / 'original.dxbc').write_bytes(original[offset:offset + size])
        disassembly = run(dxc, '-dumpbin', report / 'original.dxbc')
        assert 'target triple' in disassembly or 'define ' in disassembly, 'DXC produced no LLVM IR'
        record['checks'].append('One real shader extracted and disassembled by the pinned DXC')
        os.environ['MR_TOOLS'] = str(tools)
        from atelier.handlers import dxc_ir
        ir = dxc_ir.disassemble(original[offset:offset + size])
        rebuilt, signed = dxc_ir.assemble(ir)
        assert signed, 'Pinned DXIL validator did not sign the rebuilt shader'
        modified = original[:offset] + rebuilt + original[offset + size:]
        (report / 'reassembled.dxbc').write_bytes(rebuilt)
        (report / 'reassembled.bin').write_bytes(modified)
        run(dxc, '-dumpbin', report / 'reassembled.dxbc')
        if args.validator:
            validator = args.validator.resolve(strict=True)
            expected = load_lock()['shader']['test_validator']['sha256']
            assert digest(validator) == expected, 'Independent DXIL validator hash differs from the pin'
            validation = run(validator, str(report / 'reassembled.dxbc'))
            record['validator'] = dict(sha256=expected, success='Validation succeeded' in validation)
            assert record['validator']['success'], 'DXV did not confirm the shader signature'
        record['dxil'] = dict(original_sha256=hashlib.sha256(original[offset:offset + size]).hexdigest(),
            reassembled_sha256=hashlib.sha256(rebuilt).hexdigest(), signed=signed,
            bytes_changed=rebuilt != original[offset:offset + size])
        record['checks'].append('Application DXC COM path disassembles, reassembles and signs the real shader IR')
        if args.validator:
            record['checks'].append('Independent Microsoft DXV validation succeeds for the reassembled shader')
        print('Repacking and reading back the selected shader...', flush=True)
        stage, mod = report / 'stage', report / 'mod'
        run(retoc, 'patch-shader', *containers, '-l', library, '-s', chosen['index'],
            '-b', report / 'reassembled.bin', '-o', stage)
        run(retoc, 'pack', stage, '-o', mod)
        triples = list(mod.glob('*.utoc'))
        assert len(triples) == 1, 'Expected one isolated mod container'
        assert triples[0].with_suffix('.pak').is_file() and triples[0].with_suffix('.ucas').is_file()
        readback = extract(triples, library, chosen['index'], report / 'readback.bin')
        assert readback == modified, 'Repacked shader does not match the assembled blob'
        record['checks'].append('patch-shader and pack preserve the assembled shader exactly on mod-only readback')
        pristine = extract(containers, library, untouched['index'], report / 'untouched-original.bin')
        retained = extract(triples, library, untouched['index'], report / 'untouched-readback.bin')
        assert pristine == retained, 'An unedited shader changed during repacking'
        record['checks'].append('An unedited shader stays byte-identical after the library rebuild')
        run(retoc, 'extract-shader', *containers, '-l', library, '-s', '4294967295',
            '-o', report / 'invalid-index.bin', expect_success=False)
        assert not (report / 'invalid-index.bin').exists()
        record['checks'].append('An out-of-range shader index fails without publishing an output')
        record['mod_files'] = {path.name: digest(path) for path in mod.iterdir() if path.is_file()}
        assert stamps() == before, 'Original game container stamps changed'
        record['checks'].append('Original game containers remain unchanged; no mod was installed')
        record['ok'] = True
    except Exception as error:
        record['ok'] = False
        record['error'] = str(error)
        raise
    finally:
        record['game_containers'] = before
        (report / 'results.json').write_text(json.dumps(record, indent=2) + '\n', encoding='utf-8')
    for check in record['checks']:
        print('PASS ' + check)


if __name__ == '__main__':
    main()

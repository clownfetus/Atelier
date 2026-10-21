"""Exercise real Shader Studio handlers using isolated data and source-built tools.

Writes shader exports only under the new report folder. Never installs a game mod.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'scripts'))
from native_inputs import digest, verify_shaders


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tools', type=Path, required=True)
    parser.add_argument('--paks', type=Path, required=True)
    parser.add_argument('--key-file', type=Path, required=True)
    parser.add_argument('--report-dir', type=Path, required=True)
    args = parser.parse_args()
    tools, paks, report = args.tools.resolve(strict=True), args.paks.resolve(strict=True), args.report_dir.resolve()
    if any(report == base or report.is_relative_to(base) for base in [ROOT, paks, tools]):
        parser.error('Use a fresh external report directory outside the checkout, tools and game files')
    record = dict(tool=verify_shaders(tools), checks=[], timings={}, in_game_verified=False)
    report.mkdir(parents=True, exist_ok=False)
    data, mods = report / 'data', report / 'test-mods'
    data.mkdir()
    (data / 'mr_config.json').write_text(json.dumps(dict(paks=str(paks), tools=str(tools), mods_folder=str(mods))), encoding='utf-8')
    os.environ['ATELIER_DATA_DIR'] = str(data)
    from atelier import config as C
    C.AES_KEY_FILE = str(args.key_file.resolve(strict=True))
    from atelier.handlers import shaders as S
    assert Path(S.CACHE).resolve().is_relative_to(data) and Path(S.RETOC).resolve().is_relative_to(tools)
    assert Path(C.get_mods_folder()).resolve() == mods
    library = 'ShaderArchive-Global-PCD3D_SM6-PCD3D_SM6'
    try:
        started = time.monotonic()
        S._build_index()
        record['timings']['app_full_index_seconds'] = round(time.monotonic() - started, 3)
        status = S.status()
        assert status['db_ready'] and status['build']['done'] and not status['build']['error'], status
        counts = {item['name']: item['total'] for item in status['libraries']}
        assert sum(counts.values()) > 1_000_000
        record['libraries'] = counts
        record['checks'].append('Shader Studio builds its full SQLite index with the reconstructed tool')
        started = time.monotonic()
        disassembly = S.disasm(library, 20)
        assert disassembly['ok'] and disassembly['disasm'] and disassembly['properties']['dxbc_size'] > 0
        constants = S.edit_constants(library, 20)
        assert constants['ok'], constants
        ir = S.disassemble_ir(library, 20)
        assert ir['ok'] and 'target triple' in ir['ir'], ir.get('error')
        record['timings']['browse_and_disassemble_seconds'] = round(time.monotonic() - started, 3)
        record['checks'].append('Shader Studio disassembly, constant inspection and editable LLVM IR work with private key transport')
        started = time.monotonic()
        edited_ir = ir['ir'].replace('float 1.000000e+00', 'float 5.000000e-01', 1)
        assert edited_ir != ir['ir']
        built = S.build_shader_mod_ir(library, 20, edited_ir, 'AtelierShaderAppProbe')
        assert built['ok'] and built['signed'], built
        record['timings']['app_signed_export_seconds'] = round(time.monotonic() - started, 3)
        assert Path(built['mod_dir']).resolve() == mods
        assert {p.suffix for p in mods.iterdir()} == {'.pak', '.ucas', '.utoc'}
        # Verify the handler's exported container using only that mod.
        extracted = report / 'app-export.bin'
        result = subprocess.run([S.RETOC, 'extract-shader', str(next(mods.glob('*.utoc'))), '-l', library,
                                 '-s', '20', '-o', str(extracted)], env=C.retoc_env(), capture_output=True,
                                text=True, timeout=120, creationflags=subprocess.CREATE_NO_WINDOW)
        assert result.returncode == 0 and extracted.stat().st_size > 0, 'Application shader export cannot be read back'
        position, size = S._dxbc(extracted.read_bytes())
        assert position is not None and size > 32
        from atelier.handlers import dxc_ir
        expected, signed = dxc_ir.assemble(edited_ir.encode('utf-8'))
        assert signed and extracted.read_bytes()[position:position + size] == expected
        record['exported_files'] = {p.name: digest(p) for p in mods.iterdir()}
        record['checks'].append('The app assembles, signs and exports a complete shader mod with successful mod-only readback')
        record['checks'].append('All shader caches and exports stay in the isolated report folder')
        record['ok'] = True
    except BaseException as error:
        record.update(ok=False, error=str(error))
        raise
    finally:
        (report / 'results.json').write_text(json.dumps(record, indent=2) + '\n', encoding='utf-8')
    for check in record['checks']:
        print('PASS ' + check)


if __name__ == '__main__':
    main()

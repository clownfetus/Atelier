"""Run independent, isolated regression suites concurrently and keep one receipt."""
from concurrent.futures import ThreadPoolExecutor
import importlib.metadata
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def run_suite(suite):
    folder = ROOT / 'reports/backend-suites' / suite.stem
    process = subprocess.run([sys.executable, str(ROOT / 'tests/run_checks.py'), '--suite', suite.name,
                              '--report-dir', str(folder)], cwd=ROOT, capture_output=True, text=True,
                             encoding='utf-8', errors='replace')
    receipt = folder / 'results.json'
    if not receipt.is_file():
        raise RuntimeError(suite.name + ' produced no report:\n' + process.stdout[-3000:] + process.stderr[-3000:])
    data = json.loads(receipt.read_bytes())
    print(('FAIL ' if process.returncode else 'PASS ') + suite.name, flush=True)
    output = ROOT / 'reports/backend'
    output.mkdir(parents=True, exist_ok=True)
    log = folder / (suite.name + '.log')
    if log.is_file():
        shutil.copy2(log, output / log.name)
    if process.returncode:
        print(process.stdout[-10000:] + process.stderr[-4000:], flush=True)
    return data['results'][0]


def main():
    suites = sorted((ROOT / 'tests').glob('test_*.py'))
    with ThreadPoolExecutor(max_workers=min(4, os.cpu_count() or 1)) as pool:
        results = list(pool.map(run_suite, suites))
    output = ROOT / 'reports/backend'
    output.mkdir(parents=True, exist_ok=True)
    data = {'python': sys.version, 'platform': sys.platform, 'results': results,
            'packages': {dist.metadata['Name']: dist.version for dist in importlib.metadata.distributions()}}
    (output / 'results.json').write_text(json.dumps(data, indent=2), encoding='utf-8')
    return int(any(row['exit_code'] for row in results))


if __name__ == '__main__':
    raise SystemExit(main())

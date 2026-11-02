"""Run independent focused UI workflows concurrently, with mandatory save/update coverage."""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import subprocess
import sys

from release_check_scope import UI_SUITES, SHARED_UI_SUITES

ROOT = Path(__file__).resolve().parents[1]


def suites_for(context):
    if context['browser_mode'] not in {'updates', 'ui'}:
        # The full legacy suite does not enter the embedded Projects workspace.
        return [('full', []), ('workspace', ['--workspace-only'])]
    names = {'updates', 'workspace'}
    if context['browser_mode'] == 'ui':
        for name in context['changed']:
            names.update(UI_SUITES.get(name, SHARED_UI_SUITES.get(name, ())))
    return [(name, [f'--{name}-only']) for name in sorted(names)]


def run_suite(suite):
    name, flags = suite
    folder = ROOT / 'reports/browser' / name
    folder.mkdir(parents=True, exist_ok=True)
    # An interrupted/retried run must never consume an older passing receipt.
    (folder / 'results.json').unlink(missing_ok=True)
    process = subprocess.run([sys.executable, str(ROOT / 'tests/browser_smoke.py'), '--report-dir', str(folder), *flags],
                             cwd=ROOT, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=1200)
    (folder / 'run.log').write_text(process.stdout + process.stderr, encoding='utf-8')
    if process.returncode:
        raise RuntimeError(f'Browser gate failed: {name}\n' + process.stdout[-4000:] + process.stderr[-4000:])
    result = json.loads((folder / 'results.json').read_bytes())
    if not result.get('checks') or result.get('page_errors'):
        raise ValueError('Browser gate failed: ' + name)
    print('PASS browser ' + name, flush=True)
    return result


def main():
    context = json.loads((ROOT / '_release/context.json').read_bytes())
    suites = suites_for(context)
    output = ROOT / 'reports/browser/results.json'
    output.unlink(missing_ok=True)
    # Full coverage contains performance budgets that need an idle runner. The
    # focused workflows own separate servers, browser profiles and project data.
    workers = 1 if context['browser_mode'] == 'full' else 2
    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(run_suite, suites))
    (ROOT / 'reports/browser/results.json').write_text(json.dumps({
        'checks': [check for result in results for check in result['checks']],
        'page_errors': [error for result in results for error in result.get('page_errors', [])],
        'suites': [name for name, _ in suites],
        'selection': context['browser_mode'], 'source_commit': context['source_commit']}, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()

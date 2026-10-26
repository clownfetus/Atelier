"""Run the mandatory browser checks plus the coverage selected from source changes."""
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def main():
    context = json.loads((ROOT / '_release/context.json').read_bytes())
    suites = [('full', [])] if context['browser_mode'] == 'full' else [('updates', ['--updates-only'])]
    if context['browser_mode'] != 'full' and 'tests/model_studio_export_browser_checks.py' in context['changed']:
        suites.append(('model-export', ['--model-export-only']))
    checks, errors = [], []
    for name, flags in suites:
        folder = ROOT / 'reports/browser' / name
        subprocess.run([sys.executable, str(ROOT / 'tests/browser_smoke.py'), '--report-dir', str(folder), *flags], cwd=ROOT, check=True)
        result = json.loads((folder / 'results.json').read_bytes())
        if not result.get('checks') or result.get('page_errors'):
            raise ValueError('Browser gate failed: ' + name)
        checks.extend(result['checks'])
        errors.extend(result['page_errors'])
    (ROOT / 'reports/browser/results.json').write_text(json.dumps({
        'checks': checks, 'page_errors': errors, 'suites': [name for name, _ in suites],
        'selection': context['browser_mode'], 'source_commit': context['source_commit']}, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()

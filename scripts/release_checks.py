"""Run independent, isolated regression suites concurrently and keep one receipt."""
from concurrent.futures import ThreadPoolExecutor
import importlib.metadata
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

from release_automation import REPOSITORY, api, trusted_checks

ROOT = Path(__file__).resolve().parents[1]
# Release preparation changes only version/changelog. Recheck the consumers of
# that metadata even when the other Windows suites already passed on this commit.
METADATA_SUITES = {'test_changelog.py', 'test_packaging.py', 'test_release_bundle.py',
                   'test_release_pipeline.py', 'test_updates.py', 'test_frontend_cache.py'}


def validate_reuse(report, run, commit, suites, packages):
    if not isinstance(report, dict) or not isinstance(report.get('python'), str):
        return False
    rows = report.get('results', [])
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        return False
    return (trusted_checks(run, commit) and report.get('source_commit') == commit
            and str(report.get('run_id')) == str(run['id'])
            and report.get('run_attempt') == str(run.get('run_attempt', 1))
            and report.get('platform') == sys.platform == 'win32'
            and report.get('python', '').split()[:1] == sys.version.split()[:1]
            and report.get('packages') == packages
            and len(rows) == len(suites) and {row.get('suite') for row in rows} == set(suites)
            and all(row.get('exit_code') == 0 for row in rows))


def reuse_ci(suites, packages, commit):
    context_file = ROOT / '_release/context.json'
    if sys.platform != 'win32' or not context_file.is_file():
        return [], ''
    context = json.loads(context_file.read_bytes())
    run_id = context.get('checks_run', '')
    if not str(run_id).isdigit() or context.get('source_commit') != commit:
        return [], ''
    try:
        run = api(f'actions/runs/{run_id}')
        if not trusted_checks(run, commit):
            raise ValueError('CI run is not a successful main push for this commit.')
        with tempfile.TemporaryDirectory(prefix='atelier-ci-reuse-') as temporary:
            subprocess.run(['gh', 'run', 'download', str(run_id), '--repo', REPOSITORY,
                            '--name', 'backend-report', '--dir', temporary], check=True, capture_output=True)
            folder = Path(temporary)
            report = json.loads((folder / 'results.json').read_bytes())
            if not validate_reuse(report, run, commit, [suite.name for suite in suites], packages):
                raise ValueError('CI receipt, suite list or Python environment differs.')
            output = ROOT / 'reports/backend'
            output.mkdir(parents=True, exist_ok=True)
            for log in folder.glob('*.log'):
                shutil.copy2(log, output / log.name)
            print(f'Reusing verified Windows backend results from Checks run {run_id}.', flush=True)
            return [row | {'reused_from_run': str(run_id)} for row in report['results']
                    if row['suite'] not in METADATA_SUITES], str(run_id)
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
        # Missing/expired artifacts and older receipts simply take the full path.
        print(f'CI reuse unavailable; running all backend suites: {error}', flush=True)
        return [], ''


def run_suite(suite):
    folder = ROOT / 'reports/backend-suites' / suite.stem
    folder.mkdir(parents=True, exist_ok=True)
    receipt = folder / 'results.json'
    receipt.unlink(missing_ok=True)
    process = subprocess.run([sys.executable, str(ROOT / 'tests/run_checks.py'), '--suite', suite.name,
                              '--report-dir', str(folder)], cwd=ROOT, capture_output=True, text=True,
                             encoding='utf-8', errors='replace')
    if not receipt.is_file():
        raise RuntimeError(suite.name + ' produced no report:\n' + process.stdout[-3000:] + process.stderr[-3000:])
    data = json.loads(receipt.read_bytes())
    rows = data.get('results', [])
    if len(rows) != 1 or rows[0].get('suite') != suite.name or (process.returncode and not rows[0].get('exit_code')):
        raise RuntimeError('Regression process and receipt disagree: ' + suite.name)
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
    packages = {dist.metadata['Name']: dist.version for dist in importlib.metadata.distributions()}
    commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    reused, reused_run = reuse_ci(suites, packages, commit)
    completed = {row['suite'] for row in reused}
    suites = [suite for suite in suites if suite.name not in completed]
    exclusive = [suite for suite in suites if suite.name == 'test_search.py']
    parallel = [suite for suite in suites if suite not in exclusive]
    # Hosted Windows has fewer cores and aggressively scans each disposable tree.
    # Four simultaneous tree copies can stall short Node/browser subprocesses.
    workers = min(2 if os.name == 'nt' else 4, os.cpu_count() or 1)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = reused + list(pool.map(run_suite, parallel))
    # Performance budgets describe an idle runner, not contention from unrelated
    # test processes. Keep the original thresholds and run these after the pool.
    results.extend(run_suite(suite) for suite in exclusive)
    output = ROOT / 'reports/backend'
    output.mkdir(parents=True, exist_ok=True)
    data = {'python': sys.version, 'platform': sys.platform, 'results': results,
            'packages': packages, 'source_commit': commit, 'run_id': os.environ.get('GITHUB_RUN_ID', ''),
            'run_attempt': os.environ.get('GITHUB_RUN_ATTEMPT', '1'), 'reused_checks_run': reused_run}
    (output / 'results.json').write_text(json.dumps(data, indent=2), encoding='utf-8')
    return int(any(row['exit_code'] for row in results))


if __name__ == '__main__':
    raise SystemExit(main())

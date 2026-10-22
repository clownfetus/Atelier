"""Run regression scripts in disposable copies, never against the user's projects.

Usage: python tests/run_checks.py --report-dir _logs/checks
Browser helpers may be selected with --suite (for example surfaces_checks.py).
Each suite gets its own source tree and application data. Native-tool/game tests
may report SKIP; those are not a substitute for manual compatibility checks.
"""
import argparse
import importlib.metadata
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
BROWSER_SUITES = {
    "assembly_browser_checks.py": "--assembly-only",
    "shared_identity_checks.py": "--shared-identity-only",
    "texture_workflow_checks.py": "--texture-workflows-only",
    "browser_smoke.py": None,
    "material_bulk_browser_checks.py": "--material-bulk-only",
    "motionboard_browser_checks.py": "--motionboard-only",
    "surfaces_checks.py": "--surfaces-only",
    "polish_checks.py": "--polish-only",
    "appearance_checks.py": "--appearance-only",
    "review_followup_checks.py": "--review-followups-only",
    "viewer_followup_checks.py": "--viewer-followups-only",
    "library_pins_checks.py": "--library-only",
    "inks_dial_checks.py": "--inks-dial-only",
    "showcase_checks.py": "--showcase-only",
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report-dir", type=Path)
    parser.add_argument("--suite", action="append", help="Test filename, repeatable")
    args = parser.parse_args()
    suites = args.suite or [p.name for p in sorted((ROOT / "tests").glob("test_*.py"))]
    report = args.report_dir.resolve() if args.report_dir else None
    if report:
        report.mkdir(parents=True, exist_ok=True)
    results = []
    for suite in suites:
        if Path(suite).name != suite or not (ROOT / "tests" / suite).is_file():
            parser.error(f"Unknown test script: {suite}")
        with tempfile.TemporaryDirectory(prefix="atelier-check-") as scratch:
            checkout = Path(scratch)
            for name in ("atelier", "gui", "tests", "scripts"):
                shutil.copytree(ROOT / name, checkout / name,
                                ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
            shutil.copytree(ROOT / "tools-src", checkout / "tools-src",
                            ignore=shutil.ignore_patterns("bin", "obj", "__pycache__", "*.pyc"))
            for name in ("io_lib.py", "main.py", "version", "CHANGELOG.md", "BUILD.bat", "Atelier.iss", ".gitignore", "icon.ico", "icon.png"):
                shutil.copy2(ROOT / name, checkout / name)
            if suite in ("browser_smoke.py", "surfaces_checks.py"):
                shutil.copytree(ROOT / "docs" / "review", checkout / "docs" / "review")
            env = dict(os.environ, PYTHONUTF8="1", PYTHONDONTWRITEBYTECODE="1")
            env['ATELIER_CHECK_SOURCE_ROOT'] = str(ROOT)
            env.pop("MR_TOOLS", None)
            env.pop("ATELIER_DATA_DIR", None)
            started = time.monotonic()
            command = [sys.executable, "-B", str(checkout / "tests" / suite)]
            if suite in BROWSER_SUITES:
                browser_report = report / suite.removesuffix(".py") if report else checkout / "report"
                command = [sys.executable, "-B", str(checkout / "tests" / "browser_smoke.py")]
                if BROWSER_SUITES[suite]:
                    command.append(BROWSER_SUITES[suite])
                command.extend(["--report-dir", str(browser_report)])
                if suite == 'viewer_followup_checks.py':
                    command += ['--device-scale-factor', '2']
            timeout = 900 if suite == "browser_smoke.py" else 240
            try:
                proc = subprocess.run(command,
                                      cwd=checkout, env=env, capture_output=True,
                                      text=True, encoding="utf-8", errors="replace", timeout=timeout)
                output, code = proc.stdout + proc.stderr, proc.returncode
            except subprocess.TimeoutExpired as exc:
                def captured(value):
                    return value.decode('utf-8', errors='replace') if isinstance(value, bytes) else (value or '')
                output = captured(exc.stdout) + captured(exc.stderr) + f"\nSuite exceeded {timeout} seconds: {exc}"
                code = 124
            elapsed = round(time.monotonic() - started, 2)
            print(f"{'PASS' if code == 0 else 'FAIL'} {suite} ({elapsed}s)", flush=True)
            summaries = [line for line in output.splitlines()
                         if ' passed,' in line or 'SKIP ' in line or 'Ran ' in line or line.startswith('PASS ')]
            for line in summaries:
                print(f"  {line}", flush=True)
            if code:
                print(output[-12000:], flush=True)
            if report:
                (report / (suite + ".log")).write_text(output, encoding="utf-8")
            results.append(dict(suite=suite, exit_code=code, seconds=elapsed, summary=summaries))
    if report:
        packages = {d.metadata['Name']: d.version for d in importlib.metadata.distributions()}
        (report / "results.json").write_text(json.dumps({
            "python": sys.version, "platform": sys.platform,
            "packages": packages, "results": results,
        }, indent=2), encoding="utf-8")
    return int(any(r['exit_code'] for r in results))


if __name__ == "__main__":
    raise SystemExit(main())

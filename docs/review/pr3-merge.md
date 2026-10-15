# PR #3 upstream integration — 15 October 2026

Merged upstream main through `d592133` into the existing PR branch, preserving
the jobs, bulk editing, export-base recovery and appearance commits. Conflicts
were resolved in `BUILD.bat`, `TRIAGE.md`, the texture export resolver,
`scripts/stage_tools.py` and the isolated test runner.

The Windows and Linux builds now use upstream's explicit tool manifest and
distribution audit. Required files must be nonempty before and after copying;
the source tools and any existing/overlapping destination are preserved. A copy
failure cleans only the new staging directory. The previous Windows helper API
and positional CLI remain available through the same manifest-based copier.
`BUILD.bat` uses the platform CLI and still exits before Inno Setup on failure.

Upstream's installer user-data protections, unused-package exclusions, Oodle
lookup, mod-loader index exclusion, settings-folder recovery and retrieval
timestamp gate are retained. Texture injection keeps the current-source cache
resolver from both branches. The triage board retains the new upstream reports
and this branch's verified bulk-editor status.

## Validation of the merged tree

| Check | Result | Local report |
| --- | --- | --- |
| Complete Python runner, 13 suites | 261 passed, 0 failed; 2 existing native-only skips | `_work/pr3-merge/backend/results.json` |
| Chromium/Bottle workflows | 89 groups passed; no page errors; real decoded GLB and repeated disposal included | `_work/pr3-merge/browser/results.json` |
| Actual Windows WebView2 | Fixture browser, six palette variants, native dropdown roles, logo, font and motion checks passed | `_work/pr3-merge/desktop/desktop-smoke.json` |
| Actual desktop job shutdown | Owned child cancelled; terminal job status persisted before exit | `_work/pr3-merge/shutdown/results.json` |
| Real material/texture native tools | Both export/readback checks passed; authored project JSON/PNG hashes preserved | `D:/AtelierDev/pr3-merge-20261015-native/results.json` |
| Static/runtime consistency | JavaScript syntax, Python syntax, DOM smoke, dependency consistency, Linux build-script syntax and whitespace checks passed | Command results |

The Python runner includes both upstream packaging invariants and this branch's
staging-failure tests, including the actual Windows batch failure gate in a
disposable fixture. The two skips are legacy native cases in that isolated-copy
runner; the separate native check above runs real tools. It verifies that stale
material imports are replaced by current vanilla structure while retaining saved
values/references, and that a deleted texture base is recovered without replacing
authored pixels. No live mods were installed.

No new executable, installer or Linux runtime build was produced. These checks
do not certify in-game appearance or reproduce individual historical reports.

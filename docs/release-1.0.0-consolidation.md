# 1.0.0 consolidation

The release candidate is `codex/release-1.0.0`, based on upstream
`54a3e6531981dd7455787e40c61ed50116746c28` plus all outstanding UI waves.
No working checkout was reset or removed. The original dirty checkout remains
on `feat/galacta-flag`; a byte-for-byte snapshot and binary patch were saved
outside the checkout under `D:/AtelierDev/release-1.0-audit`.

## Source coverage

| Source | Disposition |
| --- | --- |
| `origin/main` / `codex/review-followup-fixes` (`54a3e65`) | Included; retains project-scoped imports, export retry and mapping fixes. |
| `codex/native-jobs-bulk-editing`, fork equivalent | Included through upstream; native jobs, cancellation and bulk editing retained. |
| `codex/wave-2-trust` (`48082c5`) | Included; project trash/Undo, dialogs and guided setup. |
| `codex/wave-3-find` (`cd25ee3`) | Included; hero Home, Everywhere search and edit recency. |
| `codex/wave-4a-inks-dial` (`9d04fd5`) | Included; measured inks, motion dial and moment ownership. |
| `codex/wave-4b-surfaces` (`e93fad7`) | Included, including the local commit ahead of its remote; surfaces, captions, drops and update reminders. |
| `codex/wave-4c-showcase` (`25b455c`) | Its three unique commits (`eaa03e7`, `7d22b0f`, `25b455c`) applied; preceding rebased wave commits are patch-equivalent to included waves. |
| `claude/blissful-thompson-03aa46` (`bf3ad13`) | Included; motion proposals 1–5 and review. The untracked brief is retained as reference documentation. |
| `claude/jolly-lamport-a8bc3d` (`6aee64b`) | Included; raised charge for card thumbs. |
| `claude/elated-satoshi-34c6c4` (`9ca2d48`) | Applied; card-body charge and hover contrast. |
| `codex/motion-review-6-10` (`ec60599`) | Included; shared timing, deferred logo entrance and cancellation-safe loading/export/glyph behavior. |
| `feat/krackle-mark` (`dc1583f`) | Included via `8f1c6a8`; SVG, PNG, app icons and generator are the latest mark. |
| `codex/material-replacement` (`81579b4`) | Applied; full donor material replacement, default restoration, browser and native checks. |
| `feat/galacta-flag` (`2c17422`), `docs/galacta-test-kit` | Included; preserves the live external switch, geometry checks and persistent flag state. |
| `fix/workflow-wave-1`, `fix/wave-1-followups` (`76082bb`) | Final behavior already included via upstream/rebased work; startup does not await the release service and old Skip Version behavior is absent. |
| `codex/readme-refresh` | Included; documentation refreshed again for 1.0.0. |
| `krakle`, old phase 0/1 and phase 2 branches | Their reliability, material, catalogue and original UI work is represented in current upstream and later waves. Older implementations are superseded by the current interface. |
| `codex/linux-appimage-release` (`c4c61b4`) | Current Linux builder retained; native WebKit/accessibility/tool/preservation verification from `b165e8b` restored and generalized to 1.0.0. The old workflow that publishes directly to 0.3.5 is obsolete and is not re-enabled. |
| `fork/feature/windows-packaging` (`b731d97`) | Retained pinned build dependencies/compiler bootstrap and native runtime prerequisite checks. Its older standalone orchestration, installer test namespace and forced process exit are superseded by the current disposable-runner release pipeline, stable installer identity and graceful job shutdown. Exact portable/source hash checks and final artifact gating are included in the 1.0 workflow. |

## Uncommitted files

All nineteen product files in the original dirty checkout were accounted for
by the material replacement and Krackle mark changes. The browser smoke edits
are the same material test registration adapted to the newer test dispatcher.
The local `.codex/` configuration is machine-specific and is excluded from the
application and source distribution. Other registered worktrees were clean,
except for the reference motion brief above; the separate motion clone was clean.

## Integration repair

Material replacement's original native confirmation did not match the new themed
restoration confirmation. Both now use the shared dialog. Editor and project
identity are captured before awaiting confirmation, preventing a stale answer
from changing another editor. Browser coverage checks replacement, restoration,
cancellation, failure drafts, stale replies and a closed editor's confirmation.

## Release gates

The release bundle is produced only after full backend and browser checks,
frozen WebView2 checks, clean/running-upgrade/reinstall/uninstall checks on
Windows 2022 and 2025, and real Ubuntu 24.04 GTK/WebKit AppImage checks pass.
The upgrade baseline is the published **0.4.1**, pinned by size and SHA-256.
Encrypted repository inputs stage the complete Galacta template pair into each
application package; the pair is excluded from Git and the source archive.
`VERIFICATION.json` ties each final asset and test result to its exact build commit.

The prepared README, release-page description, real application screenshots and
Discord announcement are included. Publishing the stable 1.0.0 release is a
separate final operation; this candidate does not update installed copies.

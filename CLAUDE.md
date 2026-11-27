# Atelier · notes for Claude Code

Atelier is a desktop modding studio for Marvel Rivals: Python (Bottle +
pywebview) with a vanilla-JS frontend in `gui/`, Three.js for model previews,
and native tools for the asset pipeline. Run it from source with
`scripts/Start-AtelierDev.ps1` (browser mode on http://127.0.0.1:8767, or
`-Mode Desktop`); see `docs/DEVELOPMENT.md`.

## Working agreement

- Start new work on a task branch from the latest `main`, unless the task calls
  for a different base.
- Make one focused commit per task. Push, open pull requests or merge only when
  asked.
- Use British English in all UI copy.

## Motion system v2

The motion overhaul is complete. `docs/motion-v2/HANDOFF.md` records the rollout
and its design sign-offs. For changes to motion, use `docs/motion-v2/SPEC.md` as
the current reference.

- Preserve the ten invariants in SPEC §1. Ask Thiago if a change needs an
  exception or a new design decision.
- Keep the glyph's layer order fixed (tile, mesh, disc). The accessibility
  cross-fade in Off or reduced motion is its only fade.
- Show success only after a real `succeeded` result.
- Keep motion changes in the presentation layer. Asset processing, project
  formats, native tools, server routes and artwork rendering are outside that
  scope.

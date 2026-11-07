# Atelier · notes for Claude Code

Atelier is a desktop modding studio for Marvel Rivals: Python (Bottle +
pywebview) with a vanilla-JS frontend in `gui/`, Three.js for model previews,
and native tools for the asset pipeline. Run it from source with
`scripts/Start-AtelierDev.ps1` (browser mode on http://127.0.0.1:8767, or
`-Mode Desktop`); see `docs/DEVELOPMENT.md`.

## Current workstream: motion system v2

Replacing the Krackle animation system with the three-piece assembly glyph.
Start with `docs/motion-v2/HANDOFF.md` and follow its phases in order.

Rules that always apply:

- `docs/motion-v2/SPEC.md` §1 lists ten invariants. Never break them; if a task
  seems to need it, stop and ask Thiago.
- Fixed layer order (tile, mesh, disc). No fades or dissolves in the glyph,
  except the accessibility cross-fade in Off/reduced motion.
- Success comes only from a real `succeeded` result, never a timer.
- Presentation layer only. Don't touch the asset pipeline, project formats,
  native tools, server routes or artwork rendering.
- Stop at every ⏸ checkpoint in HANDOFF.md for Thiago's sign-off. Design calls
  are his.
- Work on branch `motion-v2`, one commit per task. Don't push or merge unless asked.
- British English in all UI copy.

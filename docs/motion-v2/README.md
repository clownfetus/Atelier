# Atelier motion v2: handoff pack for Claude Code

## Install

Unzip this pack into the root of your Atelier checkout. It only adds files,
and nothing existing is overwritten (checked against `main` at `eaf4ec8`):

```
CLAUDE.md                                  project notes Claude Code reads automatically
docs/brand/Atelier_Brand_Bible_v1.2.pdf    the visual identity
docs/motion-v2/
  README.md                                this file
  START_HERE.md                            the prompt to paste into Claude Code
  HANDOFF.md                               the brief: phases, tasks, gates, checkpoints
  SPEC.md                                  every number: colours, geometry, poses, timings, easing, tiers, sound
  DECISIONS.md                             the calls to settle before any code
  SURFACE_MAP.md                           every Krackle surface, where it's mounted, what it becomes
  assets/                                  the new mark, small mark and wordmarks (SVG) + their generator
  reference/motion-prototype.html          the approved, working prototype
  reference/PROTOTYPE_NOTES.md             how the prototype maps onto production modules
  reference/checks/                        planner and film-strip scripts (Python + Playwright)
```

If you already have a `CLAUDE.md` at the repo root by then, merge the two
rather than replacing yours.

## Run

Open Claude Code in the repo root and paste the prompt from
`docs/motion-v2/START_HERE.md`. It starts with Phase 0: walking you through the
decisions.

## Where you're needed

Claude Code will stop for you at six points: the decisions (P0.2), theme
screenshots (P1.7), the new at-rest pose and small sizes (P2.8), a full
walk-through recording (P3.14), your timing pass (P5.1), and approving the
release notes and version (P5.3).

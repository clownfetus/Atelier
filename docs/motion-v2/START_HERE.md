# Kickoff prompt

Paste this into Claude Code from the root of your Atelier checkout, once the
pack's files are in place.

---

We're replacing Atelier's Krackle animation system with a new motion identity.
Everything you need is in `docs/motion-v2/`.

1. Read `docs/motion-v2/HANDOFF.md`, then `SPEC.md`,
   `reference/PROTOTYPE_NOTES.md`, `DECISIONS.md` and `SURFACE_MAP.md`.
   Open `reference/motion-prototype.html` in a browser: that's the approved
   behaviour.
2. Check the repo against the pack: re-run the greps at the bottom of
   `SURFACE_MAP.md` and tell me anything that has moved or no longer matches
   (the pack was written against `main` at `eaf4ec8`).
3. Then start Phase 0: create the `motion-v2` branch, commit the pack, and walk
   me through `DECISIONS.md` one decision at a time. Give me the recommendation
   and what it changes, and record my answer before moving on.

Don't start Phase 1 until all seven decisions are confirmed. After that, work
through the phases in order, one commit per task, and stop at every ⏸
checkpoint to show me the result.

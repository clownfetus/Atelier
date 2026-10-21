# Capwolf body overlap — 21 October 2026

Capwolf (`1022504`) was displaying its wolf body and a human Captain America body
together. The human transformation is the full skeletal mesh
`Weapons/Caption/Meshes/SK_WP_1022504_Caption`; its location caused discovery to
classify it as held equipment. Automatic attachment loaded that body over the
wolf and reserved the hand that should hold the real shield.

The Caption mesh is now a body choice. It remains unloaded and hidden until
selected, and switching forms hides the previous body. The shield remains held
equipment. Material grouping follows the discovered object kind, including body
meshes stored under Weapons. The model picker counts available body forms, not
simultaneously visible bodies. No game mesh, saved visibility or project edit is
changed to suppress the overlap.

## Verification

- Four relevant backend suites pass: 18 Model Studio, 6 frontend, 28 portable
  export and 12 model-route cases, 64 total. Regression checks cover Capwolf's
  body/shield classification and body material grouping under a Weapons path.
- 52 viewer and 12 Blender-export browser checks pass with no page errors.
  Shared startup coverage overlaps between these runs.
- The real Windows WebView2/native run opens one wolf body with its shield and
  does not request the Caption GLB initially. Its body picker exposes the human
  transformation. Selecting it and restoring the wolf each keep exactly one
  body visible. Both themes, material draft/revert, Original/Compare, idle
  playback, bloom, reader reuse and native process cleanup pass.
- The native smoke now records and fails on model, material and image HTTP
  errors. The strict run has no such failures or page errors. The earlier run
  encountered one transient head-texture HTTP 500, whose body was not captured;
  the same request then returned 200. It did not recur in the fresh native run
  or eleven parallel cold texture imports. This follow-up does not claim a
  separate decoder repair for that unreproduced warning.
- Tests use isolated application data and an empty project under
  `D:/AtelierDev/capwolf-20261021`, with a dedicated `test-mods` directory. They
  install no game mods. Screenshots of the wolf, human form and restored wolf
  were inspected. Source compilation, dependency consistency and whitespace
  checks pass.

Outcomes, initial/alternate visibility, requests, source hashes and evidence paths
are in [the verification JSON](capwolf-verification-2026-10-21.json).
The preceding import-server verification remains in
[the persistent import report](persistent-import-verification-2026-10-21.md).

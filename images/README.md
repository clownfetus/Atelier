# Atelier 1.1.2 screenshots

Captured on 22 October 2026 from the consolidated 1.1.2 source using the actual
Bottle-served interface in Microsoft Edge at 1400 × 900. Captures are unedited:
no compositing, simulated UI, cropping or image generation.

| File | View |
| --- | --- |
| `studio-dark.png` | Hero-led Home, global search, Mod tray, dark theme |
| `studio-light.png` | The same configured installation in the light theme |
| `asset-library.png` | Character and costume names in legendary ultimate skin folders |
| `material-editor.png` | Installed material parameters and comparisons |
| `material-replacement.png` | The material replacement controls |
| `model-studio.png` | Magik in the real Model Studio Inspect view |
| `blender-live-setup.png` | Model menu with live send, extension setup and portable export |
| `showcase.png` | The same model with Showcase presentation |
| `assembly-view.png` | Magik's selected body surface with connected material and textures |
| `uv-xray.png` | The selected surface's actual UV0 wireframe and decoded texture |
| `vfx-motionboard.png` | Real Niagara LUT tracks with the Motionboard editing controls |
| `appearance-settings.png` | Appearance palettes and motion preferences |
| `krackle-examples.png` | The authored motion examples and connected handoff in Settings |
| `blender-settings.png` | The option to keep Blender textures out of the project |

The game installation is read through an isolated **Release Verification**
project with an isolated test-mods destination. No material edits are saved and
no mods are built or installed during capture. Game artwork belongs to its
respective owners. These screenshots demonstrate the interface and preview;
they do not establish in-game compatibility.

`screenshots.json` records image hashes, interface source hashes (text line
endings normalized to LF for Git checkouts on either platform), and
page errors. Bundle assembly refuses screenshots from another version or source.
To reproduce, start
`server.py` with a separate configured `ATELIER_DATA_DIR` and `ATELIER_PORT`, then:

```powershell
python scripts/capture_release_screenshots.py --url http://127.0.0.1:8797 --output images
```

Older `screenshot.png` and `skin_ids.png` are historical references;
`rivals_path.png` illustrates Steam's folder-location menu.

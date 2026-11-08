# Atelier 1.2.0

This update gives Atelier a new way to show work in progress. Loading, saving and
exports are shown by Atelier's own mark, assembled from three pieces, and
pop-ups and menus open and close more calmly. How projects, mods and exports
work is unchanged.

## The assembly glyph

Atelier's mark is made of three pieces: a blue tile for textures, a teal block
for meshes and a copper disc for materials. Wherever Atelier is working, those
pieces now show it. This replaces the coloured ink and Krackle.

- **Working:** the pieces try different fits while a job runs.
- **Complete:** the pieces click together into the A, only once a job has
  actually succeeded. There is never a timer or a guess.
- **Warning and Error:** the pieces balance into a **!** or close into an **X**,
  next to a sentence that says what happened.
- **Loaders for each kind of asset.** A model loading cuts and leans the mesh
  block, a texture loading shuffles the tile's bands, and a material saving rolls
  the disc. The model stays in view while its textures load.
- The logo assembles once when Atelier opens, then stays still.
- Settings → **Preview motion** shows every state and loader at three sizes.

## Calmer pop-ups and surfaces

- Menus, tooltips, toasts, dialogs, search results and the update button open out
  of the edge they belong to and fold back into it. Nothing fades in or out.
- Opening a folder, choosing a theme, loading thumbnails and swapping a texture
  open the new picture over the old one, so you never see two blended together.
- Rows in the Mod tray click into place as they're added, and fold away when
  removed.
- The texture, mesh and material studios wear their piece's colour along the top,
  so it's clear what you're editing.

## Colour

Only textures, meshes and materials keep a category colour now: blue, teal and
copper, the same as the mark's pieces. Every other category is neutral and told
apart by its icon. Complete, warning and error keep the same hue in every theme,
adjusted only for contrast.

## Motion settings

Settings → Motion keeps three choices, and your system's reduced-motion setting
is still respected.

- **Full:** everything above.
- **Calm:** loaders work in place without lifting or travelling, and results
  appear without a punch or ripple.
- **Off:** results and loaders show as still shapes with their status sentence.

**Motion sounds** (previously Formation sounds) plays one click when a job
completes. It's off by default and plays only in Full.

## Send to Blender

- **Send to Blender (live)** no longer fails on Blender 4.4 and newer, including
  5.1. The importer's bone display shape used to cancel the whole import.
- If Blender is running an older **Atelier Live Bridge**, Send to Blender now says
  so instead of importing with older material wiring. After updating, open
  **Set up live Blender** beside Send to Blender, download the add-on and install
  it in Blender over the old one. You only need to do this once.

## A few things to know

- Showcase images now use a plain neutral backdrop. Showcase images you export
  will look different from earlier versions.
- Working panels, ink transfers, the folder flap and the halftone texture
  reconstruction have gone. The glyph and plain motion take their place.
- Nothing about your projects, mods, exports or the game files changes.

[Full changelog](../CHANGELOG.md) · [Linux setup](LINUX.md) · [Blender setup](BLENDER.md)

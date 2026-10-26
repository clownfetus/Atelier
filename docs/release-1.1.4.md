# Atelier 1.1.4

This update makes future updates easier to install and improves model previews,
Blender exports, textures and everyday browsing.

## Updates inside Atelier

Choose **Download Update**, then **Restart and Update** when you're ready.
You can choose **Restart Later** to finish editing first. Compatible Windows
updates download only the changed app files; Linux downloads the new AppImage.
If an updated app cannot finish starting, Atelier restores the previous version.

To receive this updater for the first time:

- **Windows:** close Atelier and run the new `AtelierSetup.exe` in your existing
  installation location. Your projects and settings are retained.
- **Linux:** download `Atelier-1.1.4-x86_64.AppImage`, mark it executable and launch
  it. Keep the same Atelier data location so your projects and settings carry over.

## Model and texture improvements

- Gameplay and lobby models choose the right standing animation for their skeletons.
- Skin Swapper uses the form belonging to the selected mesh automatically.
- Blender rebuilds handle repeated material names and materials at lower detail
  levels more reliably.
- Texture exports retain their complete data. Blender texture inputs keep all
  cubemap faces and transparency.

## Workspace improvements

- Costume artwork stays on screen while its model loads, then clears as the model appears.
- The Home hero list folds into a compact row while you browse categories.
- Krackle previews are simpler, and text, controls and motion are more consistent.
- Newly imported textures appear promptly in the Mod tray. The VFX editor opens
  even when automatic external opening is turned off.
- Completed exports put the finished Mod card beside the result. Update prompts
  wait until first-time setup is finished.

## A few things to know

Save open edits before choosing **Restart and Update**. A change to Atelier's
runtime may still require the full Windows installer.

HDR and cubemap inputs prepared for Blender remain read-only in Atelier's game
texture-painting workflow. They do not recreate the game's reflection shaders.
Model and export checks do not guarantee every result's appearance in-game.

[Full changelog](../CHANGELOG.md) · [Linux setup](LINUX.md) · [Blender setup](BLENDER.md)

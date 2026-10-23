**Atelier 1.1.2**

A patch for texture exports and tools, with three new editors.

• Exported textures no longer look brighter or glarey in game: mips are kept and built the way the game builds them.
• BC7 texture exports finish in seconds instead of close to a minute.
• Textures added at a custom path no longer crash the game with "Serial size mismatch".
• Assembly View: pick a model surface to see its material and connected texture slots.
• VFX Motionboard: edit Niagara LUT tracks on a timeline with playback and before/after comparison.
• Bulk edit materials: change opacity, scalars, colours or parents on up to 1,000 materials at once.
• Settings → Tools shows tool versions and can update, repair or roll back the container tool.
• Linux AppImage runs on newer distros again, with model previews and animations working without Wine.

Windows installer, portable ZIP and Linux AppImage, with source and checksums.

Download: https://github.com/clownfetus/Atelier/releases/tag/1.1.2

Windows: close Atelier and install to your existing location. Linux: download the new AppImage and mark it executable.

The brightness fix matches the game's own textures in our checks; please report anything that still looks off in game.

# Atelier 1.1.3

This patch combines the latest upstream export and toolchain fixes with the
connected ink workspace and refreshed Windows installer.

## What changed

- **Texture export improvements.** Character, weapon and world textures retain
  their mip chains. Generated mips use linear-light averaging, BC7 encoding uses
  the faster bundled texture tool, and renamed textures are size-checked before
  export at a custom path.
- **One native model tool.** AtelierNative handles mesh previews, idle animations
  and persistent imports on Windows and Linux, built from pinned source.
- **Settings → Tools.** See installed tool versions and use verified updates,
  repairs and rollback for the container tool. Downloads and extracted files must
  match their hashes and pass a command probe before replacement.
- **Windows picker fix.** File and folder selection opens without an extra
  PowerShell console.
- **Connected ink stays connected.** Loading, saving, exporting and configuration
  discovery use hero and costume colours, clear sources and destinations, and
  completion reactions along native panel borders. Replay them in
  **Settings → Try Krackle**, or choose Calm or Off.
- **Existing editing tools stay available.** Assembly View, UV X-Ray, Niagara
  Motionboard, reviewed material batches and the Paper and Ink installer are
  retained alongside safeguards for newer unsaved drafts.
- **Updated packaging.** One lockfile describes the native tools, the app uses
  Python 3.15, and the Linux package uses system GTK and WebKit together.

## Updating

Windows: close Atelier and run `AtelierSetup.exe` in the existing location.
Projects and settings are retained. The portable ZIP contains the same files.

Linux: download `Atelier-1.1.3-x86_64.AppImage`, mark it executable and launch it.

Upgrade gates use the latest published release, **1.1.1**. Version 1.1.2 remains
an unpublished candidate at preparation time. The release bundle includes the
installer, portable ZIP, AppImage, matching source, screenshots, release copy,
`SHA256SUMS.txt` and `VERIFICATION.json`, all bound to the tested source commit.

## Verification and limits

Publication requires backend and browser checks, the packaged Windows app,
clean install/upgrade/reinstall/uninstall on Windows 2022 and 2025, and native
Linux startup and upgrade. The verification file records the actual results.

Motionboard proxies do not reproduce Unreal rendering or simulation. UV X-Ray
covers decoded UV0. In-game appearance and Linux Wine workflows remain outside
the automated release gates.

[Full changelog](https://github.com/clownfetus/Atelier/blob/1.1.3/CHANGELOG.md)

# Atelier: Modding Studio
This supercharged modding interface allows anyone (seriously anyone) to make mods in seconds!  

- Combines essential functionality from UE and Fmodel into one intuitive interface: 
<img src="images\screenshot.png" alt="Screenshot" width="600" height="400">

- No more repetitive and slow Unreal Engine nonsense (extremely long export, Data Asset/texture type/filepath management)

- Unlike Fmodel, it shows character and skin names:  
<img src="images\skin_ids.png" alt="Character/Skin IDs" width="600" height="400">

- No external dependancies, everything comes with the exe, get started in seconds

## Installation
1. Download latest version from [Releases](https://github.com/clownfetus/Atelier/releases)
2. Launch the exe and setup to the default directory
3. Set your Pak folder (ex. `.../MarvelGame/Marvel/Content/Paks`)

## If Windows warns or blocks it
Atelier is an unsigned indie app that bundles native tools, so Windows may flag it. **Both warnings below are false positives** — Atelier is open source and contains no malware.

- **"Windows protected your PC" (SmartScreen).** On the first launch of a freshly downloaded copy you'll see an "unrecognized app" warning. Click **More info → Run anyway**. This only appears because the app isn't code-signed; it's normal for community modding tools.
- **Windows Defender quarantines or deletes `Atelier.exe`.** Antivirus engines frequently false-flag apps packed with PyInstaller (what Atelier uses) and its bundled `.dll`/`.exe` tools. If it happens:
  1. **Extract the release `.zip` fully before running** (don't launch from inside the zip) — this alone avoids most flags.
  2. If it's already quarantined: **Windows Security → Virus & threat protection → Protection history**, find the Atelier detection, choose **Restore**.
  3. To stop it recurring, add a folder **exclusion** for your Atelier install (Virus & threat protection → Manage settings → Exclusions → Add → Folder).

Atelier automatically un-taints its own bundled tools on launch, so no manual "unblock" is needed for those — only `Atelier.exe` itself may trip SmartScreen/Defender as above.

## Usage
1. Navigate to the textures/materials you want to edit
2. In sidebar: toggle the assets you want to export in mod
3. In sidebar: Type a mod name at the bottom and click "Export Mod"

- You can delete imported textures by pressing "X" next to it in sidebar
- Right-click for option to replace texture with external image

## Help
This section is only relevant if the current mappings/AES repo is down, until we update to using a different one
- Get AES Key from [Discord server](https://discord.com/channels/1419106202511609958/1485413590310584374/1485417747834863616)
- Get USMAP file from [SpaceHost](https://spacedepot.github.io/SpaceHost/)
- Get MarvelRivals location from Steam
<img src="images\rivals_path.png" alt="Rivals > Manage > Browse Local" width="600" height="400">

## Credits
- Noobmaster and Clownfetus  
- Xzant ([UAssetToolRivals](https://github.com/XzantGaming/UAssetToolRivals))  
- Natimerry ([repak-rivals retoc](https://github.com/natimerry/repak-rivals/))  
- Saturn ([Repak-X](https://github.com/XzantGaming/Repak-X), [SpaceHost](https://spacedepot.github.io/SpaceHost/))
- donutman07 ([Character IDs](https://github.com/donutman07/MarvelRivalsCharacterIDs/))

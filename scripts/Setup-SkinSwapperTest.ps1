<#
.SYNOPSIS
Prepare an isolated Atelier source checkout for testing Project Galacta Skin Swapper export.

.DESCRIPTION
Run from a clone of https://github.com/clownfetus/Atelier at main. See
docs/skin-swapper-testing.md for the whole test. This script:

  1. creates .venv with 64-bit Python 3.12 and installs requirements.txt;
  2. installs Atelier's native tools into <DataDir>\Tools, copied from an existing Atelier
     install (-ToolsFrom) or unpacked from the hash-pinned 0.4.1 release installer, which is
     extracted and never run;
  3. copies your GAL_ConfigTemplate.uasset and .uexp into <DataDir>\Tools\Galacta;
  4. asks Atelier itself whether Skin Swapper export is available;
  5. starts Atelier in a desktop window when you pass -Launch.

Nothing is written to the game folder, the registry or an installed copy of Atelier.
The template stays on your machine: <DataDir> is outside the checkout, and git ignores
GAL_ConfigTemplate.* everywhere.

.PARAMETER Template
Folder that holds GAL_ConfigTemplate.uasset and GAL_ConfigTemplate.uexp.

.PARAMETER DataDir
Atelier's isolated data folder: configuration, projects, exports, logs and tools.
Put it on the same drive as Marvel Rivals so the 3D viewer can keep installed mods out of
its reads (it hardlinks the game's containers).

.PARAMETER ToolsFrom
An existing Atelier 0.4.x install folder (the one holding Atelier.exe and Tools\) to copy
the native tools from, instead of downloading the 0.4.1 installer (about 150 MB).

.PARAMETER Launch
Start Atelier in a desktop window when setup finishes.

.EXAMPLE
.\scripts\Setup-SkinSwapperTest.ps1 -Template D:\Galacta\template -DataDir D:\AtelierGalactaTest -Launch
#>
param(
    [Parameter(Mandatory)][string]$Template,
    [string]$DataDir = (Join-Path $env:LOCALAPPDATA 'AtelierSkinSwapperTest'),
    [string]$ToolsFrom,
    [switch]$Launch
)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$DataDir = [IO.Path]::GetFullPath($DataDir)
$tools = Join-Path $DataDir 'Tools'

# Hash-pinned inputs: the 0.4.1 release installer (SHA256SUMS.txt on the release) and the Inno
# unpacker Install-AtelierTools.ps1 already uses.
$installerUrl = 'https://github.com/clownfetus/Atelier/releases/download/0.4.1/AtelierSetup.exe'
$installerSha = 'dd8d18228093922b460e2b2db6689c9cfff5fa7fa58137d7b0b03335525ded45'
$unpackerUrl = 'https://github.com/jrathlev/InnoUnpacker-Windows-GUI/releases/download/ui_2_2_13/innounp-2.zip'
$unpackerSha = 'f2f037fdbc63de31248efae9ccb294398d160dc0cbad5f36d14c2f159e17bbf5'
$required = 'UAssetTool.exe', 'UAssetGUI.exe', 'AtelierMesh\AtelierMesh.exe',
            'AtelierAnimation\AtelierAnimation.exe', 'shaders\retoc-rivals-cli.exe',
            'shaders\oo2core_9_win64.dll'

function Step([string]$Text) { Write-Host "`n== $Text" -ForegroundColor Cyan }
function Missing-Tools { $required | Where-Object { !(Test-Path -LiteralPath (Join-Path $tools $_)) } }

function Get-Verified([string]$Url, [string]$Name, [string]$Sha256) {
    $downloads = Join-Path $DataDir 'downloads'
    New-Item -ItemType Directory -Force -Path $downloads | Out-Null
    $target = Join-Path $downloads $Name
    if (!(Test-Path -LiteralPath $target)) {
        Write-Host "Downloading $Name"
        Invoke-WebRequest -Uri $Url -OutFile $target -UseBasicParsing
    }
    if ((Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash.ToLower() -ne $Sha256) {
        throw "Checksum mismatch for $target. Delete it and run this script again."
    }
    return $target
}

if (!(Test-Path -LiteralPath (Join-Path $root 'atelier\skin_swapper.py'))) {
    throw "This checkout has no Skin Swapper export. Use main from https://github.com/clownfetus/Atelier."
}

Step 'Python 3.12 environment'
$python = Join-Path $root '.venv\Scripts\python.exe'
if (!(Test-Path -LiteralPath $python)) {
    if (!(Get-Command py -ErrorAction SilentlyContinue)) {
        throw 'The Python launcher (py) was not found. Install 64-bit Python 3.12 from python.org.'
    }
    & py -3.12 -m venv (Join-Path $root '.venv')
    if ($LASTEXITCODE -ne 0) { throw 'Creating .venv failed. Atelier needs 64-bit Python 3.12 (py -3.12).' }
}
& $python -m pip install --disable-pip-version-check --quiet -r (Join-Path $root 'requirements.txt')
if ($LASTEXITCODE -ne 0) { throw 'Installing requirements.txt failed; see the pip output above.' }
Write-Host "Python: $python"

Step 'Native tools'
New-Item -ItemType Directory -Force -Path $tools | Out-Null
if (Missing-Tools) {
    if ($ToolsFrom) {
        $source = Join-Path ([IO.Path]::GetFullPath($ToolsFrom)) 'Tools'
        if (!(Test-Path -LiteralPath (Join-Path $source 'UAssetTool.exe'))) {
            throw "No Atelier tools in $source. Pass the folder that holds Atelier.exe."
        }
    } else {
        $setup = Get-Verified $installerUrl 'AtelierSetup-0.4.1.exe' $installerSha
        $zip = Get-Verified $unpackerUrl 'innounp-2.zip' $unpackerSha
        $unpacker = Join-Path $DataDir 'downloads\innounp'
        Expand-Archive -LiteralPath $zip -DestinationPath $unpacker -Force
        $exe = Get-ChildItem -LiteralPath $unpacker -Recurse -Filter 'innounp.exe' | Select-Object -First 1
        if (!$exe) { throw 'innounp-2.zip did not contain innounp.exe' }
        $unpacked = Join-Path $DataDir 'downloads\atelier-0.4.1'
        # Unpack files only: the installer is never executed.
        & $exe.FullName -x -y "-d$unpacked" $setup '{app}\Tools\*' *> (Join-Path $DataDir 'downloads\tools-extraction.log')
        if ($LASTEXITCODE -ne 0) { throw 'Unpacking the installer failed; see downloads\tools-extraction.log' }
        $source = Join-Path $unpacked '{app}\Tools'
    }
    foreach ($item in 'UAssetTool.exe', 'UAssetGUI.exe', 'AtelierMesh', 'AtelierAnimation', 'AtelierImport', 'shaders', 'MarvelRivalsCharacterIDs.md') {
        $from = Join-Path $source $item
        if (Test-Path -LiteralPath $from) { Copy-Item -LiteralPath $from -Destination $tools -Recurse -Force }
    }
    $missing = Missing-Tools
    if ($missing) { throw "Tools still missing after setup: $($missing -join ', ')" }
}
Write-Host "Tools: $tools"

Step 'Skin Swapper template'
$templateDir = [IO.Path]::GetFullPath($Template)
$galacta = Join-Path $tools 'Galacta'
& $python (Join-Path $root 'scripts\stage_galacta_template.py') --source $templateDir --destination $galacta
if ($LASTEXITCODE -ne 0) { throw 'Installing the template pair failed. See the error above for recovery details.' }

Step 'Asking Atelier whether Skin Swapper export is available'
$env:ATELIER_DATA_DIR = $DataDir
$env:PYTHONUTF8 = '1'
Push-Location $root
try {
    $json = & $python -c "import json; from atelier import skin_swapper as S; S.refresh_flag(); print(json.dumps(S.status()))"
    if ($LASTEXITCODE -ne 0) { throw 'Atelier could not be imported; see the error above.' }
} finally { Pop-Location }
$status = $json | Select-Object -Last 1 | ConvertFrom-Json
if ($status.available) {
    Write-Host '  Available: template installed, Galacta switch on.' -ForegroundColor Green
} else {
    Write-Warning ('Not available: ' + ($status.reasons -join ' '))
}

Write-Host "`nSetup complete. Data folder: $DataDir"
Write-Host 'Start Atelier any time with:'
Write-Host "  .\Start-AtelierDev.ps1 -Mode Desktop -DataDir '$DataDir'"
Write-Host 'Then follow docs\skin-swapper-testing.md from "First run".'
if ($Launch) {
    & (Join-Path $root 'Start-AtelierDev.ps1') -Mode Desktop -DataDir $DataDir
}

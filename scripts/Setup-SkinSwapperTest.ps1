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

$required = 'UAssetTool.exe', 'UAssetGUI.exe', 'AtelierNative\AtelierNative.exe', 'retoc\retoc-rivals-cli.exe',
            'shaders\retoc-rivals-cli.exe', 'shaders\oo2core_9_win64.dll'

function Step([string]$Text) { Write-Host "`n== $Text" -ForegroundColor Cyan }
function Missing-Tools { $required | Where-Object { !(Test-Path -LiteralPath (Join-Path $tools $_)) } }

if (!(Test-Path -LiteralPath (Join-Path $root 'atelier\skin_swapper.py'))) {
    throw "This checkout has no Skin Swapper export. Use main from https://github.com/clownfetus/Atelier."
}

Step 'Python 3.15 environment'
$python = Join-Path $root '.venv\Scripts\python.exe'
if (!(Test-Path -LiteralPath $python)) {
    if (!(Get-Command py -ErrorAction SilentlyContinue)) {
        throw 'The Python launcher (py) was not found. Install 64-bit Python 3.15 from python.org.'
    }
    & py -3.15 -m venv (Join-Path $root '.venv')
    if ($LASTEXITCODE -ne 0) { throw 'Creating .venv failed. Atelier needs 64-bit Python 3.15 (py -3.15).' }
}
& $python -m pip install --disable-pip-version-check --quiet -r (Join-Path $root 'requirements.txt')
if ($LASTEXITCODE -ne 0) { throw 'Installing requirements.txt failed; see the pip output above.' }
Write-Host "Python: $python"

Step 'Native tools'
New-Item -ItemType Directory -Force -Path $tools | Out-Null
if (Missing-Tools) {
    if ($ToolsFrom) {
        # An installed Atelier (1.2+) already has the whole verified tool set.
        $source = Join-Path ([IO.Path]::GetFullPath($ToolsFrom)) 'Tools'
        if (!(Test-Path -LiteralPath (Join-Path $source 'tools.json'))) {
            throw "No Atelier 1.2+ tools in $source. Pass the folder that holds Atelier.exe."
        }
        Get-ChildItem -LiteralPath $source | Where-Object { $_.Name -notin 'Mappings', 'AES_KEY.txt', 'Galacta' } |
            Copy-Item -Destination $tools -Recurse -Force
    } else {
        # Fetch and build every tool from toolchain/tools.lock.json (hash-pinned).
        & $python (Join-Path $root 'scripts\toolchain.py') install --dest $tools
        if ($LASTEXITCODE -ne 0) { throw 'Native tool setup failed; see the output above.' }
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
Write-Host "  .\scripts\Start-AtelierDev.ps1 -Mode Desktop -DataDir '$DataDir'"
Write-Host 'Then follow docs\skin-swapper-testing.md from "First run".'
if ($Launch) {
    & (Join-Path $root 'scripts\Start-AtelierDev.ps1') -Mode Desktop -DataDir $DataDir
}

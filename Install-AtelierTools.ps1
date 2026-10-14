param([string]$DataDir = (Join-Path $env:LOCALAPPDATA 'AtelierDev\phase-0-1'))
$ErrorActionPreference = 'Stop'
$downloadDir = Join-Path $DataDir 'downloads'
New-Item -ItemType Directory -Path $downloadDir -Force | Out-Null

function Get-VerifiedDownload([string]$Url, [string]$Name, [string]$Sha256) {
    $target = Join-Path $downloadDir $Name
    if (!(Test-Path -LiteralPath $target)) {
        Invoke-WebRequest -Uri $Url -OutFile $target -UseBasicParsing
    }
    if ((Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash.ToLower() -ne $Sha256) {
        throw "Checksum mismatch: $target"
    }
    return $target
}

# The 0.3.3 full bundle contains Atelier's custom shader retoc. The ordinary
# retoc release lacks its shader commands; do not substitute the newest generic CLI.
$bundle = Get-VerifiedDownload `
    'https://github.com/clownfetus/Atelier/releases/download/0.3.3/AtelierSetup.exe' `
    'AtelierSetup-0.3.3.exe' '6ab75b4efee71abf80c4966fbaa62fd3f0454f49ea558a1eba1264f53a47a313'
$extractorZip = Get-VerifiedDownload `
    'https://github.com/jrathlev/InnoUnpacker-Windows-GUI/releases/download/ui_2_2_13/innounp-2.zip' `
    'innounp-2.zip' 'f2f037fdbc63de31248efae9ccb294398d160dc0cbad5f36d14c2f159e17bbf5'
$extractorDir = Join-Path $downloadDir 'innounp'
Expand-Archive -LiteralPath $extractorZip -DestinationPath $extractorDir -Force
$extractor = Get-ChildItem -LiteralPath $extractorDir -Recurse -Filter 'innounp.exe' | Select-Object -First 1
if (!$extractor) { throw 'Archive did not contain innounp.exe' }
$unpacked = Join-Path $downloadDir 'atelier-tools'
# Unpack files only. Never execute AtelierSetup or change the installed app/registry.
& $extractor.FullName -x -y "-d$unpacked" $bundle '{app}\Tools\*' *> (Join-Path $downloadDir 'tools-extraction.log')
if ($LASTEXITCODE -ne 0) { throw 'Tool extraction failed; see downloads/tools-extraction.log' }
$source = Join-Path $unpacked '{app}\Tools'
$destination = Join-Path $DataDir 'Tools'
New-Item -ItemType Directory -Path $destination -Force | Out-Null
Get-ChildItem -LiteralPath $source | ForEach-Object {
    # Preserve an existing local key/mapping and tools when rerunning setup.
    $target = Join-Path $destination $_.Name
    if (!(Test-Path -LiteralPath $target)) {
        Copy-Item -LiteralPath $_.FullName -Destination $target -Recurse
    }
}
$shaderTool = Join-Path $destination 'shaders\retoc-rivals-cli.exe'
$help = & $shaderTool --help 2>&1 | Out-String
if ($help -notmatch 'dump-shaders' -or $help -notmatch 'extract-shader') {
    throw "The existing $shaderTool is incompatible. Use the bundled copy under $source\shaders."
}
$manifest = Get-ChildItem -LiteralPath $destination -File -Recurse |
    Where-Object { $_.Extension -in '.exe','.dll' } | ForEach-Object {
        @{ path=$_.FullName; sha256=(Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLower() }
    }
$manifest | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $DataDir 'tools-manifest.json') -Encoding UTF8
Write-Host "Tools installed in $destination. Hashes recorded in tools-manifest.json."

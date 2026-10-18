param(
    [string]$Python,
    [string]$ToolchainDir = (Join-Path $env:LOCALAPPDATA 'AtelierBuildTools'),
    [string]$NodeDirectory,
    [switch]$InstallWebView2
)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
if (!$Python) {
    $launcher = Get-Command py -ErrorAction SilentlyContinue
    if ($launcher) { $Python = (& $launcher.Source -3.12 -c 'import sys; print(sys.executable)') }
    elseif (Get-Command python -ErrorAction SilentlyContinue) { $Python = (Get-Command python).Source }
}
if (!$Python -or !(Test-Path -LiteralPath $Python)) { throw 'Pass -Python with the path to a Windows x64 Python 3.12 interpreter.' }
& $Python -c 'import sys; assert sys.version_info[:2] == (3,12) and sys.maxsize > 2**32, "Use Python 3.12 x64"'
if ($LASTEXITCODE -ne 0) { throw 'Python must be version 3.12 x64.' }
$venvPython = Join-Path $projectRoot '.venv-build\Scripts\python.exe'
if (!(Test-Path -LiteralPath $venvPython)) {
    & $Python -m venv (Join-Path $projectRoot '.venv-build')
    if ($LASTEXITCODE -ne 0) { throw 'Could not create the isolated build environment.' }
}
& $venvPython -m pip install --disable-pip-version-check -r (Join-Path $projectRoot 'requirements-build.txt')
if ($LASTEXITCODE -ne 0) { throw 'Installing the pinned requirements failed.' }
& $venvPython -m pip check
if ($LASTEXITCODE -ne 0) { throw 'Build environment dependencies conflict.' }
if ($NodeDirectory) { $env:PATH = "$NodeDirectory;$env:PATH" }
if (((Test-Path -LiteralPath (Join-Path $projectRoot '.git')) -and !(Get-Command git -ErrorAction SilentlyContinue)) -or !(Get-Command node -ErrorAction SilentlyContinue)) {
    throw 'Install Node.js LTS (or pass -NodeDirectory). A Git checkout also requires Git on PATH.'
}
New-Item -ItemType Directory -Path $ToolchainDir -Force | Out-Null
$toolchain = (Get-Content -LiteralPath (Join-Path $PSScriptRoot 'windows_toolchain.json') -Raw | ConvertFrom-Json).inno_setup
$download = Join-Path $ToolchainDir ("innosetup-$($toolchain.version).exe")
$expected = $toolchain.sha256
if (!(Test-Path -LiteralPath $download)) {
    Invoke-WebRequest -UseBasicParsing -Uri $toolchain.url -OutFile $download
}
if ((Get-FileHash -LiteralPath $download -Algorithm SHA256).Hash.ToLowerInvariant() -ne $expected) {
    throw "Inno Setup SHA-256 mismatch: $download"
}
$signature = Get-AuthenticodeSignature -LiteralPath $download
if ($signature.Status -ne 'Valid' -or $signature.SignerCertificate.Subject -notmatch 'Pyrsys B.V.') {
    throw 'Inno Setup signature is not valid for publisher Pyrsys B.V.'
}
$innoDir = Join-Path $ToolchainDir 'Inno Setup 6'
if (!(Test-Path -LiteralPath (Join-Path $innoDir 'ISCC.exe'))) {
    # Install the verified compiler per-user, without file associations or shortcuts.
    $arguments = @('/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/SP-', '/CURRENTUSER', '/NOICONS', '/TASKS=', "/DIR=`"$innoDir`"")
    $process = Start-Process -FilePath $download -ArgumentList $arguments -WindowStyle Hidden -Wait -PassThru
    if ($process.ExitCode -ne 0) { throw "Inno Setup installation failed: $($process.ExitCode)" }
}
$env:ISCC = Join-Path $innoDir 'ISCC.exe'
foreach ($entry in $toolchain.files.PSObject.Properties) {
    $installedFile = Join-Path $innoDir $entry.Name
    if (!(Test-Path -LiteralPath $installedFile) -or (Get-FileHash -LiteralPath $installedFile -Algorithm SHA256).Hash.ToLowerInvariant() -ne $entry.Value) {
        throw "Existing compiler component is not pinned Inno Setup $($toolchain.version): $installedFile. Choose a fresh -ToolchainDir."
    }
}
$runtimeProbe = 'import sys; sys.path.insert(0,sys.argv[1]); from atelier_runtime_check import webview2_version; sys.exit(0 if webview2_version() else 1)'
& $venvPython -c $runtimeProbe $PSScriptRoot
if ($LASTEXITCODE -ne 0 -and $InstallWebView2) {
    $webviewBootstrapper = Join-Path $ToolchainDir 'MicrosoftEdgeWebview2Setup.exe'
    Invoke-WebRequest -UseBasicParsing -Uri 'https://go.microsoft.com/fwlink/p/?LinkId=2124703' -OutFile $webviewBootstrapper
    $webviewSignature = Get-AuthenticodeSignature -LiteralPath $webviewBootstrapper
    if ($webviewSignature.Status -ne 'Valid' -or $webviewSignature.SignerCertificate.Subject -notmatch 'Microsoft Corporation') {
        throw 'WebView2 bootstrapper must have a valid Microsoft Corporation signature.'
    }
    $webviewProcess = Start-Process -FilePath $webviewBootstrapper -ArgumentList @('/silent','/install') -WindowStyle Hidden -Wait -PassThru
    if ($webviewProcess.ExitCode -ne 0) { throw "WebView2 installation failed: $($webviewProcess.ExitCode)" }
}
& $venvPython -c 'import sys; sys.path.insert(0,sys.argv[1]); from atelier_runtime_check import launch_issue; issue=launch_issue(); print(issue or "Desktop runtime prerequisites ready."); sys.exit(1 if issue else 0)' $PSScriptRoot
if ($LASTEXITCODE -ne 0) { throw 'Resolve the desktop runtime message above; use -InstallWebView2 to provision the signed Evergreen bootstrapper.' }
Write-Host "Build environment ready. In this shell run:"
Write-Host "`$env:ISCC = '$env:ISCC'"
Write-Host 'python -m PyInstaller --noconfirm --clean Atelier.spec'

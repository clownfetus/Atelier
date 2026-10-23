param(
    [ValidateSet('Browser', 'Desktop')][string]$Mode = 'Browser',
    # Keep this outside AppData when running from a packaged/sandboxed terminal: Windows may
    # silently redirect AppData writes, and the mesh tools need a normal local NTFS folder.
    [string]$DataDir = (Join-Path $env:USERPROFILE 'AtelierDev\default'),
    [ValidateRange(1, 65535)][int]$Port = 8767
)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root '.venv\Scripts\python.exe'
if (!(Test-Path -LiteralPath $python)) {
    throw 'Create .venv with Python 3.15 and install requirements-dev.txt first; see docs/DEVELOPMENT.md.'
}
$tools = Join-Path $DataDir 'Tools'
if (!(Test-Path -LiteralPath (Join-Path $tools 'tools.json'))) {
    # First run: fetch and build every native tool from toolchain/tools.lock.json. Existing
    # mappings, AES key and caches in that folder are left alone.
    Write-Host "Installing native tools into $tools ..."
    & $python (Join-Path $root 'scripts\toolchain.py') install --dest $tools
    if ($LASTEXITCODE -ne 0) { throw 'Native tool setup failed; see the output above.' }
}
$env:ATELIER_DATA_DIR = [IO.Path]::GetFullPath($DataDir)
$env:ATELIER_PORT = [string]$Port
$env:PYTHONUTF8 = '1'
$env:ATELIER_DEBUG = '1'
Write-Host "Development data: $env:ATELIER_DATA_DIR"
Push-Location $root
try {
    if ($Mode -eq 'Desktop') {
        & $python window.py
    } else {
        Write-Host "Open http://127.0.0.1:$Port (Ctrl+C stops the server)."
        & $python tests/dev_server.py --port $Port
    }
    if ($LASTEXITCODE -ne 0) { throw "Atelier exited with code $LASTEXITCODE" }
} finally { Pop-Location }

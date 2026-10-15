param(
    [ValidateSet('Browser', 'Desktop')][string]$Mode = 'Browser',
    [string]$DataDir = (Join-Path $env:LOCALAPPDATA 'AtelierDev\phase-0-1'),
    [ValidateRange(1, 65535)][int]$Port = 8767
)
$ErrorActionPreference = 'Stop'
$python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (!(Test-Path -LiteralPath $python)) {
    throw 'Create .venv and install requirements-dev.txt first; see DEVELOPMENT.md.'
}
$env:ATELIER_DATA_DIR = [IO.Path]::GetFullPath($DataDir)
$env:ATELIER_PORT = [string]$Port
$env:PYTHONUTF8 = '1'
$env:ATELIER_DEBUG = '1'
Write-Host "Development data: $env:ATELIER_DATA_DIR"
Push-Location $PSScriptRoot
try {
    if ($Mode -eq 'Desktop') {
        & $python window.py
    } else {
        Write-Host "Open http://127.0.0.1:$Port (Ctrl+C stops the server)."
        & $python tests/dev_server.py --port $Port
    }
    if ($LASTEXITCODE -ne 0) { throw "Atelier exited with code $LASTEXITCODE" }
} finally { Pop-Location }

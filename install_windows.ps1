# ── Xenia — Windows installer (uv) ───────────────────────────────────────────
# Tested on Windows 10 / 11 with PowerShell 5.1 and PowerShell 7+.
#
# FIRST TIME SETUP — run this once in PowerShell as Administrator:
#   Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
#
# Then run normally (no admin required):
#   .\install_windows.ps1
#   $env:MTG_DATA_DIR = "D:\my_data"; .\install_windows.ps1
#
# On subsequent runs the script skips already-installed steps and just starts
# the server.
# ─────────────────────────────────────────────────────────────────────────────
param(
    [string]$DataDir  = "",
    [int]   $Port     = 8994
)

$ErrorActionPreference = "Stop"

# ── colours ───────────────────────────────────────────────────────────────────
function log  { param($msg) Write-Host "[xenia] $msg" -ForegroundColor Cyan   }
function ok   { param($msg) Write-Host "[xenia] $msg" -ForegroundColor Green  }
function err  { param($msg) Write-Host "[xenia] $msg" -ForegroundColor Red; exit 1 }

# ── paths ─────────────────────────────────────────────────────────────────────
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path

if ($DataDir -eq "" -and $env:MTG_DATA_DIR) {
    $DataDir = $env:MTG_DATA_DIR
}
if ($DataDir -eq "") {
    $DataDir = Join-Path $ScriptDir "data"
}

$VenvDir  = Join-Path $ScriptDir ".venv"
$BackendDir = Join-Path $ScriptDir "backend"
$EnvFile  = Join-Path $BackendDir ".env"

log "Xenia installer — Windows"
log "Script dir : $ScriptDir"
log "Data dir   : $DataDir"
log "Port       : $Port"
Write-Host ""

# ── 1. Python check ───────────────────────────────────────────────────────────
# uv will download Python 3.11 itself, but warn if Python is missing entirely
# so the user knows what is happening.
$PythonOk = $false
try {
    $pyver = & python --version 2>&1
    if ($pyver -match "3\.(1[1-9]|[2-9]\d)") { $PythonOk = $true }
} catch {}

if (-not $PythonOk) {
    log "Python 3.11+ not found on PATH — uv will download and manage it automatically."
}

# ── 2. uv ─────────────────────────────────────────────────────────────────────
$uvCmd = Get-Command uv -ErrorAction SilentlyContinue
if (-not $uvCmd) {
    log "Installing uv..."
    Invoke-RestMethod https://astral.sh/uv/install.ps1 | Invoke-Expression
    # refresh PATH for this session
    $env:PATH = [System.Environment]::GetEnvironmentVariable("PATH","User") + ";" + $env:PATH
}

$uvVer = & uv --version 2>&1
ok "uv $uvVer"

# ── 3. virtual environment ────────────────────────────────────────────────────
if (-not (Test-Path $VenvDir)) {
    log "Creating virtual environment (Python 3.11)..."
    & uv venv $VenvDir --python 3.11
}
ok "Virtual environment at $VenvDir"

# activation script path
$ActivateScript = Join-Path $VenvDir "Scripts\Activate.ps1"
if (-not (Test-Path $ActivateScript)) {
    err "Could not find venv activation script at $ActivateScript"
}
. $ActivateScript

# ── 4. install Python packages ────────────────────────────────────────────────
log "Installing Python packages (this takes a few minutes the first time)..."

# On Windows, pyresample / rasterio / pyproj ship as pre-built wheels on PyPI
# for CPython 3.11, so plain pip install works without system libs.
# satpy[all] pulls in the full reader stack including FCI, GOES, SEVIRI.
& uv pip install `
    "fastapi>=0.111" `
    "uvicorn[standard]>=0.29" `
    "pydantic>=2.0" `
    "python-multipart" `
    "python-dotenv" `
    "numpy>=1.26" `
    "scipy>=1.12" `
    "xarray>=2024.1" `
    "netcdf4" `
    "h5py" `
    "h5netcdf" `
    "dask[distributed]" `
    "pyresample>=3.0" `
    "pyproj>=3.6" `
    "rasterio" `
    "matplotlib>=3.8" `
    "Pillow>=10.0" `
    "satpy[all]" `
    "uxarray" `
    "pycoast" `
    "trollimage" `
    "pyorbital" `
    "pykdtree"

ok "Python packages installed"

# ── 5. data directory ─────────────────────────────────────────────────────────
New-Item -ItemType Directory -Force -Path $DataDir | Out-Null
ok "Data directory: $DataDir"

# ── 6. .env file ─────────────────────────────────────────────────────────────
if (-not (Test-Path $EnvFile)) {
    log "Creating .env file..."
    "MTG_DATA_DIR=$DataDir" | Set-Content $EnvFile -Encoding UTF8
} else {
    # update existing
    (Get-Content $EnvFile) -replace "^MTG_DATA_DIR=.*", "MTG_DATA_DIR=$DataDir" |
        Set-Content $EnvFile -Encoding UTF8
}
ok ".env written"

# ── 7. open browser after a short delay ───────────────────────────────────────
$url = "http://localhost:$Port"
Start-Job -ScriptBlock {
    param($u)
    Start-Sleep -Seconds 3
    Start-Process $u
} -ArgumentList $url | Out-Null

# ── 8. launch ─────────────────────────────────────────────────────────────────
Write-Host ""
ok "Starting Xenia on $url"
Write-Host "[xenia]   -> Put your data files in: $DataDir" -ForegroundColor Cyan
Write-Host "[xenia]   -> Browser will open automatically" -ForegroundColor Cyan
Write-Host "[xenia]   -> Press Ctrl+C to stop" -ForegroundColor Cyan
Write-Host ""

Set-Location $BackendDir
& uvicorn main:app --host 0.0.0.0 --port $Port --workers 1 --no-access-log

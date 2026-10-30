# FINN on Windows: setup, tests, live smoke test, then start the app.
# Usage (from the repo root, in PowerShell):
#   powershell -ExecutionPolicy Bypass -File scripts\run_windows.ps1            # everything
#   powershell -ExecutionPolicy Bypass -File scripts\run_windows.ps1 -SkipSmoke # just start the app
param([switch]$SkipSmoke, [switch]$SkipTests, [string]$Symbol = "TRENT", [int]$Port = 8000)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
$Log = Join-Path $Root "smoke_result.txt"

function Step($msg) { Write-Host "`n== $msg" -ForegroundColor Cyan }

Step "Finding Python 3.10+"
$py = $null
foreach ($cand in @("py -3", "python", "python3", "$env:USERPROFILE\anaconda3\python.exe")) {
    try {
        $v = & cmd /c "$cand -c ""import sys;print(sys.version_info[0]*100+sys.version_info[1])""" 2>$null
        if ($LASTEXITCODE -eq 0 -and [int]$v -ge 310) { $py = $cand; break }
    } catch {}
}
if (-not $py) { throw "Python 3.10+ not found. Install from python.org (tick 'Add to PATH') and re-run." }
Write-Host "Using: $py"

Step "Virtual environment + dependencies"
if (-not (Test-Path ".venv\Scripts\python.exe")) { & cmd /c "$py -m venv .venv" }
$vpy = Join-Path $Root ".venv\Scripts\python.exe"
& $vpy -m pip install --upgrade pip -q
& $vpy -m pip install -q -r backend\requirements-dev.txt
if ($LASTEXITCODE -ne 0) { throw "pip install failed" }

Step "Checking .env"
if (-not (Test-Path ".env")) { Copy-Item ".env.example" ".env"; Write-Host "Created .env from the example." -ForegroundColor Yellow }
$envText = Get-Content ".env" -Raw
if ($envText -notmatch "FINN_LLM_API_KEY=\S{10,}" -or $envText -match "your-key-here") {
    Write-Host "No Gemini key in .env - AI sections will be disabled. Add a line: FINN_LLM_API_KEY=AIza..." -ForegroundColor Yellow
}
if ($envText -notmatch "FINN_LLM_PROVIDER=") { Add-Content ".env" "`nFINN_LLM_PROVIDER=gemini" }

Step "Frontend"
if (-not (Test-Path "frontend\dist\index.html")) {
    if (Get-Command npm -ErrorAction SilentlyContinue) {
        Push-Location frontend; npm ci; npm run build; Pop-Location
    } else { Write-Host "frontend\dist missing and npm not installed - API will run but the UI won't load." -ForegroundColor Yellow }
} else { Write-Host "Using prebuilt frontend\dist" }

$env:FINN_DATA_DIR = Join-Path $Root "var"
$env:PYTHONIOENCODING = "utf-8"
Push-Location backend
if (-not $SkipTests) {
    Step "Unit tests (offline)"
    $env:FINN_FIXTURE_MODE = "1"
    & $vpy -m pytest -q -p no:warnings
    Remove-Item Env:FINN_FIXTURE_MODE
}
if (-not $SkipSmoke) {
    Step "LIVE smoke test (real NSE/BSE/Yahoo/Screener/Gemini) - writes smoke_result.txt"
    $env:FINN_FIXTURE_MODE = "0"
    & $vpy ..\scripts\smoke_live.py $Symbol 2>&1 | Tee-Object -FilePath $Log
}
Step "Starting FINN on http://localhost:$Port  (Ctrl+C to stop)"
$env:FINN_FIXTURE_MODE = "0"
Start-Process "http://localhost:$Port"
& $vpy -m uvicorn app.main:app --port $Port
Pop-Location

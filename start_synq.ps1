# ==============================================================================
# HedgeLab - Complete Local Development Environment Startup Script
# Starts Ollama (if not running), FastAPI Backend, and Vite Frontend.
# Tracks started PIDs in .logs/hedgelab_pids.json for graceful teardown.
# ==============================================================================

param(
    [string]$OllamaModel = "qwen3.5:4b",
    [int]$BackendPort = 8000,
    [int]$FrontendPort = 5173,
    [int]$OllamaPort = 11434
)

$ErrorActionPreference = "Stop"
$ScriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Definition
Set-Location $ScriptRoot

Write-Host "================================================================================" -ForegroundColor Cyan
Write-Host "   HEDGELAB - AUTONOMOUS MARKET INTELLIGENCE LOCAL LAUNCHER" -ForegroundColor Cyan
Write-Host "================================================================================" -ForegroundColor Cyan

# 1. Ensure logs directory exists
$LogDir = Join-Path $ScriptRoot ".logs"
if (!(Test-Path $LogDir)) {
    New-Item -ItemType Directory -Path $LogDir | Out-Null
}
$PidFile = Join-Path $LogDir "hedgelab_pids.json"
$BackendLog = Join-Path $LogDir "backend.log"
$BackendErrLog = Join-Path $LogDir "backend.err.log"
$FrontendLog = Join-Path $LogDir "frontend.log"
$FrontendErrLog = Join-Path $LogDir "frontend.err.log"
$OllamaLog = Join-Path $LogDir "ollama.log"
$OllamaErrLog = Join-Path $LogDir "ollama.err.log"

$StartedProcesses = @{
    ollama_pid = $null
    backend_pid = $null
    frontend_pid = $null
    started_at = (Get-Date).ToString("o")
}

# 2. Validate prerequisites
Write-Host "[1/6] Checking prerequisites..." -ForegroundColor White

$pyCmd = Get-Command python -ErrorAction SilentlyContinue
$PythonExe = if ($pyCmd) { $pyCmd.Source } else { $null }
if (!$PythonExe) {
    Write-Host "[FAIL] Python 3.10+ not found in PATH. Please install Python and try again." -ForegroundColor Red
    exit 1
}

$npmCmd = Get-Command npm -ErrorAction SilentlyContinue
$NpmExe = if ($npmCmd) { $npmCmd.Source } else { $null }
if (!$NpmExe) {
    Write-Host "[FAIL] Node.js / npm not found in PATH. Please install Node.js and try again." -ForegroundColor Red
    exit 1
}

$ollamaCmd = Get-Command ollama -ErrorAction SilentlyContinue
$OllamaExe = if ($ollamaCmd) { $ollamaCmd.Source } else { $null }

Write-Host "      Python: $PythonExe" -ForegroundColor DarkGray
Write-Host "      npm   : $NpmExe" -ForegroundColor DarkGray

# 3. Check and start Ollama if needed
Write-Host "[2/6] Checking Ollama service..." -ForegroundColor White
$OllamaRunning = $false
try {
    $tagResp = Invoke-RestMethod -Uri "http://127.0.0.1:${OllamaPort}/api/tags" -Method Get -TimeoutSec 2 -ErrorAction Stop
    $OllamaRunning = $true
} catch {
    $OllamaRunning = $false
}

if (!$OllamaRunning) {
    if ($OllamaExe) {
        Write-Host "      Starting 'ollama serve' in background..." -ForegroundColor Yellow
        $ollamaProc = Start-Process -FilePath "ollama" -ArgumentList "serve" -RedirectStandardOutput $OllamaLog -RedirectStandardError $OllamaErrLog -PassThru -NoNewWindow
        $StartedProcesses.ollama_pid = $ollamaProc.Id
        Start-Sleep -Seconds 3
        try {
            $tagResp = Invoke-RestMethod -Uri "http://127.0.0.1:${OllamaPort}/api/tags" -Method Get -TimeoutSec 5 -ErrorAction Stop
            $OllamaRunning = $true
        } catch {
            Write-Host "[WARN] Ollama could not be started automatically. Continuing in deterministic fallback mode." -ForegroundColor Yellow
        }
    } else {
        Write-Host "[WARN] Ollama executable not found. HedgeLab will operate in verified deterministic mode." -ForegroundColor Yellow
    }
}

if ($OllamaRunning) {
    $installedModels = @($tagResp.models | ForEach-Object { $_.name })
    $hasModel = $installedModels | Where-Object { $_ -like "*$OllamaModel*" }
    if ($hasModel) {
        Write-Host "      [OK] Ollama connected on port ${OllamaPort}. Model '$OllamaModel' verified." -ForegroundColor Green
    } else {
        Write-Host "      [WARN] Ollama active, but model '$OllamaModel' not found in: $($installedModels -join ', ')." -ForegroundColor Yellow
        Write-Host "             To install: run 'ollama pull $OllamaModel' in a separate terminal." -ForegroundColor Yellow
        Write-Host "             System will use deterministic local fallbacks without cloud APIs." -ForegroundColor DarkGray
    }
}

# 3b. Check and start local 0xramm provisional market API provider (port 8787)
Write-Host "      Checking 0xramm provisional market API provider on port 8787..." -ForegroundColor White
$rammConn = Get-NetTCPConnection -LocalPort 8787 -State Listen -ErrorAction SilentlyContinue
if ($rammConn) {
    Write-Host "      [OK] 0xramm provider active on port 8787 (PID: $($rammConn.OwningProcess[0]))." -ForegroundColor Green
} else {
    $rammServerScript = Join-Path $ScriptRoot "services\ramm_stock_api\server.mjs"
    if (Test-Path $rammServerScript) {
        $rammProc = Start-Process -FilePath "node" -ArgumentList "`"$rammServerScript`"" `
            -WorkingDirectory $ScriptRoot `
            -PassThru -NoNewWindow
        $StartedProcesses.ramm_pid = $rammProc.Id
        Write-Host "      [OK] Launched local 0xramm provider server on port 8787 (PID: $($rammProc.Id))." -ForegroundColor Green
    }
}

# 4. Check Backend Port & Launch FastAPI
Write-Host "[3/6] Starting FastAPI backend on port ${BackendPort}..." -ForegroundColor White

$backendConn = Get-NetTCPConnection -LocalPort $BackendPort -State Listen -ErrorAction SilentlyContinue
if ($backendConn) {
    # Check if existing process is healthy
    try {
        $health = Invoke-RestMethod -Uri "http://127.0.0.1:${BackendPort}/api/v1/health" -Method Get -TimeoutSec 2 -ErrorAction Stop
        if ($health.status -eq "ok") {
            Write-Host "      [OK] FastAPI backend is already running on port ${BackendPort} (PID: $($backendConn.OwningProcess[0]))." -ForegroundColor Green
        }
    } catch {
        Write-Host "[WARN] Port ${BackendPort} occupied by non-HedgeLab process (PID: $($backendConn.OwningProcess[0])). Attempting to proceed." -ForegroundColor Yellow
    }
} else {
    $backendProc = Start-Process -FilePath "python" `
        -ArgumentList "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "$BackendPort", "--app-dir", "backend" `
        -WorkingDirectory $ScriptRoot `
        -RedirectStandardOutput $BackendLog `
        -RedirectStandardError $BackendErrLog `
        -PassThru -NoNewWindow

    $StartedProcesses.backend_pid = $backendProc.Id
    Write-Host "      Launched backend process (PID: $($backendProc.Id))." -ForegroundColor DarkGray
}

# 5. Wait for Backend Health
Write-Host "[4/6] Waiting for FastAPI backend to respond..." -ForegroundColor White
$backendHealthy = $false
$retries = 25
while ($retries -gt 0 -and !$backendHealthy) {
    Start-Sleep -Milliseconds 600
    try {
        $resp = Invoke-RestMethod -Uri "http://127.0.0.1:${BackendPort}/api/v1/health" -Method Get -TimeoutSec 2 -ErrorAction Stop
        if ($resp.status -eq "ok") {
            $backendHealthy = $true
            break
        }
    } catch {
        $retries--
    }
}

if (!$backendHealthy) {
    Write-Host "[FAIL] FastAPI backend failed to respond within 15 seconds." -ForegroundColor Red
    Write-Host "       Check log: $BackendLog" -ForegroundColor Yellow
    exit 1
}
Write-Host "      [OK] Backend health verified: $($resp.app_name) | DB: $($resp.database_status) | Ollama: $($resp.ollama_status)" -ForegroundColor Green

# 6. Check Frontend Port & Launch Vite Dev Server
Write-Host "[5/6] Starting Vite frontend on port ${FrontendPort}..." -ForegroundColor White
$frontendConn = Get-NetTCPConnection -LocalPort $FrontendPort -State Listen -ErrorAction SilentlyContinue
if ($frontendConn) {
    Write-Host "      [OK] Frontend is already running on port ${FrontendPort} (PID: $($frontendConn.OwningProcess[0]))." -ForegroundColor Green
} else {
    $env:CI = "true"
    $nodeExe = (Get-Command node -ErrorAction SilentlyContinue)
    $nodePath = if ($nodeExe) { $nodeExe.Source } else { "node" }
    $viteScript = Join-Path $ScriptRoot "node_modules\vite\bin\vite.js"

    if (Test-Path $viteScript) {
        $frontendProc = Start-Process -FilePath $nodePath `
            -ArgumentList "`"$viteScript`"", "--host", "0.0.0.0", "--port", "$FrontendPort" `
            -WorkingDirectory $ScriptRoot `
            -RedirectStandardOutput $FrontendLog `
            -RedirectStandardError $FrontendErrLog `
            -PassThru -NoNewWindow
    } else {
        $frontendProc = Start-Process -FilePath "npx.cmd" `
            -ArgumentList "vite", "--host", "0.0.0.0", "--port", "$FrontendPort" `
            -WorkingDirectory $ScriptRoot `
            -RedirectStandardOutput $FrontendLog `
            -RedirectStandardError $FrontendErrLog `
            -PassThru -NoNewWindow
    }

    $StartedProcesses.frontend_pid = $frontendProc.Id
    Write-Host "      Launched frontend process (PID: $($frontendProc.Id))." -ForegroundColor DarkGray
}

# 7. Wait for Frontend
Write-Host "[6/6] Verifying frontend accessibility..." -ForegroundColor White
$frontendReady = $false
$retries = 20
while ($retries -gt 0 -and !$frontendReady) {
    Start-Sleep -Milliseconds 600
    try {
        $fResp = Invoke-WebRequest -Uri "http://127.0.0.1:${FrontendPort}" -UseBasicParsing -TimeoutSec 2 -ErrorAction Stop
        if ($fResp.StatusCode -eq 200) {
            $frontendReady = $true
            break
        }
    } catch {
        $retries--
    }
}

if (!$frontendReady) {
    Write-Host "[WARN] Frontend did not respond immediately, but may still be compiling." -ForegroundColor Yellow
    Write-Host "       Check log: $FrontendLog" -ForegroundColor DarkGray
} else {
    Write-Host "      [OK] Frontend dev server ready." -ForegroundColor Green
}

# Save started PIDs to file for graceful shutdown
$StartedProcesses | ConvertTo-Json | Set-Content -Path $PidFile -Encoding UTF8

Write-Host "`n================================================================================" -ForegroundColor Cyan
Write-Host "   HEDGELAB SERVICES ARE LIVE AND OPERATIONAL" -ForegroundColor Cyan
Write-Host "================================================================================" -ForegroundColor Cyan
Write-Host "   Frontend Application : http://localhost:${FrontendPort}" -ForegroundColor Green
Write-Host "   FastAPI Swagger Docs : http://127.0.0.1:${BackendPort}/docs" -ForegroundColor White
Write-Host "   Health Endpoint      : http://127.0.0.1:${BackendPort}/api/v1/health" -ForegroundColor White
Write-Host "   Logs Directory       : $LogDir" -ForegroundColor DarkGray
Write-Host "   To stop services     : run 'powershell -File stop_hedgelab.ps1'" -ForegroundColor Yellow
Write-Host "================================================================================`n" -ForegroundColor Cyan

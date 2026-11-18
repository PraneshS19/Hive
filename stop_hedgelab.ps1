# ==============================================================================
# HedgeLab - Graceful Shutdown Script
# Terminates only the processes launched and recorded by start_hedgelab.ps1.
# Preserves SQLite database, historical market datasets, and Ollama server.
# ==============================================================================

$ScriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Definition
Set-Location $ScriptRoot

Write-Host "================================================================================" -ForegroundColor Cyan
Write-Host "   HEDGELAB - SHUTTING DOWN RECORDED LOCAL SERVICES" -ForegroundColor Cyan
Write-Host "================================================================================" -ForegroundColor Cyan

$PidFile = Join-Path $ScriptRoot ".logs\hedgelab_pids.json"

if (!(Test-Path $PidFile)) {
    Write-Host "[INFO] No active process record file found (.logs/hedgelab_pids.json)." -ForegroundColor Yellow
    Write-Host "       Checking for standalone HedgeLab processes on ports 8000 and 5173..." -ForegroundColor White

    $p8000 = Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue
    if ($p8000) {
        $proc = Get-Process -Id $p8000.OwningProcess[0] -ErrorAction SilentlyContinue
        if ($proc -and $proc.ProcessName -like "*python*") {
            Write-Host "       Stopping FastAPI backend (PID: $($proc.Id))..." -ForegroundColor Yellow
            Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
        }
    }

    $p5173 = Get-NetTCPConnection -LocalPort 5173 -State Listen -ErrorAction SilentlyContinue
    if ($p5173) {
        $proc = Get-Process -Id $p5173.OwningProcess[0] -ErrorAction SilentlyContinue
        if ($proc -and $proc.ProcessName -like "*node*") {
            Write-Host "       Stopping Vite frontend (PID: $($proc.Id))..." -ForegroundColor Yellow
            Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
        }
    }
    Write-Host "[OK] Shutdown complete. SQLite database and datasets untouched." -ForegroundColor Green
    exit 0
}

try {
    $pids = Get-Content -Path $PidFile -Raw | ConvertFrom-Json
} catch {
    Write-Host "[WARN] Could not parse PID file. Removing stale record." -ForegroundColor Yellow
    Remove-Item -Path $PidFile -Force -ErrorAction SilentlyContinue
    exit 0
}

# 1. Stop Frontend Dev Server
if ($pids.frontend_pid) {
    $fProc = Get-Process -Id $pids.frontend_pid -ErrorAction SilentlyContinue
    if ($fProc) {
        Write-Host "Stopping Vite frontend dev server (PID: $($fProc.Id))..." -ForegroundColor Yellow
        Stop-Process -Id $fProc.Id -Force -ErrorAction SilentlyContinue
        Write-Host "  [OK] Frontend stopped." -ForegroundColor Green
    } else {
        Write-Host "  [INFO] Frontend process (PID: $($pids.frontend_pid)) already exited." -ForegroundColor DarkGray
    }
}

# 2. Stop Backend Server
if ($pids.backend_pid) {
    $bProc = Get-Process -Id $pids.backend_pid -ErrorAction SilentlyContinue
    if ($bProc) {
        Write-Host "Stopping FastAPI backend server (PID: $($bProc.Id))..." -ForegroundColor Yellow
        Stop-Process -Id $bProc.Id -Force -ErrorAction SilentlyContinue
        Write-Host "  [OK] Backend stopped." -ForegroundColor Green
    } else {
        Write-Host "  [INFO] Backend process (PID: $($pids.backend_pid)) already exited." -ForegroundColor DarkGray
    }
}

# 3. Handle Ollama
# Keep Ollama running as other applications might share it, unless launched exclusively
if ($pids.ollama_pid) {
    Write-Host "  [INFO] Leaving Ollama server active on port 11434 for local LLM availability." -ForegroundColor DarkGray
}

# Remove PID file
Remove-Item -Path $PidFile -Force -ErrorAction SilentlyContinue

Write-Host "`n[OK] HedgeLab services gracefully stopped." -ForegroundColor Green
Write-Host "     Database at 'backend/hedgelab.db' is preserved." -ForegroundColor White
Write-Host "     Historical market datasets at 'backend/data/historical' are preserved." -ForegroundColor White
Write-Host "================================================================================`n" -ForegroundColor Cyan

param(
    [string]$PythonExe = "$PSScriptRoot/backend/.venv/Scripts/python.exe",
    [ValidateRange(1, 65535)][int]$BackendPort = 8000,
    [ValidateRange(1, 65535)][int]$FrontendPort = 5173,
    [switch]$NoOllamaStart
)

$ErrorActionPreference = 'Stop'
$logDir = Join-Path $PSScriptRoot '.logs'
$processFile = Join-Path $logDir 'hive-services.json'
$vite = Join-Path $PSScriptRoot 'node_modules/vite/bin/vite.js'
if (-not (Test-Path -LiteralPath $PythonExe) -or -not (Test-Path -LiteralPath $vite)) {
    throw 'Install the Python environment and locked npm dependencies from the README first.'
}
$PythonExe = (Resolve-Path -LiteralPath $PythonExe).Path
$nodeExe = (Get-Command node -ErrorAction Stop).Source
if (Test-Path -LiteralPath $processFile) { throw 'Run stop_hive.ps1 before starting another HIVE session.' }
if ($BackendPort -eq $FrontendPort) { throw 'HIVE backend and frontend need different ports.' }
foreach ($port in @($BackendPort, $FrontendPort)) {
    if (Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue) {
        throw "Port $port is already occupied. Choose another port or stop the service that owns it."
    }
}
New-Item -ItemType Directory -Path $logDir -Force | Out-Null
New-Item -ItemType File -Path $processFile -Value '{}' -ErrorAction Stop | Out-Null
$services = @{}

function Start-HiveProcess($role, $executable, $arguments, $directory) {
    $process = Start-Process -FilePath $executable -ArgumentList $arguments -WorkingDirectory $directory `
        -RedirectStandardOutput (Join-Path $logDir "$role.log") `
        -RedirectStandardError (Join-Path $logDir "$role.err.log") -WindowStyle Hidden -PassThru
    $services[$role] = @{ id = $process.Id; started = $process.StartTime.ToUniversalTime().Ticks }
    $services | ConvertTo-Json | Set-Content -LiteralPath $processFile -Encoding UTF8
    return $process
}

function Wait-HiveEndpoint($uri, $process) {
    $deadline = [DateTime]::UtcNow.AddSeconds(45)
    do {
        if ($process.HasExited) { break }
        try { return Invoke-WebRequest -Uri $uri -UseBasicParsing -TimeoutSec 2 }
        catch { Start-Sleep -Milliseconds 400 }
    } while ([DateTime]::UtcNow -lt $deadline)
    throw "HIVE service did not respond at $uri. Check $logDir for details."
}

$previousProxyTarget = $env:HIVE_DEV_API_TARGET
$previousOllamaHost = $env:OLLAMA_HOST
$previousCi = $env:CI
try {
    $api = "http://127.0.0.1:$BackendPort"
    $ui = "http://127.0.0.1:$FrontendPort"
    $backend = Start-HiveProcess 'backend' $PythonExe @('-m','uvicorn','app.main:app','--host','127.0.0.1','--port',$BackendPort) (Join-Path $PSScriptRoot 'backend')
    $health = Wait-HiveEndpoint "$api/api/v1/health" $backend
    if (($health.Content | ConvertFrom-Json).status -ne 'ok') { throw 'HIVE backend reported an unhealthy state.' }

    $modelStatus = Invoke-RestMethod "$api/api/v1/model-status" -TimeoutSec 10
    $ollama = Get-Command ollama -ErrorAction SilentlyContinue
    $modelUri = [uri]$modelStatus.base_url
    if (-not $NoOllamaStart -and $ollama -and $modelUri.IsLoopback -and $modelUri.Scheme -eq 'http' `
            -and -not $modelStatus.ollama_available -and $modelStatus.status_message -notmatch 'disabled') {
        $env:OLLAMA_HOST = $modelUri.Authority
        $localModelProcess = Start-HiveProcess 'ollama' $ollama.Source @('serve') $PSScriptRoot
        try {
            Wait-HiveEndpoint "$($modelStatus.base_url)/api/tags" $localModelProcess | Out-Null
            $modelStatus = Invoke-RestMethod "$api/api/v1/model-status" -TimeoutSec 10
        } catch { Write-Warning 'Ollama could not be started. See the HIVE log directory.' }
    }
    if (-not $modelStatus.ready) {
        Write-Warning $modelStatus.status_message
        $modelStatus.pull_commands | ForEach-Object { Write-Host $_ }
    }

    $sidecar = Join-Path $PSScriptRoot 'services/ramm_stock_api/server.mjs'
    if ((Test-Path -LiteralPath $sidecar) -and -not (Get-NetTCPConnection -LocalPort 8787 -State Listen -ErrorAction SilentlyContinue)) {
        Start-HiveProcess 'market-data' $nodeExe @('"' + $sidecar + '"') $PSScriptRoot | Out-Null
    }

    $env:HIVE_DEV_API_TARGET = $api
    $env:CI = 'true'
    $frontend = Start-HiveProcess 'frontend' $nodeExe @('"' + $vite + '"','--host','127.0.0.1','--strictPort','--port',$FrontendPort) $PSScriptRoot
    Wait-HiveEndpoint $ui $frontend | Out-Null
    Wait-HiveEndpoint "$ui/api/v1/health" $frontend | Out-Null
    Write-Host "HIVE — Analyze. Evaluate. Evolve."
    Write-Host "Application: $ui  API documentation: $api/docs"
    Write-Host 'Stop services with stop_hive.ps1.'
} catch {
    & (Join-Path $PSScriptRoot 'stop_hive.ps1')
    throw
} finally {
    $env:HIVE_DEV_API_TARGET = $previousProxyTarget
    $env:OLLAMA_HOST = $previousOllamaHost
    $env:CI = $previousCi
}

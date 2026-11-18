$ErrorActionPreference = 'Stop'
$processFile = Join-Path $PSScriptRoot '.logs/hive-services.json'
if (-not (Test-Path -LiteralPath $processFile)) {
    Write-Host 'No HIVE services are recorded for this checkout.'
    return
}

$services = Get-Content -LiteralPath $processFile -Raw | ConvertFrom-Json
foreach ($role in 'frontend', 'backend', 'market-data') {
    $record = $services.$role
    if (-not $record) { continue }
    $process = Get-Process -Id $record.id -ErrorAction SilentlyContinue
    if ($process -and $process.StartTime.ToUniversalTime().Ticks -eq [long]$record.started) {
        # The Windows Python launcher can spawn a child that owns the socket.
        taskkill.exe /PID $process.Id /T /F | Out-Null
        if ($LASTEXITCODE -and (Get-Process -Id $record.id -ErrorAction SilentlyContinue)) {
            throw "Could not stop the recorded HIVE $role."
        }
        Write-Host "Stopped HIVE $role."
    }
}
if ($services.ollama) { Write-Host 'Ollama remains available for other applications.' }
Remove-Item -LiteralPath $processFile
Write-Host 'HIVE databases and datasets remain in place.'

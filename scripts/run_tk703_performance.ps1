param(
    [string]$TargetHost = "http://127.0.0.1:18000",
    [int]$Users = 12,
    [double]$SpawnRate = 3,
    [string]$RunTime = "2m",
    [int]$MinimumRequests = 20,
    [string]$OutputDirectory = "artifacts/tk-703-03"
)

$ErrorActionPreference = "Stop"

if (-not $env:PERF_USERNAME -or -not $env:PERF_PASSWORD) {
    throw "Set PERF_USERNAME and PERF_PASSWORD in the current PowerShell session."
}
if ($Users -lt 1 -or $SpawnRate -le 0 -or $MinimumRequests -lt 1) {
    throw "Users, SpawnRate, and MinimumRequests must be positive."
}

$repositoryRoot = Split-Path -Parent $PSScriptRoot
$outputPath = Join-Path $repositoryRoot $OutputDirectory
$csvPrefix = Join-Path $outputPath "locust"
$statsCsv = "${csvPrefix}_stats.csv"
$jsonReport = Join-Path $outputPath "gate-result.json"
$markdownReport = Join-Path $outputPath "gate-result.md"
$htmlReport = Join-Path $outputPath "locust-report.html"

New-Item -ItemType Directory -Force -Path $outputPath | Out-Null
$originalPythonPath = $env:PYTHONPATH
$backendPath = Join-Path $repositoryRoot "backend"
$env:PYTHONPATH = if ($originalPythonPath) {
    "$backendPath$([System.IO.Path]::PathSeparator)$originalPythonPath"
} else {
    $backendPath
}
Push-Location $repositoryRoot
try {
    py -3.13 -m locust `
        -f backend/performance/locustfile.py `
        --host $TargetHost `
        --headless `
        --users $Users `
        --spawn-rate $SpawnRate `
        --run-time $RunTime `
        --stop-timeout 5 `
        --csv $csvPrefix `
        --csv-full-history `
        --html $htmlReport `
        --exit-code-on-error 0 `
        --only-summary
    if ($LASTEXITCODE -ne 0) {
        throw "Locust failed with exit code $LASTEXITCODE."
    }

    py -3.13 -m performance.gate `
        $statsCsv `
        --minimum-requests $MinimumRequests `
        --json $jsonReport `
        --markdown $markdownReport
    if ($LASTEXITCODE -ne 0) {
        Write-Error "TK-703-03 performance gate failed. See $markdownReport"
    }
    Write-Host "TK-703-03 performance gate passed. See $markdownReport"
}
finally {
    Pop-Location
    if ($null -eq $originalPythonPath) {
        Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue
    } else {
        $env:PYTHONPATH = $originalPythonPath
    }
}

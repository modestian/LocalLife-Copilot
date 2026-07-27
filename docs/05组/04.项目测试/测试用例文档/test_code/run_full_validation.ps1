param(
    [string]$OutputDirectory = '',
    [switch]$IntegrationOnly
)

$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..\..')).Path
$outputPath = if ($OutputDirectory) {
    Join-Path $repoRoot $OutputDirectory
} else {
    Join-Path (Split-Path -Parent $PSScriptRoot) 'execution_results\current\full-validation'
}
New-Item -ItemType Directory -Force -Path $outputPath | Out-Null

function Get-DotEnvValue {
    param([Parameter(Mandatory)][string]$Name)
    $line = Get-Content -LiteralPath (Join-Path $repoRoot '.env') |
        Where-Object { $_ -match "^$([regex]::Escape($Name))=" } |
        Select-Object -First 1
    if (-not $line) { throw "Missing $Name in .env" }
    return ($line -split '=', 2)[1]
}

$results = [System.Collections.Generic.List[object]]::new()
if ($IntegrationOnly -and (Test-Path -LiteralPath (Join-Path $outputPath 'summary.json'))) {
    $previousSummary = Get-Content -Raw -LiteralPath (Join-Path $outputPath 'summary.json') |
        ConvertFrom-Json
    foreach ($previousResult in $previousSummary.results) {
        if ($previousResult.name -ne 'MySQL and Redis integration tests') {
            $results.Add($previousResult)
        }
    }
}
function Invoke-Evidence {
    param(
        [Parameter(Mandatory)][string]$Name,
        [Parameter(Mandatory)][string]$WorkingDirectory,
        [Parameter(Mandatory)][scriptblock]$Action,
        [Parameter(Mandatory)][string]$LogName
    )
    $logPath = Join-Path $outputPath $LogName
    $started = [DateTime]::UtcNow
    $previousErrorActionPreference = $ErrorActionPreference
    Push-Location $WorkingDirectory
    try {
        $ErrorActionPreference = 'Continue'
        & $Action 2>&1 | Tee-Object -LiteralPath $logPath
        $exitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $previousErrorActionPreference
        Pop-Location
    }
    $finished = [DateTime]::UtcNow
    $results.Add([pscustomobject]@{
        name = $Name
        status = if ($exitCode -eq 0) { 'PASS' } else { 'FAIL' }
        exit_code = $exitCode
        started_at_utc = $started.ToString('o')
        finished_at_utc = $finished.ToString('o')
        duration_seconds = [math]::Round(($finished - $started).TotalSeconds, 3)
        log = $LogName
    })
}

$databaseName = "local_life_delivery_$([DateTime]::UtcNow.ToString('yyyyMMddHHmmss'))"
if ($databaseName -notmatch '^[a-z0-9_]+$') {
    throw 'Generated integration database name is unsafe.'
}
$mysqlUser = Get-DotEnvValue -Name 'MYSQL_USER'
$mysqlPassword = Get-DotEnvValue -Name 'MYSQL_PASSWORD'
$mysqlRootPassword = Get-DotEnvValue -Name 'MYSQL_ROOT_PASSWORD'
$integrationDatabaseCreated = $false

Push-Location $repoRoot
try {
    if (-not $IntegrationOnly) {
        Invoke-Evidence -Name 'Backend full pytest suite' -WorkingDirectory (Join-Path $repoRoot 'backend') `
            -LogName '01-backend-full.log' -Action {
                py -3.13 -m pytest tests -q `
                    --junitxml "$outputPath\backend-full-junit.xml"
            }

        Invoke-Evidence -Name 'Frontend full Vitest suite' -WorkingDirectory (Join-Path $repoRoot 'frontend') `
            -LogName '02-frontend-full.log' -Action {
                npm test -- --reporter=default --reporter=junit `
                    --outputFile.junit="$outputPath\frontend-full-junit.xml"
            }

        Invoke-Evidence -Name 'Frontend lint' -WorkingDirectory (Join-Path $repoRoot 'frontend') `
            -LogName '03-frontend-lint.log' -Action { npm run lint }

        Invoke-Evidence -Name 'Frontend production build' -WorkingDirectory (Join-Path $repoRoot 'frontend') `
            -LogName '04-frontend-build.log' -Action { npm run build }
    }

    $createSql = "CREATE DATABASE $databaseName CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci; " +
        "GRANT ALL PRIVILEGES ON $databaseName.* TO '$mysqlUser'@'%'; FLUSH PRIVILEGES;"
    docker compose exec -T mysql mysql -uroot "-p$mysqlRootPassword" -e $createSql
    if ($LASTEXITCODE -ne 0) { throw 'Creating the isolated integration database failed.' }
    $integrationDatabaseCreated = $true

    $oldValues = @{
        AUTH_MYSQL_INTEGRATION = $env:AUTH_MYSQL_INTEGRATION
        AUTH_MYSQL_DATABASE_URL = $env:AUTH_MYSQL_DATABASE_URL
        MIGRATION_DATABASE_URL = $env:MIGRATION_DATABASE_URL
        ST102_MYSQL_INTEGRATION = $env:ST102_MYSQL_INTEGRATION
        ST103_MYSQL_INTEGRATION = $env:ST103_MYSQL_INTEGRATION
        MYSQL_DATABASE = $env:MYSQL_DATABASE
        MYSQL_USER = $env:MYSQL_USER
        MYSQL_PASSWORD = $env:MYSQL_PASSWORD
        MYSQL_HOST = $env:MYSQL_HOST
        MYSQL_PORT = $env:MYSQL_PORT
        REDIS_URL = $env:REDIS_URL
    }
    try {
        $escapedPassword = [uri]::EscapeDataString($mysqlPassword)
        $env:AUTH_MYSQL_INTEGRATION = '1'
        $env:AUTH_MYSQL_DATABASE_URL =
            "mysql+asyncmy://${mysqlUser}:${escapedPassword}@127.0.0.1:13306/${databaseName}?charset=utf8mb4"
        $env:MIGRATION_DATABASE_URL =
            "mysql+pymysql://${mysqlUser}:${escapedPassword}@127.0.0.1:13306/${databaseName}?charset=utf8mb4"
        $env:ST102_MYSQL_INTEGRATION = '1'
        $env:ST103_MYSQL_INTEGRATION = '1'
        $env:MYSQL_DATABASE = $databaseName
        $env:MYSQL_USER = $mysqlUser
        $env:MYSQL_PASSWORD = $mysqlPassword
        $env:MYSQL_HOST = '127.0.0.1'
        $env:MYSQL_PORT = '13306'
        $env:REDIS_URL = 'redis://127.0.0.1:6379/0'

        Invoke-Evidence -Name 'MySQL and Redis integration tests' `
            -WorkingDirectory (Join-Path $repoRoot 'backend') `
            -LogName '05-mysql-redis-integration.log' -Action {
                py -3.13 -m pytest `
                    tests/test_identity_migration_mysql_integration.py `
                    tests/test_auth_mysql_integration.py `
                    tests/test_authorization_mysql_integration.py `
                    tests/test_st102_mysql_integration.py `
                    tests/test_governance_safety.py `
                    -q --junitxml "$outputPath\integration-junit.xml"
            }
    }
    finally {
        foreach ($key in $oldValues.Keys) {
            if ($null -eq $oldValues[$key]) {
                Remove-Item "Env:$key" -ErrorAction SilentlyContinue
            }
            else {
                Set-Item "Env:$key" $oldValues[$key]
            }
        }
    }
}
finally {
    if ($integrationDatabaseCreated) {
        $dropSql = "DROP DATABASE IF EXISTS $databaseName;"
        docker compose exec -T mysql mysql -uroot "-p$mysqlRootPassword" -e $dropSql
    }
    Pop-Location
}

$passed = @($results | Where-Object status -eq 'PASS').Count
$summary = [pscustomobject]@{
    generated_at_utc = [DateTime]::UtcNow.ToString('o')
    overall_status = if ($passed -eq $results.Count) { 'PASS' } else { 'FAIL' }
    checks_total = $results.Count
    checks_passed = $passed
    checks_failed = $results.Count - $passed
    results = $results
}
$summary | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $outputPath 'summary.json') -Encoding UTF8

$markdown = @(
    '# Full test and build validation'
    ''
    "- Generated at (UTC): $($summary.generated_at_utc)"
    "- Checks: $($summary.checks_total)"
    "- Passed: $($summary.checks_passed)"
    "- Failed: $($summary.checks_failed)"
    "- Overall result: **$($summary.overall_status)**"
    ''
    '| Check | Result | Duration (seconds) | Log |'
    '|---|---:|---:|---|'
)
foreach ($result in $results) {
    $markdown += "| $($result.name) | $($result.status) | $($result.duration_seconds) | $($result.log) |"
}
$markdown | Set-Content -LiteralPath (Join-Path $outputPath 'summary.md') -Encoding UTF8

if ($summary.overall_status -ne 'PASS') { exit 1 }

param(
    [string]$OutputDirectory = "artifacts/tk-703-04",
    [switch]$ConfirmRedisFlush,
    [switch]$KeepRestoredDatabase
)

$ErrorActionPreference = "Stop"

if (-not $ConfirmRedisFlush) {
    throw "Redis loss rehearsal clears DB 0. Re-run with -ConfirmRedisFlush in an isolated demo environment."
}
if (-not $env:BACKUP_ENCRYPTION_PASSWORD) {
    throw "Set BACKUP_ENCRYPTION_PASSWORD in the current PowerShell session."
}

$repositoryRoot = Split-Path -Parent $PSScriptRoot
$outputPath = Join-Path $repositoryRoot $OutputDirectory
$timestamp = [DateTime]::UtcNow.ToString("yyyyMMddTHHmmssZ")
$restoredDatabase = "local_life_restore_drill_$($timestamp.ToLowerInvariant())"
$targetIndex = "local-life-chunks-rebuild-$($timestamp.ToLowerInvariant())"
$containerBackup = "/tmp/tk-703-04-$timestamp.sql.enc"
$encryptedBackup = Join-Path $outputPath "mysql-$timestamp.sql.enc"

if ($restoredDatabase -notmatch '^[a-z0-9_]+$' -or $targetIndex -notmatch '^[a-z0-9-]+$') {
    throw "Generated recovery target names failed validation."
}

New-Item -ItemType Directory -Force -Path $outputPath | Out-Null
Push-Location $repositoryRoot
try {
    docker compose ps --status running
    if ($LASTEXITCODE -ne 0) { throw "Docker Compose services are not available." }
    $mysqlContainer = (docker compose ps -q mysql).Trim()
    $apiContainer = (docker compose ps -q api).Trim()
    if (-not $mysqlContainer -or -not $apiContainer) {
        throw "The mysql and api containers must be running."
    }

    $containerScriptRoot = "/tmp/tk-703-04-scripts-$timestamp"
    docker compose exec -T mysql mkdir -p -- $containerScriptRoot
    if ($LASTEXITCODE -ne 0) { throw "Creating the container script directory failed." }
    foreach ($scriptName in @(
        "mysql_backup.sh",
        "mysql_restore.sh",
        "mysql_table_counts.sh",
        "mysql_drop_drill_database.sh"
    )) {
        $localScript = Join-Path $repositoryRoot "scripts\recovery\$scriptName"
        docker cp $localScript "${mysqlContainer}:$containerScriptRoot/$scriptName"
        if ($LASTEXITCODE -ne 0) { throw "Copying $scriptName into MySQL failed." }
    }

    docker compose exec -T -e BACKUP_ENCRYPTION_PASSWORD mysql `
        sh "$containerScriptRoot/mysql_backup.sh" $containerBackup
    if ($LASTEXITCODE -ne 0) { throw "Encrypted MySQL backup failed." }
    docker cp "${mysqlContainer}:$containerBackup" $encryptedBackup
    if ($LASTEXITCODE -ne 0) { throw "Copying the encrypted backup failed." }
    $backupHash = (Get-FileHash -LiteralPath $encryptedBackup -Algorithm SHA256).Hash.ToLowerInvariant()

    docker compose exec -T -e BACKUP_ENCRYPTION_PASSWORD mysql `
        sh "$containerScriptRoot/mysql_restore.sh" $containerBackup $restoredDatabase
    if ($LASTEXITCODE -ne 0) { throw "MySQL restore into the isolated database failed." }

    $sourceCounts = @(
        docker compose exec -T mysql sh "$containerScriptRoot/mysql_table_counts.sh" '__SOURCE__'
    )
    $restoredCounts = @(
        docker compose exec -T mysql sh "$containerScriptRoot/mysql_table_counts.sh" $restoredDatabase
    )
    $countDifference = @(Compare-Object $sourceCounts $restoredCounts)
    if (-not $sourceCounts -or $countDifference) {
        throw "Restored MySQL table counts differ from the source database."
    }

    $preReportContainer = "/tmp/tk-703-04-pre-reconcile.json"
    $preOutput = @(docker compose exec -T api python -m app.cli.storage_recovery reconcile `
        --report $preReportContainer)
    $preReconcileExit = $LASTEXITCODE
    $preOutput | Set-Content -LiteralPath (Join-Path $outputPath "pre-reconcile.json") -Encoding UTF8

    $rebuildReportContainer = "/tmp/tk-703-04-rebuild.json"
    $rebuildOutput = @(docker compose exec -T api python -m app.cli.storage_recovery rebuild `
        --target-index $targetIndex `
        --report $rebuildReportContainer)
    $rebuildExit = $LASTEXITCODE
    $rebuildOutput | Set-Content -LiteralPath (Join-Path $outputPath "rebuild.json") -Encoding UTF8
    if ($rebuildExit -ne 0) { throw "OpenSearch full rebuild failed; aliases were not switched." }

    $postReportContainer = "/tmp/tk-703-04-post-reconcile.json"
    $postOutput = @(docker compose exec -T api python -m app.cli.storage_recovery reconcile `
        --index $targetIndex `
        --report $postReportContainer)
    $postExit = $LASTEXITCODE
    $postOutput | Set-Content -LiteralPath (Join-Path $outputPath "post-reconcile.json") -Encoding UTF8
    if ($postExit -ne 0) { throw "Post-rebuild reconciliation failed." }

    $redisReportContainer = "/tmp/tk-703-04-redis-fallback.json"
    $redisOutput = @(docker compose exec -T api python -m app.cli.storage_recovery redis-fallback `
        --confirm-flush FLUSH-TK-703-04 `
        --report $redisReportContainer)
    $redisExit = $LASTEXITCODE
    $redisOutput | Set-Content -LiteralPath (Join-Path $outputPath "redis-fallback.json") -Encoding UTF8
    if ($redisExit -ne 0) { throw "Redis read-through recovery failed." }

    $summary = @"
# TK-703-04 recovery drill result

- Executed at (UTC): $timestamp
- Encrypted MySQL backup: $(Split-Path -Leaf $encryptedBackup)
- Backup SHA-256: $backupHash
- Isolated restore database: $restoredDatabase
- Tables compared by exact row count: $($sourceCounts.Count)
- Rebuilt index: $targetIndex
- Post-rebuild reconciliation: PASS
- MySQL fallback after Redis loss: PASS
- Pre-rebuild reconciliation exit code: $preReconcileExit (nonzero is allowed when drift exists)

Overall result: **PASS**.
"@
    Set-Content -LiteralPath (Join-Path $outputPath "summary.md") -Value $summary -Encoding UTF8

    if (-not $KeepRestoredDatabase) {
        docker compose exec -T mysql `
            sh "$containerScriptRoot/mysql_drop_drill_database.sh" $restoredDatabase
        if ($LASTEXITCODE -ne 0) { throw "Temporary restore database cleanup failed." }
    }
    docker compose exec -T mysql rm -f -- $containerBackup
    if ($LASTEXITCODE -ne 0) { throw "Container backup cleanup failed." }
    foreach ($scriptName in @(
        "mysql_backup.sh",
        "mysql_restore.sh",
        "mysql_table_counts.sh",
        "mysql_drop_drill_database.sh"
    )) {
        docker compose exec -T mysql rm -f -- "$containerScriptRoot/$scriptName"
        if ($LASTEXITCODE -ne 0) { throw "Container recovery script cleanup failed." }
    }
    docker compose exec -T mysql rmdir -- $containerScriptRoot
    if ($LASTEXITCODE -ne 0) { throw "Container script directory cleanup failed." }
    Write-Host "TK-703-04 recovery drill passed. Evidence: $outputPath"
}
finally {
    Pop-Location
}

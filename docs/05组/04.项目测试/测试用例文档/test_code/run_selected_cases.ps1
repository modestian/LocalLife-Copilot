param(
    [ValidateSet('AUTH', 'KB', 'GOV', 'SEARCH', 'RAG', 'WS', 'MERCHANT', 'MODEL', 'UI', 'ADMIN', 'OPS', 'E2E', 'DELIVERY', 'SMOKE')]
    [string[]]$Group = @('SMOKE'),
    [switch]$All,
    [switch]$List,
    [switch]$ContinueOnFailure,
    [string]$ResultDirectory
)

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..\..')).Path
$runner = Join-Path $PSScriptRoot 'run_project_test_cases.py'
$arguments = @($runner) + $Group
if ($All) { $arguments += '--all' }
if ($List) { $arguments += '--list' }
if ($ContinueOnFailure) { $arguments += '--continue-on-failure' }
if ($ResultDirectory) { $arguments += @('--result-dir', $ResultDirectory) }

Push-Location $repoRoot
try {
    py -3.13 @arguments
    exit $LASTEXITCODE
}
finally {
    Pop-Location
}

[CmdletBinding()]
param(
    [ValidateRange(1, 10)]
    [int]$Rounds = 3,
    [string]$ArtifactRoot,
    [switch]$RebuildImages,
    [switch]$SkipPlaywright
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
if ([string]::IsNullOrWhiteSpace($ArtifactRoot)) {
    $ArtifactRoot = Join-Path $repoRoot 'artifacts\tk-702-03'
}
$apiBaseUrl = 'http://127.0.0.1:18000'
$knowledgeBaseId = '70200000-0000-4000-8000-000000000010'
$merchantId = '70200000-0000-4000-8000-000000000020'
$ungrantedMerchantId = '70200000-0000-4000-8000-000000000022'
$conversationId = '70200000-0000-4000-8000-000000000050'
$assistantMessageId = '70200000-0000-4000-8000-000000000052'
$modelVersionId = '70200000-0000-4000-8000-000000000032'

function Invoke-Compose {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Arguments)

    & docker compose @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "docker compose $($Arguments -join ' ') failed with exit code $LASTEXITCODE"
    }
}

function Invoke-Api {
    param(
        [Parameter(Mandatory)][ValidateSet('GET', 'POST')][string]$Method,
        [Parameter(Mandatory)][string]$Path,
        [string]$AccessToken,
        [object]$Body,
        [int]$ExpectedStatus = 200
    )

    $headers = @{}
    if ($AccessToken) {
        $headers.Authorization = "Bearer $AccessToken"
    }
    $parameters = @{
        Method = $Method
        Uri = "$apiBaseUrl$Path"
        Headers = $headers
        UseBasicParsing = $true
    }
    if ($PSBoundParameters.ContainsKey('Body')) {
        $parameters.ContentType = 'application/json'
        $parameters.Body = $Body | ConvertTo-Json -Depth 8 -Compress
    }

    try {
        $response = Invoke-WebRequest @parameters
    } catch {
        $status = if ($_.Exception.Response) { [int]$_.Exception.Response.StatusCode } else { 0 }
        if ($status -eq $ExpectedStatus) {
            return $null
        }
        throw "${Method} $Path returned HTTP $status; expected $ExpectedStatus. $($_.Exception.Message)"
    }
    if ([int]$response.StatusCode -ne $ExpectedStatus) {
        throw "${Method} $Path returned HTTP $($response.StatusCode); expected $ExpectedStatus."
    }
    return $response.Content | ConvertFrom-Json
}

function Get-AccessToken {
    param([Parameter(Mandatory)][string]$Username, [Parameter(Mandatory)][string]$Password)

    $response = Invoke-Api -Method POST -Path '/api/v1/auth/login' -Body @{ username = $Username; password = $Password }
    if (-not $response.data.access_token) {
        throw "Login for $Username did not return an access token."
    }
    return [string]$response.data.access_token
}

function Assert-True {
    param([Parameter(Mandatory)][bool]$Condition, [Parameter(Mandatory)][string]$Message)

    if (-not $Condition) {
        throw $Message
    }
}

function Wait-ForTask {
    param([Parameter(Mandatory)][string]$TaskId, [Parameter(Mandatory)][string]$AccessToken)

    foreach ($attempt in 1..60) {
        $task = Invoke-Api -Method GET -Path "/api/v1/tasks/$TaskId" -AccessToken $AccessToken
        $status = [string]$task.data.status
        if ($status -eq 'SUCCEEDED') {
            return $task.data
        }
        if ($status -in @('FAILED', 'CANCELLED')) {
            throw "Task $TaskId ended as ${status}: $($task.data.error_code) $($task.data.error_message)"
        }
        Start-Sleep -Seconds 2
    }
    throw "Task $TaskId did not complete within 120 seconds."
}

function Invoke-DocumentUpload {
    param(
        [Parameter(Mandatory)][string]$FilePath,
        [Parameter(Mandatory)][string]$AccessToken
    )

    $raw = & curl.exe --fail-with-body --silent --show-error --request POST `
        --header "Authorization: Bearer $AccessToken" `
        --form "files[]=@$FilePath;type=text/markdown" `
        --form 'splitter=recursive' `
        --form 'chunk_size=500' `
        --form 'chunk_overlap=80' `
        --form 'force_new_version=false' `
        "$apiBaseUrl/api/v1/knowledge-bases/$knowledgeBaseId/documents:upload"
    if ($LASTEXITCODE -ne 0) {
        throw "Document upload failed with exit code $LASTEXITCODE."
    }
    return $raw | ConvertFrom-Json
}

function Write-ComposeLogs {
    param([Parameter(Mandatory)][string]$RoundDirectory)

    $logPath = Join-Path $RoundDirectory 'compose.log'
    & docker compose logs --no-color | Out-File -FilePath $logPath -Encoding utf8
}

New-Item -ItemType Directory -Force -Path $ArtifactRoot | Out-Null
$startedAt = Get-Date
$allRounds = @()

try {
    foreach ($round in 1..$Rounds) {
        $roundStartedAt = Get-Date
        $roundDirectory = Join-Path $ArtifactRoot ("round-{0:d2}" -f $round)
        New-Item -ItemType Directory -Force -Path $roundDirectory | Out-Null
        $roundResult = [ordered]@{
            round = $round
            started_at = $roundStartedAt.ToUniversalTime().ToString('o')
            status = 'FAILED'
            checks = [ordered]@{}
            metrics = [ordered]@{}
            error = $null
        }

        try {
            Push-Location $repoRoot
            Invoke-Compose down --volumes --remove-orphans
            if ($RebuildImages) {
                Invoke-Compose up --build --wait --wait-timeout 300
            } else {
                Invoke-Compose up --wait --wait-timeout 300
            }

            $seedPassword = "Tk702-$round-$([guid]::NewGuid().ToString('N'))"
            $seedOutput = & docker compose exec -T -e "DEMO_SEED_PASSWORD=$seedPassword" api python -m app.cli.seed_demo_data
            if ($LASTEXITCODE -ne 0) {
                throw "Deterministic demo seed failed with exit code $LASTEXITCODE."
            }
            $seedOutput | Out-File -FilePath (Join-Path $roundDirectory 'seed.log') -Encoding utf8
            Assert-True ($seedOutput -match '3 users, 2 merchants, 12 reviews, 2 documents, 3 standard questions') 'Seed summary did not match the deterministic fixture.'
            $roundResult.checks.seed = 'passed'

            $ready = Invoke-Api -Method GET -Path '/health/ready'
            Assert-True ($ready.status -eq 'ready') 'Readiness endpoint was not ready.'
            $roundResult.checks.readiness = 'passed'

            $adminToken = Get-AccessToken -Username 'demo-admin' -Password $seedPassword
            $userToken = Get-AccessToken -Username 'demo-user' -Password $seedPassword
            $merchantToken = Get-AccessToken -Username 'demo-merchant' -Password $seedPassword
            $roundResult.checks.role_login = 'passed'

            $knowledgeBase = Invoke-Api -Method GET -Path "/api/v1/knowledge-bases/$knowledgeBaseId" -AccessToken $adminToken
            $documents = Invoke-Api -Method GET -Path "/api/v1/knowledge-bases/$knowledgeBaseId/documents?page=1&page_size=20" -AccessToken $adminToken
            Assert-True ($knowledgeBase.data.id -eq $knowledgeBaseId) 'Seed knowledge base was not readable by the administrator.'
            Assert-True ($documents.data.items.Count -eq 2) 'Seed document count was not 2 before upload.'
            $roundResult.checks.seed_knowledge = 'passed'

            $uploadPath = Join-Path $roundDirectory "round-$round-upload.md"
            $evidenceLine = "Round $round upload evidence for deterministic indexing and traceable retrieval."
            @(
                '# ST-702 fresh-environment regression'
                (1..30 | ForEach-Object { "$evidenceLine Evidence segment $_." })
            ) | Set-Content -Path $uploadPath -Encoding utf8
            $upload = Invoke-DocumentUpload -FilePath $uploadPath -AccessToken $adminToken
            $taskId = [string]$upload.data.task_id
            Assert-True (-not [string]::IsNullOrWhiteSpace($taskId)) 'Upload did not return an async task id.'
            $task = Wait-ForTask -TaskId $taskId -AccessToken $adminToken
            $roundResult.checks.upload_and_index = 'passed'

            $search = Invoke-Api -Method POST -Path '/api/v1/search' -AccessToken $userToken -Body @{
                query = "Round $round upload evidence"
                knowledge_base_ids = @($knowledgeBaseId)
                top_k = 5
                vector_weight = 0.6
                keyword_weight = 0.4
                rerank = $true
                filters = @{}
            }
            Assert-True ($search.data.total -ge 1) 'Indexed upload was not returned by the real search API.'
            Assert-True (-not [string]::IsNullOrWhiteSpace([string]$search.data.items[0].source_url)) 'Search result did not include a traceable source URL.'
            $roundResult.checks.rag_source = 'passed'

            $messages = Invoke-Api -Method GET -Path "/api/v1/conversations/$conversationId/messages?limit=20" -AccessToken $userToken
            Assert-True ($messages.data.items.Count -ge 2) 'Seed conversation did not contain the expected messages.'
            Assert-True ($messages.data.items[1].sources.Count -ge 1) 'Seed assistant answer did not retain a citation.'
            $feedback = Invoke-Api -Method POST -Path '/api/v1/chat/feedback' -AccessToken $userToken -Body @{
                conversation_id = $conversationId
                message_id = $assistantMessageId
                rating = 1
                reason_codes = @('HELPFUL')
            }
            Assert-True ($feedback.data.rating -eq 1) 'Feedback submission did not persist the expected rating.'
            $roundResult.checks.citation_and_feedback = 'passed'

            $trend = Invoke-Api -Method GET -Path "/api/v1/merchants/$merchantId/analytics/sentiment-trend?granularity=week" -AccessToken $merchantToken
            Assert-True ($trend.data.Count -ge 1) 'Merchant trend endpoint returned no deterministic data.'
            Invoke-Api -Method GET -Path "/api/v1/merchants/$ungrantedMerchantId/analytics/sentiment-trend" -AccessToken $merchantToken -ExpectedStatus 404 | Out-Null
            $roundResult.checks.merchant_and_authorization = 'passed'

            $models = Invoke-Api -Method GET -Path '/api/v1/models' -AccessToken $adminToken
            Assert-True ($models.data.items.Count -ge 2) 'Administrator could not view the seeded model versions.'
            $rollback = Invoke-Api -Method POST -Path "/api/v1/models/$modelVersionId/rollback" -AccessToken $adminToken -ExpectedStatus 201 -Body @{
                scene = 'sentiment'
                environment = 'demo'
                reason = "TK-702-03 round $round deterministic rollback verification"
            }
            Assert-True ($rollback.data.action -eq 'ROLLBACK') 'Model rollback did not create a rollback deployment record.'
            $roundResult.checks.model_rollback = 'passed'

            if (-not $SkipPlaywright) {
                Push-Location (Join-Path $repoRoot 'frontend')
                & npm run test:e2e *>&1 | Tee-Object -FilePath (Join-Path $roundDirectory 'playwright.log')
                if ($LASTEXITCODE -ne 0) {
                    throw "Playwright regression failed with exit code $LASTEXITCODE."
                }
                Pop-Location
                $roundResult.checks.playwright = 'passed'
            }

            $roundResult.metrics.seed_users = 3
            $roundResult.metrics.seed_merchants = 2
            $roundResult.metrics.seed_reviews = 12
            $roundResult.metrics.seed_documents_before_upload = 2
            $roundResult.metrics.seed_questions = 3
            $roundResult.metrics.indexed_task_status = [string]$task.status
            $roundResult.metrics.search_hits = [int]$search.data.total
            $roundResult.metrics.trend_buckets = [int]$trend.data.Count
            $roundResult.status = 'PASSED'
        } catch {
            $roundResult.error = $_.Exception.Message
            throw
        } finally {
            try { Write-ComposeLogs -RoundDirectory $roundDirectory } catch { Write-Warning "Unable to collect compose logs: $($_.Exception.Message)" }
            $roundResult.completed_at = (Get-Date).ToUniversalTime().ToString('o')
            $roundResult.duration_seconds = [math]::Round(((Get-Date) - $roundStartedAt).TotalSeconds, 3)
            $roundResult | ConvertTo-Json -Depth 8 | Set-Content -Path (Join-Path $roundDirectory 'summary.json') -Encoding utf8
            $allRounds += [pscustomobject]$roundResult
            while ((Get-Location).Path -ne $repoRoot) { Pop-Location }
        }
    }
} finally {
    $summary = [ordered]@{
        task = 'TK-702-03'
        generated_at = (Get-Date).ToUniversalTime().ToString('o')
        source_revision = (git -C $repoRoot rev-parse HEAD).Trim()
        rounds_requested = $Rounds
        rounds_passed = @($allRounds | Where-Object { $_.status -eq 'PASSED' }).Count
        rounds = $allRounds
    }
    $summary | ConvertTo-Json -Depth 10 | Set-Content -Path (Join-Path $ArtifactRoot 'summary.json') -Encoding utf8
}

if (@($allRounds | Where-Object { $_.status -eq 'PASSED' }).Count -ne $Rounds) {
    throw "TK-702-03 completed with failed rounds. See $ArtifactRoot."
}

Write-Host "TK-702-03 completed: $Rounds/$Rounds fresh-environment rounds passed. Evidence: $ArtifactRoot"

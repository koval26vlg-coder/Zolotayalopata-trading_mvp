param(
    [Parameter(Mandatory = $true)][string]$ManifestPath,
    [string]$ExpectedPlanHash = "f2135b1059be438da5e1f9d2d48ce871e7012ad738a288716b521ed952dde9b6",
    [string]$EvidencePath = "E:\ZolotyayLopata-data\exports\trading-mvp\autopilot\research\paper-public-readonly-probe-evidence-v2.json",
    [string]$GatePath = "",
    [string]$CurrentRunPath = ""
)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$ProbeModule = Join-Path $ProjectRoot "trading_mvp\src\paper_public_readonly_probe.py"
if (-not $GatePath) {
    $GatePath = Join-Path $ProjectRoot "docs\agent-log\active-run-gate.json"
}
if (-not $CurrentRunPath) {
    $CurrentRunPath = Join-Path $ProjectRoot "docs\agent-log\current-run.json"
}
$ManifestPath = [System.IO.Path]::GetFullPath($ManifestPath)
$EvidencePath = [System.IO.Path]::GetFullPath($EvidencePath)
$GatePath = [System.IO.Path]::GetFullPath($GatePath)
$CurrentRunPath = [System.IO.Path]::GetFullPath($CurrentRunPath)

function Resolve-Python {
    $candidates = @(
        $env:TRADING_MVP_PYTHON,
        (Join-Path $ProjectRoot ".venv\Scripts\python.exe"),
        (Join-Path $ProjectRoot "trading_mvp\.venv\Scripts\python.exe"),
        "C:\Program Files\Python313\python.exe",
        "C:\Program Files\Python312\python.exe",
        "C:\Users\koval\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
    ) | Where-Object { $_ }
    foreach ($candidate in $candidates) {
        if (-not (Test-Path -LiteralPath $candidate -PathType Leaf)) { continue }
        & $candidate -c "import requests" 2>$null
        if ($LASTEXITCODE -eq 0) {
            return [System.IO.Path]::GetFullPath($candidate)
        }
    }
    throw "Python runtime with requests is unavailable. Set TRADING_MVP_PYTHON."
}

function Write-JsonAtomic {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)]$Value
    )
    $parent = Split-Path -Parent $Path
    if ($parent) {
        New-Item -ItemType Directory -Force -Path $parent | Out-Null
    }
    $temporary = "$Path.tmp.$PID.$([DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds())"
    try {
        $Value | ConvertTo-Json -Depth 50 |
            Set-Content -LiteralPath $temporary -Encoding UTF8
        Move-Item -LiteralPath $temporary -Destination $Path -Force
    } finally {
        Remove-Item -LiteralPath $temporary -Force -ErrorAction SilentlyContinue
    }
}

function Set-Property {
    param(
        [Parameter(Mandatory = $true)]$Object,
        [Parameter(Mandatory = $true)][string]$Name,
        $Value
    )
    if ($Object.PSObject.Properties.Name -contains $Name) {
        $Object.$Name = $Value
    } else {
        $Object | Add-Member -NotePropertyName $Name -NotePropertyValue $Value
    }
}

foreach ($required in @($ProbeModule, $ManifestPath, $GatePath)) {
    if (-not (Test-Path -LiteralPath $required -PathType Leaf)) {
        throw "Required public probe postrun file is missing: $required"
    }
}
$gate = Get-Content -LiteralPath $GatePath -Raw | ConvertFrom-Json
$gateStatus = if ($gate.gate_status) {
    [string]$gate.gate_status
} else {
    [string]$gate.status
}
if ($gateStatus -ne "READY_FOR_POSTPROCESS" -or $gate.final -ne $true) {
    throw "Public probe postrun requires final READY_FOR_POSTPROCESS."
}
if ([System.IO.Path]::GetFullPath([string]$gate.manifest_path) -ne $ManifestPath) {
    throw "Public probe postrun manifest does not own the active gate."
}

$Python = Resolve-Python
$env:TRADING_MVP_PYTHON = $Python
$validation = & $Python -u $ProbeModule validate-result `
    --manifest $ManifestPath `
    --expected-plan-hash $ExpectedPlanHash
if ($LASTEXITCODE -ne 0) {
    throw "Public probe manifest validation failed."
}
$report = Get-Content -LiteralPath $ManifestPath -Raw | ConvertFrom-Json
if (
    $report.final -ne $true -or
    [string]$report.status -ne "READY_FOR_POSTPROCESS" -or
    [string]$report.verdict -ne "PUBLIC_READONLY_PROBE_ACCEPTED"
) {
    throw "Public probe result is not technically accepted."
}
if ([string]$report.run_id -ne [string]$gate.run_id) {
    throw "Public probe result run id does not match the active gate."
}

$evidenceReused = $false
if (Test-Path -LiteralPath $EvidencePath -PathType Leaf) {
    $evidenceReused = $true
} else {
    $evidenceParent = Split-Path -Parent $EvidencePath
    if ($evidenceParent) {
        New-Item -ItemType Directory -Force -Path $evidenceParent | Out-Null
    }
    $null = & $Python -u $ProbeModule postprocess `
        --manifest $ManifestPath `
        --expected-plan-hash $ExpectedPlanHash `
        --output $EvidencePath
    if ($LASTEXITCODE -ne 0) {
        throw "Public probe immutable evidence creation failed."
    }
}
$validatedEvidence = & $Python -u $ProbeModule validate-evidence `
    --evidence $EvidencePath `
    --manifest $ManifestPath `
    --expected-plan-hash $ExpectedPlanHash
if ($LASTEXITCODE -ne 0) {
    throw "Public probe immutable evidence validation failed."
}
$evidence = Get-Content -LiteralPath $EvidencePath -Raw | ConvertFrom-Json
if (
    [string]$evidence.verdict -ne
    "PUBLIC_READONLY_PROBE_EVIDENCE_ACCEPTED"
) {
    throw "Public probe postrun evidence verdict is not accepted."
}

$now = [DateTimeOffset]::Now.ToString("o")
foreach ($entry in @(
    @("updated_at", $now),
    @("postprocessed_at", $now),
    @("evidence_path", $EvidencePath),
    @(
        "evidence_file_sha256",
        (
            Get-FileHash -Algorithm SHA256 -LiteralPath $EvidencePath
        ).Hash.ToLowerInvariant()
    ),
    @(
        "evidence_deterministic_result_hash",
        [string]$evidence.deterministic_result_hash
    ),
    @("next_goal_decision", "RUN_PAPER_PRODUCT_READINESS_AUDIT_V8"),
    @(
        "next_goal_reason",
        "Accepted technical probe evidence is immutable; the next bounded offline step is readiness audit v8."
    ),
    @(
        "next_step_after_ready",
        "Run paper_product_readiness_audit_v8 without returns/PnL/OOS, grid, retune, paper-forward, live, or private API access."
    ),
    @("postprocess_command", $null)
)) {
    Set-Property -Object $gate -Name $entry[0] -Value $entry[1]
}
Write-JsonAtomic -Path $GatePath -Value $gate

if (Test-Path -LiteralPath $CurrentRunPath -PathType Leaf) {
    $pointer = Get-Content -LiteralPath $CurrentRunPath -Raw | ConvertFrom-Json
    if ([string]$pointer.run_id -ne [string]$gate.run_id) {
        throw "Current-run pointer changed during public probe postrun."
    }
    Set-Property -Object $pointer -Name "updated_at" -Value $now
    Set-Property -Object $pointer -Name "evidence_path" -Value $EvidencePath
    Write-JsonAtomic -Path $CurrentRunPath -Value $pointer
}

$launchRecordPath = [string]$gate.launch_record_path
if (
    $launchRecordPath -and
    (Test-Path -LiteralPath $launchRecordPath -PathType Leaf)
) {
    $launch = Get-Content -LiteralPath $launchRecordPath -Raw |
        ConvertFrom-Json
    foreach ($entry in @(
        @("postprocessed_at", $now),
        @("evidence_path", $EvidencePath),
        @(
            "evidence_file_sha256",
            (
                Get-FileHash -Algorithm SHA256 -LiteralPath $EvidencePath
            ).Hash.ToLowerInvariant()
        ),
        @("evidence_reused", $evidenceReused),
        @("next_goal_decision", "RUN_PAPER_PRODUCT_READINESS_AUDIT_V8")
    )) {
        Set-Property -Object $launch -Name $entry[0] -Value $entry[1]
    }
    Write-JsonAtomic -Path $launchRecordPath -Value $launch
}

[ordered]@{
    decision = "PUBLIC_READONLY_PROBE_POSTRUN_COMPLETE"
    run_id = [string]$report.run_id
    plan_hash_sha256 = $ExpectedPlanHash
    manifest_path = $ManifestPath
    manifest_file_sha256 = (
        Get-FileHash -Algorithm SHA256 -LiteralPath $ManifestPath
    ).Hash.ToLowerInvariant()
    evidence_path = $EvidencePath
    evidence_file_sha256 = (
        Get-FileHash -Algorithm SHA256 -LiteralPath $EvidencePath
    ).Hash.ToLowerInvariant()
    evidence_deterministic_result_hash = [string]$evidence.deterministic_result_hash
    evidence_reused = $evidenceReused
    next_allowed_action = "paper_product_readiness_audit_v8"
} | ConvertTo-Json -Depth 10

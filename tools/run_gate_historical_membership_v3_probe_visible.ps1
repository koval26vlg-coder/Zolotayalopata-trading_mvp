param(
    [Parameter(Mandatory = $true)][string]$PlanPath,
    [Parameter(Mandatory = $true)][string]$ExpectedPlanHash,
    [Parameter(Mandatory = $true)][string]$OutputPath,
    [Parameter(Mandatory = $true)][string]$RunId,
    [ValidateRange(1, 600)][int]$MaxRuntimeSec = 600,
    [ValidateRange(1, 8)][int]$Workers = 8,
    [ValidateRange(0, 600)][int]$HoldOpenSec = 60,
    [string]$GatePath = "",
    [string]$CurrentRunPath = "",
    [string]$LaunchRecordPath = "",
    [string]$LogPath = ""
)

$ErrorActionPreference = 'Stop'
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$Module = Join-Path $RepoRoot 'trading_mvp\src\gate_historical_membership_v3.py'
if (-not $GatePath) { $GatePath = Join-Path $RepoRoot 'docs\agent-log\active-run-gate.json' }
if (-not $CurrentRunPath) { $CurrentRunPath = Join-Path $RepoRoot 'docs\agent-log\current-run.json' }
$PlanPath = [System.IO.Path]::GetFullPath($PlanPath)
$OutputPath = [System.IO.Path]::GetFullPath($OutputPath)
$GatePath = [System.IO.Path]::GetFullPath($GatePath)
$CurrentRunPath = [System.IO.Path]::GetFullPath($CurrentRunPath)
if (-not $LogPath) {
    $LogPath = Join-Path $RepoRoot "exports\trading-mvp\run\$RunId.membership-v3.visible.log"
}
$LogPath = [System.IO.Path]::GetFullPath($LogPath)
if ($LaunchRecordPath) { $LaunchRecordPath = [System.IO.Path]::GetFullPath($LaunchRecordPath) }
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $LogPath) | Out-Null

function Resolve-Python {
    $candidates = @(
        $env:TRADING_MVP_PYTHON,
        (Join-Path $RepoRoot '.venv\Scripts\python.exe'),
        (Join-Path $RepoRoot 'trading_mvp\.venv\Scripts\python.exe'),
        'C:\Program Files\Python313\python.exe',
        'C:\Program Files\Python312\python.exe',
        'C:\Users\koval\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
    ) | Where-Object { $_ }
    foreach ($candidate in $candidates) {
        if (-not (Test-Path -LiteralPath $candidate -PathType Leaf)) { continue }
        & $candidate -c 'import requests' 2>$null
        if ($LASTEXITCODE -eq 0) { return [System.IO.Path]::GetFullPath($candidate) }
    }
    throw 'Python runtime with requests was not found. Set TRADING_MVP_PYTHON.'
}

function Write-JsonAtomic {
    param([Parameter(Mandatory = $true)][string]$Path, [Parameter(Mandatory = $true)]$Value)
    $parent = Split-Path -Parent $Path
    if ($parent) { New-Item -ItemType Directory -Force -Path $parent | Out-Null }
    $temporary = "$Path.tmp.$PID.$([DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds())"
    try {
        $Value | ConvertTo-Json -Depth 50 | Set-Content -LiteralPath $temporary -Encoding UTF8
        Move-Item -LiteralPath $temporary -Destination $Path -Force
    } finally {
        Remove-Item -LiteralPath $temporary -Force -ErrorAction SilentlyContinue
    }
}

function Set-Property {
    param([Parameter(Mandatory = $true)]$Object, [Parameter(Mandatory = $true)][string]$Name, $Value)
    if ($Object.PSObject.Properties.Name -contains $Name) { $Object.$Name = $Value }
    else { $Object | Add-Member -NotePropertyName $Name -NotePropertyValue $Value }
}

function Update-LaunchRecord {
    param([Parameter(Mandatory = $true)][hashtable]$Values)
    if (-not $LaunchRecordPath -or -not (Test-Path -LiteralPath $LaunchRecordPath -PathType Leaf)) { return }
    $record = Get-Content -LiteralPath $LaunchRecordPath -Raw | ConvertFrom-Json
    foreach ($entry in $Values.GetEnumerator()) {
        Set-Property -Object $record -Name ([string]$entry.Key) -Value $entry.Value
    }
    Write-JsonAtomic -Path $LaunchRecordPath -Value $record
}

function Set-RunState {
    param(
        [Parameter(Mandatory = $true)][string]$Status,
        [Parameter(Mandatory = $true)][bool]$Final,
        [int]$Rows = 0,
        [int]$Errors = 0,
        [string]$NextDecision = '',
        [string]$Reason = '',
        [string]$StopReason = ''
    )
    if (Test-Path -LiteralPath $GatePath -PathType Leaf) {
        $gate = Get-Content -LiteralPath $GatePath -Raw | ConvertFrom-Json
        $existingStatus = if ($gate.gate_status) { [string]$gate.gate_status } else { [string]$gate.status }
        if ($existingStatus -eq 'RUNNING' -and [string]$gate.run_id -ne $RunId) {
            throw "Refusing to overwrite active gate owned by run_id=$($gate.run_id)."
        }
    } else {
        $gate = [pscustomobject]@{ schema = 'active_run_gate_v2'; project = 'trading_mvp' }
    }
    $processIds = if ($Status -eq 'RUNNING') { @($PID) } else { @() }
    foreach ($entry in @(
        @('run_id', $RunId), @('status', $Status), @('gate_status', $Status), @('final', $Final),
        @('updated_at', [DateTimeOffset]::Now.ToString('o')), @('stop_reason', $StopReason),
        @('manifest_path', $OutputPath), @('output', [pscustomobject]@{ path = $OutputPath; kind = 'file' }),
        @('completed_cycles', $(if ($Final) { 1 } else { 0 })), @('total_cycles', 1),
        @('remaining_cycles', $(if ($Final) { 0 } else { 1 })), @('rows', $Rows), @('errors', $Errors),
        @('primary_output_complete', $Final), @('expected_outputs_complete', $Final),
        @('collector_pid', $(if ($Status -eq 'RUNNING') { $PID } else { $null })),
        @('monitor_pid', $null), @('process_ids', $processIds), @('replay_allowed', $false),
        @('grid_allowed', $false), @('backtest_allowed', $false), @('execution_probe_allowed', $false),
        @('paper_forward_allowed', $false), @('live_orders', $false), @('private_api_keys', $false),
        @('leverage_or_margin', $false), @('next_goal_decision', $NextDecision),
        @('next_goal_reason', $Reason),
        @('next_step_after_ready', $(
            if (-not $Final) { 'Status-only until the membership-v3 source probe finishes.' }
            elseif ($NextDecision -eq 'GATE_MEMBERSHIP_V3_ARCHIVE_SOURCE_ACCEPTED_READY_FOR_HISTORY_PLANONLY') {
                'Build a separate hash-bound full-history PlanOnly; do not collect or evaluate automatically.'
            } else { 'Close membership momentum without history/OOS and select a different PlanOnly branch.' }
        ))
    )) { Set-Property -Object $gate -Name $entry[0] -Value $entry[1] }
    Write-JsonAtomic -Path $GatePath -Value $gate
    $pointer = [ordered]@{
        schema = 'active_run_pointer_v1'; project = 'trading_mvp'; run_id = $RunId; status = $Status
        updated_at = [DateTimeOffset]::Now.ToString('o'); manifest_path = $OutputPath
        output = [ordered]@{ path = $OutputPath; kind = 'file' }
        collector_pid = $(if ($Status -eq 'RUNNING') { $PID } else { $null })
        monitor_pid = $null; process_ids = $processIds; launch_record_path = $LaunchRecordPath
    }
    Write-JsonAtomic -Path $CurrentRunPath -Value $pointer
}

if (-not (Test-Path -LiteralPath $Module -PathType Leaf)) { throw "Probe module is missing: $Module" }
if (-not (Test-Path -LiteralPath $PlanPath -PathType Leaf)) { throw "PlanOnly artifact is missing: $PlanPath" }
$Python = Resolve-Python
Update-LaunchRecord -Values @{
    status = 'RUNNING'; gate_status = 'RUNNING'; worker_pid = $PID; collector_pid = $PID
    process_ids = @($PID); worker_started_at = [DateTimeOffset]::Now.ToString('o')
}
Set-RunState -Status 'RUNNING' -Final $false -NextDecision 'GATE_MEMBERSHIP_V3_ARCHIVE_SOURCE_PROBE_RUNNING' `
    -Reason 'Visible bounded public archive-metadata probe is running; no overlapping collector or consumer is allowed.'

$arguments = @(
    '-u', $Module, 'probe', '--plan', $PlanPath, '--expected-plan-hash', $ExpectedPlanHash,
    '--output', $OutputPath, '--max-runtime-sec', [string]$MaxRuntimeSec, '--workers', [string]$Workers
)
$exitCode = 1
try {
    "[$(Get-Date -Format o)] visible membership-v3 source probe start run_id=$RunId" |
        Tee-Object -FilePath $LogPath
    & $Python @arguments 2>&1 | Tee-Object -FilePath $LogPath -Append
    $exitCode = $LASTEXITCODE
    if (-not (Test-Path -LiteralPath $OutputPath -PathType Leaf)) {
        throw "Probe output was not created: $OutputPath"
    }
    $report = Get-Content -LiteralPath $OutputPath -Raw | ConvertFrom-Json
    if ([string]$report.plan_hash -ne $ExpectedPlanHash) {
        throw 'Membership-v3 output plan hash mismatch.'
    }
    $rowCount = @($report.results).Count
    # A missing JSON property becomes @($null), whose Count is one in PowerShell.
    # Count only actual report errors so a clean source rejection is not misreported as a runtime failure.
    $reportErrors = @()
    if ($report.PSObject.Properties.Name -contains 'errors' -and $null -ne $report.errors) {
        $reportErrors = @($report.errors | Where-Object { $null -ne $_ -and [string]$_ -ne '' })
    }
    $resultErrors = @($report.results | Where-Object { $_.status -eq 'error' })
    $errorCount = $reportErrors.Count + $resultErrors.Count
    if ($report.final -eq $true) {
        Update-LaunchRecord -Values @{
            status = 'READY_FOR_POSTPROCESS'; gate_status = 'READY_FOR_POSTPROCESS'; final = $true
            completed_at = [DateTimeOffset]::Now.ToString('o'); worker_exit_code = $exitCode
            collector_pid = $null; process_ids = @(); rows = $rowCount; errors = $errorCount
            artifact_hash = [string]$report.artifact_hash; decision = [string]$report.decision
        }
        Set-RunState -Status 'READY_FOR_POSTPROCESS' -Final $true -Rows $rowCount -Errors $errorCount `
            -NextDecision ([string]$report.decision) -Reason 'Membership-v3 source probe completed; only its technical source verdict may be read.'
    } else {
        Update-LaunchRecord -Values @{
            status = 'STOPPED_INCOMPLETE'; gate_status = 'STOPPED_INCOMPLETE'; final = $false
            completed_at = [DateTimeOffset]::Now.ToString('o'); worker_exit_code = $exitCode
            collector_pid = $null; process_ids = @(); rows = $rowCount; errors = $errorCount
            failure = (@($report.errors) -join '; '); decision = [string]$report.decision
        }
        Set-RunState -Status 'STOPPED_INCOMPLETE' -Final $false -Rows $rowCount -Errors $errorCount `
            -NextDecision ([string]$report.decision) -Reason 'Membership-v3 source probe stopped incomplete and cannot authorize history.' `
            -StopReason (@($report.errors) -join '; ')
    }
} catch {
    $message = $_.Exception.Message
    Update-LaunchRecord -Values @{
        status = 'STOPPED_INCOMPLETE'; gate_status = 'STOPPED_INCOMPLETE'; final = $false
        completed_at = [DateTimeOffset]::Now.ToString('o'); worker_exit_code = 1
        collector_pid = $null; process_ids = @(); errors = 1; failure = $message
    }
    Set-RunState -Status 'STOPPED_INCOMPLETE' -Final $false -Rows 0 -Errors 1 `
        -NextDecision 'GATE_MEMBERSHIP_V3_ARCHIVE_SOURCE_PROBE_STOPPED_INCOMPLETE' -Reason $message -StopReason $message
    $message | Tee-Object -FilePath $LogPath -Append
    $exitCode = 1
}
"[$(Get-Date -Format o)] visible membership-v3 source probe exit_code=$exitCode" |
    Tee-Object -FilePath $LogPath -Append
if ($HoldOpenSec -gt 0) {
    Write-Host "Terminal closes in $HoldOpenSec seconds."
    Start-Sleep -Seconds $HoldOpenSec
}
exit $exitCode

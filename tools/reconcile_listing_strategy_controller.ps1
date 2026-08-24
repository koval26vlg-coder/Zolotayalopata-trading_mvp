param(
    [string]$GatePath = "C:\Users\koval\Documents\ZolotyayLopata\docs\agent-log\active-run-gate.json",
    [string]$CurrentRunPath = "C:\Users\koval\Documents\ZolotyayLopata\docs\agent-log\current-run.json",
    [string]$ArchiveDir = "C:\Users\koval\Documents\ZolotyayLopata\docs\agent-log\archived-gates",
    [string]$ReceiptPath = "C:\Users\koval\Documents\ZolotyayLopata\docs\agent-log\listing-strategy-controller-reconciliation-20260821.json",
    [string]$ExpectedStoppedRunId = "slow_liquidity_listing_momentum_forward_monitor_20260817_v2",
    [string]$ExpectedNeutralRunId = "resolved_incomplete_20260819_094844395",
    [ValidateRange(1, 300)][int]$ControllerMutexTimeoutSec = 30,
    [string]$BeforeCommitTestHookPath = "",
    [string]$AfterFinalSnapshotTestHookPath = "",
    [switch]$PlanOnly,
    [switch]$Json
)

$ErrorActionPreference = "Stop"
$strictUtf8 = [System.Text.UTF8Encoding]::new($false, $true)

function Get-FileSha256 {
    param([Parameter(Mandatory = $true)][string]$Path)
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

function Read-StrictJson {
    param([Parameter(Mandatory = $true)][string]$Path)
    return (Read-StrictJsonSnapshot -Path $Path).Value
}

function Read-StrictJsonSnapshot {
    param([Parameter(Mandatory = $true)][string]$Path)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "Required JSON file missing: $Path"
    }
    $bytes = [System.IO.File]::ReadAllBytes($Path)
    if ($bytes.Length -eq 0) { throw "Required JSON file is empty: $Path" }
    $text = $strictUtf8.GetString($bytes)
    if ($text.Length -gt 0 -and $text[0] -eq [char]0xFEFF) {
        $text = $text.Substring(1)
    }
    return [pscustomobject]@{
        Value = ConvertFrom-Json -InputObject $text -ErrorAction Stop
        Sha256 = [System.Convert]::ToHexString(
            [System.Security.Cryptography.SHA256]::HashData($bytes)
        ).ToLowerInvariant()
    }
}

function Get-DeclaredProcessIds {
    param([Parameter(Mandatory = $true)]$Record)
    $ids = [System.Collections.Generic.List[int]]::new()
    foreach ($value in @(@($Record.process_ids) + @($Record.collector_pid, $Record.monitor_pid))) {
        if ($null -eq $value -or [string]::IsNullOrWhiteSpace([string]$value)) { continue }
        $parsed = 0
        if ([int]::TryParse([string]$value, [ref]$parsed) -and $parsed -gt 0) {
            $ids.Add($parsed)
        }
    }
    return @($ids | Sort-Object -Unique)
}

function Write-JsonAtomic {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)]$Value
    )
    $parent = Split-Path -Parent $Path
    if ($parent) { New-Item -ItemType Directory -Path $parent -Force | Out-Null }
    $tempPath = "$Path.tmp.$PID.$([DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds())"
    try {
        $encoded = $Value | ConvertTo-Json -Depth 30
        [System.IO.File]::WriteAllText($tempPath, $encoded + [Environment]::NewLine, [System.Text.UTF8Encoding]::new($false))
        Move-Item -LiteralPath $tempPath -Destination $Path -Force
    } finally {
        if (Test-Path -LiteralPath $tempPath) { Remove-Item -LiteralPath $tempPath -Force }
    }
}

function Get-TextSha256 {
    param([Parameter(Mandatory = $true)][string]$Text)
    $bytes = [System.Text.Encoding]::UTF8.GetBytes($Text)
    return [System.Convert]::ToHexString(
        [System.Security.Cryptography.SHA256]::HashData($bytes)
    ).ToLowerInvariant()
}

function Assert-NeutralGate {
    param([Parameter(Mandatory = $true)]$Record)
    if (
        [string]$Record.schema -ne "active_run_gate_v2" -or
        [string]$Record.project -ne "trading_mvp" -or
        [string]$Record.run_id -ne $ExpectedNeutralRunId -or
        [string]$Record.status -ne "READY_FOR_POSTPROCESS" -or
        [string]$Record.gate_status -ne "READY_FOR_POSTPROCESS" -or
        -not [bool]$Record.final
    ) {
        throw "Neutral active-run gate does not match the expected resolved-incomplete controller."
    }
    if (
        [bool]$Record.replay_allowed -or
        [bool]$Record.grid_allowed -or
        [bool]$Record.backtest_allowed -or
        [bool]$Record.paper_forward_allowed
    ) {
        throw "Neutral active-run gate unexpectedly authorizes downstream execution."
    }
    if (@(Get-DeclaredProcessIds -Record $Record).Count -ne 0) {
        throw "Neutral active-run gate declares process identity."
    }
}

function Assert-ControllerPointer {
    param([Parameter(Mandatory = $true)]$Record)
    if (
        [string]$Record.schema -ne "active_run_pointer_v1" -or
        [string]$Record.project -ne "trading_mvp"
    ) {
        throw "Current-run pointer schema or project mismatch."
    }
}

function Test-ReconciledPointer {
    param([Parameter(Mandatory = $true)]$Record)
    return (
        [string]$Record.run_id -eq $ExpectedNeutralRunId -and
        [string]$Record.status -eq "READY_FOR_POSTPROCESS" -and
        @(Get-DeclaredProcessIds -Record $Record).Count -eq 0 -and
        (Test-Path -LiteralPath $ReceiptPath -PathType Leaf)
    )
}

function Assert-StoppedPointer {
    param([Parameter(Mandatory = $true)]$Record)
    Assert-ControllerPointer -Record $Record
    if (
        [string]$Record.run_id -ne $ExpectedStoppedRunId -or
        [string]$Record.status -ne "STOPPED_INCOMPLETE"
    ) {
        throw "Current-run pointer is not the expected stopped listing attempt."
    }
    if (@(Get-DeclaredProcessIds -Record $Record).Count -ne 0) {
        throw "Stopped current-run pointer declares process identity."
    }
}

$initialGateSnapshot = Read-StrictJsonSnapshot -Path $GatePath
$initialPointerSnapshot = Read-StrictJsonSnapshot -Path $CurrentRunPath
$gate = $initialGateSnapshot.Value
$pointer = $initialPointerSnapshot.Value

Assert-NeutralGate -Record $gate
Assert-ControllerPointer -Record $pointer
$initialAlreadyReconciled = Test-ReconciledPointer -Record $pointer
if (-not $initialAlreadyReconciled) {
    Assert-StoppedPointer -Record $pointer
}

if (-not $PlanOnly -and -not [string]::IsNullOrWhiteSpace($BeforeCommitTestHookPath)) {
    if (-not (Test-Path -LiteralPath $BeforeCommitTestHookPath -PathType Leaf)) {
        throw "Before-commit test hook missing: $BeforeCommitTestHookPath"
    }
    & $BeforeCommitTestHookPath
}

$mutexKey = Get-TextSha256 -Text (
    [System.IO.Path]::GetFullPath($CurrentRunPath).ToLowerInvariant()
)
$mutexName = "Global\ZolotyayLopata.ListingStrategyCurrentRun.$mutexKey"
$controllerMutex = [System.Threading.Mutex]::new($false, $mutexName)
$mutexHeld = $false

try {
    try {
        $mutexHeld = $controllerMutex.WaitOne(
            [TimeSpan]::FromSeconds($ControllerMutexTimeoutSec)
        )
    } catch [System.Threading.AbandonedMutexException] {
        $mutexHeld = $true
    }
    if (-not $mutexHeld) {
        throw "Timed out waiting for listing-strategy controller mutex."
    }

    $lockedGateSnapshot = Read-StrictJsonSnapshot -Path $GatePath
    $lockedPointerSnapshot = Read-StrictJsonSnapshot -Path $CurrentRunPath
    $gateChanged = (
        $lockedGateSnapshot.Sha256 -ne $initialGateSnapshot.Sha256
    )
    $pointerChanged = (
        $lockedPointerSnapshot.Sha256 -ne $initialPointerSnapshot.Sha256
    )
    $concurrentReconciliationWon = (
        $pointerChanged -and
        -not $gateChanged -and
        (Test-ReconciledPointer -Record $lockedPointerSnapshot.Value)
    )
    if ($gateChanged -or ($pointerChanged -and -not $concurrentReconciliationWon)) {
        throw "Controller inputs changed during reconciliation; refusing commit."
    }

    $gate = $lockedGateSnapshot.Value
    $pointer = $lockedPointerSnapshot.Value
    Assert-NeutralGate -Record $gate
    Assert-ControllerPointer -Record $pointer

    $alreadyReconciled = Test-ReconciledPointer -Record $pointer
    if ($alreadyReconciled) {
        $existingReceipt = Read-StrictJson -Path $ReceiptPath
        if (
            [string]$existingReceipt.schema -ne
            "trading_mvp_listing_strategy_controller_reconciliation_v1" -or
            [string]$existingReceipt.stopped_run_id -ne $ExpectedStoppedRunId -or
            [string]$existingReceipt.neutral_run_id -ne $ExpectedNeutralRunId
        ) {
            throw "Existing reconciliation receipt identity mismatch."
        }
        $existingCore = [ordered]@{
            schema = [string]$existingReceipt.schema
            project = [string]$existingReceipt.project
            stopped_run_id = [string]$existingReceipt.stopped_run_id
            neutral_run_id = [string]$existingReceipt.neutral_run_id
            disposition = [string]$existingReceipt.disposition
            stopped_pointer = $existingReceipt.stopped_pointer
            neutral_gate = $existingReceipt.neutral_gate
            accrual_state = $existingReceipt.accrual_state
            failed_launch_record = $existingReceipt.failed_launch_record
            acceptance_authorized = [bool]$existingReceipt.acceptance_authorized
            replay_authorized = [bool]$existingReceipt.replay_authorized
            evaluator_or_oos_authorized = [bool]$existingReceipt.evaluator_or_oos_authorized
            runtime_activated = [bool]$existingReceipt.runtime_activated
        }
        $existingHash = Get-TextSha256 -Text (
            $existingCore | ConvertTo-Json -Depth 30 -Compress
        )
        if ([string]$existingReceipt.deterministic_result_hash -ne $existingHash) {
            throw "Existing reconciliation receipt deterministic hash mismatch."
        }
        $reused = [ordered]@{
            status = "RECONCILIATION_REUSED"
            stopped_run_id = $ExpectedStoppedRunId
            neutral_run_id = $ExpectedNeutralRunId
            disposition = [string]$existingReceipt.disposition
            deterministic_result_hash = $existingHash
            accrual_counts = [ordered]@{
                tick_count = [int]$existingReceipt.accrual_state.tick_count
                window_count = [int]$existingReceipt.accrual_state.window_count
                complete_window_count = [int]$existingReceipt.accrual_state.complete_window_count
            }
            runtime_activated = $false
            pointer_updated = $false
            receipt_path = [System.IO.Path]::GetFullPath($ReceiptPath)
            archived_pointer_path = $null
        }
        if ($Json) {
            $reused | ConvertTo-Json -Depth 20
        } else {
            [pscustomobject]$reused | Format-List
        }
        return
    }

    Assert-StoppedPointer -Record $pointer
    $commitGateSha256 = [string]$lockedGateSnapshot.Sha256
    $commitPointerSha256 = [string]$lockedPointerSnapshot.Sha256

    $statePath = [string]$pointer.manifest_path
    $launchPath = [string]$pointer.launch_record_path
    $state = Read-StrictJson -Path $statePath
    $launch = Read-StrictJson -Path $launchPath
    if ([string]$launch.run_id -ne $ExpectedStoppedRunId) {
        throw "Failed launch record run_id mismatch."
    }
    if ([string]$launch.status -notin @("FAILED", "STOPPED_INCOMPLETE")) {
        throw "Expected a terminal failed listing launch record."
    }
    $visiblePid = 0
    if (
        [int]::TryParse([string]$launch.visible_terminal_pid, [ref]$visiblePid) -and
        $visiblePid -gt 0 -and
        (Get-Process -Id $visiblePid -ErrorAction SilentlyContinue)
    ) {
        throw "Failed listing launch still has a live visible terminal PID."
    }
    if ([string]$state.acceptance_decision -ne "NONE_ACCRUAL_ONLY") {
        throw "Listing accrual state is not descriptive-only."
    }

    $receiptCore = [ordered]@{
        schema = "trading_mvp_listing_strategy_controller_reconciliation_v1"
        project = "trading_mvp"
        stopped_run_id = $ExpectedStoppedRunId
        neutral_run_id = $ExpectedNeutralRunId
        disposition = "INCOMPLETE_ATTEMPT_REJECTED_ACCRUAL_PRESERVED"
        stopped_pointer = [ordered]@{
            path = [System.IO.Path]::GetFullPath($CurrentRunPath)
            file_sha256 = $commitPointerSha256
        }
        neutral_gate = [ordered]@{
            path = [System.IO.Path]::GetFullPath($GatePath)
            file_sha256 = $commitGateSha256
        }
        accrual_state = [ordered]@{
            path = [System.IO.Path]::GetFullPath($statePath)
            file_sha256 = Get-FileSha256 -Path $statePath
            tick_count = [int]$state.tick_count
            window_count = [int]$state.window_count
            complete_window_count = [int]$state.complete_window_count
            acceptance_decision = [string]$state.acceptance_decision
            preservation = "DESCRIPTIVE_ACCRUAL_ONLY"
        }
        failed_launch_record = [ordered]@{
            path = [System.IO.Path]::GetFullPath($launchPath)
            file_sha256 = Get-FileSha256 -Path $launchPath
            status = [string]$launch.status
            tick_exit_code = $launch.tick_exit_code
        }
        acceptance_authorized = $false
        replay_authorized = $false
        evaluator_or_oos_authorized = $false
        runtime_activated = $false
    }
    $deterministicHash = Get-TextSha256 -Text (
        $receiptCore | ConvertTo-Json -Depth 30 -Compress
    )
    $now = [DateTimeOffset]::UtcNow.ToString("o")

    $result = [ordered]@{
        status = if ($PlanOnly) {
            "RECONCILIATION_PLAN_VALID"
        } else {
            "RECONCILED"
        }
        stopped_run_id = $ExpectedStoppedRunId
        neutral_run_id = $ExpectedNeutralRunId
        disposition = $receiptCore.disposition
        deterministic_result_hash = $deterministicHash
        accrual_counts = [ordered]@{
            tick_count = [int]$state.tick_count
            window_count = [int]$state.window_count
            complete_window_count = [int]$state.complete_window_count
        }
        runtime_activated = $false
        pointer_updated = $false
        receipt_path = [System.IO.Path]::GetFullPath($ReceiptPath)
        archived_pointer_path = $null
    }

    if (-not $PlanOnly) {
        $finalGateSnapshot = Read-StrictJsonSnapshot -Path $GatePath
        $finalPointerSnapshot = Read-StrictJsonSnapshot -Path $CurrentRunPath
        if (
            $finalGateSnapshot.Sha256 -ne $commitGateSha256 -or
            $finalPointerSnapshot.Sha256 -ne $commitPointerSha256
        ) {
            throw "Controller inputs changed during reconciliation; refusing commit."
        }
        Assert-NeutralGate -Record $finalGateSnapshot.Value
        Assert-StoppedPointer -Record $finalPointerSnapshot.Value

        if (-not [string]::IsNullOrWhiteSpace($AfterFinalSnapshotTestHookPath)) {
            if (-not (Test-Path -LiteralPath $AfterFinalSnapshotTestHookPath -PathType Leaf)) {
                throw "After-final-snapshot test hook missing: $AfterFinalSnapshotTestHookPath"
            }
            & $AfterFinalSnapshotTestHookPath
        }

        $receipt = [ordered]@{}
        foreach ($entry in $receiptCore.GetEnumerator()) { $receipt[$entry.Key] = $entry.Value }
        $receipt["deterministic_result_hash"] = $deterministicHash
        $receipt["reconciled_at_utc"] = $now

        if (Test-Path -LiteralPath $ReceiptPath) {
            $prior = Read-StrictJson -Path $ReceiptPath
            if ([string]$prior.deterministic_result_hash -ne $deterministicHash) {
                throw "Immutable reconciliation receipt mismatch."
            }
        } else {
            Write-JsonAtomic -Path $ReceiptPath -Value $receipt
        }

        New-Item -ItemType Directory -Path $ArchiveDir -Force | Out-Null
        $stamp = [DateTimeOffset]::UtcNow.ToString("yyyyMMddTHHmmssfffZ")
        $safeRun = $ExpectedStoppedRunId -replace "[^A-Za-z0-9_.-]", "_"
        $archivePath = Join-Path $ArchiveDir "current-run.$safeRun.$stamp.json"
        Copy-Item -LiteralPath $CurrentRunPath -Destination $archivePath

        $neutralPointer = [ordered]@{
            schema = "active_run_pointer_v1"
            project = "trading_mvp"
            run_id = $ExpectedNeutralRunId
            status = "READY_FOR_POSTPROCESS"
            updated_at = $now
            collector_pid = $null
            monitor_pid = $null
            process_ids = @()
            controller_reconciliation_receipt_path = [System.IO.Path]::GetFullPath($ReceiptPath)
            controller_reconciliation_receipt_sha256 = Get-FileSha256 -Path $ReceiptPath
        }
        Write-JsonAtomic -Path $CurrentRunPath -Value $neutralPointer
        $result.pointer_updated = $true
        $result.archived_pointer_path = $archivePath
    }

    if ($Json) {
        $result | ConvertTo-Json -Depth 20
    } else {
        [pscustomobject]$result | Format-List
    }
} finally {
    if ($mutexHeld) {
        $controllerMutex.ReleaseMutex()
    }
    $controllerMutex.Dispose()
}

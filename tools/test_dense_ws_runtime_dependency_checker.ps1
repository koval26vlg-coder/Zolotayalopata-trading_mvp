param(
    [string]$PlanPath = "E:\ZolotyayLopata-data\exports\trading-mvp\autopilot\campaigns\dense-ws-microstructure-regime-filter-planonly-20260803-aef-24h-v1.json",
    [string]$ExpectedPlanHash = "57231016ac62e79bcbef54c71ba059b330d08254683c3334ed6ae5de40335a8b"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$checker = Join-Path $PSScriptRoot "check_dense_ws_runtime_dependencies.ps1"
$manifest = Join-Path (Resolve-Path (Join-Path $PSScriptRoot "..")) `
    "docs\plans\dense-ws-runtime-dependency-manifest-20260803-aef-24h-v1.json"
$passed = 0
$failed = 0
$cases = [System.Collections.Generic.List[object]]::new()

function Record-Case {
    param([string]$Name, [bool]$Passed, [string]$Reason = "")
    if ($Passed) { $script:passed++ } else { $script:failed++ }
    $record = [ordered]@{ name = $Name; passed = $Passed }
    if (-not $Passed) { $record.reason = $Reason }
    $script:cases.Add($record)
}

try {
    $manifestPayload = Get-Content -Raw -LiteralPath $manifest |
        ConvertFrom-Json -DateKind String
    Record-Case "manifest_schema" `
        ($manifestPayload.schema -eq "trading_mvp_dense_ws_runtime_dependency_manifest_v1")
    Record-Case "manifest_exact_plan" `
        ($manifestPayload.plan.plan_hash -eq $ExpectedPlanHash)
    Record-Case "manifest_no_runtime_scope_expansion" `
        (
            $manifestPayload.scope.changes_frozen_collector -eq $false -and
            $manifestPayload.scope.starts_writer -eq $false -and
            $manifestPayload.scope.reads_returns_pnl_or_oos -eq $false
        )
} catch {
    Record-Case "manifest_load" $false $_.Exception.Message
}

if (-not (Test-Path -LiteralPath $checker -PathType Leaf)) {
    Record-Case "checker_exists" $false "checker is not implemented"
} else {
    Record-Case "checker_exists" $true
    try {
        $raw = & pwsh -NoProfile -ExecutionPolicy Bypass -File $checker `
            -PlanPath $PlanPath -ExpectedPlanHash $ExpectedPlanHash -Json 2>&1
        if ($LASTEXITCODE -ne 0) {
            throw "checker exit $LASTEXITCODE`: $($raw | Out-String)"
        }
        $result = ($raw | Out-String) | ConvertFrom-Json -DateKind String
        Record-Case "current_runtime_ready" ($result.status -eq "READY")
        Record-Case "write_free" ($result.no_run_or_output_writes -eq $true)
        Record-Case "network_free" `
            (
                $result.network_request_performed -eq $false -and
                @($result.python_probe.outbound_network_events).Count -eq 0
            )
        Record-Case "writer_not_started" ($result.writer_started -eq $false)
        Record-Case "all_dependencies_verified" `
            (
                @($result.blockers).Count -eq 0 -and
                $result.python_probe.imports_ok -eq $true
            )
    } catch {
        Record-Case "checker_execution" $false $_.Exception.Message
    }

    $source = Get-Content -Raw -LiteralPath $checker
    $mutatingPattern = "(?i)Start-Process|Invoke-WebRequest|Invoke-RestMethod|New-Item|Set-Content|Add-Content|Out-File"
    Record-Case "checker_has_no_writer_or_web_primitive" `
        ($source -notmatch $mutatingPattern)

    try {
        $bad = & pwsh -NoProfile -ExecutionPolicy Bypass -File $checker `
            -PlanPath $PlanPath -ExpectedPlanHash ("0" * 64) -Json 2>&1
        Record-Case "reject_wrong_plan_hash" ($LASTEXITCODE -ne 0)
    } catch {
        Record-Case "reject_wrong_plan_hash" $true
    }
}

$result = [ordered]@{
    schema = "trading_mvp_dense_ws_runtime_dependency_checker_test_v1"
    passed = $failed -eq 0
    passed_count = $passed
    failed_count = $failed
    cases = $cases
    network_collector_started = $false
    writer_started = $false
    market_rows_read = $false
    returns_read = $false
    pnl_read = $false
    oos_run = $false
    grid_or_retune = $false
}
$result | ConvertTo-Json -Depth 12
if ($failed -ne 0) { exit 1 }

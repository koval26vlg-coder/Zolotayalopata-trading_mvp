param(
    [string]$OutputPath = "",
    [switch]$UpdateGate,
    [switch]$Json
)

$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$gateChecker = Join-Path $repoRoot "tools\check_active_run_gate.ps1"
$gatePath = Join-Path $repoRoot "docs\agent-log\active-run-gate.json"
$fundingClientPath = Join-Path $repoRoot "trading_mvp\src\funding.py"
$dailyCollectorPath = Join-Path $repoRoot "trading_mvp\src\daily_collector.py"
$basisClientPath = Join-Path $repoRoot "trading_mvp\src\basis.py"

if (-not $OutputPath) {
    $timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
    $OutputPath = Join-Path $repoRoot "exports\trading-mvp\analysis\pit_universe_snapshot_preflight_planonly_$timestamp.json"
}

function Read-JsonFileOrNull {
    param([string]$Path)
    if ([string]::IsNullOrWhiteSpace($Path) -or -not (Test-Path -LiteralPath $Path)) {
        return $null
    }
    return (Get-Content -Raw -LiteralPath $Path | ConvertFrom-Json)
}

function Set-JsonProperty {
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

function Save-Result {
    param($Payload)
    $outDir = Split-Path -Parent $OutputPath
    if ($outDir -and -not (Test-Path -LiteralPath $outDir)) {
        New-Item -ItemType Directory -Force -Path $outDir | Out-Null
    }
    $Payload | ConvertTo-Json -Depth 16 | Set-Content -LiteralPath $OutputPath -Encoding UTF8
    if ($Json) {
        $Payload | ConvertTo-Json -Depth 16
        return
    }
    Write-Host "PIT Universe Snapshot Preflight PlanOnly" -ForegroundColor Cyan
    Write-Host "Decision: $($Payload.decision)"
    Write-Host "Output: $OutputPath"
}

$gate = & pwsh -NoProfile -ExecutionPolicy Bypass -File $gateChecker -Json | ConvertFrom-Json
if ([string]$gate.status -in @("RUNNING", "STOPPED_INCOMPLETE")) {
    $blocked = [ordered]@{
        generated_at = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss zzz")
        mode = "pit_universe_snapshot_preflight_planonly"
        decision = "BLOCKED_BY_ACTIVE_RUN_GATE"
        would_start = $false
        research_only = $true
        live_orders = $false
        api_keys = $false
        leverage_or_margin = $false
        collect_allowed_now = $false
        replay_allowed_now = $false
        grid_allowed_now = $false
        paper_forward_allowed = $false
        reason = "Active run gate is $($gate.status); only status/resume work is allowed."
        output_path = $OutputPath
    }
    Save-Result -Payload $blocked
    exit 0
}

$rawGate = Read-JsonFileOrNull -Path $gatePath
$fundingClientExists = Test-Path -LiteralPath $fundingClientPath
$dailyCollectorExists = Test-Path -LiteralPath $dailyCollectorPath
$basisClientExists = Test-Path -LiteralPath $basisClientPath
$readyForPublicProbe = [bool]($fundingClientExists -and $dailyCollectorExists)
$decision = if ($readyForPublicProbe) { "PIT_UNIVERSE_SNAPSHOT_PREFLIGHT_PLANONLY_READY_FOR_PUBLIC_PROBE" } else { "PIT_UNIVERSE_SNAPSHOT_PREFLIGHT_PLANONLY_BLOCKED_MISSING_CLIENTS" }

$result = [ordered]@{
    generated_at = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss zzz")
    mode = "pit_universe_snapshot_preflight_planonly"
    decision = $decision
    selected_branch = "forward_pit_universe_event_liquidity_anomaly"
    would_start = $false
    research_only = $true
    live_orders = $false
    api_keys = $false
    leverage_or_margin = $false
    collect_allowed_now = $false
    replay_allowed_now = $false
    grid_allowed_now = $false
    paper_forward_allowed = $false
    public_probe_allowed_next = $readyForPublicProbe
    reason = if ($readyForPublicProbe) { "Local public REST client stack exists. A short foreground public probe can verify fields before any visible snapshot collector is proposed." } else { "Missing local client files required to build the PIT snapshot public probe." }
    current_gate = [ordered]@{
        status = $gate.status
        next_goal_decision = $gate.next_goal_decision
        replay_allowed = $gate.replay_allowed
        strategy_branch_status = if ($rawGate) { $rawGate.strategy_branch_status } else { $null }
    }
    local_readiness = [ordered]@{
        funding_client_path = $fundingClientPath
        funding_client_exists = $fundingClientExists
        daily_collector_path = $dailyCollectorPath
        daily_collector_exists = $dailyCollectorExists
        basis_client_path = $basisClientPath
        basis_client_exists = $basisClientExists
    }
    public_probe_design = [ordered]@{
        exchanges_v1 = @("mexc", "gateio")
        no_api_keys = $true
        endpoints = @(
            [ordered]@{ exchange = "mexc"; endpoint = "contract/detail"; purpose = "active contract list and contract metadata" },
            [ordered]@{ exchange = "mexc"; endpoint = "contract/ticker"; purpose = "current quote volume and ticker fields for snapshot ranking only" },
            [ordered]@{ exchange = "gateio"; endpoint = "futures/usdt/contracts"; purpose = "active contract list and status metadata" },
            [ordered]@{ exchange = "gateio"; endpoint = "futures/usdt/tickers"; purpose = "current quote volume and ticker fields for snapshot ranking only" }
        )
        required_snapshot_fields = @(
            "snapshot_ts",
            "exchange",
            "symbol",
            "base",
            "quote",
            "contract_type",
            "status",
            "listed_now",
            "inactive_or_delisted",
            "volume_24h_quote",
            "source_endpoint",
            "raw_status",
            "first_seen_ts",
            "last_seen_ts"
        )
        anti_survivorship_rules = @(
            "Every future signal uses only symbols present in snapshots at or before decision time.",
            "Symbols disappearing from later snapshots stay in the universe with inactive_or_delisted=true.",
            "No-data, inactive, delisted and too-illiquid outcomes stay in the denominator.",
            "Current 24h volume may rank only the current snapshot; it must never backfill historical membership."
        )
    }
    acceptance_gates = @(
        "public_probe_returns_contracts_for_mexc_and_gateio",
        "snapshot_schema_has_status_and_volume_fields",
        "point_in_time_keys_available_or_derivable",
        "inactive_missing_symbols_can_be_represented_as_negative_outcomes",
        "no_api_keys_or_private_endpoints_required"
    )
    rejection_gates = @(
        "public_probe_cannot_get_contract_lists",
        "status_or_symbol_identity_missing",
        "cannot_represent_inactive_or_missing_symbols",
        "requires_private_api_or_live_trading_access"
    )
    next_valid_moves = if ($readyForPublicProbe) {
        @(
            "Run a short foreground public probe for MEXC/Gate contract/ticker fields.",
            "If probe passes, build a visible snapshot collector approval packet.",
            "Do not run long collector, replay, grid, live orders, API keys, leverage, margin or paper-forward."
        )
    } else {
        @(
            "Restore or implement public client files before any probe.",
            "Do not run collector, replay, grid, live orders, API keys, leverage, margin or paper-forward."
        )
    }
    blocked_moves = @(
        "live_orders",
        "api_keys",
        "leverage_or_margin",
        "grid_search",
        "paper_forward",
        "hidden_background_collect",
        "long_collect_without_visible_approval"
    )
    commands = [ordered]@{
        rerun_this_planonly = "pwsh -NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`" -Json"
        rerun_and_update_gate = "pwsh -NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`" -UpdateGate -Json"
        active_run_gate = "pwsh -NoProfile -ExecutionPolicy Bypass -File `"$gateChecker`""
    }
    output_path = $OutputPath
}

if ($UpdateGate) {
    $gateDoc = Get-Content -Raw -LiteralPath $gatePath | ConvertFrom-Json
    $nextStep = if ($readyForPublicProbe) { "Run short foreground PIT universe public probe; no long collect/grid/live/API/paper-forward." } else { "Restore public client stack for PIT universe preflight; no collect/grid/live/API/paper-forward." }
    $branchVerdict = if ($readyForPublicProbe) { "pit_snapshot_preflight_ready_for_public_probe" } else { "pit_snapshot_preflight_blocked_missing_clients" }
    $branchNextStep = if ($readyForPublicProbe) { "run_short_pit_universe_public_probe" } else { "restore_public_client_stack" }
    Set-JsonProperty -Object $gateDoc -Name "updated_at" -Value ((Get-Date).ToString("yyyy-MM-ddTHH:mm:sszzz"))
    Set-JsonProperty -Object $gateDoc -Name "next_goal_decision" -Value $decision
    Set-JsonProperty -Object $gateDoc -Name "next_goal_reason" -Value $result.reason
    Set-JsonProperty -Object $gateDoc -Name "next_step_after_ready" -Value $nextStep
    Set-JsonProperty -Object $gateDoc -Name "raw_gate_next_step_after_ready" -Value $gateDoc.next_step_after_ready
    Set-JsonProperty -Object $gateDoc -Name "replay_allowed" -Value $false
    Set-JsonProperty -Object $gateDoc -Name "requires_explicit_user_approval_for_public_probe" -Value $false
    Set-JsonProperty -Object $gateDoc -Name "requires_explicit_user_approval_for_actual_collect" -Value $true
    Set-JsonProperty -Object $gateDoc -Name "strategy_branch_status" -Value ([ordered]@{
        branch = "forward_pit_universe_event_liquidity_anomaly"
        verdict = $branchVerdict
        decision_source = $OutputPath
        selected_at = $result.generated_at
        live_orders = $false
        api_keys = $false
        leverage_or_margin = $false
        collect_allowed_now = $false
        replay_allowed_now = $false
        grid_allowed = $false
        paper_forward_allowed = $false
        next_step_required = $branchNextStep
    })
    Set-JsonProperty -Object $gateDoc -Name "last_pit_universe_snapshot_preflight_output_path" -Value $OutputPath
    Set-JsonProperty -Object $gateDoc -Name "last_pit_universe_snapshot_preflight_decision" -Value $decision
    $gateDoc | ConvertTo-Json -Depth 16 | Set-Content -LiteralPath $gatePath -Encoding UTF8
    $result["gate_updated"] = $true
} else {
    $result["gate_updated"] = $false
}

Save-Result -Payload $result

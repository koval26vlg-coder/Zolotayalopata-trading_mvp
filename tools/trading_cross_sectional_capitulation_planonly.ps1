param(
    [string]$OutputPath = "E:\ZolotyayLopata-data\exports\trading-mvp\analysis\cross_sectional_capitulation_planonly_20260712_2125.json",
    [switch]$UpdateGate,
    [switch]$Json
)

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$gatePath = Join-Path $repoRoot "docs\agent-log\active-run-gate.json"
$gateChecker = Join-Path $repoRoot "tools\check_active_run_gate.ps1"
$sourcePath = "E:\trading_mvp\slow-liquidity-history\slow_liquidity_history_collect_20260709_201330\ohlcv.jsonl"
$historyManifestPath = "E:\trading_mvp\slow-liquidity-history\slow_liquidity_history_collect_20260709_201330\manifest.json"
$universePath = Join-Path $repoRoot "coins_not_on_binance_full_2026-05-29.csv"
$priorAuditPath = "E:\ZolotyayLopata-data\exports\trading-mvp\analysis\cross_venue_spot_lead_lag_audit_20260712_2115.json"

function Write-JsonAtomic {
    param($Value, [string]$Path)
    $parent = Split-Path -Parent $Path
    New-Item -ItemType Directory -Force -Path $parent | Out-Null
    $temp = "$Path.tmp.$PID"
    $Value | ConvertTo-Json -Depth 100 | Set-Content -LiteralPath $temp -Encoding UTF8
    Move-Item -LiteralPath $temp -Destination $Path -Force
}

function Set-JsonProperty {
    param($Object, [string]$Name, $Value)
    if ($Object.PSObject.Properties.Name -contains $Name) { $Object.$Name = $Value }
    else { $Object | Add-Member -NotePropertyName $Name -NotePropertyValue $Value }
}

foreach ($path in @($sourcePath, $historyManifestPath, $universePath, $priorAuditPath)) {
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "Required evidence not found: $path" }
}
$gate = & pwsh -NoProfile -ExecutionPolicy Bypass -File $gateChecker -Json | ConvertFrom-Json
if ([string]$gate.status -eq "RUNNING") { throw "Active run gate is RUNNING; PlanOnly selection is blocked." }

if (Test-Path -LiteralPath $OutputPath -PathType Leaf) {
    $plan = Get-Content -Raw -LiteralPath $OutputPath | ConvertFrom-Json
    if ([string]$plan.schema -ne "cross_sectional_capitulation_plan_v1") {
        throw "Refusing to overwrite non-matching sealed plan: $OutputPath"
    }
} else {
    $sourceHash = (Get-FileHash -LiteralPath $sourcePath -Algorithm SHA256).Hash.ToLowerInvariant()
    $manifestHash = (Get-FileHash -LiteralPath $historyManifestPath -Algorithm SHA256).Hash.ToLowerInvariant()
    $universeHash = (Get-FileHash -LiteralPath $universePath -Algorithm SHA256).Hash.ToLowerInvariant()
    $priorAuditHash = (Get-FileHash -LiteralPath $priorAuditPath -Algorithm SHA256).Hash.ToLowerInvariant()
    $plan = [ordered]@{
        schema = "cross_sectional_capitulation_plan_v1"
        generated_at = (Get-Date).ToString("yyyy-MM-ddTHH:mm:sszzz")
        decision = "CROSS_SECTIONAL_CAPITULATION_PLANONLY_READY_FOR_FIXED_REPLAY_IMPLEMENTATION"
        branch = "cross_sectional_capitulation_rebound_4h_spot"
        research_only = $true
        would_start = $false
        fixed_parameters_no_grid = $true
        strategy_accepted = $false
        prior_branch_closure = [ordered]@{
            branch = "cross_venue_spot_lead_lag_spillover"
            verdict = "verified_rejected_no_fixed_signals"
            audit_path = $priorAuditPath
            audit_sha256 = $priorAuditHash
        }
        data = [ordered]@{
            history_jsonl_path = $sourcePath
            history_jsonl_sha256 = $sourceHash
            history_manifest_path = $historyManifestPath
            history_manifest_sha256 = $manifestHash
            universe_path = $universePath
            universe_sha256 = $universeHash
            universe_asof = "2026-05-29T23:59:59Z"
            analysis_start = "2026-05-30T00:00:00Z"
            max_universe_rank = 50
            exchange = "gateio"
            instrument = "spot"
            quote = "USDT"
            timeframe = "4h"
            bar_sec = 14400
            require_source_status = "ok"
            retain_no_data_and_api_error_bases_in_coverage = $true
        }
        signal = [ordered]@{
            name = "cross_sectional_capitulation_rebound_v1"
            direction = "long_only_spot"
            lookback_bars = 6
            lookback_hours = 24
            base_return_max_bps = -800.0
            residual_vs_peer_median_max_bps = -600.0
            min_peer_count = 10
            close_location_min = 0.60
            volume_lookback_bars = 20
            min_current_quote_volume = 50000.0
            min_trailing_median_quote_volume = 25000.0
            min_volume_ratio = 1.50
            entry = "next_4h_open"
            hold_bars = 6
            hold_hours = 24
            cooldown_bars = 12
            cooldown_hours = 48
            max_concurrent_positions = 3
            same_timestamp_priority = "most_negative_residual_first"
            take_profit = $null
            stop_loss = $null
        }
        execution = [ordered]@{
            account_assumption = "base_or_vip0_no_volume"
            notional_quote = 100.0
            normal_round_trip_fee_bps = 40.0
            normal_spread_slippage_buffer_bps = 80.0
            normal_total_cost_bps = 120.0
            stress_total_cost_bps = 245.0
            fill_model = "next_bar_open_then_fixed_hold_close"
            missing_entry_or_exit = "skip_and_count_as_execution_failure"
            simultaneous_positions_share = "equal_notional_up_to_three"
        }
        validation = [ordered]@{
            train_fraction = 0.70
            walk_forward_folds = 4
            min_total_trades = 50
            min_oos_trades = 15
            min_distinct_oos_bases = 5
            min_oos_expectancy_bps = 0.0
            min_oos_profit_factor = 1.20
            min_positive_fold_ratio = 0.60
            min_trades_per_fold = 5
            min_stress_expectancy_bps = 0.0
            max_top_base_positive_contribution = 0.40
            max_drawdown_quote = 25.0
            win_rate = "diagnostic_only"
        }
        proof_policy = [ordered]@{
            optimize_for = "net_expectancy_after_costs"
            no_same_sample_tuning = $true
            oos_required = $true
            walk_forward_required = $true
            stress_required = $true
            survivorship_control_required = $true
            paper_forward_only_after_all_gates_and_independent_audit = $true
        }
        blocked_actions = @(
            "collect",
            "grid_search",
            "live_orders",
            "api_keys",
            "leverage_or_margin",
            "paper_forward_before_pass",
            "reuse_lead_lag_threshold_tuning"
        )
    }
    Write-JsonAtomic $plan $OutputPath
}

$planHash = (Get-FileHash -LiteralPath $OutputPath -Algorithm SHA256).Hash.ToLowerInvariant()
$result = [ordered]@{
    schema = "cross_sectional_capitulation_planonly_result_v1"
    generated_at = (Get-Date).ToString("yyyy-MM-ddTHH:mm:sszzz")
    decision = [string]$plan.decision
    selected_branch = [string]$plan.branch
    research_only = $true
    would_start = $false
    collect_allowed_now = $false
    grid_allowed_now = $false
    paper_forward_allowed = $false
    live_orders = $false
    api_keys = $false
    leverage_or_margin = $false
    plan_path = $OutputPath
    plan_sha256 = $planHash
    next_step = "Implement and test one fixed replay over existing 4h Gate spot history; do not inspect or tune parameter grids."
    gate_updated = [bool]$UpdateGate
}

if ($UpdateGate) {
    $gateDoc = Get-Content -Raw -LiteralPath $gatePath | ConvertFrom-Json
    Set-JsonProperty $gateDoc "updated_at" ((Get-Date).ToString("yyyy-MM-ddTHH:mm:sszzz"))
    Set-JsonProperty $gateDoc "status" "READY_FOR_POSTPROCESS"
    Set-JsonProperty $gateDoc "gate_status" "READY_FOR_POSTPROCESS"
    Set-JsonProperty $gateDoc "next_goal_decision" "CROSS_SECTIONAL_CAPITULATION_PLANONLY_READY_FOR_FIXED_REPLAY_IMPLEMENTATION"
    Set-JsonProperty $gateDoc "next_goal_reason" "Distinct slow 4h cross-sectional rebound hypothesis is sealed before replay; existing data only, fixed 120/245 bps cost gates, no grid."
    Set-JsonProperty $gateDoc "next_step_after_ready" $result.next_step
    Set-JsonProperty $gateDoc "raw_gate_next_step_after_ready" $result.next_step
    Set-JsonProperty $gateDoc "last_cross_sectional_capitulation_plan_path" $OutputPath
    Set-JsonProperty $gateDoc "last_cross_sectional_capitulation_plan_sha256" $planHash
    Set-JsonProperty $gateDoc "strategy_branch_status" ([ordered]@{
        branch = "cross_sectional_capitulation_rebound_4h_spot"
        verdict = "fixed_plan_sealed_ready_for_replay_implementation"
        strategy_accepted = $false
        replay_allowed_now = $true
        grid_allowed = $false
        collect_allowed = $false
        paper_forward_allowed = $false
    })
    Write-JsonAtomic $gateDoc $gatePath
}

if ($Json) { $result | ConvertTo-Json -Depth 20 } else { $result | Format-List }

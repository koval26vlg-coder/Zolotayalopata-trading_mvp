param(
    [string]$OutputPath = "E:\ZolotyayLopata-data\exports\trading-mvp\analysis\spot_pit_event_forward_planonly_20260712_2145.json",
    [switch]$UpdateGate,
    [switch]$Json
)

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$gatePath = Join-Path $repoRoot "docs\agent-log\active-run-gate.json"
$gateChecker = Join-Path $repoRoot "tools\check_active_run_gate.ps1"
$priorAuditPath = "E:\ZolotyayLopata-data\exports\trading-mvp\analysis\cross_sectional_capitulation_audit_20260712_2140.json"

function Write-JsonAtomic {
    param($Value, [string]$Path)
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $Path) | Out-Null
    $temp = "$Path.tmp.$PID"
    $Value | ConvertTo-Json -Depth 100 | Set-Content -LiteralPath $temp -Encoding UTF8
    Move-Item -LiteralPath $temp -Destination $Path -Force
}

function Set-JsonProperty {
    param($Object, [string]$Name, $Value)
    if ($Object.PSObject.Properties.Name -contains $Name) { $Object.$Name = $Value }
    else { $Object | Add-Member -NotePropertyName $Name -NotePropertyValue $Value }
}

if (-not (Test-Path -LiteralPath $priorAuditPath -PathType Leaf)) { throw "Prior closure audit missing: $priorAuditPath" }
$gate = & pwsh -NoProfile -ExecutionPolicy Bypass -File $gateChecker -Json | ConvertFrom-Json
if ([string]$gate.status -eq "RUNNING") { throw "Active run gate is RUNNING; forward PlanOnly is blocked." }

if (Test-Path -LiteralPath $OutputPath -PathType Leaf) {
    $plan = Get-Content -Raw -LiteralPath $OutputPath | ConvertFrom-Json
    if ([string]$plan.schema -ne "spot_pit_event_forward_plan_v1") { throw "Refusing to overwrite another artifact: $OutputPath" }
} else {
    $plan = [ordered]@{
        schema = "spot_pit_event_forward_plan_v1"
        generated_at = (Get-Date).ToString("yyyy-MM-ddTHH:mm:sszzz")
        decision = "SPOT_PIT_EVENT_FORWARD_PLANONLY_READY_FOR_PUBLIC_PREFLIGHT_IMPLEMENTATION"
        branch = "spot_pit_idiosyncratic_crash_reclaim_1m"
        research_only = $true
        would_start = $false
        strategy_accepted = $false
        manual_codex_control = $true
        swarm = "cancelled_by_user_do_not_restart"
        rationale = @(
            "Existing local fixed hypotheses are rejected, failed, or blocked; repeated threshold variants would be same-sample tuning.",
            "Future point-in-time spot data is independent of hypothesis design and preserves listings, delistings, missing data, and no-trade outcomes.",
            "One-minute public bulk snapshots target moves measured in hundreds of bps without collecting another multi-tens-of-GB HFT stream."
        )
        prior_closure = [ordered]@{
            audit_path = $priorAuditPath
            audit_sha256 = (Get-FileHash -LiteralPath $priorAuditPath -Algorithm SHA256).Hash.ToLowerInvariant()
            verdict = "existing_data_hypotheses_exhausted"
        }
        public_preflight = [ordered]@{
            required_before_collect = $true
            credentials = "none"
            mexc_endpoints = @(
                "/api/v3/exchangeInfo",
                "/api/v3/ticker/bookTicker",
                "/api/v3/ticker/24hr"
            )
            gate_endpoints = @(
                "/api/v4/spot/currency_pairs",
                "/api/v4/spot/tickers"
            )
            binance_role = "reference_only_for_spot_exclusion_never_execution"
            required_checks = @(
                "schema_and_numeric_field_probe",
                "both_venues_return_tradable_USDT_pairs",
                "bulk_ticker_latency_and_rate_limit_headroom",
                "bid_ask_and_24h_quote_volume_coverage",
                "fresh_non_binance_universe_can_be_frozen_before_cycle_1"
            )
        }
        universe = [ordered]@{
            construction_time = "before_cycle_1"
            source = "fresh ranked public universe minus Binance spot assets"
            max_initial_bases = 100
            require_spot_on = @("mexc", "gateio")
            cross_venue_priority = "both_venues"
            single_venue_rows = "retain_as_weaker_evidence_not_drop"
            new_listings_after_start = "append_with_first_seen_ts_never_backfill"
            inactive_delisted_missing = "retain_tombstones_and_no_data_rows"
            exclude_stable_wrapped_staked_derivative_assets = $true
        }
        collection = [ordered]@{
            duration_days = 14
            interval_sec = 60
            segment_sec = 21600
            output_root = "E:\ZolotyayLopata-data\exports\trading-mvp\spot-pit-event-forward"
            estimated_max_disk_gib = 10
            minimum_free_disk_gib_before_start = 20
            visible_terminal_required = $true
            durable_segments = $true
            append_only_cycle_journal = $true
            atomic_manifest = $true
            immutable_launch_record = $true
            resume_same_run_id = $true
            reconnect_backoff_sec = @("5", "15", "30", "60", "300")
            vpn_or_network_loss = "mark_failed_cycle_preserve_data_and_resume_same_run_id"
            no_hidden_background_run = $true
            status_every_cycles = 5
            alert_file_required = $true
        }
        row_schema = @(
            "run_id", "cycle", "snapshot_ts", "exchange", "symbol", "base", "quote",
            "status", "listed_now", "inactive_or_delisted", "first_seen_ts", "last_seen_ts",
            "missing_since_ts", "tombstone", "bid", "ask", "bid_qty", "ask_qty", "last",
            "spread_bps", "base_volume_24h", "quote_volume_24h", "source_endpoint",
            "binance_spot_listed_now", "eligible_non_binance_spot", "error"
        )
        fixed_signal = [ordered]@{
            name = "spot_pit_idiosyncratic_crash_reclaim_v1"
            direction = "long_only_spot"
            bar_interval_min = 1
            shock_lookback_min = 60
            base_return_max_bps = -500.0
            residual_vs_cross_sectional_median_max_bps = -300.0
            reclaim_from_rolling_low_min_bps = 100.0
            max_spread_bps = 30.0
            min_quote_volume_24h = 500000.0
            min_peer_count = 10
            entry = "next_1m_observation_ask"
            hold_min = 360
            exit = "first_fresh_bid_at_or_after_hold_with_5m_grace"
            cooldown_min = 1440
            max_concurrent_positions = 3
            no_grid = $true
        }
        economics = [ordered]@{
            account_assumption = "base_or_vip0_no_volume"
            normal_total_cost_bps = 120.0
            stress_total_cost_bps = 245.0
            notional_quote = 100.0
            optimize_for = "net_expectancy_after_costs"
            win_rate = "diagnostic_only"
        }
        early_gates = [ordered]@{
            schema_gate_after_min = 10
            coverage_gate_after_hours = 2
            futility_gate_after_hours = 48
            min_valid_cycle_ratio = 0.95
            min_bases_per_venue = 15
            min_two_venue_bases = 8
            min_fixed_signals_by_48h = 10
            min_signal_bases_by_48h = 5
            action_on_futility = "stop_cleanly_final_true_decision_futile_do_not_wait_14d"
        }
        validation = [ordered]@{
            min_total_trades = 100
            min_oos_trades = 30
            chronological_train_fraction = 0.70
            walk_forward_folds = 5
            min_positive_fold_ratio = 0.60
            min_oos_profit_factor = 1.20
            min_oos_expectancy_bps = 0.0
            min_stress_expectancy_bps = 0.0
            min_distinct_oos_bases = 8
            max_top_base_positive_contribution = 0.25
            max_drawdown_quote = 25.0
            independent_artifact_audit_required = $true
            paper_forward_only_after_all_gates = $true
        }
        blocked_actions = @(
            "actual_public_probe_before_implementation_tests",
            "actual_collect_without_separate_explicit_visible_confirmation",
            "grid_search",
            "live_orders",
            "api_keys",
            "leverage_or_margin",
            "paper_forward_before_pass"
        )
        next_step = "Implement mocked public preflight clients and tests, then run one short visible public preflight. Do not start the 14-day collector yet."
    }
    Write-JsonAtomic $plan $OutputPath
}

$planHash = (Get-FileHash -LiteralPath $OutputPath -Algorithm SHA256).Hash.ToLowerInvariant()
$result = [ordered]@{
    schema = "spot_pit_event_forward_planonly_result_v1"
    generated_at = (Get-Date).ToString("yyyy-MM-ddTHH:mm:sszzz")
    decision = [string]$plan.decision
    selected_branch = [string]$plan.branch
    research_only = $true
    would_start = $false
    actual_collect_allowed_now = $false
    explicit_visible_confirmation_required_for_collect = $true
    live_orders = $false
    api_keys = $false
    leverage_or_margin = $false
    grid_search = $false
    paper_forward_allowed = $false
    plan_path = $OutputPath
    plan_sha256 = $planHash
    next_step = [string]$plan.next_step
    gate_updated = [bool]$UpdateGate
}

if ($UpdateGate) {
    $gateDoc = Get-Content -Raw -LiteralPath $gatePath | ConvertFrom-Json
    Set-JsonProperty $gateDoc "updated_at" ((Get-Date).ToString("yyyy-MM-ddTHH:mm:sszzz"))
    Set-JsonProperty $gateDoc "status" "READY_FOR_POSTPROCESS"
    Set-JsonProperty $gateDoc "gate_status" "READY_FOR_POSTPROCESS"
    Set-JsonProperty $gateDoc "next_goal_decision" "SPOT_PIT_EVENT_FORWARD_PLANONLY_READY_FOR_PUBLIC_PREFLIGHT_IMPLEMENTATION"
    Set-JsonProperty $gateDoc "next_goal_reason" "Existing-data branches are verified closed; a compact independent forward spot plan is sealed before any future data."
    Set-JsonProperty $gateDoc "next_step_after_ready" $result.next_step
    Set-JsonProperty $gateDoc "raw_gate_next_step_after_ready" $result.next_step
    Set-JsonProperty $gateDoc "last_spot_pit_event_forward_plan_path" $OutputPath
    Set-JsonProperty $gateDoc "last_spot_pit_event_forward_plan_sha256" $planHash
    Set-JsonProperty $gateDoc "requires_explicit_user_approval_for_actual_collect" $true
    Set-JsonProperty $gateDoc "collect_allowed" $false
    Set-JsonProperty $gateDoc "replay_allowed" $false
    Set-JsonProperty $gateDoc "grid_allowed" $false
    Set-JsonProperty $gateDoc "paper_forward_allowed" $false
    Set-JsonProperty $gateDoc "strategy_branch_status" ([ordered]@{
        branch = "spot_pit_idiosyncratic_crash_reclaim_1m"
        verdict = "forward_plan_sealed_ready_for_public_preflight_implementation"
        strategy_accepted = $false
        collect_allowed_now = $false
        grid_allowed = $false
        paper_forward_allowed = $false
    })
    Write-JsonAtomic $gateDoc $gatePath
}

if ($Json) { $result | ConvertTo-Json -Depth 20 } else { $result | Format-List }

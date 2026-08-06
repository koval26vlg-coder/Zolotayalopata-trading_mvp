param(
    [string]$ThresholdsPath = "",
    [string]$FeeTierEvidencePath = "",
    [switch]$Json
)

$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
if (-not $ThresholdsPath) {
    $ThresholdsPath = Join-Path $repoRoot "exports\trading-mvp\analysis\funding_economic_thresholds_20260617.csv"
}
if (-not $FeeTierEvidencePath) {
    $FeeTierEvidencePath = Join-Path $repoRoot "exports\trading-mvp\analysis\funding_account_fee_tiers_current.json"
}

function To-Double {
    param($Value, [double]$Default = 0.0)
    if ($null -eq $Value) {
        return $Default
    }
    $text = [string]$Value
    if ([string]::IsNullOrWhiteSpace($text)) {
        return $Default
    }
    $parsed = 0.0
    if ([double]::TryParse($text, [System.Globalization.NumberStyles]::Float, [System.Globalization.CultureInfo]::InvariantCulture, [ref]$parsed)) {
        return $parsed
    }
    return $Default
}

function To-Bool {
    param($Value)
    if ($Value -is [bool]) {
        return $Value
    }
    return ([string]$Value).ToLowerInvariant() -eq "true"
}

if (-not (Test-Path -LiteralPath $ThresholdsPath)) {
    throw "Thresholds artifact not found: $ThresholdsPath"
}

$thresholdRows = @(Import-Csv -LiteralPath $ThresholdsPath)
$feeEvidence = $null
$feeEvidencePresent = Test-Path -LiteralPath $FeeTierEvidencePath
$feeEvidenceAccepted = $false
$feeEvidenceReasons = [System.Collections.Generic.List[string]]::new()

if ($feeEvidencePresent) {
    try {
        $feeEvidence = Get-Content -Raw -LiteralPath $FeeTierEvidencePath | ConvertFrom-Json
        if ($feeEvidence.mode -ne "funding_account_fee_tiers") {
            $feeEvidenceReasons.Add("mode_not_funding_account_fee_tiers") | Out-Null
        }
        if (-not (To-Bool $feeEvidence.accepted)) {
            $feeEvidenceReasons.Add("accepted_not_true") | Out-Null
        }
        if (-not $feeEvidence.exchanges) {
            $feeEvidenceReasons.Add("exchanges_missing") | Out-Null
        }
        foreach ($exchangeName in @("mexc", "gateio")) {
            $exchange = $feeEvidence.exchanges.$exchangeName
            if (-not $exchange) {
                $feeEvidenceReasons.Add("${exchangeName}_missing") | Out-Null
                continue
            }
            foreach ($field in @("spot_maker_fee_bps", "spot_taker_fee_bps", "perp_maker_fee_bps", "perp_taker_fee_bps")) {
                if ($null -eq $exchange.$field) {
                    $feeEvidenceReasons.Add("${exchangeName}_${field}_missing") | Out-Null
                }
            }
        }
        if ($feeEvidenceReasons.Count -eq 0) {
            $feeEvidenceAccepted = $true
        }
    } catch {
        $feeEvidenceReasons.Add("fee_evidence_parse_failed: $($_.Exception.Message)") | Out-Null
    }
} else {
    $feeEvidenceReasons.Add("fee_tier_evidence_missing") | Out-Null
}

$scenarioGroups = $thresholdRows | Group-Object scenario
$scenarioDecisions = @(
    foreach ($group in $scenarioGroups) {
        $scenario = [string]$group.Name
        $rows = @($group.Group)
        $first = $rows | Select-Object -First 1
        $status = "hypothesis_only"
        $reason = "Lower-cost scenario lacks accepted account fee-tier evidence."
        $allowedForAcceptance = $false

        if ($scenario -eq "current_taker_like") {
            $status = "operational_conservative"
            $reason = "Uses current postprocess cost model; allowed for research acceptance."
            $allowedForAcceptance = $true
        } elseif ($scenario -eq "zero_cost_theoretical") {
            $status = "blocked_theoretical"
            $reason = "Zero-cost scenario is a lower bound only; never allowed as acceptance evidence."
            $allowedForAcceptance = $false
        } elseif ($feeEvidenceAccepted) {
            $status = "requires_mapping_review"
            $reason = "Accepted fee-tier evidence exists, but this sensitivity scenario still needs explicit mapping to exchange/account/order-type assumptions."
            $allowedForAcceptance = $false
        }

        [pscustomobject][ordered]@{
            scenario = $scenario
            status = $status
            allowed_for_acceptance = $allowedForAcceptance
            reason = $reason
            spot_fee_bps = To-Double $first.spot_fee_bps
            perp_fee_bps = To-Double $first.perp_fee_bps
            slippage_bps = To-Double $first.slippage_bps
            round_trip_cost_bps = To-Double $first.round_trip_cost_bps
            best_required_funding_bps_per_interval = (
                $rows |
                    ForEach-Object { To-Double $_.required_funding_bps_per_interval_for_zero_net } |
                    Measure-Object -Minimum
            ).Minimum
            p95_clears_any = [bool](@($rows | Where-Object { To-Bool $_.p95_clears_required }).Count -gt 0)
            p99_clears_any = [bool](@($rows | Where-Object { To-Bool $_.p99_clears_required }).Count -gt 0)
            max_clears_any = [bool](@($rows | Where-Object { To-Bool $_.max_clears_required }).Count -gt 0)
        }
    }
)

$acceptanceScenarios = @($scenarioDecisions | Where-Object { $_.allowed_for_acceptance } | ForEach-Object { $_.scenario })
$sensitivityOnlyScenarios = @($scenarioDecisions | Where-Object { -not $_.allowed_for_acceptance -and $_.status -ne "blocked_theoretical" } | ForEach-Object { $_.scenario })
$blockedScenarios = @($scenarioDecisions | Where-Object { $_.status -eq "blocked_theoretical" } | ForEach-Object { $_.scenario })

$decision = if ($feeEvidenceAccepted) {
    "ACCOUNT_FEE_EVIDENCE_PRESENT_REVIEW_REQUIRED"
} else {
    "USE_CURRENT_COST_ONLY_FOR_ACCEPTANCE"
}

$result = [ordered]@{
    generated_at = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss zzz")
    mode = "funding_cost_assumption_gate"
    decision = $decision
    fee_tier_evidence_path = $FeeTierEvidencePath
    fee_tier_evidence_present = $feeEvidencePresent
    fee_tier_evidence_accepted = $feeEvidenceAccepted
    fee_tier_evidence_reasons = @($feeEvidenceReasons)
    acceptance_scenarios = $acceptanceScenarios
    sensitivity_only_scenarios = $sensitivityOnlyScenarios
    blocked_scenarios = $blockedScenarios
    scenario_decisions = $scenarioDecisions
    rules = @(
        "Only scenarios with allowed_for_acceptance=true may support strategy acceptance.",
        "Lower-cost maker/VIP scenarios require accepted non-secret account fee-tier evidence and explicit mapping review.",
        "Zero-cost theoretical scenarios are never acceptance evidence.",
        "Do not use lower fees to manufacture high winrate or positive edge."
    )
    next_valid_moves = @(
        "Keep current_taker_like as the acceptance cost model until fee-tier evidence exists.",
        "Use reduced_fee and maker/VIP rows only as sensitivity diagnostics.",
        "If the user later provides actual account maker/taker fee tiers, store a non-secret funding_account_fee_tiers_current.json and re-run this gate.",
        "Live, API keys and leverage remain blocked."
    )
    inputs = [ordered]@{
        thresholds = $ThresholdsPath
        fee_tier_evidence = $FeeTierEvidencePath
    }
}

if ($Json) {
    $result | ConvertTo-Json -Depth 8
    exit 0
}

Write-Host "Funding Cost Assumption Gate" -ForegroundColor Cyan
Write-Host "Generated: $($result.generated_at)"
Write-Host "Decision: $decision"
Write-Host "Fee-tier evidence present: $feeEvidencePresent"
Write-Host "Fee-tier evidence accepted: $feeEvidenceAccepted"
Write-Host ""

Write-Host "Acceptance scenarios" -ForegroundColor Yellow
foreach ($scenario in $acceptanceScenarios) {
    Write-Host "  - $scenario"
}
Write-Host ""

Write-Host "Sensitivity-only scenarios" -ForegroundColor Yellow
foreach ($scenario in $sensitivityOnlyScenarios) {
    Write-Host "  - $scenario"
}
Write-Host ""

Write-Host "Blocked scenarios" -ForegroundColor Yellow
foreach ($scenario in $blockedScenarios) {
    Write-Host "  - $scenario"
}
Write-Host ""

Write-Host "Fee evidence reasons" -ForegroundColor Yellow
foreach ($reason in $feeEvidenceReasons) {
    Write-Host "  - $reason"
}
Write-Host ""

Write-Host "Scenario decisions" -ForegroundColor Yellow
foreach ($scenario in $scenarioDecisions) {
    Write-Host ("  - {0}: {1}; acceptance={2}; cost={3} bps; reason={4}" -f $scenario.scenario, $scenario.status, $scenario.allowed_for_acceptance, $scenario.round_trip_cost_bps, $scenario.reason)
}
Write-Host ""

Write-Host "Next valid moves" -ForegroundColor Yellow
foreach ($move in $result.next_valid_moves) {
    Write-Host "  - $move"
}

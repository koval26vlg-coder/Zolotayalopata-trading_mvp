function Get-SlowLiquidityExactRecollectStatus {
    param(
        [Parameter(Mandatory = $true)]$Gate,
        [Parameter(Mandatory = $true)][string]$PlanPath,
        [Parameter(Mandatory = $true)][string]$ReadinessPath,
        [Parameter(Mandatory = $true)][string]$DefaultLauncherPath,
        [string]$RawGatePath = ""
    )

    function Get-ExactSha256 {
        param([Parameter(Mandatory = $true)][string]$Path)
        return (Get-FileHash -Algorithm SHA256 -LiteralPath $Path).Hash.ToLowerInvariant()
    }

    function Test-ExactPath {
        param($Actual, $Expected)
        try {
            if (
                [string]::IsNullOrWhiteSpace([string]$Actual) -or
                [string]::IsNullOrWhiteSpace([string]$Expected)
            ) {
                return $false
            }
            return [string]::Equals(
                [System.IO.Path]::GetFullPath([string]$Actual),
                [System.IO.Path]::GetFullPath([string]$Expected),
                [System.StringComparison]::OrdinalIgnoreCase
            )
        } catch {
            return $false
        }
    }

    function Test-ExactSequence {
        param($Actual, $Expected)
        $actualItems = @($Actual)
        $expectedItems = @($Expected)
        if ($actualItems.Count -ne $expectedItems.Count) {
            return $false
        }
        for ($index = 0; $index -lt $expectedItems.Count; $index++) {
            if ([string]$actualItems[$index] -cne [string]$expectedItems[$index]) {
                return $false
            }
        }
        return $true
    }

    function Test-StandingResearchAuthorization {
        param(
            $Policy,
            $Plan
        )

        $authorization = if ($null -ne $Policy) {
            $Policy.standing_research_authorization
        } else {
            $null
        }
        $scope = if ($null -ne $authorization) {
            $authorization.scope_binding
        } else {
            $null
        }
        if ($null -eq $authorization -or $null -eq $scope) {
            return $false
        }
        if ([string]$authorization.schema -ne
            "trading_mvp_standing_same_scope_public_research_authorization_v1" -or
            -not [bool]$authorization.enabled -or
            -not [bool]$authorization.same_scope_auto_continue) {
            return $false
        }

        $authorizedActions = @($authorization.authorized_actions | ForEach-Object { [string]$_ })
        foreach ($requiredAction in @(
            "technical_quality",
            "public_identity_discovery",
            "public_request_plan_discovery",
            "public_topology_discovery",
            "synthetic_tests",
            "immutable_manifest_refreeze",
            "preflight_only"
        )) {
            if ($authorizedActions -notcontains $requiredAction) {
                return $false
            }
        }

        $requiredGuards = @(
            "fresh_authoritative_guard",
            "active_run_gate_must_be_ready_for_postprocess",
            "single_global_market_data_writer",
            "visible_terminal_for_network_writers",
            "exact_hash_and_schema_binding",
            "public_read_only_only",
            "no_redirects_proxies_or_retries",
            "no_private_api_or_real_capital"
        )
        $technicalGuards = @($authorization.technical_guards | ForEach-Object { [string]$_ })
        foreach ($requiredGuard in $requiredGuards) {
            if ($technicalGuards -notcontains $requiredGuard) {
                return $false
            }
        }

        $requiredCheckpoints = @(
            "hypothesis_change",
            "venue_change",
            "universe_change",
            "signal_cost_risk_or_acceptance_contract_change",
            "stopped_incomplete_resume",
            "integrity_conflict",
            "evaluator_oos_returns_pnl_grid_retune",
            "paper_live_private_api_real_capital_leverage_margin_or_withdrawal"
        )
        $checkpoints = @($authorization.user_checkpoint_required_for | ForEach-Object { [string]$_ })
        foreach ($requiredCheckpoint in $requiredCheckpoints) {
            if ($checkpoints -notcontains $requiredCheckpoint) {
                return $false
            }
        }

        if ([string]$scope.strategy_branch -cne [string]$Plan.strategy_branch) {
            return $false
        }
        if (-not (Test-ExactSequence $scope.exchanges $Plan.execution.exchanges)) {
            return $false
        }
        if (-not (Test-ExactSequence $scope.bases $Plan.universe.bases)) {
            return $false
        }
        if (-not (Test-ExactSequence $scope.timeframes $Plan.execution.timeframes)) {
            return $false
        }
        try {
            if ([int]$scope.history_days -ne [int]$Plan.execution.history_days) {
                return $false
            }
        } catch {
            return $false
        }
        return $true
    }

    function Expand-ExactCommand {
        param(
            $Template,
            [Parameter(Mandatory = $true)][string]$PlanHash,
            [Parameter(Mandatory = $true)][string]$PlanFileSha256,
            [string]$ReceiptSha256 = ""
        )
        $command = [string]$Template
        if ([string]::IsNullOrWhiteSpace($command)) {
            return $null
        }
        if ($command.Contains("<RECEIPT_SHA256>") -and [string]::IsNullOrWhiteSpace($ReceiptSha256)) {
            return $null
        }
        return $command.Replace("<PLAN_HASH>", $PlanHash).
            Replace("<PLAN_FILE_SHA256>", $PlanFileSha256).
            Replace("<RECEIPT_SHA256>", $ReceiptSha256)
    }

    $preapprovalDecision = "SLOW_LIQUIDITY_HISTORY_DATA_QUALITY_REJECTED_NEEDS_RECOLLECT_OR_RESCOPE"
    $approvedDecision = "SLOW_LIQUIDITY_HISTORY_RECOLLECT_EXACT_APPROVED_PAGECAP_PROVENANCE_SLOTINTEGRITY_V6"
    $runningDecision = "SLOW_LIQUIDITY_HISTORY_RECOLLECT_RUNNING"
    $readyForQualityDecision = "SLOW_LIQUIDITY_HISTORY_RECOLLECT_COMPLETED_READY_FOR_DATA_QUALITY"
    $stoppedDecision = "SLOW_LIQUIDITY_HISTORY_RECOLLECT_STOPPED_INCOMPLETE_NO_RETRY"
    $qualityAcceptedDecision = "SLOW_LIQUIDITY_HISTORY_RECOLLECT_QUALITY_ACCEPTED_AWAIT_OFFICIAL_IDENTITY_APPROVAL"
    $qualityRejectedDecision = "TERMINAL_DATA_QUALITY_REJECT_NO_RETRY_WITHOUT_NEW_EXACT_APPROVAL"
    $qualityAcceptedStandingDecision = "QUALITY_ACCEPTED_CONTINUE_STANDING_PUBLIC_RESEARCH"

    $result = [ordered]@{
        checkpoint_relevant = $false
        phase = "IRRELEVANT"
        observed_phase = "IRRELEVANT"
        awaiting_approval = $false
        approved_awaiting_launch = $false
        visible_launch_starting = $false
        running = $false
        ready_for_quality = $false
        technical_quality_committing = $false
        stopped_incomplete_no_retry = $false
        quality_accepted_awaiting_identity_approval = $false
        standing_research_continue_allowed = $false
        standing_research_authorized = $false
        standing_research_scope_binding_valid = $false
        standing_research_policy_file_sha256 = $null
        quality_rejected_terminal_no_retry = $false
        integrity_blocked = $false
        plan_valid = $false
        plan_path = $PlanPath
        plan_file_sha256 = $null
        plan_hash = $null
        run_id = $null
        receipt_path = $null
        receipt_present = $false
        receipt_sha256 = $null
        receipt_valid = $false
        launch_record_path = $null
        launch_record_present = $false
        launch_record_valid = $false
        output_path = $null
        output_present = $false
        manifest_path = $null
        manifest_present = $false
        quality_output_path = $null
        quality_output_present = $false
        quality_output_valid = $false
        readiness_path = $ReadinessPath
        readiness_present = $false
        raw_gate_path = $RawGatePath
        raw_gate_present = $false
        policy_path = $null
        policy_present = $false
        launcher_path = $DefaultLauncherPath
        preflight_command = $null
        approval_packet_command = $null
        approval_packet_command_valid = $false
        launch_command = $null
        status_command = $null
        stop_command = $null
        quality_preflight_command = $null
        quality_command = $null
        primary_command = $null
        requires_user_approval = $false
        required_user_input = ""
        next_action = $null
        errors = @()
    }

    $gateDecision = [string]$Gate.next_goal_decision
    $knownDecisions = @(
        $preapprovalDecision,
        $approvedDecision,
        $runningDecision,
        $readyForQualityDecision,
        $stoppedDecision,
        $qualityAcceptedDecision,
        $qualityAcceptedStandingDecision,
        $qualityRejectedDecision
    )
    if ($gateDecision -notin $knownDecisions) {
        return [pscustomobject]$result
    }
    $result.checkpoint_relevant = $true

    $observedPhase = switch ($gateDecision) {
        $preapprovalDecision { "AWAITING_EXACT_APPROVAL"; break }
        $approvedDecision { "APPROVED_AWAITING_VISIBLE_LAUNCH"; break }
        $runningDecision { "RUNNING"; break }
        $readyForQualityDecision { "READY_FOR_TECHNICAL_QUALITY"; break }
        $stoppedDecision { "STOPPED_INCOMPLETE_NO_RETRY"; break }
        $qualityAcceptedDecision { "QUALITY_ACCEPTED_AWAIT_OFFICIAL_IDENTITY_APPROVAL"; break }
        $qualityAcceptedStandingDecision { "QUALITY_ACCEPTED_CONTINUE_STANDING_PUBLIC_RESEARCH"; break }
        $qualityRejectedDecision { "QUALITY_REJECTED_TERMINAL_NO_RETRY"; break }
        default { "IRRELEVANT" }
    }
    $result.observed_phase = $observedPhase

    try {
        if (-not (Test-Path -LiteralPath $PlanPath -PathType Leaf)) {
            throw "exact recollect PlanOnly is missing"
        }
        if (-not (Test-Path -LiteralPath $ReadinessPath -PathType Leaf)) {
            throw "sprint readiness binding is missing"
        }

        $plan = Get-Content -Raw -LiteralPath $PlanPath | ConvertFrom-Json -DateKind String
        $readiness = Get-Content -Raw -LiteralPath $ReadinessPath | ConvertFrom-Json -DateKind String
        $result.readiness_present = $true
        $candidate = $readiness.slow_liquidity_candidate
        if ($null -eq $candidate) {
            throw "readiness slow_liquidity_candidate binding is missing"
        }

        $normalizedPlanPath = [System.IO.Path]::GetFullPath($PlanPath)
        $planFileSha256 = Get-ExactSha256 $PlanPath
        $planHash = ([string]$plan.plan_hash).ToLowerInvariant()
        $runId = [string]$plan.execution.run_id
        $result.plan_path = $normalizedPlanPath
        $result.plan_file_sha256 = $planFileSha256
        $result.plan_hash = $planHash
        $result.run_id = $runId
        $result.receipt_path = [string]$plan.approval_receipt.path
        $result.launch_record_path = [string]$plan.execution.launch_record_path
        $result.output_path = [string]$plan.execution.output_path
        $result.manifest_path = [string]$plan.execution.manifest_path
        $result.quality_output_path = [string]$plan.data_quality_after_success.output_path
        $result.policy_path = [string]$plan.guard_contract.active_policy_path
        if (-not [string]::IsNullOrWhiteSpace([string]$plan.launcher.path)) {
            $result.launcher_path = [string]$plan.launcher.path
        }

        $result.receipt_present = [bool](
            -not [string]::IsNullOrWhiteSpace([string]$result.receipt_path) -and
            (Test-Path -LiteralPath ([string]$result.receipt_path) -PathType Leaf)
        )
        $result.launch_record_present = [bool](
            -not [string]::IsNullOrWhiteSpace([string]$result.launch_record_path) -and
            (Test-Path -LiteralPath ([string]$result.launch_record_path) -PathType Leaf)
        )
        $result.output_present = [bool](
            -not [string]::IsNullOrWhiteSpace([string]$result.output_path) -and
            (Test-Path -LiteralPath ([string]$result.output_path))
        )
        $result.manifest_present = [bool](
            -not [string]::IsNullOrWhiteSpace([string]$result.manifest_path) -and
            (Test-Path -LiteralPath ([string]$result.manifest_path) -PathType Leaf)
        )
        $result.quality_output_present = [bool](
            -not [string]::IsNullOrWhiteSpace([string]$result.quality_output_path) -and
            (Test-Path -LiteralPath ([string]$result.quality_output_path) -PathType Leaf)
        )
        $result.raw_gate_present = [bool](
            -not [string]::IsNullOrWhiteSpace($RawGatePath) -and
            (Test-Path -LiteralPath $RawGatePath -PathType Leaf)
        )
        $result.policy_present = [bool](
            -not [string]::IsNullOrWhiteSpace([string]$result.policy_path) -and
            (Test-Path -LiteralPath ([string]$result.policy_path) -PathType Leaf)
        )
        $policy = $null
        if ($result.policy_present) {
            try {
                $policy = Get-Content -Raw -LiteralPath ([string]$result.policy_path) |
                    ConvertFrom-Json -DateKind String
                $result.standing_research_policy_file_sha256 = Get-ExactSha256 ([string]$result.policy_path)
            } catch {
                $policy = $null
            }
        }
        $result.standing_research_scope_binding_valid = [bool](
            $policy -and (Test-StandingResearchAuthorization -Policy $policy -Plan $plan)
        )
        $result.standing_research_authorized = [bool](
            $result.standing_research_scope_binding_valid -and
            [string]$Gate.status -eq "READY_FOR_POSTPROCESS"
        )

        if ($observedPhase -eq "APPROVED_AWAITING_VISIBLE_LAUNCH" -and $result.launch_record_present) {
            $observedPhase = "VISIBLE_LAUNCH_STARTING"
            $result.observed_phase = $observedPhase
        }
        if ($observedPhase -eq "READY_FOR_TECHNICAL_QUALITY" -and $result.quality_output_present) {
            $observedPhase = "TECHNICAL_QUALITY_COMMITTING"
            $result.observed_phase = $observedPhase
        }

        $validationErrors = [System.Collections.Generic.List[string]]::new()
        if ([string]$readiness.schema -ne "trading_mvp_one_week_historical_edge_sprint_readiness_v1") {
            $validationErrors.Add("unexpected readiness schema")
        }
        if ([string]$readiness.status -ne "AWAIT_EXACT_SLOW_LIQUIDITY_RECOLLECT_APPROVAL") {
            $validationErrors.Add("readiness exact recollect checkpoint mismatch")
        }
        if (-not (Test-ExactPath $candidate.exact_plan_path $normalizedPlanPath)) {
            $validationErrors.Add("readiness plan path mismatch")
        }
        if (([string]$candidate.exact_plan_file_sha256).ToLowerInvariant() -ne $planFileSha256) {
            $validationErrors.Add("readiness plan file SHA256 mismatch")
        }
        if (([string]$candidate.exact_plan_hash).ToLowerInvariant() -ne $planHash) {
            $validationErrors.Add("readiness plan hash mismatch")
        }
        if ([string]$plan.schema -ne "trading_mvp_slow_liquidity_history_recollect_planonly_v1") {
            $validationErrors.Add("unexpected PlanOnly schema")
        }
        if ([string]$plan.mode -ne "PlanOnly") {
            $validationErrors.Add("exact recollect mode is not PlanOnly")
        }
        if ([string]$plan.status -ne "AWAIT_EXACT_HASH_BOUND_APPROVAL") {
            $validationErrors.Add("immutable PlanOnly status mismatch")
        }
        if ([bool]$plan.actual_collection_allowed) {
            $validationErrors.Add("immutable PlanOnly unexpectedly allows collection")
        }
        if ($planHash -notmatch "^[0-9a-f]{64}$") {
            $validationErrors.Add("PlanOnly hash is invalid")
        }
        if ([string]::IsNullOrWhiteSpace($runId)) {
            $validationErrors.Add("PlanOnly run_id is missing")
        }
        if (
            [string]::IsNullOrWhiteSpace([string]$result.launcher_path) -or
            -not (Test-Path -LiteralPath ([string]$result.launcher_path) -PathType Leaf)
        ) {
            $validationErrors.Add("exact visible launcher is missing")
        } elseif (
            -not [string]::IsNullOrWhiteSpace([string]$plan.launcher.sha256) -and
            (Get-ExactSha256 ([string]$result.launcher_path)) -ne
                ([string]$plan.launcher.sha256).ToLowerInvariant()
        ) {
            $validationErrors.Add("exact visible launcher SHA256 mismatch")
        }

        $commands = $plan.commands
        $approvalPacketCommandErrorCount = $validationErrors.Count
        $result.approval_packet_command = Expand-ExactCommand `
            $commands.approval_freeze_preflight `
            $planHash `
            $planFileSha256
        $approvalPacketCommand = [string]$result.approval_packet_command
        if ([string]::IsNullOrWhiteSpace($approvalPacketCommand)) {
            $validationErrors.Add("exact approval packet command is missing")
        } else {
            if ($approvalPacketCommand -notmatch '(?i)freeze_exact_approved_slow_liquidity_history_recollect\.ps1') {
                $validationErrors.Add("exact approval packet command uses an unexpected script")
            }
            if ($approvalPacketCommand -notmatch '(?i)(^|\s)-PreflightOnly(\s|$)') {
                $validationErrors.Add("exact approval packet command is not PreflightOnly")
            }
            if ($approvalPacketCommand -notmatch '(?i)(^|\s)-Json(\s|$)') {
                $validationErrors.Add("exact approval packet command does not request JSON")
            }
            if ($approvalPacketCommand -match '(?i)(^|\s)-Apply(\s|$)') {
                $validationErrors.Add("exact approval packet command would apply approval")
            }
            if ($approvalPacketCommand.Contains("<")) {
                $validationErrors.Add("exact approval packet command contains unresolved placeholders")
            }
            if (-not $approvalPacketCommand.Contains($planHash)) {
                $validationErrors.Add("exact approval packet command plan hash mismatch")
            }
            if (-not $approvalPacketCommand.Contains($planFileSha256)) {
                $validationErrors.Add("exact approval packet command plan file SHA256 mismatch")
            }
        }
        $result.approval_packet_command_valid = (
            $validationErrors.Count -eq $approvalPacketCommandErrorCount
        )
        if (-not $result.approval_packet_command_valid) {
            $result.approval_packet_command = $null
        }

        $expectedGateStatus = switch ($observedPhase) {
            "RUNNING" { "RUNNING"; break }
            "STOPPED_INCOMPLETE_NO_RETRY" { "STOPPED_INCOMPLETE"; break }
            default { "READY_FOR_POSTPROCESS" }
        }
        if ([string]$Gate.status -ne $expectedGateStatus) {
            $validationErrors.Add("gate status does not match exact recollect phase")
        }
        if (
            $observedPhase -notin @(
                "AWAITING_EXACT_APPROVAL",
                "APPROVED_AWAITING_VISIBLE_LAUNCH",
                "VISIBLE_LAUNCH_STARTING"
            ) -and
            [string]$Gate.run_id -ne $runId
        ) {
            $validationErrors.Add("gate run_id mismatch")
        }

        $postApprovalPhase = $observedPhase -ne "AWAITING_EXACT_APPROVAL"
        $receipt = $null
        if ($postApprovalPhase) {
            if (-not $result.receipt_present) {
                $validationErrors.Add("exact approval receipt is missing")
            } else {
                $receipt = Get-Content -Raw -LiteralPath ([string]$result.receipt_path) |
                    ConvertFrom-Json -DateKind String
                $result.receipt_sha256 = Get-ExactSha256 ([string]$result.receipt_path)
                if ([string]$receipt.schema -ne "trading_mvp_slow_liquidity_history_recollect_approval_v1") {
                    $validationErrors.Add("approval receipt schema mismatch")
                }
                if ([string]$receipt.status -ne "APPROVED") {
                    $validationErrors.Add("approval receipt status mismatch")
                }
                if ([string]$receipt.approval_type -ne "EXACT_HASH_BOUND_VISIBLE_PUBLIC_RECOLLECT") {
                    $validationErrors.Add("approval receipt type mismatch")
                }
                if (-not (Test-ExactPath $receipt.plan_path $normalizedPlanPath)) {
                    $validationErrors.Add("approval receipt plan path mismatch")
                }
                if (([string]$receipt.plan_file_sha256).ToLowerInvariant() -ne $planFileSha256) {
                    $validationErrors.Add("approval receipt plan file SHA256 mismatch")
                }
                if (([string]$receipt.plan_hash).ToLowerInvariant() -ne $planHash) {
                    $validationErrors.Add("approval receipt plan hash mismatch")
                }
                if ([string]$receipt.run_id -ne $runId) {
                    $validationErrors.Add("approval receipt run_id mismatch")
                }
                if (-not (Test-ExactSequence $receipt.bases $plan.universe.bases)) {
                    $validationErrors.Add("approval receipt bases mismatch")
                }
                if (-not (Test-ExactSequence $receipt.exchanges $plan.execution.exchanges)) {
                    $validationErrors.Add("approval receipt exchanges mismatch")
                }
                if (-not (Test-ExactSequence $receipt.timeframes $plan.execution.timeframes)) {
                    $validationErrors.Add("approval receipt timeframes mismatch")
                }
                foreach ($field in @(
                    "history_days",
                    "max_runtime_sec",
                    "hard_output_cap_bytes",
                    "maximum_http_attempts"
                )) {
                    if ($receipt.$field -ne $plan.execution.$field) {
                        $validationErrors.Add("approval receipt $field mismatch")
                    }
                }
                if ([string]$receipt.policy_rebind_status -ne [string]$plan.guard_contract.required_policy_rebind_status) {
                    $validationErrors.Add("approval receipt policy rebind mismatch")
                }
                if ([string]$receipt.required_guard_decision -ne [string]$plan.guard_contract.required_decision_after_approval) {
                    $validationErrors.Add("approval receipt guard decision mismatch")
                }
                if ($receipt.single_use -isnot [bool] -or -not [bool]$receipt.single_use) {
                    $validationErrors.Add("approval receipt is not single use")
                }
                if (
                    $receipt.stop_incomplete_retry_authorized -isnot [bool] -or
                    [bool]$receipt.stop_incomplete_retry_authorized
                ) {
                    $validationErrors.Add("approval receipt authorizes STOPPED_INCOMPLETE retry")
                }
                foreach ($field in @(
                    "official_identity_verification_authorized",
                    "evaluator_or_oos_authorized",
                    "paper_or_live_authorized",
                    "private_api_or_real_capital_authorized"
                )) {
                    if ($receipt.$field -isnot [bool] -or [bool]$receipt.$field) {
                        $validationErrors.Add("approval receipt opens forbidden action: $field")
                    }
                }
                if ([string]$receipt.receipt_hash -notmatch "^[0-9a-f]{64}$") {
                    $validationErrors.Add("approval receipt canonical hash is invalid")
                }
                $result.receipt_valid = $validationErrors.Count -eq 0
            }

            if (-not $result.raw_gate_present) {
                $validationErrors.Add("raw active gate is missing for postapproval lifecycle")
            } else {
                $rawGate = Get-Content -Raw -LiteralPath $RawGatePath | ConvertFrom-Json -DateKind String
                if (
                    $Gate.PSObject.Properties.Name -contains "gate_read_sha256" -and
                    -not [string]::IsNullOrWhiteSpace([string]$Gate.gate_read_sha256) -and
                    (Get-ExactSha256 $RawGatePath) -ne ([string]$Gate.gate_read_sha256).ToLowerInvariant()
                ) {
                    $validationErrors.Add("raw active gate changed after guarded read")
                }
                if ([string]$rawGate.status -ne $expectedGateStatus) {
                    $validationErrors.Add("raw active gate status mismatch")
                }
                if ([string]$rawGate.next_goal_decision -ne $gateDecision) {
                    $validationErrors.Add("raw active gate decision mismatch")
                }
                if ([string]$rawGate.slow_liquidity_recollect_policy_rebind_status -ne [string]$plan.guard_contract.required_policy_rebind_status) {
                    $validationErrors.Add("raw active gate policy rebind mismatch")
                }
                if (-not (Test-ExactPath $rawGate.slow_liquidity_recollect_plan_path $normalizedPlanPath)) {
                    $validationErrors.Add("raw active gate plan path mismatch")
                }
                if (([string]$rawGate.slow_liquidity_recollect_plan_file_sha256).ToLowerInvariant() -ne $planFileSha256) {
                    $validationErrors.Add("raw active gate plan file SHA256 mismatch")
                }
                if (([string]$rawGate.slow_liquidity_recollect_plan_hash).ToLowerInvariant() -ne $planHash) {
                    $validationErrors.Add("raw active gate plan hash mismatch")
                }
                if ($receipt) {
                    if (-not (Test-ExactPath $rawGate.slow_liquidity_recollect_approval_receipt_path $result.receipt_path)) {
                        $validationErrors.Add("raw active gate approval receipt path mismatch")
                    }
                    if (([string]$rawGate.slow_liquidity_recollect_approval_receipt_sha256).ToLowerInvariant() -ne [string]$result.receipt_sha256) {
                        $validationErrors.Add("raw active gate approval receipt SHA256 mismatch")
                    }
                    if ([string]$rawGate.slow_liquidity_recollect_approval_receipt_hash -ne [string]$receipt.receipt_hash) {
                        $validationErrors.Add("raw active gate approval receipt hash mismatch")
                    }
                }
            }

            if (-not $result.policy_present) {
                $validationErrors.Add("active policy rebind is missing")
            } else {
                $policy = Get-Content -Raw -LiteralPath ([string]$result.policy_path) |
                    ConvertFrom-Json -DateKind String
                $rebind = $policy.slow_liquidity_history_recollect
                if ($null -eq $rebind) {
                    $validationErrors.Add("active policy exact recollect rebind is missing")
                } else {
                    if ([string]$rebind.schema -ne [string]$plan.guard_contract.required_policy_rebind_schema) {
                        $validationErrors.Add("active policy rebind schema mismatch")
                    }
                    if ([string]$rebind.status -ne [string]$plan.guard_contract.required_policy_rebind_status) {
                        $validationErrors.Add("active policy rebind status mismatch")
                    }
                    if ([string]$rebind.run_id -ne $runId) {
                        $validationErrors.Add("active policy rebind run_id mismatch")
                    }
                    if (-not (Test-ExactPath $rebind.plan_path $normalizedPlanPath)) {
                        $validationErrors.Add("active policy rebind plan path mismatch")
                    }
                    if (([string]$rebind.plan_file_sha256).ToLowerInvariant() -ne $planFileSha256) {
                        $validationErrors.Add("active policy rebind plan file SHA256 mismatch")
                    }
                    if (([string]$rebind.plan_hash).ToLowerInvariant() -ne $planHash) {
                        $validationErrors.Add("active policy rebind plan hash mismatch")
                    }
                    if ($receipt) {
                        if (-not (Test-ExactPath $rebind.approval_receipt_path $result.receipt_path)) {
                            $validationErrors.Add("active policy rebind receipt path mismatch")
                        }
                        if (([string]$rebind.approval_receipt_file_sha256).ToLowerInvariant() -ne [string]$result.receipt_sha256) {
                            $validationErrors.Add("active policy rebind receipt SHA256 mismatch")
                        }
                        if ([string]$rebind.approval_receipt_hash -ne [string]$receipt.receipt_hash) {
                            $validationErrors.Add("active policy rebind receipt hash mismatch")
                        }
                    }
                    if (-not [bool]$rebind.actual_collection_allowed) {
                        $validationErrors.Add("active policy rebind does not allow exact collection")
                    }
                    if ([bool]$rebind.stop_incomplete_retry_authorized) {
                        $validationErrors.Add("active policy rebind authorizes STOPPED_INCOMPLETE retry")
                    }
                }
            }
        }

        if ($observedPhase -eq "AWAITING_EXACT_APPROVAL") {
            foreach ($artifact in @(
                @($result.receipt_present, "approval receipt"),
                @($result.launch_record_present, "launch record"),
                @($result.output_present, "output namespace"),
                @($result.quality_output_present, "quality output")
            )) {
                if ([bool]$artifact[0]) {
                    $validationErrors.Add("$($artifact[1]) exists while gate is preapproval")
                }
            }
        } elseif ($observedPhase -eq "APPROVED_AWAITING_VISIBLE_LAUNCH") {
            if ($result.launch_record_present) { $validationErrors.Add("launch record exists before visible launch") }
            if ($result.output_present) { $validationErrors.Add("output namespace exists before visible launch") }
            if ($result.quality_output_present) { $validationErrors.Add("quality output exists before visible launch") }
        } else {
            if (-not $result.launch_record_present) {
                $validationErrors.Add("exact launch record is missing")
            } else {
                $launchRecord = Get-Content -Raw -LiteralPath ([string]$result.launch_record_path) |
                    ConvertFrom-Json -DateKind String
                if ([string]$launchRecord.schema -ne "trading_mvp_slow_liquidity_recollect_launch_v1") {
                    $validationErrors.Add("launch record schema mismatch")
                }
                if ([string]$launchRecord.run_id -ne $runId) {
                    $validationErrors.Add("launch record run_id mismatch")
                }
                if (-not [bool]$launchRecord.terminal_ownership_verified) {
                    $validationErrors.Add("launch record terminal ownership is not verified")
                }
                if (-not (Test-ExactPath $launchRecord.plan_path $normalizedPlanPath)) {
                    $validationErrors.Add("launch record plan path mismatch")
                }
                if (([string]$launchRecord.plan_file_sha256).ToLowerInvariant() -ne $planFileSha256) {
                    $validationErrors.Add("launch record plan file SHA256 mismatch")
                }
                if (([string]$launchRecord.plan_hash).ToLowerInvariant() -ne $planHash) {
                    $validationErrors.Add("launch record plan hash mismatch")
                }
                if (-not (Test-ExactPath $launchRecord.approval_receipt_path $result.receipt_path)) {
                    $validationErrors.Add("launch record approval receipt path mismatch")
                }
                if (([string]$launchRecord.approval_receipt_sha256).ToLowerInvariant() -ne [string]$result.receipt_sha256) {
                    $validationErrors.Add("launch record approval receipt SHA256 mismatch")
                }
                if ([bool]$launchRecord.retry_authorized) {
                    $validationErrors.Add("launch record authorizes retry")
                }
                $allowedLaunchStates = switch ($observedPhase) {
                    "VISIBLE_LAUNCH_STARTING" {
                        @("VISIBLE_WORKER_CLAIMED", "PREFLIGHT_PASSED", "GLOBAL_WRITER_CLAIMED", "RUNNING")
                        break
                    }
                    "RUNNING" {
                        @("GLOBAL_WRITER_CLAIMED", "RUNNING", "COMPLETE", "STOPPED_INCOMPLETE")
                        break
                    }
                    "STOPPED_INCOMPLETE_NO_RETRY" { @("STOPPED_INCOMPLETE"); break }
                    default { @("COMPLETE") }
                }
                if ([string]$launchRecord.status -notin $allowedLaunchStates) {
                    $validationErrors.Add("launch record status does not match exact lifecycle phase")
                }
                $result.launch_record_valid = $validationErrors.Count -eq 0
            }
        }

        if ($observedPhase -eq "RUNNING" -and -not $result.output_present) {
            $validationErrors.Add("running exact recollect output namespace is missing")
        }
        if ($observedPhase -in @(
            "READY_FOR_TECHNICAL_QUALITY",
            "TECHNICAL_QUALITY_COMMITTING",
            "QUALITY_ACCEPTED_AWAIT_OFFICIAL_IDENTITY_APPROVAL",
            "QUALITY_REJECTED_TERMINAL_NO_RETRY"
        )) {
            if (-not $result.output_present) { $validationErrors.Add("completed exact output namespace is missing") }
            if (-not $result.manifest_present) { $validationErrors.Add("completed exact manifest is missing") }
        }
        if ($observedPhase -eq "READY_FOR_TECHNICAL_QUALITY" -and $result.quality_output_present) {
            $validationErrors.Add("quality output exists before exact quality gate commit")
        }
        if ($observedPhase -eq "TECHNICAL_QUALITY_COMMITTING" -and -not $result.quality_output_present) {
            $validationErrors.Add("quality commit marker is missing")
        }
        if ($observedPhase -in @(
            "QUALITY_ACCEPTED_AWAIT_OFFICIAL_IDENTITY_APPROVAL",
            "QUALITY_REJECTED_TERMINAL_NO_RETRY"
        )) {
            if (-not $result.quality_output_present) {
                $validationErrors.Add("exact quality output is missing")
            } else {
                try {
                    $quality = Get-Content -Raw -LiteralPath ([string]$result.quality_output_path) |
                        ConvertFrom-Json -DateKind String
                    $provenance = $quality.exact_recollect_provenance
                    if ([string]$quality.decision -ne $gateDecision) {
                        $validationErrors.Add("exact quality decision mismatch")
                    }
                    if ($null -eq $provenance) {
                        $validationErrors.Add("exact quality provenance is missing")
                    } else {
                        if ([string]$provenance.run_id -ne $runId) {
                            $validationErrors.Add("exact quality run id mismatch")
                        }
                        if (-not (Test-ExactPath $provenance.plan_path $normalizedPlanPath)) {
                            $validationErrors.Add("exact quality plan path mismatch")
                        }
                        if (([string]$provenance.plan_file_sha256).ToLowerInvariant() -ne $planFileSha256) {
                            $validationErrors.Add("exact quality plan file SHA256 mismatch")
                        }
                        if (([string]$provenance.plan_hash).ToLowerInvariant() -ne $planHash) {
                            $validationErrors.Add("exact quality plan hash mismatch")
                        }
                        if (-not (Test-ExactPath $provenance.approval_receipt_path $result.receipt_path)) {
                            $validationErrors.Add("exact quality approval receipt path mismatch")
                        }
                        if (([string]$provenance.approval_receipt_file_sha256).ToLowerInvariant() -ne [string]$result.receipt_sha256) {
                            $validationErrors.Add("exact quality approval receipt SHA256 mismatch")
                        }
                        if (-not (Test-ExactPath $provenance.launch_record_path $result.launch_record_path)) {
                            $validationErrors.Add("exact quality launch record path mismatch")
                        }
                        if (([string]$provenance.launch_record_file_sha256).ToLowerInvariant() -ne (Get-ExactSha256 ([string]$result.launch_record_path))) {
                            $validationErrors.Add("exact quality launch record SHA256 mismatch")
                        }
                        if (-not (Test-ExactPath $provenance.manifest_path $result.manifest_path)) {
                            $validationErrors.Add("exact quality manifest path mismatch")
                        }
                        if (([string]$provenance.manifest_file_sha256).ToLowerInvariant() -ne (Get-ExactSha256 ([string]$result.manifest_path))) {
                            $validationErrors.Add("exact quality manifest SHA256 mismatch")
                        }
                        if (-not (Test-ExactPath $provenance.output_jsonl_path $plan.execution.output_jsonl)) {
                            $validationErrors.Add("exact quality output JSONL path mismatch")
                        }
                        if (([string]$provenance.output_jsonl_file_sha256).ToLowerInvariant() -ne (Get-ExactSha256 ([string]$plan.execution.output_jsonl))) {
                            $validationErrors.Add("exact quality output JSONL SHA256 mismatch")
                        }
                        if (-not [bool]$provenance.technical_quality_only) {
                            $validationErrors.Add("exact quality technical-only boundary mismatch")
                        }
                        if ([bool]$provenance.official_identity_verification_authorized) {
                            $validationErrors.Add("exact quality illegally authorizes identity verification")
                        }
                        if ([bool]$provenance.evaluator_or_oos_authorized) {
                            $validationErrors.Add("exact quality illegally authorizes evaluator or OOS")
                        }
                        if ([bool]$provenance.stopped_incomplete_retry_authorized) {
                            $validationErrors.Add("exact quality illegally authorizes stopped-incomplete retry")
                        }
                    }
                    if ([bool]$quality.retry_authorized -or [bool]$quality.rescope_authorized -or
                        [bool]$quality.evaluator_or_oos_authorized) {
                        $validationErrors.Add("exact quality terminal safety boundary mismatch")
                    }
                    if ($observedPhase -in @(
                        "QUALITY_ACCEPTED_AWAIT_OFFICIAL_IDENTITY_APPROVAL",
                        "QUALITY_ACCEPTED_CONTINUE_STANDING_PUBLIC_RESEARCH"
                    )) {
                        if ([bool]$quality.terminal -or -not [bool]$quality.identity_verification_required -or
                            [bool]$quality.identity_verification_authorized) {
                            $validationErrors.Add("accepted exact quality identity checkpoint mismatch")
                        }
                    } elseif (-not [bool]$quality.terminal -or [bool]$quality.identity_verification_required -or
                        [bool]$quality.identity_verification_authorized) {
                        $validationErrors.Add("rejected exact quality terminal checkpoint mismatch")
                    }
                } catch {
                    $validationErrors.Add("exact quality output is unreadable: $($_.Exception.Message)")
                }

                if ($result.raw_gate_present) {
                    if (-not (Test-ExactPath $rawGate.last_slow_liquidity_history_data_quality_output_path $result.quality_output_path)) {
                        $validationErrors.Add("raw active gate quality output path mismatch")
                    }
                    if (([string]$rawGate.last_slow_liquidity_history_data_quality_output_sha256).ToLowerInvariant() -ne (Get-ExactSha256 ([string]$result.quality_output_path))) {
                        $validationErrors.Add("raw active gate quality output SHA256 mismatch")
                    }
                }
                $result.quality_output_valid = $validationErrors.Count -eq 0
            }
        }

        if (
            $observedPhase -eq "QUALITY_ACCEPTED_AWAIT_OFFICIAL_IDENTITY_APPROVAL" -and
            [bool]$result.standing_research_authorized
        ) {
            $observedPhase = $qualityAcceptedStandingDecision
            $result.observed_phase = $observedPhase
        }
        $result.standing_research_continue_allowed = [bool](
            $observedPhase -eq $qualityAcceptedStandingDecision -and
            $result.standing_research_authorized
        )

        $result.errors = @($validationErrors)
        $result.plan_valid = $validationErrors.Count -eq 0
        if (-not $result.plan_valid) {
            $result.phase = "INTEGRITY_BLOCKED"
            $result.integrity_blocked = $true
            return [pscustomobject]$result
        }

        $result.preflight_command = Expand-ExactCommand $commands.preflight $planHash $planFileSha256
        if ([string]::IsNullOrWhiteSpace([string]$result.preflight_command)) {
            $quotedLauncher = '"' + ([string]$result.launcher_path -replace '"', '\"') + '"'
            $quotedPlan = '"' + ($normalizedPlanPath -replace '"', '\"') + '"'
            $result.preflight_command = (
                "pwsh -NoProfile -ExecutionPolicy Bypass -File {0} -PlanPath {1} " +
                "-ExpectedPlanHash {2} -ExpectedPlanFileSha256 {3} -PreflightOnly -Json"
            ) -f $quotedLauncher, $quotedPlan, $planHash, $planFileSha256
        }
        if ($postApprovalPhase) {
            $receiptSha256 = [string]$result.receipt_sha256
            $result.launch_command = Expand-ExactCommand $commands.start_after_receipt $planHash $planFileSha256 $receiptSha256
            $result.status_command = Expand-ExactCommand $commands.status $planHash $planFileSha256 $receiptSha256
            $result.stop_command = Expand-ExactCommand $commands.stop $planHash $planFileSha256 $receiptSha256
            $result.quality_preflight_command = Expand-ExactCommand $commands.data_quality_after_complete_preflight $planHash $planFileSha256 $receiptSha256
            $result.quality_command = Expand-ExactCommand $commands.data_quality_after_complete $planHash $planFileSha256 $receiptSha256
        }

        $result.phase = $observedPhase
        switch ($observedPhase) {
            "AWAITING_EXACT_APPROVAL" {
                $result.awaiting_approval = $true
                $result.requires_user_approval = $true
                $result.required_user_input = "exact_slow_liquidity_recollect_approval"
                $result.primary_command = $result.approval_packet_command
                $result.next_action = "Read the current exact approval packet with the non-writing approval-freeze preflight, then await matching exact user text."
                break
            }
            "APPROVED_AWAITING_VISIBLE_LAUNCH" {
                $result.approved_awaiting_launch = $true
                $result.primary_command = $result.launch_command
                $result.next_action = "Run the exact single-use public read-only collector once in a visible terminal."
                break
            }
            "VISIBLE_LAUNCH_STARTING" {
                $result.visible_launch_starting = $true
                $result.primary_command = $result.status_command
                $result.next_action = "The visible exact launch already owns the run; use status only and do not launch again."
                break
            }
            "RUNNING" {
                $result.running = $true
                $result.primary_command = $result.status_command
                $result.next_action = "The exact collector is running; use status or the exact stop command only."
                break
            }
            "READY_FOR_TECHNICAL_QUALITY" {
                $result.ready_for_quality = $true
                $result.primary_command = $result.quality_command
                $result.next_action = "Run only the exact offline technical quality gate."
                break
            }
            "TECHNICAL_QUALITY_COMMITTING" {
                $result.technical_quality_committing = $true
                $result.primary_command = $result.status_command
                $result.next_action = "The exact quality result is being committed; do not start it again."
                break
            }
            "STOPPED_INCOMPLETE_NO_RETRY" {
                $result.stopped_incomplete_no_retry = $true
                $result.primary_command = $result.status_command
                $result.next_action = "Terminal incomplete stop; retry and resume are not authorized."
                break
            }
            "QUALITY_ACCEPTED_CONTINUE_STANDING_PUBLIC_RESEARCH" {
                $result.quality_accepted_awaiting_identity_approval = $true
                $result.standing_research_continue_allowed = $true
                $result.requires_user_approval = $false
                $result.required_user_input = ""
                $result.primary_command = $result.status_command
                $result.next_action = "Technical quality passed; continue the next bounded same-scope public research step under standing policy."
                break
            }
            "QUALITY_ACCEPTED_AWAIT_OFFICIAL_IDENTITY_APPROVAL" {
                $result.quality_accepted_awaiting_identity_approval = $true
                $result.standing_research_continue_allowed = $false
                $result.requires_user_approval = $true
                $result.required_user_input = "exact_official_asset_identity_verification_approval"
                $result.primary_command = $result.status_command
                $result.next_action = "Technical quality passed; await separate exact official asset-identity approval."
                break
            }
            "QUALITY_REJECTED_TERMINAL_NO_RETRY" {
                $result.quality_rejected_terminal_no_retry = $true
                $result.primary_command = $result.status_command
                $result.next_action = "Terminal technical-quality reject; no retry or rescope is authorized."
                break
            }
        }
    } catch {
        $result.errors = @($_.Exception.Message)
        $result.phase = "INTEGRITY_BLOCKED"
        $result.integrity_blocked = $true
    }

    return [pscustomobject]$result
}

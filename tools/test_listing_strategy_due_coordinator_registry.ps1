param([string]$TestFilter = "")

$ErrorActionPreference = "Stop"
$PSNativeCommandUseErrorActionPreference = $false
$repoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$pwshExe = (Get-Process -Id $PID).Path
$gitExe = "C:\Program Files\Git\cmd\git.exe"
$pythonExe = "C:\Program Files\Python313\python.exe"
$script:passed = 0
$script:failed = 0
$script:testRoots = [Collections.Generic.List[string]]::new()

function Assert-True {
    param([bool]$Condition, [string]$Message)
    if (-not $Condition) { throw $Message }
}

function Assert-Equal {
    param($Actual, $Expected, [string]$Message)
    if ($Actual -cne $Expected) { throw "$Message (expected=$Expected actual=$Actual)" }
}

function Invoke-Test {
    param([string]$Name, [scriptblock]$Body)
    if ($TestFilter -and $Name -notmatch $TestFilter) { return }
    try {
        & $Body
        $script:passed += 1
        Write-Host "PASS $Name" -ForegroundColor Green
    } catch {
        $script:failed += 1
        Write-Host "FAIL $Name :: $($_.Exception.Message)" -ForegroundColor Red
    }
}

function Get-RawSha256 {
    param([string]$Path)
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

function Write-TestJson {
    param([string]$Path, $Payload)
    $Payload | ConvertTo-Json -Depth 50 | Set-Content -LiteralPath $Path -Encoding utf8NoBOM
}

function Invoke-TestGit {
    param([string[]]$Arguments)
    $output = & $gitExe @Arguments 2>&1 | Out-String
    if ($LASTEXITCODE -ne 0) { throw "fixture git failed: $output" }
    return $output.Trim()
}

function New-RegistryFixture {
    param(
        [switch]$Due,
        [switch]$Staging,
        [ValidateSet("visible", "terminal_pid", "unknown")][string]$LauncherResult = "visible",
        [ValidateSet("", "launcher", "state", "topology")][string]$PrelaunchTamper = ""
    )
    $root = Join-Path ([IO.Path]::GetTempPath()) ("listing-coordinator-registry-" + [guid]::NewGuid().ToString("N"))
    [void](New-Item -ItemType Directory -Path $root)
    $script:testRoots.Add($root)
    $control = Join-Path $root "control"
    $controlTools = Join-Path $control "tools"
    $controlSrc = Join-Path $control "trading_mvp\src"
    $runtime = Join-Path $root "runtime"
    $legacyRoot = Join-Path $root "legacy-automations"
    foreach ($directory in @($controlTools, $controlSrc, $runtime, $legacyRoot)) {
        [void](New-Item -ItemType Directory -Path $directory -Force)
    }
    foreach ($id in @(
        "zolotyaylopata-listing-momentum-monitor",
        "zolotyaylopata-pre-market-perpetual-listing-impulse-monitor",
        "zolotyaylopata-pre-ipo-perpetual-event-monitor"
    )) {
        $directory = Join-Path $legacyRoot $id
        [void](New-Item -ItemType Directory -Path $directory)
        "id = `"$id`"`nstatus = `"PAUSED`"`n" | Set-Content -LiteralPath (Join-Path $directory "automation.toml") -Encoding utf8NoBOM
    }
    $coordinator = Join-Path $controlTools "invoke_listing_strategy_due_coordinator.ps1"
    $source = Get-Content -Raw -LiteralPath (Join-Path $repoRoot "tools\invoke_listing_strategy_due_coordinator.ps1")
    # Only the machine-owned topology location is isolated.  The complete real
    # canonical preflight and execution engine remain in this committed copy.
    $topologyStatement = '$CodexAutomationsRoot = Join-Path $userProfilePath ".codex\automations"'
    Assert-True ($source.Contains($topologyStatement)) "canonical topology default is missing"
    $source = $source.Replace($topologyStatement, ('$CodexAutomationsRoot = ''' + $legacyRoot.Replace("'", "''") + "'"))
    if ($PrelaunchTamper) {
        $target = if ($PrelaunchTamper -eq "launcher") { '$LauncherPath' } else { '$StatePath' }
        $injection = if ($PrelaunchTamper -eq "launcher") {
            '    [IO.File]::AppendAllText(' + $target + ', "`n# changed after initial validation`n")' + [Environment]::NewLine
        } elseif ($PrelaunchTamper -eq "state") {
            '    [IO.File]::WriteAllText(' + $target + ', ''{"status":"COMPLETE","next_interval_at_utc":"2099-01-01T00:00:00Z"}'')' + [Environment]::NewLine
        } else {
            '    $changedTopology = Join-Path $CodexAutomationsRoot "zolotyaylopata-listing-momentum-monitor\automation.toml"' + [Environment]::NewLine +
            '    [IO.File]::WriteAllText($changedTopology, "id = `"zolotyaylopata-listing-momentum-monitor`"`nstatus = `"ACTIVE`"`n")' + [Environment]::NewLine
        }
        $needle = '    $pwshExe = Resolve-PowerShellExecutable'
        Assert-True ($source.Contains($needle)) "prelaunch fixture seam is missing"
        $source = $source.Replace($needle, ($injection + $needle))
    }
    [IO.File]::WriteAllText($coordinator, $source, [Text.UTF8Encoding]::new($false))
    Copy-Item -LiteralPath (Join-Path $repoRoot "tools\install_listing_strategy_due_coordinator_task.ps1") -Destination $controlTools
    foreach ($name in @("canonical_strategy_runtime.py", "external_registry_materializer.py", "external_registry_promoter.py")) {
        Copy-Item -LiteralPath (Join-Path $repoRoot "trading_mvp\src\$name") -Destination $controlSrc
    }
    $sourceEvidence = Join-Path $control "source.json"
    foreach ($entry in @(@($control, "control"), @($runtime, "runtime"))) {
        [void](Invoke-TestGit @("-C", $entry[0], "init", "--quiet"))
        [void](Invoke-TestGit @("-C", $entry[0], "config", "core.autocrlf", "false"))
        [void](Invoke-TestGit @("-C", $entry[0], "config", "user.email", "coordinator-tests@example.invalid"))
        [void](Invoke-TestGit @("-C", $entry[0], "config", "user.name", "Coordinator Tests"))
        [void](Invoke-TestGit @("-C", $entry[0], "remote", "add", "origin", "https://example.invalid/$($entry[1]).git"))
    }
    $worker = Join-Path $runtime "worker.py"
    $launcher = Join-Path $runtime "launcher.ps1"
    $planPath = Join-Path $runtime "plan.json"
    $state = Join-Path $runtime "state.json"
    $marker = Join-Path $root "launcher-invocations.jsonl"
    "def run():`n    return 'synthetic only'`n" | Set-Content -LiteralPath $worker -Encoding utf8NoBOM
    $launcherSource = @'
param([switch]$ScheduledTick, [switch]$Json, [string]$PlanPath)
$ErrorActionPreference = "Stop"
if (-not $ScheduledTick -or -not $Json) { throw "required scheduler arguments are missing" }
if ([IO.Path]::GetFullPath($PlanPath) -cne '__PLAN__') { throw "bound PlanPath not forwarded" }
if ((Get-Location).Path -cne '__RUNTIME__') { throw "launcher cwd is not canonical runtime" }
$attempt = "fixture_" + [guid]::NewGuid().ToString("N")
[IO.File]::AppendAllText('__MARKER__', (([ordered]@{ cwd=(Get-Location).Path; plan_path=$PlanPath; attempt_id=$attempt } | ConvertTo-Json -Compress) + "`n"))
[ordered]@{ status="COMPLETE"; next_interval_at_utc=[datetimeoffset]::UtcNow.UtcDateTime.AddHours(6).ToString("o"); last_attempt_id=$attempt; last_finished_at_utc=[datetimeoffset]::UtcNow.UtcDateTime.ToString("o"); worker_pid=$null } | ConvertTo-Json | Set-Content -LiteralPath '__STATE__' -Encoding utf8NoBOM
$result = [ordered]@{ status="VISIBLE_TERMINAL_LAUNCHED"; visible_terminal_pid=$PID; visible_terminal_exit_pid=$PID; visible_terminal_exit_code=0; visible_terminal_exit_attempt_id=$attempt; visible_terminal_exit_observed_at_utc=[datetimeoffset]::UtcNow.ToString("o") }
__RESULT_CHANGE__
$result | ConvertTo-Json -Compress
exit 0
'@
    $resultChange = switch ($LauncherResult) {
        "terminal_pid" { '$result.Remove("visible_terminal_pid"); $result["terminal_pid"]=$PID' }
        "unknown" { '$result.status="UNKNOWN_SUCCESS"' }
        default { "" }
    }
    $launcherSource = $launcherSource.Replace("__PLAN__", $planPath.Replace("'", "''")).Replace("__RUNTIME__", $runtime.Replace("'", "''")).Replace("__MARKER__", $marker.Replace("'", "''")).Replace("__STATE__", $state.Replace("'", "''")).Replace("__RESULT_CHANGE__", $resultChange)
    [IO.File]::WriteAllText($launcher, $launcherSource, [Text.UTF8Encoding]::new($false))
    Write-TestJson -Path $planPath -Payload ([ordered]@{
        schema = "fixture_plan_v1"; plan_id = "fixture_plan_20260826_v1"; status = "READY_FOR_PUBLIC_RESEARCH"
        implementation = [ordered]@{ files = @([ordered]@{ role="worker"; repo_path="worker.py"; sha256=(Get-RawSha256 $worker) }) }
    })
    $planHasher = 'import hashlib,json,sys; p=json.load(open(sys.argv[1],encoding="utf-8-sig")); p["plan_hash"]=hashlib.sha256(json.dumps(p,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()).hexdigest(); open(sys.argv[1],"w",encoding="utf-8",newline="\n").write(json.dumps(p,ensure_ascii=False,indent=2)+"\n")'
    & $pythonExe -c $planHasher $planPath
    Assert-Equal $LASTEXITCODE 0 "fixture PlanOnly hashing failed"
    [void](Invoke-TestGit @("-C", $runtime, "add", "worker.py", "launcher.ps1", "plan.json"))
    [void](Invoke-TestGit @("-C", $runtime, "commit", "--quiet", "-m", "bound synthetic runtime"))
    $runtimeCommit = Invoke-TestGit @("-C", $runtime, "rev-parse", "HEAD")
    $plan = Get-Content -Raw -LiteralPath $planPath | ConvertFrom-Json
    $next = if ($Due) { [datetimeoffset]::UtcNow.AddMinutes(-30) } else { [datetimeoffset]::UtcNow.AddHours(6) }
    Write-TestJson -Path $state -Payload ([ordered]@{ status="COMPLETE"; next_interval_at_utc=$next.UtcDateTime.ToString("o"); last_attempt_id="before"; last_finished_at_utc=[datetimeoffset]::UtcNow.UtcDateTime.AddHours(-1).ToString("o"); worker_pid=$null })
    $ledger = Join-Path $runtime "attempts.jsonl"
    [IO.File]::WriteAllBytes($ledger, [byte[]]@())

    $parentRoot = Join-Path $root "staging-publications"
    $activeRoot = Join-Path $root "active-publications"
    [void](New-Item -ItemType Directory -Path $parentRoot)
    [void](New-Item -ItemType Directory -Path $activeRoot)
    $selectedRuntime = [ordered]@{
        strategy_id="fixture_selected"; track_class="spot_listing"; runtime_status="INACTIVE"; activation_readiness="READY_AFTER_ROUTER_MIGRATION"
        namespace_prefix="listing.fixture.selected"; scope="crypto_spot_listing"; venues=@("bybit")
        canonical_repo=$runtime; canonical_remote_url="https://example.invalid/runtime.git"; canonical_git_commit=$runtimeCommit
        canonical_plan_path=$planPath; canonical_plan_sha256=[string]$plan.plan_hash; canonical_plan_file_sha256=(Get-RawSha256 $planPath); canonical_plan_id=[string]$plan.plan_id; canonical_plan_status=[string]$plan.status
        launcher_path=$launcher; launcher_sha256=(Get-RawSha256 $launcher); scheduler_routable=$false; allowed_modes=@("DISCOVERY")
        state_path=$state; ledger_path=$ledger; public_data_only=$true; live_trading_allowed=$false
        implementation_bindings=@([ordered]@{ role="worker"; path=$worker; sha256=(Get-RawSha256 $worker) }); supersedes=@(); retired_aliases=@()
    }
    $inactiveRuntime = $selectedRuntime | ConvertTo-Json -Depth 30 | ConvertFrom-Json -AsHashtable
    $inactiveRuntime.strategy_id="fixture_inactive"
    $inactiveRuntime.namespace_prefix="listing.fixture.inactive"
    $inactiveRuntime.scope="crypto_premarket_perpetual"
    $inactiveRuntime.venues=@("okx")
    $inactiveRuntime.state_path=Join-Path $runtime "missing-inactive-state.json"
    $inactiveRuntime.ledger_path=Join-Path $runtime "missing-inactive-attempts.jsonl"
    Write-TestJson -Path $sourceEvidence -Payload ([ordered]@{
        schema="zolotyaylopata.canonical_strategy_runtime.v1"; registry_id="fixture_staging_20260826_v1"; generated_at_utc="2026-08-25T00:00:00Z"; activation_status="STAGING_NOT_INSTALLED"
        canonical_owners=@(
            [ordered]@{ strategy_id="fixture_selected"; namespace_prefix="listing.fixture.selected"; scope="crypto_spot_listing"; venues=@("bybit") },
            [ordered]@{ strategy_id="fixture_inactive"; namespace_prefix="listing.fixture.inactive"; scope="crypto_premarket_perpetual"; venues=@("okx") }
        ); runtimes=@($selectedRuntime, $inactiveRuntime)
    })
    [void](Invoke-TestGit @("-C", $control, "add", "tools", "trading_mvp", "source.json"))
    [void](Invoke-TestGit @("-C", $control, "commit", "--quiet", "-m", "bound real control plane and source"))
    $controlCommit = Invoke-TestGit @("-C", $control, "rev-parse", "HEAD")
    $validator = Join-Path $controlSrc "canonical_strategy_runtime.py"
    $materializer = Join-Path $controlSrc "external_registry_materializer.py"
    $materializationArguments = Join-Path $root "materialization-input.json"
    Write-TestJson -Path $materializationArguments -Payload ([ordered]@{
        source_path=$sourceEvidence; publication_root=$parentRoot
        expected_source_head_sha256=(Get-RawSha256 $sourceEvidence)
        expected_materializer_head_sha256=(Get-RawSha256 $materializer)
        expected_validator_head_sha256=(Get-RawSha256 $validator)
        expected_control_plane_git_commit=$controlCommit
    })
    $materializationCode = 'import json,sys; sys.path.insert(0,sys.argv[1]); from external_registry_materializer import materialize_external_registry; print(json.dumps(materialize_external_registry(**json.load(open(sys.argv[2],encoding="utf-8-sig")))))'
    $materializationOutput = & $pythonExe -B -c $materializationCode $controlSrc $materializationArguments 2>&1 | Out-String
    Assert-Equal $LASTEXITCODE 0 "fixture staging materialization failed: $materializationOutput"
    $materialization = $materializationOutput | ConvertFrom-Json
    $parentRegistry = [string]$materialization.registry_path
    $parentReceipt = [string]$materialization.receipt_path
    $parentRegistrySha = Get-RawSha256 $parentRegistry
    $registryPath=$parentRegistry
    $receiptPath=$parentReceipt
    if (-not $Staging) {
        $promotionArguments = Join-Path $root "promotion-input.json"
        Write-TestJson -Path $promotionArguments -Payload ([ordered]@{
            parent_registry_path=$parentRegistry; parent_receipt_path=$parentReceipt; publication_root=$activeRoot; active_strategy_id="fixture_selected"; generated_at_utc="2026-08-26T00:00:00Z"
            expected_parent_registry_raw_sha256=$parentRegistrySha; expected_parent_receipt_raw_sha256=(Get-RawSha256 $parentReceipt)
            expected_promoter_head_sha256=(Get-RawSha256 (Join-Path $controlSrc "external_registry_promoter.py")); expected_validator_head_sha256=(Get-RawSha256 $validator)
            expected_publication_primitive_head_sha256=(Get-RawSha256 $materializer); expected_coordinator_head_sha256=(Get-RawSha256 $coordinator)
            expected_installer_head_sha256=(Get-RawSha256 (Join-Path $controlTools "install_listing_strategy_due_coordinator_task.ps1")); expected_control_plane_git_commit=$controlCommit
        })
        $promotionCode = 'import json,sys; sys.path.insert(0,sys.argv[1]); from external_registry_promoter import promote_external_registry; print(json.dumps(promote_external_registry(**json.load(open(sys.argv[2],encoding="utf-8-sig")))))'
        $promotionOutput = & $pythonExe -B -c $promotionCode $controlSrc $promotionArguments 2>&1 | Out-String
        Assert-Equal $LASTEXITCODE 0 "fixture ACTIVE promotion failed: $promotionOutput"
        $promotion = $promotionOutput | ConvertFrom-Json
        $registryPath=[string]$promotion.registry_path
        $receiptPath=[string]$promotion.receipt_path
    }
    return [pscustomobject]@{
        root=$root; control=$control; runtime=$runtime; coordinator=$coordinator; validator=$validator; launcher=$launcher; plan=$planPath
        registry=$registryPath; receipt=$receiptPath; parent_registry=$parentRegistry; parent_receipt=$parentReceipt
        registry_sha=(Get-RawSha256 $registryPath); receipt_sha=(Get-RawSha256 $receiptPath); coordinator_sha=(Get-RawSha256 $coordinator); validator_sha=(Get-RawSha256 $validator); control_commit=$controlCommit
        state=$state; ledger=$ledger; marker=$marker; legacy_root=$legacyRoot; coordinator_artifacts=(Join-Path $control "docs\agent-log\run-gates")
    }
}

function Invoke-FixtureCoordinator {
    param($Fixture, [ValidateSet("scheduled", "preflight", "both", "none")][string]$Mode="scheduled", [string[]]$ExtraArguments=@())
    $arguments=@("-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", $Fixture.coordinator, "-Json", "-WorkerExitTimeoutSec", "2")
    if ($Mode -in @("scheduled", "both")) { $arguments += "-ScheduledTick" }
    if ($Mode -in @("preflight", "both")) { $arguments += "-PreflightOnly" }
    $arguments += @(
        "-RegistryPath", $Fixture.registry, "-ReceiptPath", $Fixture.receipt,
        "-ExpectedRegistrySha256", $Fixture.registry_sha, "-ExpectedReceiptSha256", $Fixture.receipt_sha,
        "-ExpectedCoordinatorSha256", $Fixture.coordinator_sha, "-ExpectedValidatorSha256", $Fixture.validator_sha,
        "-ExpectedControlPlaneGitCommit", $Fixture.control_commit
    ) + $ExtraArguments
    $output=& $pwshExe @arguments 2>&1 | Out-String
    $exitCode=$LASTEXITCODE
    $payload=$null
    try { $payload=$output | ConvertFrom-Json -DateKind String -ErrorAction Stop } catch { }
    return [pscustomobject]@{ exit_code=$exitCode; payload=$payload; raw=$output }
}

function Get-MutationSnapshot {
    param($Fixture)
    $result=[ordered]@{}
    foreach ($path in @($Fixture.state, $Fixture.ledger, $Fixture.marker)) {
        $result[$path]=if (Test-Path -LiteralPath $path -PathType Leaf) { Get-RawSha256 $path } else { $null }
    }
    $result["coordinator_artifacts"] = if (Test-Path -LiteralPath $Fixture.coordinator_artifacts) {
        @(Get-ChildItem -LiteralPath $Fixture.coordinator_artifacts -Recurse -File | Sort-Object FullName | ForEach-Object { $_.FullName + ":" + (Get-RawSha256 $_.FullName) })
    } else { @() }
    return ($result | ConvertTo-Json -Depth 10 -Compress)
}

try {
    Invoke-Test "STAGING real preflight remains read-only" {
        $fixture=New-RegistryFixture -Due -Staging
        $before=Get-MutationSnapshot $fixture
        $result=Invoke-FixtureCoordinator $fixture
        Assert-Equal $result.exit_code 0 "STAGING preflight failed: $($result.raw)"
        Assert-Equal $result.payload.status "STAGED_FAIL_CLOSED" "STAGING was not terminal"
        Assert-Equal $result.payload.launch_allowed $false "STAGING allowed launch"
        Assert-Equal (Get-MutationSnapshot $fixture) $before "STAGING mutated durable state"
    }
    Invoke-Test "ACTIVE PreflightOnly never executes a due runtime" {
        $fixture=New-RegistryFixture -Due
        $before=Get-MutationSnapshot $fixture
        $result=Invoke-FixtureCoordinator $fixture -Mode preflight
        Assert-Equal $result.exit_code 0 "ACTIVE preflight failed: $($result.raw)"
        Assert-Equal $result.payload.status "ACTIVE_PREFLIGHT_OK" "ACTIVE preflight status"
        Assert-Equal $result.payload.reason "PREFLIGHT_ONLY" "ACTIVE preflight reason"
        Assert-Equal $result.payload.launch_allowed $true "ACTIVE binding was not acknowledged"
        Assert-Equal $result.payload.execution_performed $false "preflight executed work"
        Assert-Equal $result.payload.active_strategy_id "fixture_selected" "preflight lost active identity"
        Assert-Equal (Get-MutationSnapshot $fixture) $before "ACTIVE preflight mutated durable state"
    }
    Invoke-Test "ACTIVE NOT_DUE touches neither writer artifacts nor inactive state" {
        $fixture=New-RegistryFixture
        $before=Get-MutationSnapshot $fixture
        $result=Invoke-FixtureCoordinator $fixture
        Assert-Equal $result.exit_code 0 "ACTIVE not-due failed: $($result.raw)"
        Assert-Equal $result.payload.status "NOT_DUE" "ACTIVE not-due status"
        Assert-Equal @($result.payload.state_inputs).Count 1 "inactive runtime was routed"
        Assert-Equal $result.payload.state_inputs[0].track "fixture_selected" "wrong selected runtime"
        Assert-Equal (Get-MutationSnapshot $fixture) $before "NOT_DUE mutated durable state"
    }
    Invoke-Test "ACTIVE due launches one runtime with canonical cwd and bound PlanPath" {
        $fixture=New-RegistryFixture -Due
        $result=Invoke-FixtureCoordinator $fixture
        Assert-Equal $result.exit_code 0 "ACTIVE due execution failed: $($result.raw)"
        Assert-Equal $result.payload.status "COMPLETE" "synthetic execution did not complete"
        $calls=@(Get-Content -LiteralPath $fixture.marker | ForEach-Object { $_ | ConvertFrom-Json })
        Assert-Equal $calls.Count 1 "more than one runtime was launched"
        Assert-Equal $calls[0].cwd $fixture.runtime "canonical cwd was lost"
        Assert-Equal $calls[0].plan_path $fixture.plan "bound PlanPath was lost"
        Assert-Equal $result.payload.track_outcomes[0].track "fixture_selected" "wrong active runtime outcome"
        Assert-Equal $result.payload.registry_raw_sha256 $fixture.registry_sha "runtime outcome lost registry provenance"
        Assert-True (-not (Test-Path -LiteralPath (Join-Path $fixture.coordinator_artifacts "listing_strategy_due_coordinator.claim.json"))) "finished worker claim was retained"
    }
    Invoke-Test "ACTIVE mutable state advances without pinning activation snapshot" {
        $fixture=New-RegistryFixture -Due
        $first=Invoke-FixtureCoordinator $fixture
        Assert-Equal $first.exit_code 0 "first synthetic tick failed: $($first.raw)"
        $before=Get-MutationSnapshot $fixture
        $second=Invoke-FixtureCoordinator $fixture
        Assert-Equal $second.exit_code 0 "advanced state was blocked: $($second.raw)"
        Assert-Equal $second.payload.status "NOT_DUE" "advanced due-state was not used"
        Assert-Equal (Get-MutationSnapshot $fixture) $before "advanced NOT_DUE state was mutated"
    }
    Invoke-Test "ACTIVE parent bytes changed after promotion fail closed" {
        $fixture=New-RegistryFixture -Due
        [IO.File]::AppendAllText($fixture.parent_receipt, " ")
        $before=Get-MutationSnapshot $fixture
        $result=Invoke-FixtureCoordinator $fixture
        Assert-Equal $result.exit_code 2 "changed parent receipt was accepted: $($result.raw)"
        Assert-True ($result.payload.reason -match "PARENT") "parent mismatch was not explicit: $($result.raw)"
        Assert-Equal (Get-MutationSnapshot $fixture) $before "parent mismatch performed work"
    }
    Invoke-Test "ACTIVE strict receipt rejects control policy and runtime tampering" {
        $fixture=New-RegistryFixture -Due
        $receiptText=Get-Content -Raw -LiteralPath $fixture.receipt
        $before=Get-MutationSnapshot $fixture
        foreach ($mutation in @(
            { param($r) $r.control_bindings[0].head_sha256=("0"*64) },
            { param($r) $r.control_bindings[0].role=$r.control_bindings[1].role },
            { param($r) $r.policy_evidence.public_data_only=$false },
            { param($r) $r.active_strategy_id="fixture_inactive" },
            { param($r) $r.active_runtime_binding.launcher_path="C:\unbound.ps1" },
            { param($r) $r.parent_lineage | Add-Member -NotePropertyName unexpected -NotePropertyValue $true }
        )) {
            $receipt=$receiptText | ConvertFrom-Json -DateKind String
            & $mutation $receipt
            Write-TestJson $fixture.receipt $receipt
            $fixture.receipt_sha=Get-RawSha256 $fixture.receipt
            $result=Invoke-FixtureCoordinator $fixture -Mode preflight
            Assert-Equal $result.exit_code 2 "tampered receipt passed: $($result.raw)"
            Assert-Equal $result.payload.execution_performed $false "tampered receipt executed work"
            Assert-Equal (Get-MutationSnapshot $fixture) $before "tampered receipt mutated writer artifacts"
        }
    }
    Invoke-Test "ACTIVE matching parent and child source hashes still require historical Git blob" {
        $fixture=New-RegistryFixture -Due
        $before=Get-MutationSnapshot $fixture
        $parent=Get-Content -Raw -LiteralPath $fixture.parent_receipt | ConvertFrom-Json -DateKind String
        $receipt=Get-Content -Raw -LiteralPath $fixture.receipt | ConvertFrom-Json -DateKind String
        $parent.source_head_sha256=("0"*64)
        $receipt.parent_lineage.source_head_sha256=("0"*64)
        Write-TestJson $fixture.parent_receipt $parent
        $receipt.parent_lineage.receipt_raw_sha256=Get-RawSha256 $fixture.parent_receipt
        Write-TestJson $fixture.receipt $receipt
        $fixture.receipt_sha=Get-RawSha256 $fixture.receipt
        $result=Invoke-FixtureCoordinator $fixture -Mode preflight
        Assert-Equal $result.exit_code 2 "forged historical source passed: $($result.raw)"
        Assert-Equal $result.payload.reason "PARENT_HISTORICAL_SHA256_MISMATCH:source" "historical Git verification was not reached"
        Assert-Equal (Get-MutationSnapshot $fixture) $before "historical source rejection mutated artifacts"
    }
    Invoke-Test "ACTIVE installer dry-run uses real coordinator without due worker execution" {
        $fixture=New-RegistryFixture -Due
        $before=Get-MutationSnapshot $fixture
        $installer=Join-Path $fixture.control "tools\install_listing_strategy_due_coordinator_task.ps1"
        $output=& $pwshExe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $installer -DryRun -Json `
            -RegistryPath $fixture.registry -ReceiptPath $fixture.receipt `
            -ExpectedRegistrySha256 $fixture.registry_sha -ExpectedReceiptSha256 $fixture.receipt_sha `
            -ExpectedInstallerSha256 (Get-RawSha256 $installer) -ExpectedCoordinatorSha256 $fixture.coordinator_sha `
            -ExpectedValidatorSha256 $fixture.validator_sha -ExpectedControlPlaneGitCommit $fixture.control_commit `
            -CodexAutomationsRoot $fixture.legacy_root 2>&1 | Out-String
        Assert-Equal $LASTEXITCODE 0 "real installer dry-run failed: $output"
        $result=$output | ConvertFrom-Json -DateKind String
        Assert-Equal $result.status "ACTIVE_DRY_RUN_OK" "installer dry-run status"
        Assert-Equal $result.registration_attempted $false "installer attempted scheduler registration"
        Assert-Equal $result.execution_performed $false "installer executed work"
        Assert-Equal $result.coordinator_preflight.status "ACTIVE_PREFLIGHT_OK" "installer did not use real ACTIVE preflight"
        Assert-True ($result.action_arguments -match "-ScheduledTick" -and $result.action_arguments -notmatch "-PreflightOnly") "registered task mode differs from scheduled action"
        Assert-Equal (Get-MutationSnapshot $fixture) $before "installer dry-run mutated writer artifacts"
    }
    Invoke-Test "ACTIVE final prelaunch check rejects changed launcher through retry path" {
        $fixture=New-RegistryFixture -Due -PrelaunchTamper launcher
        $result=Invoke-FixtureCoordinator $fixture
        Assert-Equal $result.exit_code 2 "changed launcher was accepted: $($result.raw)"
        Assert-Equal $result.payload.status "RETRY_NEXT_INTERVAL" "changed launcher did not reach terminal retry"
        Assert-Equal $result.payload.track_outcomes[0].status "RUNTIME_BINDING_CHANGED" "changed launcher reason was lost"
        Assert-True (-not (Test-Path -LiteralPath $fixture.marker)) "changed launcher was executed"
        Assert-True (Test-Path -LiteralPath (Join-Path $fixture.coordinator_artifacts "listing_strategy_due_coordinator_attempts.jsonl")) "retry attempt was not recorded"
    }
    Invoke-Test "ACTIVE final due-state check defers a newly future interval" {
        $fixture=New-RegistryFixture -Due -PrelaunchTamper state
        $result=Invoke-FixtureCoordinator $fixture
        Assert-Equal $result.exit_code 0 "updated due-state failed: $($result.raw)"
        Assert-Equal $result.payload.track_outcomes[0].status "NOT_DUE_AFTER_RECHECK" "updated due-state did not defer"
        Assert-True (-not (Test-Path -LiteralPath $fixture.marker)) "newly not-due runtime was launched"
    }
    Invoke-Test "ACTIVE legacy topology changing before launch remains a durable retry" {
        $fixture=New-RegistryFixture -Due -PrelaunchTamper topology
        $result=Invoke-FixtureCoordinator $fixture
        Assert-Equal $result.exit_code 2 "newly active legacy automation was accepted: $($result.raw)"
        Assert-Equal $result.payload.status "RETRY_NEXT_INTERVAL" "topology race did not persist retry"
        Assert-Equal $result.payload.track_outcomes[0].status "LEGACY_TOPOLOGY_CHANGED" "topology reason was lost"
        Assert-True (-not (Test-Path -LiteralPath $fixture.marker)) "duplicate legacy topology launched runtime"
        Assert-True (Test-Path -LiteralPath (Join-Path $fixture.coordinator_artifacts "listing_strategy_due_coordinator_attempts.jsonl")) "topology retry was not recorded"
    }
    Invoke-Test "ACTIVE rejects ambiguous modes and unbound production overrides" {
        $fixture=New-RegistryFixture -Due
        $before=Get-MutationSnapshot $fixture
        foreach ($case in @(
            @{ mode="both"; extra=@(); reason="EXECUTION_MODE_CONFLICT" },
            @{ mode="none"; extra=@(); reason="SCHEDULED_TICK_REQUIRED" },
            @{ mode="scheduled"; extra=@("-NowUtc", "2099-01-01T00:00:00Z"); reason="PRODUCTION_PATH_OVERRIDE_FORBIDDEN" },
            @{ mode="scheduled"; extra=@("-ListingLauncherPath", $fixture.launcher); reason="PRODUCTION_PATH_OVERRIDE_FORBIDDEN" }
        )) {
            $result=Invoke-FixtureCoordinator $fixture -Mode $case.mode -ExtraArguments $case.extra
            Assert-Equal $result.exit_code 2 "forbidden mode/override accepted: $($result.raw)"
            Assert-Equal $result.payload.reason $case.reason "wrong mode/override failure: $($result.raw)"
        }
        Assert-Equal (Get-MutationSnapshot $fixture) $before "mode/override rejection performed work"
    }
    Invoke-Test "ACTIVE terminal_pid is not accepted as visible_terminal_pid" {
        $fixture=New-RegistryFixture -Due -LauncherResult terminal_pid
        $result=Invoke-FixtureCoordinator $fixture
        Assert-Equal $result.exit_code 2 "terminal_pid-only launcher was accepted: $($result.raw)"
        Assert-Equal $result.payload.track_outcomes[0].status "NO_VISIBLE_WORKER_PID" "visible PID rejection missing"
    }
    Invoke-Test "ACTIVE unknown launcher success status is rejected" {
        $fixture=New-RegistryFixture -Due -LauncherResult unknown
        $result=Invoke-FixtureCoordinator $fixture
        Assert-Equal $result.exit_code 2 "unknown launcher status was accepted: $($result.raw)"
        Assert-Equal $result.payload.track_outcomes[0].status "INVALID_LAUNCHER_STATUS" "unknown launcher status rejection missing"
    }
} finally {
    foreach ($root in $script:testRoots) {
        if (-not (Test-Path -LiteralPath $root)) { continue }
        $resolved=[IO.Path]::GetFullPath($root)
        $tempPrefix=[IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd('\','/') + [IO.Path]::DirectorySeparatorChar
        if (-not $resolved.StartsWith($tempPrefix,[StringComparison]::OrdinalIgnoreCase) -or (Split-Path -Leaf $resolved) -notlike "listing-coordinator-registry-*") {
            throw "refusing to remove unexpected fixture directory: $resolved"
        }
        Remove-Item -LiteralPath $resolved -Recurse -Force
    }
}
Write-Host "RESULT passed=$script:passed failed=$script:failed"
if ($script:failed -gt 0 -or $script:passed -eq 0) { exit 1 }
exit 0

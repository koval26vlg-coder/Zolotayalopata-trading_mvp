$ErrorActionPreference = "Stop"

$installerPath = Join-Path $PSScriptRoot "install_listing_strategy_due_coordinator_task.ps1"
$pwsh = (Get-Process -Id $PID).Path
$script:installerIntegrationCases = 0

function Assert-True {
    param([bool]$Condition, [string]$Message)
    if (-not $Condition) { throw $Message }
}

function Write-FixtureJson {
    param([string]$Path, [object]$Value)
    [IO.File]::WriteAllText($Path, (($Value | ConvertTo-Json -Depth 60) + "`n"), [Text.UTF8Encoding]::new($false))
}

function Get-FixtureSha([string]$Path) {
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

function New-InstallerFixture {
    param([string]$Root, [bool]$Active = $true)
    $repo = Join-Path $Root "repo"
    $tools = Join-Path $repo "tools"
    $src = Join-Path $repo "trading_mvp\src"
    $legacy = Join-Path $Root "legacy"
    foreach ($directory in @($tools, $src, $legacy)) { New-Item -ItemType Directory -Path $directory -Force | Out-Null }
    $copyInstaller = Join-Path $tools "install_listing_strategy_due_coordinator_task.ps1"
    Copy-Item -LiteralPath $installerPath -Destination $copyInstaller
    $coordinator = Join-Path $tools "invoke_listing_strategy_due_coordinator.ps1"
    $coordinatorSource = @'
param([switch]$PreflightOnly,[switch]$ScheduledTick,[switch]$Json,[int]$WorkerExitTimeoutSec,
 [string]$RegistryPath,[string]$ReceiptPath,[string]$ExpectedRegistrySha256,[string]$ExpectedReceiptSha256,
 [string]$ExpectedCoordinatorSha256,[string]$ExpectedValidatorSha256,[string]$ExpectedControlPlaneGitCommit,
 [string]$CodexAutomationsRoot)
$ErrorActionPreference = "Stop"
$fixtureRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
if ($ScheduledTick -or -not $PreflightOnly) {
 [IO.File]::WriteAllText((Join-Path $fixtureRoot "worker.marker"), "unsafe scheduled tick")
 @{status="WORKER_WOULD_HAVE_RUN"; execution_performed=$true} | ConvertTo-Json -Compress
 exit 12
}
[IO.File]::WriteAllText((Join-Path $fixtureRoot "preflight.marker"), "PreflightOnly")
$registry = Get-Content -LiteralPath $RegistryPath -Raw | ConvertFrom-Json
$mutationPath = Join-Path $fixtureRoot "mutation.json"
if (Test-Path -LiteralPath $mutationPath) {
 $mutation = Get-Content -LiteralPath $mutationPath -Raw | ConvertFrom-Json
 [IO.File]::AppendAllText([string]$mutation.path, [string]$mutation.append)
}
$active = $registry.activation_status -ceq "ACTIVE_INSTALLED"
$result = @{status=$(if($active){"ACTIVE_PREFLIGHT_OK"}else{"STAGED_FAIL_CLOSED"});
 reason=$(if($active){"PREFLIGHT_ONLY"}else{"NOT_ACTIVATED"});
 registry_decision=$(if($active){"ACTIVE_ROUTABLE"}else{"STAGED_FAIL_CLOSED"});
 execution_performed=$false; launch_allowed=$active; active_strategy_id=$registry.active_strategy_id;
 registry_raw_sha256=$ExpectedRegistrySha256; receipt_raw_sha256=$ExpectedReceiptSha256;
 validator_exit_code=0}
$override = Join-Path $fixtureRoot "preflight-override.json"
if (Test-Path -LiteralPath $override) {
 $values = Get-Content -LiteralPath $override -Raw | ConvertFrom-Json -AsHashtable
 foreach ($entry in $values.GetEnumerator()) { $result[$entry.Key] = $entry.Value }
}
$result | ConvertTo-Json -Compress
exit 0
'@
    [IO.File]::WriteAllText($coordinator, $coordinatorSource, [Text.UTF8Encoding]::new($false))
    $validator = Join-Path $src "canonical_strategy_runtime.py"
    $materializer = Join-Path $src "external_registry_materializer.py"
    $promoter = Join-Path $src "external_registry_promoter.py"
    foreach ($file in @($validator, $materializer, $promoter)) { [IO.File]::WriteAllText($file, "# committed installer fixture`n") }
    $launcher = Join-Path $tools "public_research_launcher.ps1"
    [IO.File]::WriteAllText($launcher, "throw 'installer must never launch this worker'`n")
    $plan = Join-Path $repo "fixture-plan.json"
    Write-FixtureJson $plan @{plan_id="fixture_plan";plan_hash=("a" * 64);status="READY"}
    $sourceRegistry = Join-Path $repo "staging-source.json"
    Write-FixtureJson $sourceRegistry @{fixture="historical staging source"}
    $statePath = Join-Path $Root "state.json"
    Write-FixtureJson $statePath @{status="READY";next_interval_at_utc="2000-01-01T00:00:00Z"}
    $git = "C:\Program Files\Git\cmd\git.exe"
    & $git init --quiet $repo
    & $git -C $repo config core.autocrlf false
    & $git -C $repo add --all
    & $git -C $repo -c user.name=Fixture -c user.email=fixture@example.invalid -c core.autocrlf=false commit --quiet -m "synthetic installer fixture"
    Assert-True ($LASTEXITCODE -eq 0) "fixture commit failed"
    $commit = (& $git -C $repo rev-parse HEAD).Trim()
    $runtime = [ordered]@{
        strategy_id="fixture_public_research";canonical_repo=$repo;canonical_remote_url="https://example.invalid/research.git";
        canonical_git_commit=$commit;canonical_plan_path=$plan;canonical_plan_sha256=("a" * 64);
        canonical_plan_file_sha256=(Get-FixtureSha $plan);canonical_plan_id="fixture_plan";canonical_plan_status="READY";
        launcher_path=$launcher;launcher_sha256=(Get-FixtureSha $launcher);state_path=$statePath;
        implementation_bindings=@(@{role="launcher";path=$launcher;sha256=(Get-FixtureSha $launcher)});
        runtime_status="INACTIVE";scheduler_routable=$false;activation_readiness="READY_AFTER_ROUTER_MIGRATION";
        public_data_only=$true;live_trading_allowed=$false;allowed_modes=@("DISCOVERY","PAPER_RESEARCH")
    }
    $parentDirectory = Join-Path $Root ("1" * 64)
    New-Item -ItemType Directory -Path $parentDirectory | Out-Null
    $parentRegistryPath = Join-Path $parentDirectory "canonical_strategy_runtime.json"
    $parentReceiptPath = Join-Path $parentDirectory "materialization_receipt.json"
    $parentRegistry = [ordered]@{schema="zolotyaylopata.canonical_strategy_runtime.v1";registry_id="fixture";
        generated_at_utc="2026-08-25T00:00:00Z";activation_status="STAGING_NOT_INSTALLED";runtimes=@($runtime)}
    Write-FixtureJson $parentRegistryPath $parentRegistry
    $canonicalRepos = @(@{canonical_repo=$repo;canonical_git_commit=$commit})
    $parentReceipt = [ordered]@{
        schema="zolotyaylopata.external_registry_materialization_receipt.v2";status="MATERIALIZED_FAIL_CLOSED";
        decision="STAGED_FAIL_CLOSED";launch_allowed=$false;publication_id=("1" * 64);publication_directory=$parentDirectory;
        registry_path=$parentRegistryPath;receipt_path=$parentReceiptPath;registry_raw_sha256=(Get-FixtureSha $parentRegistryPath);
        source_path=$sourceRegistry;source_git_commit=$commit;source_head_sha256=(Get-FixtureSha $sourceRegistry);
        materializer_git_commit=$commit;validator_git_commit=$commit;
        materializer_path=$materializer;materializer_head_sha256=(Get-FixtureSha $materializer);
        validator_path=$validator;validator_head_sha256=(Get-FixtureSha $validator);canonical_repositories=$canonicalRepos;
        validation=@{ok=$true;registry_valid=$true;all_runtime_bindings_valid=$true;decision="STAGED_FAIL_CLOSED";
            launch_allowed=$false;registry_raw_sha256=(Get-FixtureSha $parentRegistryPath);
            runtimes=@(@{strategy_id="fixture_public_research";binding_status="MATCH"})}
    }
    Write-FixtureJson $parentReceiptPath $parentReceipt
    $registryPath = $parentRegistryPath
    $receiptPath = $parentReceiptPath
    if ($Active) {
        $directory = Join-Path $Root ("2" * 64)
        New-Item -ItemType Directory -Path $directory | Out-Null
        $registryPath = Join-Path $directory "canonical_strategy_runtime.json"
        $receiptPath = Join-Path $directory "activation_receipt.json"
        $runtime.runtime_status="ACTIVE"
        $runtime.scheduler_routable=$true
        $registry = [ordered]@{schema="zolotyaylopata.canonical_strategy_runtime.v2";registry_id="fixture.active.fixture_public_research";
            generated_at_utc="2026-08-26T00:00:00Z";activation_status="ACTIVE_INSTALLED";
            active_strategy_id="fixture_public_research";runtimes=@($runtime)}
        Write-FixtureJson $registryPath $registry
        $controlBindings = @(
            @{role="promoter";path=$promoter},@{role="validator";path=$validator},@{role="publication_primitive";path=$materializer},
            @{role="coordinator";path=$coordinator},@{role="installer";path=$copyInstaller}
        ) | ForEach-Object { @{role=$_.role;path=$_.path;git_commit=$commit;head_sha256=(Get-FixtureSha $_.path)} }
        $activeBinding = [ordered]@{}
        foreach ($field in @("strategy_id","canonical_repo","canonical_remote_url","canonical_git_commit","canonical_plan_path",
            "canonical_plan_sha256","canonical_plan_file_sha256","canonical_plan_id","canonical_plan_status","launcher_path",
            "launcher_sha256","state_path","implementation_bindings")) { $activeBinding[$field] = $runtime[$field] }
        $activeBinding.state_raw_sha256=Get-FixtureSha $statePath
        $activeBinding.state_status="READY"
        $activeBinding.next_interval_at_utc="2000-01-01T00:00:00Z"
        $receipt = [ordered]@{
            schema="zolotyaylopata.external_registry_activation_receipt.v1";status="ACTIVATED_PUBLIC_RESEARCH_ONLY";
            decision="ACTIVE_ROUTABLE";launch_allowed=$true;publication_id=("2" * 64);publication_directory=$directory;
            registry_path=$registryPath;receipt_path=$receiptPath;registry_raw_sha256=(Get-FixtureSha $registryPath);
            active_strategy_id="fixture_public_research";control_plane_git_commit=$commit;control_bindings=@($controlBindings);
            canonical_repositories=$canonicalRepos;active_runtime_binding=$activeBinding;
            parent_lineage=@{publication_id=("1" * 64);registry_path=$parentRegistryPath;registry_raw_sha256=(Get-FixtureSha $parentRegistryPath);
                receipt_path=$parentReceiptPath;receipt_raw_sha256=(Get-FixtureSha $parentReceiptPath);
                source_path=$sourceRegistry;source_git_commit=$commit;source_head_sha256=(Get-FixtureSha $sourceRegistry);
                materializer_path=$materializer;materializer_git_commit=$commit;materializer_head_sha256=(Get-FixtureSha $materializer);
                validator_path=$validator;validator_git_commit=$commit;validator_head_sha256=(Get-FixtureSha $validator)};
            policy_evidence=@{source_decision="STAGED_FAIL_CLOSED";all_source_bindings_match=$true;active_runtime_count=1;
                routable_runtime_count=1;activation_readiness="READY_AFTER_ROUTER_MIGRATION";public_data_only=$true;
                live_trading_allowed=$false;allowed_modes=@("DISCOVERY","PAPER_RESEARCH")};
            validation=@{ok=$true;registry_valid=$true;all_runtime_bindings_valid=$true;decision="ACTIVE_ROUTABLE";
                launch_allowed=$true;registry_raw_sha256=(Get-FixtureSha $registryPath)}
        }
        Write-FixtureJson $receiptPath $receipt
    }
    foreach ($id in @("zolotyaylopata-listing-momentum-monitor","zolotyaylopata-pre-market-perpetual-listing-impulse-monitor","zolotyaylopata-pre-ipo-perpetual-event-monitor")) {
        $directory = Join-Path $legacy $id
        New-Item -ItemType Directory -Path $directory | Out-Null
        [IO.File]::WriteAllText((Join-Path $directory "automation.toml"), "id = `"$id`"`nstatus = `"PAUSED`"`n")
    }
    return [pscustomobject]@{root=$Root;repo=$repo;installer=$copyInstaller;coordinator=$coordinator;validator=$validator;
        promoter=$promoter;registry=$registryPath;receipt=$receiptPath;parent_registry=$parentRegistryPath;parent_receipt=$parentReceiptPath;
        legacy=$legacy;commit=$commit;state=$statePath}
}

function Invoke-FixtureInstaller {
    param([object]$Fixture)
    $script:installerIntegrationCases += 1
    $arguments = @("-NoProfile","-NonInteractive","-ExecutionPolicy","Bypass","-File",$Fixture.installer,"-DryRun","-Json",
        "-RegistryPath",$Fixture.registry,"-ReceiptPath",$Fixture.receipt,
        "-ExpectedRegistrySha256",(Get-FixtureSha $Fixture.registry),"-ExpectedReceiptSha256",(Get-FixtureSha $Fixture.receipt),
        "-ExpectedInstallerSha256",(Get-FixtureSha $Fixture.installer),"-ExpectedCoordinatorSha256",(Get-FixtureSha $Fixture.coordinator),
        "-ExpectedValidatorSha256",(Get-FixtureSha $Fixture.validator),"-ExpectedControlPlaneGitCommit",$Fixture.commit,
        "-CodexAutomationsRoot",$Fixture.legacy)
    $output = & $pwsh @arguments 2>&1 | Out-String
    $exitCode = $LASTEXITCODE
    try { $payload = $output | ConvertFrom-Json -DateKind String -ErrorAction Stop }
    catch { throw "installer fixture produced invalid JSON (exit $exitCode): $output" }
    Assert-True (-not (Test-Path -LiteralPath (Join-Path $Fixture.root "worker.marker"))) "installer dry-run executed ScheduledTick with due state"
    return [pscustomobject]@{exit_code=$exitCode;payload=$payload}
}

function Set-FixtureReceipt {
    param([object]$Fixture, [scriptblock]$Mutation)
    $receipt = Get-Content -LiteralPath $Fixture.receipt -Raw | ConvertFrom-Json -AsHashtable
    & $Mutation $receipt
    Write-FixtureJson $Fixture.receipt $receipt
}

function Set-FixtureCleanFilteredDrift {
    param([object]$Fixture, [string]$RelativePath)
    $git = "C:\Program Files\Git\cmd\git.exe"
    $target = Join-Path $Fixture.repo $RelativePath
    $before = Get-FixtureSha $target
    $filterCommand = '"C:/Program Files/Git/cmd/git.exe" cat-file blob ' + $Fixture.commit + ':' + $RelativePath
    & $git -C $Fixture.repo config filter.installer_exact_bytes.clean $filterCommand
    Assert-True ($LASTEXITCODE -eq 0) "fixture clean filter configuration failed"
    & $git -C $Fixture.repo config filter.installer_exact_bytes.required true
    Assert-True ($LASTEXITCODE -eq 0) "fixture required filter configuration failed"
    [IO.File]::WriteAllText((Join-Path $Fixture.repo ".git\info\attributes"), "$RelativePath -text filter=installer_exact_bytes`n")
    [IO.File]::AppendAllText($target, "`n# rehashed uncommitted bytes hidden by a Git clean filter`n")
    $after = Get-FixtureSha $target
    Assert-True ($before -cne $after) "fixture failed to change the raw worktree bytes"
    & $git -C $Fixture.repo diff --quiet $Fixture.commit -- $RelativePath
    Assert-True ($LASTEXITCODE -eq 0) "fixture did not reproduce the clean-filter Git diff bypass"
    return $after
}

$source = Get-Content -Raw -LiteralPath $installerPath
Assert-True ($source -match 'ExpectedReceiptSha256') "installer does not bind receipt SHA"
Assert-True ($source -match 'ExpectedInstallerSha256') "installer does not bind its own SHA"
Assert-True ($source -match 'ExpectedValidatorSha256') "installer does not bind validator SHA"
Assert-True ($source -match 'ExpectedControlPlaneGitCommit') "installer does not bind control-plane commit"
Assert-True ($source -match 'GetFinalPathNameByHandle') "installer does not resolve physical paths"
Assert-True ($source -match 'materialization_receipt\.v2') "installer does not require the materialization receipt"
Assert-True ($source -match 'canonical_strategy_runtime\.json') "installer does not require the canonical registry filename"
Assert-True ($source -match 'materialization_receipt\.json') "installer does not require the canonical receipt filename"
Assert-True ($source -match 'Assert-ControlPlaneBinding') "installer does not recheck the committed trust root"
Assert-True ($source -match 'Assert-PublicationBinding') "installer does not recheck the publication pair"
Assert-True ($source -notmatch '\[string\]\$CoordinatorPath') "production installer accepts a coordinator override"

$tokens = $null
$parseErrors = $null
$installerAst = [System.Management.Automation.Language.Parser]::ParseInput($source, [ref]$tokens, [ref]$parseErrors)
Assert-True ($parseErrors.Count -eq 0) "installer contains syntax errors"
$resolver = $installerAst.Find({param($node) $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -ceq "Resolve-InstallAutomationRoot"}, $true)
Assert-True ($null -ne $resolver) "installer has no fail-closed legacy-root resolver"
. ([scriptblock]::Create($resolver.Extent.Text))
$canonicalLegacyRoot = Join-Path ([Environment]::GetFolderPath([Environment+SpecialFolder]::UserProfile)) ".codex\automations"
$fixtureLegacyOverride = Join-Path ([IO.Path]::GetTempPath()) "installer-legacy-override-uncreated"
Assert-True ((Resolve-InstallAutomationRoot -RequestedRoot "" -AllowTestOverride $false) -ceq $canonicalLegacyRoot) "installer default legacy root is not canonical"
Assert-True ((Resolve-InstallAutomationRoot -RequestedRoot $fixtureLegacyOverride -AllowTestOverride $true) -ceq $fixtureLegacyOverride) "dry-run fixture legacy root was rejected"
$rootError = $null
try { Resolve-InstallAutomationRoot -RequestedRoot $fixtureLegacyOverride -AllowTestOverride $false | Out-Null } catch { $rootError = $_.Exception.Message }
Assert-True ($rootError -ceq "LEGACY_AUTOMATIONS_OVERRIDE_REQUIRES_DRY_RUN") "real install accepts an unbound legacy topology root"

$tempRoot = Join-Path ([IO.Path]::GetTempPath()) ("listing-installer-path-override-" + [Guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $tempRoot | Out-Null
try {
    $fakeCoordinator = Join-Path $tempRoot "fake-coordinator.ps1"
    $marker = Join-Path $tempRoot "executed.marker"
    "[IO.File]::WriteAllText('$($marker.Replace("'", "''"))','executed')" | Set-Content -LiteralPath $fakeCoordinator -Encoding utf8NoBOM
    $arguments = @(
        "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", $installerPath,
        "-DryRun", "-Json",
        "-RegistryPath", (Join-Path $tempRoot "missing-registry.json"),
        "-ReceiptPath", (Join-Path $tempRoot "missing-receipt.json"),
        "-ExpectedRegistrySha256", ("0" * 64),
        "-ExpectedReceiptSha256", ("0" * 64),
        "-ExpectedInstallerSha256", ("0" * 64),
        "-ExpectedCoordinatorSha256", ("0" * 64),
        "-ExpectedValidatorSha256", ("0" * 64),
        "-ExpectedControlPlaneGitCommit", ("0" * 40),
        "-CoordinatorPath", $fakeCoordinator
    )
    $output = & $pwsh @arguments 2>&1 | Out-String
    $exitCode = $LASTEXITCODE
    Assert-True ($exitCode -ne 0) "arbitrary CoordinatorPath override was accepted"
    Assert-True (-not (Test-Path -LiteralPath $marker)) "arbitrary coordinator was executed"
    Assert-True ($output -match 'CoordinatorPath') "parameter-binding rejection did not identify CoordinatorPath"

    # Run the actual topology read/recheck statements with a deterministic race:
    # the old second read sees ACTIVE after the first read parsed PAUSED.
    $legacySnapshotRace = & {
        $CodexAutomationsRoot = Join-Path $tempRoot "legacy-snapshot-race"
        $legacyAutomationIds = @("zolotyaylopata-listing-momentum-monitor")
        $legacyRecords = [Collections.Generic.List[object]]::new()
        $legacyErrors = [Collections.Generic.List[string]]::new()
        $directory = Join-Path $CodexAutomationsRoot $legacyAutomationIds[0]
        New-Item -ItemType Directory -Path $directory -Force | Out-Null
        $legacyRacePath = Join-Path $directory "automation.toml"
        $pausedToml = "id = `"$($legacyAutomationIds[0])`"`nstatus = `"PAUSED`"`n"
        $activeToml = "id = `"$($legacyAutomationIds[0])`"`nstatus = `"ACTIVE`"`n"
        [IO.File]::WriteAllText($legacyRacePath, $pausedToml)
        function Get-RawSha256 {
            param([string]$Path)
            [IO.File]::WriteAllText($legacyRacePath, $activeToml)
            return Get-FixtureSha $Path
        }
        $reader = $installerAst.Find({param($node) $node -is [System.Management.Automation.Language.ForEachStatementAst] -and $node.Variable.VariablePath.UserPath -ceq "automationId"}, $true)
        $recheck = $installerAst.Find({param($node) $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -ceq "Assert-LegacyAutomationSnapshot"}, $true)
        Assert-True ($null -ne $reader -and $null -ne $recheck) "installer legacy snapshot statements are missing"
        . ([scriptblock]::Create($reader.Extent.Text))
        . ([scriptblock]::Create($recheck.Extent.Text))
        Assert-True ($legacyErrors.Count -eq 0 -and $legacyRecords[0].status -ceq "PAUSED") "fixture did not parse the initial PAUSED snapshot"
        [IO.File]::WriteAllText($legacyRacePath, $activeToml)
        $snapshotError = $null
        try { Assert-LegacyAutomationSnapshot } catch { $snapshotError = $_.Exception.Message }
        return [pscustomobject]@{error=$snapshotError;status=$legacyRecords[0].status}
    }
    Assert-True ($legacySnapshotRace.error -ceq "LEGACY_AUTOMATION_CONFIG_CHANGED:zolotyaylopata-listing-momentum-monitor") "legacy PAUSED parse + ACTIVE hash passed final topology check"
    $cleanFilterFailures = [Collections.Generic.List[string]]::new()
    foreach ($case in @(
        @{role="coordinator";relative="tools/invoke_listing_strategy_due_coordinator.ps1";reason="COORDINATOR_WORKTREE_DIFFERS_FROM_COMMIT"},
        @{role="installer";relative="tools/install_listing_strategy_due_coordinator_task.ps1";reason="INSTALLER_WORKTREE_DIFFERS_FROM_COMMIT"},
        @{role="validator";relative="trading_mvp/src/canonical_strategy_runtime.py";reason="VALIDATOR_WORKTREE_DIFFERS_FROM_COMMIT"},
        @{role="promoter";relative="trading_mvp/src/external_registry_promoter.py";reason="CONTROL_BINDING_WORKTREE_DIFFERS_FROM_COMMIT:promoter"},
        @{role="publication_primitive";relative="trading_mvp/src/external_registry_materializer.py";reason="CONTROL_BINDING_WORKTREE_DIFFERS_FROM_COMMIT:publication_primitive"}
    )) {
        $filtered = New-InstallerFixture -Root (Join-Path $tempRoot ("filtered-" + $case.role))
        $filteredSha = Set-FixtureCleanFilteredDrift -Fixture $filtered -RelativePath $case.relative
        Set-FixtureReceipt $filtered {param($r) ($r.control_bindings | Where-Object role -eq $case.role).head_sha256=$filteredSha}
        $filteredResult = Invoke-FixtureInstaller $filtered
        $preflightExecuted = Test-Path -LiteralPath (Join-Path $filtered.root "preflight.marker")
        if ($filteredResult.exit_code -eq 0 -or $filteredResult.payload.status -cne "BLOCKED_INSTALL_BINDING" -or $filteredResult.payload.reason -cne $case.reason -or $preflightExecuted) {
            $cleanFilterFailures.Add("$($case.role):status=$($filteredResult.payload.status),reason=$($filteredResult.payload.reason),preflight_executed=$preflightExecuted")
        }
    }
    $filteredStaging = New-InstallerFixture -Root (Join-Path $tempRoot "filtered-staging-materializer") -Active $false
    $filteredStagingSha = Set-FixtureCleanFilteredDrift -Fixture $filteredStaging -RelativePath "trading_mvp/src/external_registry_materializer.py"
    Set-FixtureReceipt $filteredStaging {param($r) $r.materializer_head_sha256=$filteredStagingSha}
    $filteredStagingResult = Invoke-FixtureInstaller $filteredStaging
    $stagingPreflightExecuted = Test-Path -LiteralPath (Join-Path $filteredStaging.root "preflight.marker")
    if ($filteredStagingResult.exit_code -eq 0 -or $filteredStagingResult.payload.status -cne "BLOCKED_INSTALL_BINDING" -or $filteredStagingResult.payload.reason -cne "MATERIALIZER_WORKTREE_DIFFERS_FROM_COMMIT" -or $stagingPreflightExecuted) {
        $cleanFilterFailures.Add("staging_materializer:status=$($filteredStagingResult.payload.status),reason=$($filteredStagingResult.payload.reason),preflight_executed=$stagingPreflightExecuted")
    }
    Assert-True ($cleanFilterFailures.Count -eq 0) ("installer trusted clean-filtered uncommitted bytes: " + ($cleanFilterFailures -join "; "))

    $active = New-InstallerFixture -Root (Join-Path $tempRoot "active")
    $activeResult = Invoke-FixtureInstaller $active
    Assert-True ($activeResult.exit_code -eq 0 -and $activeResult.payload.status -ceq "ACTIVE_DRY_RUN_OK") "ACTIVE installer dry-run was not accepted: $($activeResult.payload | ConvertTo-Json -Compress -Depth 10)"
    Assert-True ($activeResult.payload.execution_performed -eq $false -and $activeResult.payload.registration_attempted -eq $false) "ACTIVE dry-run performed execution or registration"
    Assert-True ((Get-Content -LiteralPath (Join-Path $active.root "preflight.marker") -Raw) -ceq "PreflightOnly") "installer did not use read-only preflight"
    Assert-True ($activeResult.payload.action_arguments -match '-ScheduledTick' -and $activeResult.payload.action_arguments -notmatch '-PreflightOnly') "installed action is not a scheduled tick"
    Write-FixtureJson $active.state @{status="RETRY_NEXT_INTERVAL";next_interval_at_utc="2030-01-01T00:00:00Z"}
    $evolvedState = Invoke-FixtureInstaller $active
    Assert-True ($evolvedState.exit_code -eq 0 -and $evolvedState.payload.status -ceq "ACTIVE_DRY_RUN_OK") "promotion snapshot hash incorrectly freezes the mutable runtime state"
    $validReceipt = [IO.File]::ReadAllBytes($active.receipt)
    foreach ($test in @(
        @{name="promoter hash";reason="CONTROL_BINDING_SHA256_MISMATCH:promoter";mutate={param($r) ($r.control_bindings | Where-Object role -eq "promoter").head_sha256="0" * 64}},
        @{name="duplicate control role";reason="CONTROL_BINDING_ROLE_SET_INVALID";mutate={param($r) $r.control_bindings+=@($r.control_bindings[0])}},
        @{name="live mode";reason="ACTIVE_POLICY_INVALID";mutate={param($r) $r.policy_evidence.allowed_modes=@("LIVE")}},
        @{name="string boolean";reason="RECEIPT_STATUS_INVALID";mutate={param($r) $r.launch_allowed="true"}},
        @{name="parent hash";reason="PARENT_REGISTRY_SHA256_MISMATCH";mutate={param($r) $r.parent_lineage.registry_raw_sha256="0" * 64}},
        @{name="parent commit";reason="PARENT_LINEAGE_COMMIT_MISMATCH";mutate={param($r) $r.parent_lineage.source_git_commit="0" * 40}},
        @{name="active launcher lineage";reason="ACTIVE_RUNTIME_BINDING_MISMATCH:launcher_sha256";mutate={param($r) $r.active_runtime_binding.launcher_sha256="0" * 64}},
        @{name="unknown receipt field";reason="ACTIVE_RECEIPT_FIELDS_INVALID";mutate={param($r) $r.unsafe_extension=$true}}
    )) {
        [IO.File]::WriteAllBytes($active.receipt, $validReceipt)
        Set-FixtureReceipt $active $test.mutate
        $blocked = Invoke-FixtureInstaller $active
        Assert-True ($blocked.exit_code -ne 0 -and $blocked.payload.status -ceq "BLOCKED_INSTALL_BINDING" -and $blocked.payload.reason -ceq $test.reason) "negative case '$($test.name)' did not fail closed: $($blocked.payload | ConvertTo-Json -Compress -Depth 10)"
    }
    [IO.File]::WriteAllBytes($active.receipt, $validReceipt)
    $promoterBefore = [IO.File]::ReadAllBytes($active.promoter)
    [IO.File]::AppendAllText($active.promoter, "# uncommitted drift`n")
    $driftSha = Get-FixtureSha $active.promoter
    Set-FixtureReceipt $active {param($r) ($r.control_bindings | Where-Object role -eq "promoter").head_sha256=$driftSha}
    $uncommittedPromoter = Invoke-FixtureInstaller $active
    Assert-True ($uncommittedPromoter.payload.status -ceq "BLOCKED_INSTALL_BINDING" -and $uncommittedPromoter.payload.reason -ceq "CONTROL_BINDING_WORKTREE_DIFFERS_FROM_COMMIT:promoter") "installer accepted a rehashed but uncommitted promoter"
    [IO.File]::WriteAllBytes($active.promoter, $promoterBefore)
    [IO.File]::WriteAllBytes($active.receipt, $validReceipt)
    $validParentReceipt = [IO.File]::ReadAllBytes($active.parent_receipt)
    $parentEvidence = Get-Content -LiteralPath $active.parent_receipt -Raw | ConvertFrom-Json -AsHashtable
    $parentEvidence.source_head_sha256="0" * 64
    Write-FixtureJson $active.parent_receipt $parentEvidence
    $forgedParentSha = Get-FixtureSha $active.parent_receipt
    Set-FixtureReceipt $active {param($r) $r.parent_lineage.source_head_sha256="0" * 64; $r.parent_lineage.receipt_raw_sha256=$forgedParentSha}
    $forgedHistory = Invoke-FixtureInstaller $active
    Assert-True ($forgedHistory.payload.status -ceq "BLOCKED_INSTALL_BINDING" -and $forgedHistory.payload.reason -ceq "PARENT_LINEAGE_HISTORICAL_SHA256_MISMATCH:source") "installer trusted self-consistent but forged historical source SHA"
    [IO.File]::WriteAllBytes($active.parent_receipt, $validParentReceipt)
    [IO.File]::WriteAllBytes($active.receipt, $validReceipt)
    Write-FixtureJson (Join-Path $active.root "preflight-override.json") @{execution_performed=$true}
    $executingPreflight = Invoke-FixtureInstaller $active
    Assert-True ($executingPreflight.payload.status -ceq "BLOCKED_COORDINATOR_PREFLIGHT") "installer trusted a preflight that reported execution"
    Write-FixtureJson (Join-Path $active.root "preflight-override.json") @{execution_performed=$false;active_strategy_id="other_strategy"}
    $wrongStrategy = Invoke-FixtureInstaller $active
    Assert-True ($wrongStrategy.payload.status -ceq "BLOCKED_COORDINATOR_PREFLIGHT") "installer accepted wrong active strategy from coordinator"
    Write-FixtureJson (Join-Path $active.root "preflight-override.json") @{}
    $validParentRegistry = [IO.File]::ReadAllBytes($active.parent_registry)
    Write-FixtureJson (Join-Path $active.root "mutation.json") @{path=$active.parent_registry;append=" "}
    $changedParent = Invoke-FixtureInstaller $active
    Assert-True ($changedParent.payload.status -ceq "BLOCKED_INSTALL_INPUT_CHANGED" -and $changedParent.payload.reason -ceq "PARENT_REGISTRY_SHA256_MISMATCH") "installer did not recheck parent lineage after coordinator preflight"
    [IO.File]::WriteAllBytes($active.parent_registry, $validParentRegistry)
    $activeLegacyPath = Join-Path $active.legacy "zolotyaylopata-listing-momentum-monitor\automation.toml"
    Write-FixtureJson (Join-Path $active.root "mutation.json") @{path=$activeLegacyPath;append="status = `"ACTIVE`"`n"}
    $changedLegacy = Invoke-FixtureInstaller $active
    Assert-True ($changedLegacy.payload.status -ceq "BLOCKED_INSTALL_INPUT_CHANGED" -and $changedLegacy.payload.reason -ceq "LEGACY_AUTOMATION_CONFIG_CHANGED:zolotyaylopata-listing-momentum-monitor") "installer trusted a legacy topology modified during preflight"

    $staging = New-InstallerFixture -Root (Join-Path $tempRoot "staging") -Active $false
    $stagingResult = Invoke-FixtureInstaller $staging
    Assert-True ($stagingResult.exit_code -eq 0 -and $stagingResult.payload.status -ceq "STAGED_FAIL_CLOSED") "staging dry-run behavior regressed: $($stagingResult.payload | ConvertTo-Json -Compress -Depth 10)"
    $legacyPath = Join-Path $staging.legacy "zolotyaylopata-listing-momentum-monitor\automation.toml"
    [IO.File]::WriteAllText($legacyPath, "id = `"zolotyaylopata-listing-momentum-monitor`"`nstatus = `"ACTIVE`"`n")
    $legacyResult = Invoke-FixtureInstaller $staging
    Assert-True ($legacyResult.payload.status -ceq "BLOCKED_LEGACY_AUTOMATIONS") "installer allowed active legacy automation"

    [ordered]@{
        status = "PASS"
        tests = 16 + $script:installerIntegrationCases
        installer_integration_cases = $script:installerIntegrationCases
        legacy_root_function_cases = 3
        legacy_snapshot_race_cases = 1
        coordinator = "committed_read_only_probe_stub"
        registration_attempted = $false
        arbitrary_coordinator_executed = $false
    } | ConvertTo-Json -Compress
} finally {
    if (Test-Path -LiteralPath $tempRoot) {
        $resolved = (Resolve-Path -LiteralPath $tempRoot).Path
        $tempBase = (Resolve-Path -LiteralPath ([IO.Path]::GetTempPath())).Path.TrimEnd('\', '/') + [IO.Path]::DirectorySeparatorChar
        if (-not $resolved.StartsWith($tempBase, [StringComparison]::OrdinalIgnoreCase)) {
            throw "refusing to remove temp path outside system temp: $resolved"
        }
        Remove-Item -LiteralPath $resolved -Recurse -Force
    }
}

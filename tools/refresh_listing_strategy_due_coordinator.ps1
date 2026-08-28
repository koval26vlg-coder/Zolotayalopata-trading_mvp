param(
    [switch]$Apply,
    [string]$PublicationRoot = "",
    [string]$ActivePublicationRoot = "",
    [string]$ActiveStrategyId = "",
    [switch]$Json
)

# Re-bind the due coordinator to the current committed state of this repository.
#
# The installed scheduled task carries the control-plane commit it was registered
# against, and the coordinator refuses to run when the repository has moved past it -
# CONTROL_PLANE_COMMIT_MISMATCH, exit 2. That refusal is correct: the task must run the
# control plane someone reviewed, not whatever happens to be checked out. Its practical
# consequence is easy to miss, though. Every commit to this repository - including one
# that touches nothing the coordinator reads - puts the task back into fail-closed
# refusal until it is re-registered, and the task keeps waking every five minutes and
# failing quietly while that is true.
#
# So the recovery is one command rather than a remembered sequence of four. It
# materialises a publication from the committed registry at HEAD, promotes it to the
# active registry, and re-registers the task against that.
#
# **The promotion step is not optional, and this script used to omit it.** A materialised
# publication validates as STAGED_FAIL_CLOSED: every binding matches and no runtime is
# routable, which is correct - activating a runtime is a decision, not a side effect of
# publishing. Installing that publication leaves a task that runs, refuses to route, and
# reports success, which is the worst of the three outcomes because nothing complains.
# Which runtime is active is therefore carried over from the installed task rather than
# guessed: re-binding after a commit must not silently change what is running.
#
# **Without -Apply this writes nothing at all.** It used to materialise in both modes,
# so a dry run published, and the -Apply that followed died on publication_already_exists
# against the artifact its own dry run had just created. A dry run that has to be
# recovered from is not a dry run.
#
# It refuses when any file the publication binds has uncommitted edits. The check is
# deliberately narrow rather than a whole-tree cleanliness demand: seven run-gate state
# files in this repository are modified by every wake, so a whole-tree guard would refuse
# always and be worked around within a day. What must be clean is what gets bound.

$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$gitExe = "C:\Program Files\Git\cmd\git.exe"
if (-not (Test-Path -LiteralPath $gitExe)) { throw "Git not found at $gitExe" }

function Resolve-PythonExecutable {
    # Absolute paths only: an interpreter taken from PATH is chosen by whatever is
    # earliest on it, which is not a decision the control plane should delegate.
    if ($env:PYTHON_EXE -and (Test-Path -LiteralPath $env:PYTHON_EXE)) { return $env:PYTHON_EXE }
    foreach ($candidate in @(
        "C:\Program Files\Python313\python.exe",
        "C:\Users\koval\AppData\Local\Programs\Python\Python313\python.exe"
    )) {
        if (Test-Path -LiteralPath $candidate) { return $candidate }
    }
    throw "Python executable not found; set PYTHON_EXE to an absolute path"
}

function Get-RawSha256([string]$Path) {
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

function Get-InstalledActiveStrategyId {
    # The installed action carries -RegistryPath into the active publication it was
    # registered against. Reading the id back out of that registry is what makes a
    # re-bind preserve the activation instead of re-deciding it.
    $task = Get-ScheduledTask -TaskName "ZolotyayLopata Listing Strategy Due Coordinator" -ErrorAction SilentlyContinue
    if (-not $task) { return $null }
    foreach ($action in $task.Actions) {
        $match = [regex]::Match([string]$action.Arguments, '-RegistryPath\s+"([^"]+)"')
        if (-not $match.Success) { continue }
        $registryPath = $match.Groups[1].Value
        if (-not (Test-Path -LiteralPath $registryPath)) { continue }
        $payload = Get-Content -LiteralPath $registryPath -Raw -Encoding UTF8 | ConvertFrom-Json
        $id = [string]$payload.active_strategy_id
        if (-not [string]::IsNullOrWhiteSpace($id)) { return $id }
    }
    return $null
}

$boundRelativePaths = @(
    "docs/control/canonical_strategy_runtime.staging.json",
    "trading_mvp/src/external_registry_materializer.py",
    "trading_mvp/src/external_registry_promoter.py",
    "trading_mvp/src/canonical_strategy_runtime.py",
    "tools/invoke_listing_strategy_due_coordinator.ps1",
    "tools/install_listing_strategy_due_coordinator_task.ps1"
)
$dirty = & $gitExe -C $repoRoot status --porcelain --untracked-files=no -- @boundRelativePaths
if ($LASTEXITCODE -ne 0) { throw "git status failed" }
if ($dirty) {
    throw ("these bound control-plane files have uncommitted edits; commit them before re-binding: " + ($dirty -join "; "))
}
$commit = (& $gitExe -C $repoRoot rev-parse HEAD).Trim()

if (-not $PublicationRoot) {
    $PublicationRoot = Join-Path $env:LOCALAPPDATA "ZolotyayLopata\control-plane\canonical-registry"
}
if (-not $ActivePublicationRoot) {
    $ActivePublicationRoot = Join-Path $env:LOCALAPPDATA "ZolotyayLopata\control-plane\active-registry"
}

$source      = Join-Path $repoRoot "docs\control\canonical_strategy_runtime.staging.json"
$materializer= Join-Path $repoRoot "trading_mvp\src\external_registry_materializer.py"
$promoter    = Join-Path $repoRoot "trading_mvp\src\external_registry_promoter.py"
$validator   = Join-Path $repoRoot "trading_mvp\src\canonical_strategy_runtime.py"
$installer   = Join-Path $repoRoot "tools\install_listing_strategy_due_coordinator_task.ps1"
$coordinator = Join-Path $repoRoot "tools\invoke_listing_strategy_due_coordinator.ps1"

if (-not $ActiveStrategyId) {
    $ActiveStrategyId = Get-InstalledActiveStrategyId
}
if (-not $ActiveStrategyId) {
    throw ("no runtime is currently active and none was named; pass -ActiveStrategyId. " +
           "Activating a runtime for the first time is a decision, so it is not defaulted.")
}

if (-not $Apply) {
    $report = [ordered]@{
        status               = "DRY_RUN_NO_WRITES"
        commit               = $commit
        active_strategy_id   = $ActiveStrategyId
        source_sha256        = (Get-RawSha256 $source)
        publication_root     = $PublicationRoot
        active_root          = $ActivePublicationRoot
        bound_files_clean    = $true
        would                = @("materialize", "promote", "install")
    }
    if ($Json) {
        $report | ConvertTo-Json -Depth 6
    } else {
        Write-Host "=== Listing strategy due coordinator: re-bind (dry run) ===" -ForegroundColor Cyan
        Write-Host ("commit        : " + $commit)
        Write-Host ("active runtime: " + $ActiveStrategyId + "  (carried over from the installed task)")
        Write-Host ("source sha256 : " + $report.source_sha256)
        Write-Host ("would         : materialize -> promote -> install")
        Write-Host ""
        Write-Host "nothing written; re-run with -Apply" -ForegroundColor Green
    }
    exit 0
}

$pythonExe = Resolve-PythonExecutable
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUTF8 = "1"

if (-not (Test-Path -LiteralPath $PublicationRoot)) {
    New-Item -ItemType Directory -Force -Path $PublicationRoot | Out-Null
}

$sourceSha = Get-RawSha256 $source

# A publication is immutable and addressed by its content, so materialising the same
# registry at the same commit twice is refused rather than repeated. Look for the one
# already published before asking for another, so that running this command twice is a
# no-op instead of a dead end - which matters, because the point of the command is that
# somebody under time pressure can re-run it without thinking.
#
# Identified from the receipt rather than from the refusal message: the message arrives
# inside a Python traceback that the console wraps, and a path read back out of wrapped
# text is a path that will one day be wrong.
$reusedPublication = $false
$publication = $null
foreach ($directory in Get-ChildItem -LiteralPath $PublicationRoot -Directory -ErrorAction SilentlyContinue) {
    $receiptFile = Join-Path $directory.FullName "materialization_receipt.json"
    if (-not (Test-Path -LiteralPath $receiptFile)) { continue }
    try {
        $existing = Get-Content -LiteralPath $receiptFile -Raw -Encoding UTF8 | ConvertFrom-Json
    } catch { continue }
    if ([string]$existing.source_git_commit -cne $commit) { continue }
    if ([string]$existing.source_head_sha256 -cne $sourceSha) { continue }
    $publication = [pscustomobject]@{
        publication_id = [string]$existing.publication_id
        registry_path  = [string]$existing.registry_path
        receipt_path   = [string]$existing.receipt_path
    }
    $reusedPublication = $true
    break
}

if (-not $publication) {
    $materializeInput = [ordered]@{
        source_path                      = $source
        publication_root                 = $PublicationRoot
        expected_source_head_sha256      = $sourceSha
        expected_materializer_head_sha256= (Get-RawSha256 $materializer)
        expected_validator_head_sha256   = (Get-RawSha256 $validator)
        expected_control_plane_git_commit= $commit
    }
    $inputPath = Join-Path ([IO.Path]::GetTempPath()) ("coordinator-refresh-" + [guid]::NewGuid().ToString("N") + ".json")
    $materializeInput | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $inputPath -Encoding UTF8

    $code = 'import json,sys; sys.path.insert(0, sys.argv[1]); from external_registry_materializer import materialize_external_registry; print(json.dumps(materialize_external_registry(**json.load(open(sys.argv[2], encoding="utf-8-sig")))))'
    try {
        $raw = & $pythonExe -B -c $code (Join-Path $repoRoot "trading_mvp\src") $inputPath 2>&1 | Out-String
        if ($LASTEXITCODE -ne 0) { throw "materialization failed: $raw" }
    } finally {
        Remove-Item -LiteralPath $inputPath -Force -ErrorAction SilentlyContinue
    }
    $publication = $raw | ConvertFrom-Json
}

$parentRegistry = [string]$publication.registry_path
$parentReceipt  = [string]$publication.receipt_path

# Promote. A materialised publication is STAGED_FAIL_CLOSED by construction; this is the
# step that produces something the coordinator may actually route.
$stamp = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
$promoteRaw = & $pythonExe -B $promoter --promote `
    --parent-registry $parentRegistry `
    --parent-receipt $parentReceipt `
    --publication-root $ActivePublicationRoot `
    --active-strategy-id $ActiveStrategyId `
    --generated-at-utc $stamp `
    --expected-parent-registry-raw-sha256 (Get-RawSha256 $parentRegistry) `
    --expected-parent-receipt-raw-sha256 (Get-RawSha256 $parentReceipt) `
    --expected-promoter-head-sha256 (Get-RawSha256 $promoter) `
    --expected-validator-head-sha256 (Get-RawSha256 $validator) `
    --expected-publication-primitive-head-sha256 (Get-RawSha256 $materializer) `
    --expected-coordinator-head-sha256 (Get-RawSha256 $coordinator) `
    --expected-installer-head-sha256 (Get-RawSha256 $installer) `
    --expected-control-plane-git-commit $commit `
    --json 2>&1 | Out-String
if ($LASTEXITCODE -ne 0) {
    # The promoter reads the active runtime's state file. After a plan change that file is
    # archived deliberately - a new plan does not inherit the previous plan's attempts -
    # and it has to be re-created before anything can be promoted against it.
    if ($promoteRaw -match "active_state_read_failed") {
        throw ("promotion failed because the active runtime has no state file. After a plan " +
               "change the order is: archive the state directory, run the runtime's " +
               "--launch-probe to re-create it, then re-run this. Raw: " + $promoteRaw)
    }
    throw ("promotion failed: " + $promoteRaw)
}
$active = $promoteRaw | ConvertFrom-Json
$registry = [string]$active.registry_path
$receipt  = [string]$active.receipt_path

$installArguments = @{
    RegistryPath                  = $registry
    ReceiptPath                   = $receipt
    ExpectedRegistrySha256        = (Get-RawSha256 $registry)
    ExpectedReceiptSha256         = (Get-RawSha256 $receipt)
    ExpectedInstallerSha256       = (Get-RawSha256 $installer)
    ExpectedCoordinatorSha256     = (Get-RawSha256 $coordinator)
    ExpectedValidatorSha256       = (Get-RawSha256 $validator)
    ExpectedControlPlaneGitCommit = $commit
    Json                          = $true
}

if (-not $Json) {
    Write-Host "=== Listing strategy due coordinator: re-bind ===" -ForegroundColor Cyan
    Write-Host ("commit        : " + $commit)
    Write-Host ("publication   : " + $publication.publication_id + $(if ($reusedPublication) { "  (reused)" } else { "" }))
    Write-Host ("active        : " + $active.publication_id)
    Write-Host ("runtime       : " + $ActiveStrategyId)
    Write-Host ("decision      : " + $active.decision + "  launch_allowed=" + $active.launch_allowed)
    Write-Host ""
}

& $installer @installArguments
$installExit = [int]$LASTEXITCODE

if (-not $Json) {
    Write-Host ""
    if ($installExit -eq 0) {
        Write-Host "task re-registered" -ForegroundColor Green
    } else {
        Write-Host ("installer refused (exit " + $installExit + ")") -ForegroundColor Yellow
    }
}

exit $installExit

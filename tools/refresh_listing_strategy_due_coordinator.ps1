param(
    [switch]$Apply,
    [string]$PublicationRoot = "",
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
# So the recovery is one command rather than a remembered sequence of three. It
# materialises a fresh publication from the committed registry at HEAD and re-registers
# the task against it. Without -Apply it only reports what it would do.
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

$boundRelativePaths = @(
    "docs/control/canonical_strategy_runtime.staging.json",
    "trading_mvp/src/external_registry_materializer.py",
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
if (-not (Test-Path -LiteralPath $PublicationRoot)) {
    New-Item -ItemType Directory -Force -Path $PublicationRoot | Out-Null
}

$source      = Join-Path $repoRoot "docs\control\canonical_strategy_runtime.staging.json"
$materializer= Join-Path $repoRoot "trading_mvp\src\external_registry_materializer.py"
$validator   = Join-Path $repoRoot "trading_mvp\src\canonical_strategy_runtime.py"
$installer   = Join-Path $repoRoot "tools\install_listing_strategy_due_coordinator_task.ps1"
$coordinator = Join-Path $repoRoot "tools\invoke_listing_strategy_due_coordinator.ps1"

$pythonExe = Resolve-PythonExecutable
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUTF8 = "1"

$materializeInput = [ordered]@{
    source_path                      = $source
    publication_root                 = $PublicationRoot
    expected_source_head_sha256      = (Get-RawSha256 $source)
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
$registry = [string]$publication.registry_path
$receipt  = [string]$publication.receipt_path

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
if (-not $Apply) { $installArguments["DryRun"] = $true }

if (-not $Json) {
    Write-Host "=== Listing strategy due coordinator: re-bind ===" -ForegroundColor Cyan
    Write-Host ("commit        : " + $commit)
    Write-Host ("publication   : " + $publication.publication_id)
    Write-Host ("decision      : " + $publication.decision + "  launch_allowed=" + $publication.launch_allowed)
    Write-Host ("mode          : " + $(if ($Apply) { "APPLY" } else { "DRY-RUN" }))
    Write-Host ""
}

& $installer @installArguments
$installExit = [int]$LASTEXITCODE

if (-not $Json) {
    Write-Host ""
    if ($installExit -eq 0) {
        Write-Host ($(if ($Apply) { "task re-registered" } else { "dry run clean; re-run with -Apply" })) -ForegroundColor Green
    } else {
        Write-Host ("installer refused (exit " + $installExit + ")") -ForegroundColor Yellow
    }
}

exit $installExit

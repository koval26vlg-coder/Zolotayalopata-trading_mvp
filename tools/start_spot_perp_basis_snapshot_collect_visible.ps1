[CmdletBinding()]
param(
    [double]$Hours = 72,
    [int]$IntervalSec = 300,
    [int]$TimeoutSec = 10,
    [int]$DepthLimit = 5,
    [string]$Bases = "AERO,B,BAS,BIRB,DEEP,ESPORTS",
    [string]$OutputRoot = "E:\trading_mvp\spot-perp-basis-snapshots",
    [string]$RunId = "",
    [string]$PreflightPath = "",
    [string]$GatePath = "",
    [int]$MaxCycles = 0,
    [switch]$ConfirmedSpotPerpBasisCollect,
    [switch]$Resume,
    [switch]$PlanOnly,
    [switch]$Json,
    [switch]$NoPause
)

$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$gateChecker = Join-Path $repoRoot "tools\check_active_run_gate.ps1"
if (-not $GatePath) { $GatePath = Join-Path $repoRoot "docs\agent-log\active-run-gate.json" }
$collectorModule = Join-Path $repoRoot "trading_mvp\src\spot_perp_basis_snapshot_collector.py"

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

function Write-JsonAtomic {
    param(
        [Parameter(Mandatory = $true)]$Object,
        [Parameter(Mandatory = $true)][string]$Path
    )

    $tempPath = "$Path.tmp.$PID.$([DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds())"
    try {
        $Object | ConvertTo-Json -Depth 24 | Set-Content -LiteralPath $tempPath -Encoding UTF8
        Move-Item -LiteralPath $tempPath -Destination $Path -Force
    } finally {
        Remove-Item -LiteralPath $tempPath -Force -ErrorAction SilentlyContinue
    }
}

function Resolve-Python {
    $candidates = @(
        $env:TRADING_MVP_PYTHON,
        "C:\Program Files\Python313\python.exe",
        "C:\Program Files\Python312\python.exe",
        "C:\Program Files\Python311\python.exe",
        "C:\Users\koval\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
    )
    foreach ($candidate in $candidates) {
        if (-not [string]::IsNullOrWhiteSpace($candidate) -and (Test-Path -LiteralPath $candidate)) {
            return $candidate
        }
    }
    $pythonCmd = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($pythonCmd) { return $pythonCmd.Source }
    $pythonCmd = Get-Command python -ErrorAction SilentlyContinue
    if ($pythonCmd) { return $pythonCmd.Source }
    throw "Python runtime not found. Set TRADING_MVP_PYTHON."
}

if (-not $PreflightPath) {
    $latest = Get-ChildItem -Path (Join-Path $repoRoot "exports\trading-mvp\analysis") -Filter "spot_perp_basis_availability_preflight_*.json" |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1
    if ($latest) { $PreflightPath = $latest.FullName }
}

$gate = & pwsh -NoProfile -ExecutionPolicy Bypass -File $gateChecker -Json | ConvertFrom-Json

if (-not $RunId) {
    if ($Resume -or [string]$gate.status -eq "STOPPED_INCOMPLETE") {
        $RunId = [string]$gate.run_id
    } else {
        $RunId = "spot_perp_basis_collect_" + (Get-Date -Format "yyyyMMdd_HHmmss")
    }
}

$runDir = Join-Path $OutputRoot $RunId
$snapshotPath = Join-Path $runDir "snapshots.jsonl"
$manifestPath = Join-Path $runDir "manifest.json"
$stdoutPath = Join-Path $runDir "stdout.log"
$stderrPath = Join-Path $runDir "stderr.log"

if ($PlanOnly) {
    $plan = [ordered]@{
        schema = "spot_perp_basis_snapshot_collect_plan_v1"
        mode = "PlanOnly"
        run_id = $RunId
        hours = $Hours
        interval_sec = $IntervalSec
        timeout_sec = $TimeoutSec
        depth_limit = $DepthLimit
        bases = $Bases
        output_root = $OutputRoot
        output_dir = $runDir
        snapshot_path = $snapshotPath
        manifest_path = $manifestPath
        preflight_path = $PreflightPath
        resume = [bool]$Resume
        command = "pwsh -NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`" -Hours $Hours -IntervalSec $IntervalSec -TimeoutSec $TimeoutSec -Bases `"$Bases`" -OutputRoot `"$OutputRoot`" -RunId $RunId -ConfirmedSpotPerpBasisCollect"
    }
    if ($Json) {
        $plan | ConvertTo-Json -Depth 12
    } else {
        Write-Host "Spot/Perp Basis Snapshot Collect PlanOnly" -ForegroundColor Cyan
        Write-Host "Run ID: $RunId"
        Write-Host "Bases: $Bases"
        Write-Host "Output: $runDir"
    }
    exit 0
}

if (-not $ConfirmedSpotPerpBasisCollect) {
    throw "ConfirmedSpotPerpBasisCollect is required to start collector. Run with -ConfirmedSpotPerpBasisCollect."
}

if ([string]$gate.status -eq "RUNNING") {
    throw "Active run gate is RUNNING: $($gate.run_id)"
}

New-Item -ItemType Directory -Force -Path $runDir | Out-Null
$python = Resolve-Python

$pythonArgs = @(
    $collectorModule,
    "--preflight", $PreflightPath,
    "--output-root", $OutputRoot,
    "--run-id", $RunId,
    "--hours", "$Hours",
    "--interval-sec", "$IntervalSec",
    "--timeout-sec", "$TimeoutSec",
    "--depth-limit", "$DepthLimit",
    "--gate-path", $GatePath,
    "--bases", $Bases
)
if ($MaxCycles -gt 0) {
    $pythonArgs += @("--max-cycles", "$MaxCycles")
}

Write-Host "=== trading_mvp visible spot/perp basis snapshot collect ===" -ForegroundColor Cyan
Write-Host "Run ID: $RunId"
Write-Host "Bases: $Bases"
Write-Host "Output dir: $runDir"
Write-Host "Snapshots: $snapshotPath"
Write-Host "Manifest: $manifestPath"
Write-Host "Stdout: $stdoutPath"
Write-Host "Stderr: $stderrPath"

$proc = Start-Process -FilePath $python -ArgumentList $pythonArgs -RedirectStandardOutput $stdoutPath -RedirectStandardError $stderrPath -PassThru

Write-Host "Collector PID: $($proc.Id)" -ForegroundColor Green

$gateDoc = Get-Content -Raw -LiteralPath $GatePath | ConvertFrom-Json
Set-JsonProperty -Object $gateDoc -Name "run_id" -Value $RunId
Set-JsonProperty -Object $gateDoc -Name "status" -Value "RUNNING"
Set-JsonProperty -Object $gateDoc -Name "gate_status" -Value "RUNNING"
Set-JsonProperty -Object $gateDoc -Name "manifest_path" -Value $manifestPath
Set-JsonProperty -Object $gateDoc -Name "output_path" -Value $snapshotPath
Set-JsonProperty -Object $gateDoc -Name "monitor_pid" -Value $PID
Set-JsonProperty -Object $gateDoc -Name "collector_pid" -Value $proc.Id
Set-JsonProperty -Object $gateDoc -Name "process_ids" -Value @($PID, $proc.Id)
Set-JsonProperty -Object $gateDoc -Name "updated_at" -Value ((Get-Date).ToString("yyyy-MM-ddTHH:mm:sszzz"))
Write-JsonAtomic -Object $gateDoc -Path $GatePath

if ($Json) {
    [ordered]@{
        schema = "spot_perp_basis_snapshot_launch_result_v1"
        decision = "VISIBLE_SNAPSHOT_COLLECTOR_LAUNCHED"
        run_id = $RunId
        worker_pid = $proc.Id
        output_dir = $runDir
        manifest_path = $manifestPath
        snapshots_path = $snapshotPath
        bases = $Bases
        hours = $Hours
        interval_sec = $IntervalSec
        visible_terminal = $true
    } | ConvertTo-Json -Depth 10
}

while (-not $proc.HasExited) {
    try {
        if (Test-Path -LiteralPath $manifestPath) {
            $m = Get-Content -Raw -LiteralPath $manifestPath | ConvertFrom-Json
            $c = [int]($m.completed_cycles ?? 0)
            $tot = [int]($m.expected_cycles ?? 1)
            $pct = if ($tot -gt 0) { [Math]::Round(($c / $tot) * 100.0, 2) } else { 0 }
            Write-Host "[$((Get-Date).ToString('yyyy-MM-dd HH:mm:ss'))] PID=$($proc.Id) cycles=$c/$tot ($pct%) rows=$($m.total_rows) errors=$($m.total_errors)"
        } else {
            Write-Host ("[{0}] PID={1} waiting for first cycle..." -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $proc.Id)
        }
        if ((Test-Path -LiteralPath $stderrPath) -and (Get-Item -LiteralPath $stderrPath).Length -gt 0) {
            Write-Host "--- stderr tail ---"
            Get-Content -LiteralPath $stderrPath -Tail 5
            Write-Host "--- end stderr tail ---"
        }
    } catch {
        Write-Host ("[{0}] monitor error: {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $_.Exception.Message)
    }
    Start-Sleep -Seconds 30
    try { $proc.Refresh() } catch {}
}

$proc.Refresh()
$exitCode = $proc.ExitCode
Write-Host "Collector process exited. ExitCode=$exitCode" -ForegroundColor Yellow

$finalStatus = if ($exitCode -eq 0) { "READY_FOR_POSTPROCESS" } else { "STOPPED_INCOMPLETE" }
try {
    if (Test-Path -LiteralPath $manifestPath) {
        $m = Get-Content -Raw -LiteralPath $manifestPath | ConvertFrom-Json
        Write-Host ("Final status: cycles={0}/{1} rows={2} errors={3}" -f $m.completed_cycles, $m.expected_cycles, $m.total_rows, $m.total_errors)
    }
} catch {}

$gateDoc = Get-Content -Raw -LiteralPath $GatePath | ConvertFrom-Json
Set-JsonProperty -Object $gateDoc -Name "status" -Value $finalStatus
Set-JsonProperty -Object $gateDoc -Name "gate_status" -Value $finalStatus
Set-JsonProperty -Object $gateDoc -Name "updated_at" -Value ((Get-Date).ToString("yyyy-MM-ddTHH:mm:sszzz"))
Set-JsonProperty -Object $gateDoc -Name "monitor_pid" -Value $null
Set-JsonProperty -Object $gateDoc -Name "collector_pid" -Value $null
Set-JsonProperty -Object $gateDoc -Name "process_ids" -Value @()
Write-JsonAtomic -Object $gateDoc -Path $GatePath

if (-not $NoPause) {
    Write-Host "Collect finished with status $finalStatus." -ForegroundColor Cyan
}

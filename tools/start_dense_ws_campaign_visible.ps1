param(
    [Parameter(Mandatory = $true)]
    [string]$PlanPath,
    [Parameter(Mandatory = $true)]
    [ValidatePattern("^[0-9a-f]{64}$")]
    [string]$ExpectedPlanHash,
    [string]$PolicyPath = "",
    [switch]$ConfirmedLongCampaign,
    [switch]$PreflightOnly,
    [switch]$Json,
    [switch]$VisibleChild,
    [string]$ReservationPath = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$runner = Join-Path $projectRoot "trading_mvp\src\dense_ws_campaign_runner.py"
$guardScript = Join-Path $projectRoot "tools\check_trading_mvp_autopilot.ps1"
if (-not $PolicyPath) {
    $PolicyPath = Join-Path $projectRoot "docs\plans\trading-mvp-autopilot-policy-v1.json"
}

function Resolve-CampaignPython {
    $candidates = @(
        $env:TRADING_MVP_PYTHON,
        "C:\Program Files\Python313\python.exe",
        (Join-Path $projectRoot ".venv\Scripts\python.exe"),
        (Join-Path $projectRoot "trading_mvp\.venv\Scripts\python.exe"),
        "C:\Users\koval\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
    ) | Where-Object { $_ }
    foreach ($candidate in $candidates) {
        if (-not (Test-Path -LiteralPath $candidate -PathType Leaf)) {
            continue
        }
        & $candidate -c "import psutil, requests" 2>$null
        if ($LASTEXITCODE -eq 0) {
            return [System.IO.Path]::GetFullPath($candidate)
        }
    }
    throw "Python runtime with psutil and requests was not found."
}

function Invoke-CampaignPreflight {
    param(
        [Parameter(Mandatory = $true)][string]$Python,
        [switch]$RequireDue
    )
    $arguments = @(
        $runner,
        "preflight",
        "--plan", $PlanPath,
        "--expected-plan-hash", $ExpectedPlanHash,
        "--policy", $PolicyPath
    )
    if ($RequireDue) {
        $arguments += "--require-due"
    }
    $raw = & $Python @arguments 2>&1
    $exitCode = $LASTEXITCODE
    $rawText = $raw | Out-String
    try {
        $result = $rawText | ConvertFrom-Json
    } catch {
        throw "Dense WS campaign preflight did not return valid JSON (exit $exitCode): $rawText"
    }
    if ($exitCode -notin @(0, 1)) {
        throw "Dense WS campaign preflight failed with exit $exitCode`: $rawText"
    }
    if ([string]$result.schema -ne "trading_mvp_dense_ws_campaign_preflight_v1") {
        throw "Dense WS campaign preflight schema mismatch."
    }
    return $result
}

function Write-ReservationCreateNew {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)]$Payload
    )
    $parent = Split-Path -Parent $Path
    New-Item -ItemType Directory -Force -Path $parent | Out-Null
    $bytes = [System.Text.UTF8Encoding]::new($false).GetBytes(
        (($Payload | ConvertTo-Json -Depth 12) + [Environment]::NewLine)
    )
    $stream = $null
    try {
        $stream = [System.IO.File]::Open(
            $Path,
            [System.IO.FileMode]::CreateNew,
            [System.IO.FileAccess]::Write,
            [System.IO.FileShare]::Read
        )
        $stream.Write($bytes, 0, $bytes.Length)
        $stream.Flush($true)
    } finally {
        if ($stream) {
            $stream.Dispose()
        }
    }
}

function Write-JsonAtomic {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)]$Payload
    )
    $temporary = "$Path.tmp.$PID.$([DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds())"
    try {
        $bytes = [System.Text.UTF8Encoding]::new($false).GetBytes(
            (($Payload | ConvertTo-Json -Depth 12) + [Environment]::NewLine)
        )
        [System.IO.File]::WriteAllBytes($temporary, $bytes)
        [System.IO.File]::Move($temporary, $Path, $true)
    } finally {
        Remove-Item -LiteralPath $temporary -Force -ErrorAction SilentlyContinue
    }
}

function Get-Sha256Text {
    param([Parameter(Mandatory = $true)][string]$Value)
    $algorithm = [System.Security.Cryptography.SHA256]::Create()
    try {
        $bytes = [System.Text.Encoding]::UTF8.GetBytes($Value)
        return [Convert]::ToHexString($algorithm.ComputeHash($bytes)).ToLowerInvariant()
    } finally {
        $algorithm.Dispose()
    }
}

$PlanPath = [System.IO.Path]::GetFullPath($PlanPath)
$PolicyPath = [System.IO.Path]::GetFullPath($PolicyPath)
foreach ($required in @($PlanPath, $PolicyPath, $runner, $guardScript)) {
    if (-not (Test-Path -LiteralPath $required -PathType Leaf)) {
        throw "Required file is missing: $required"
    }
}
$python = Resolve-CampaignPython

if ($VisibleChild) {
    if (-not $ConfirmedLongCampaign) {
        throw "VisibleChild requires ConfirmedLongCampaign."
    }
    if (-not $ReservationPath) {
        throw "VisibleChild requires ReservationPath."
    }
    $ReservationPath = [System.IO.Path]::GetFullPath($ReservationPath)
    $childPlan = Get-Content -Raw -LiteralPath $PlanPath | ConvertFrom-Json
    $expectedReservationPath = [System.IO.Path]::GetFullPath(
        (Join-Path ([string]$childPlan.outputs.campaign_root) "_control\launch-reservation.json")
    )
    if ($ReservationPath -ne $expectedReservationPath) {
        throw "VisibleChild reservation path does not match the immutable PlanOnly."
    }
    $childReservation = $null
    for ($attempt = 0; $attempt -lt 120; $attempt++) {
        if (Test-Path -LiteralPath $ReservationPath -PathType Leaf) {
            try {
                $candidate = Get-Content -Raw -LiteralPath $ReservationPath | ConvertFrom-Json
                if (
                    [int]$candidate.expected_terminal_pid -eq $PID -and
                    [string]$candidate.plan_hash -eq $ExpectedPlanHash
                ) {
                    $childReservation = $candidate
                    break
                }
            } catch {}
        }
        Start-Sleep -Milliseconds 250
    }
    if (-not $childReservation) {
        throw "VisibleChild did not receive a parent-bound terminal reservation."
    }
    $reservationToken = [string]$childReservation.reservation_token
    if ($reservationToken -notmatch "^[0-9a-f]{32}$") {
        throw "VisibleChild reservation token is invalid."
    }
    Write-Host "Starting hash-bound dense WS campaign orchestrator" -ForegroundColor Cyan
    Write-Host "Plan: $PlanPath"
    Write-Host "Plan hash: $ExpectedPlanHash"
    $env:TRADING_MVP_DENSE_WS_RESERVATION_TOKEN = $reservationToken
    try {
        & $python -u $runner run `
            --plan $PlanPath `
            --expected-plan-hash $ExpectedPlanHash `
            --policy $PolicyPath
        $exitCode = $LASTEXITCODE
    } finally {
        Remove-Item Env:TRADING_MVP_DENSE_WS_RESERVATION_TOKEN -ErrorAction SilentlyContinue
        $reservationToken = $null
    }
    if ($exitCode -eq 0) {
        Write-Host "Campaign orchestrator reached READY_FOR_POSTPROCESS." -ForegroundColor Green
    } else {
        Write-Host "Campaign orchestrator stopped incomplete. ExitCode=$exitCode" -ForegroundColor Yellow
    }
    Write-Host "Visible campaign terminal remains open for inspection. Close it manually when finished." -ForegroundColor DarkGray
    return
}

$preflight = Invoke-CampaignPreflight -Python $python -RequireDue:$false
if ($PreflightOnly) {
    if ($Json) {
        $preflight | ConvertTo-Json -Depth 20
    } else {
        $preflight | Format-List
    }
    exit 0
}

if (-not $ConfirmedLongCampaign) {
    throw "Exact long-campaign approval is required. Use PreflightOnly until the user approves this exact PlanOnly hash."
}

$duePreflight = Invoke-CampaignPreflight -Python $python -RequireDue
if (-not [bool]$duePreflight.can_launch_now) {
    throw "Campaign cannot launch now: status=$($duePreflight.status); reasons=$(@($duePreflight.reasons) -join ',')."
}

$guard = & pwsh -NoProfile -ExecutionPolicy Bypass -File $guardScript -Json |
    ConvertFrom-Json
$remaining = [double]$guard.usage.remaining_percent
if ($remaining -le 15.0) {
    throw "Weekly quota remaining is $remaining%, must exceed 15%."
}
if ([string]$guard.status -ne "ACTIVE" -or [bool]$guard.stop_new_actions) {
    throw "Authoritative guard blocks launch: status=$($guard.status), decision=$($guard.decision)."
}
if ([string]$guard.long_campaign_candidate.status -ne "READY_FOR_APPROVAL") {
    throw "Long campaign is not READY_FOR_APPROVAL."
}
if ([string]$guard.long_campaign_candidate.plan_hash -ne $ExpectedPlanHash) {
    throw "Authoritative guard plan hash mismatch."
}

$plan = Get-Content -Raw -LiteralPath $PlanPath | ConvertFrom-Json
$campaignRoot = [System.IO.Path]::GetFullPath([string]$plan.outputs.campaign_root)
$controlRoot = Join-Path $campaignRoot "_control"
$reservationPath = Join-Path $controlRoot "launch-reservation.json"
$token = [Guid]::NewGuid().ToString("N")
$reservation = [ordered]@{
    schema = "trading_mvp_dense_ws_campaign_launch_reservation_v1"
    campaign_id = [string]$plan.campaign_id
    created_at_utc = [DateTimeOffset]::UtcNow.ToString("o")
    reservation_token = $token
    top_level_pid = $PID
    terminal_pid = $null
    expected_terminal_pid = $null
    plan_path = $PlanPath
    plan_hash = $ExpectedPlanHash
    policy_path = $PolicyPath
    explicit_confirmation = $true
}
Write-ReservationCreateNew -Path $reservationPath -Payload $reservation

$pwsh = (Get-Command pwsh -ErrorAction Stop).Source
$childArguments = @(
    "-NoExit",
    "-NoProfile",
    "-ExecutionPolicy", "Bypass",
    "-File", $PSCommandPath,
    "-PlanPath", $PlanPath,
    "-ExpectedPlanHash", $ExpectedPlanHash,
    "-PolicyPath", $PolicyPath,
    "-ConfirmedLongCampaign",
    "-VisibleChild",
    "-ReservationPath", $reservationPath
)

try {
    $terminal = Start-Process `
        -FilePath $pwsh `
        -ArgumentList $childArguments `
        -WorkingDirectory $projectRoot `
        -WindowStyle Normal `
        -PassThru
} catch {
    Remove-Item -LiteralPath $reservationPath -Force -ErrorAction SilentlyContinue
    throw
}

$reservation.expected_terminal_pid = $terminal.Id
$reservation.terminal_started_at_utc = [DateTimeOffset]::UtcNow.ToString("o")
Write-JsonAtomic -Path $reservationPath -Payload $reservation

$ownershipVerified = $false
$commandLine = ""
for ($attempt = 0; $attempt -lt 120; $attempt++) {
    Start-Sleep -Milliseconds 500
    try {
        $process = Get-CimInstance Win32_Process -Filter "ProcessId = $($terminal.Id)"
        $commandLine = [string]$process.CommandLine
        $commandLineVerified = (
            $commandLine -match [regex]::Escape("-VisibleChild") -and
            $commandLine -match [regex]::Escape($ExpectedPlanHash) -and
            $commandLine -match [regex]::Escape("-ReservationPath") -and
            $commandLine -match [regex]::Escape($reservationPath)
        )
        if (
            $commandLineVerified -and
            (Test-Path -LiteralPath $reservationPath -PathType Leaf) -and
            (Test-Path -LiteralPath (Join-Path $controlRoot "owner.json") -PathType Leaf)
        ) {
            $adoptedReservation = Get-Content -Raw -LiteralPath $reservationPath |
                ConvertFrom-Json
            $owner = Get-Content -Raw -LiteralPath (Join-Path $controlRoot "owner.json") |
                ConvertFrom-Json
            $orchestratorPid = [int]$adoptedReservation.orchestrator_pid
            $orchestrator = Get-Process -Id $orchestratorPid -ErrorAction Stop
            $tokenHash = Get-Sha256Text -Value $token
            if (
                [int]$adoptedReservation.expected_terminal_pid -eq $terminal.Id -and
                [int]$adoptedReservation.terminal_pid -eq $terminal.Id -and
                [string]$adoptedReservation.adopted_at_utc -and
                [int]$owner.orchestrator_pid -eq $orchestratorPid -and
                [int]$owner.terminal_pid -eq $terminal.Id -and
                [string]$owner.plan_hash -eq $ExpectedPlanHash -and
                [string]$owner.reservation_token_sha256 -eq $tokenHash -and
                [bool]$owner.final -eq $false -and
                $orchestrator.Id -eq $orchestratorPid
            ) {
                $ownershipVerified = $true
                break
            }
        }
    } catch {}
}
if (-not $ownershipVerified) {
    throw "Visible terminal launched but ownership could not be verified. Do not retry until status proves there is no live owner."
}

$result = [ordered]@{
    schema = "trading_mvp_dense_ws_campaign_visible_launch_v1"
    status = "VISIBLE_TERMINAL_LAUNCHED"
    campaign_id = [string]$plan.campaign_id
    run_id = [string]$plan.campaign_id
    first_phase_run_id = [string]$plan.phases[0].run_id
    plan_path = $PlanPath
    plan_hash = $ExpectedPlanHash
    terminal_pid = $terminal.Id
    terminal_ownership_verified = $true
    reservation_path = $reservationPath
    status_command = [string]$plan.launch_controls.status_command
    stop_command = [string]$plan.launch_controls.stop_command
    command_line_verified = $true
    verified_terminal_command_fields = @(
        "-VisibleChild",
        $ExpectedPlanHash,
        "-ReservationPath",
        $reservationPath,
        "owner_adoption_verified"
    )
}
if ($Json) {
    $result | ConvertTo-Json -Depth 12
} else {
    $result | Format-List
}

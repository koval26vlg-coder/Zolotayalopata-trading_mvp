param(
    [string]$Source = "C:\Users\koval\Documents\ZolotyayLopata\exports\trading-mvp",
    [string]$Destination = "E:\ZolotyayLopata-data\exports\trading-mvp",
    [switch]$ConfirmedMove,
    [switch]$PlanOnly,
    [switch]$NoPause
)

$ErrorActionPreference = "Stop"

function Resolve-RequiredPath {
    param([string]$Path)
    return (Resolve-Path -LiteralPath $Path).Path
}

function Assert-WithinExpectedRoot {
    param(
        [string]$Path,
        [string]$ExpectedPrefix,
        [string]$Name
    )
    $full = [System.IO.Path]::GetFullPath($Path)
    $prefix = [System.IO.Path]::GetFullPath($ExpectedPrefix)
    if (-not $full.StartsWith($prefix, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "$Name path '$full' is outside expected root '$prefix'."
    }
}

function Invoke-RobocopyChecked {
    param(
        [string]$From,
        [string]$To,
        [string[]]$ExtraArgs,
        [string]$LogPath
    )
    $robocopy = Join-Path $env:SystemRoot "System32\robocopy.exe"
    if (-not (Test-Path -LiteralPath $robocopy)) {
        throw "robocopy.exe not found at $robocopy"
    }
    New-Item -ItemType Directory -Force -Path $To | Out-Null
    $args = @($From, $To) + $ExtraArgs + @("/R:2", "/W:2", "/MT:8", "/NP", "/TEE", "/LOG+:$LogPath")
    & $robocopy @args
    $code = $LASTEXITCODE
    if ($code -gt 7) {
        throw "robocopy failed with exit code $($code): $From -> $To"
    }
    return $code
}

function Get-TreeSummary {
    param(
        [string]$Path,
        [string[]]$ExcludeTopLevel = @()
    )
    $root = Get-Item -LiteralPath $Path -Force
    if (-not $root.PSIsContainer) {
        return [pscustomobject]@{ files = 1; bytes = [int64]$root.Length }
    }
    $files = 0
    [int64]$bytes = 0
    foreach ($child in Get-ChildItem -LiteralPath $Path -Force -ErrorAction SilentlyContinue) {
        if ($ExcludeTopLevel -contains $child.Name) {
            continue
        }
        if (($child.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
            continue
        }
        if ($child.PSIsContainer) {
            foreach ($file in Get-ChildItem -LiteralPath $child.FullName -Recurse -File -Force -ErrorAction SilentlyContinue) {
                if (($file.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
                    continue
                }
                $files += 1
                $bytes += [int64]$file.Length
            }
        } else {
            $files += 1
            $bytes += [int64]$child.Length
        }
    }
    return [pscustomobject]@{ files = $files; bytes = $bytes }
}

function Assert-SummaryMatches {
    param(
        [object]$Before,
        [object]$After,
        [string]$Label
    )
    if ([int64]$Before.files -ne [int64]$After.files -or [int64]$Before.bytes -ne [int64]$After.bytes) {
        throw "$Label verification failed. before files=$($Before.files) bytes=$($Before.bytes); after files=$($After.files) bytes=$($After.bytes)"
    }
}

$sourcePath = Resolve-RequiredPath $Source
$sourceItem = Get-Item -LiteralPath $sourcePath -Force
if (-not $sourceItem.PSIsContainer) {
    throw "Source must be a directory: $sourcePath"
}
Assert-WithinExpectedRoot -Path $sourcePath -ExpectedPrefix "C:\Users\koval\Documents\ZolotyayLopata\exports" -Name "Source"

$destFull = [System.IO.Path]::GetFullPath($Destination)
if (-not $destFull.StartsWith("E:\", [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Destination must be on E: for this migration: $destFull"
}
Assert-WithinExpectedRoot -Path $destFull -ExpectedPrefix "E:\ZolotyayLopata-data" -Name "Destination"

$repoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
$logDir = Join-Path $repoRoot "docs\agent-log"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$transcriptPath = Join-Path $logDir "move_trading_mvp_exports_to_external_$stamp.console.log"
$robocopyLog = Join-Path $logDir "move_trading_mvp_exports_to_external_$stamp.robocopy.log"

$rawDurablePath = Join-Path $sourcePath "raw-durable"
$rawDurableTarget = $null
if (Test-Path -LiteralPath $rawDurablePath) {
    $rawItem = Get-Item -LiteralPath $rawDurablePath -Force
    if (($rawItem.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0 -and $rawItem.Target) {
        $rawDurableTarget = [string]$rawItem.Target
    }
}

$sourceSummary = Get-TreeSummary -Path $sourcePath -ExcludeTopLevel @("raw-durable")
$rawSummary = $null
if ($rawDurableTarget -and (Test-Path -LiteralPath $rawDurableTarget)) {
    $rawSummary = Get-TreeSummary -Path $rawDurableTarget
}

$plan = [ordered]@{
    mode = "move_trading_mvp_exports_to_external"
    source = $sourcePath
    destination = $destFull
    raw_durable_junction = if (Test-Path -LiteralPath $rawDurablePath) { $rawDurablePath } else { $null }
    raw_durable_target = $rawDurableTarget
    destination_raw_durable = Join-Path $destFull "raw-durable"
    source_non_junction_summary = $sourceSummary
    raw_durable_summary = $rawSummary
    transcript = $transcriptPath
    robocopy_log = $robocopyLog
    would_move = [bool]$ConfirmedMove -and -not [bool]$PlanOnly
    plan_only = [bool]$PlanOnly
    confirmed_move = [bool]$ConfirmedMove
    warning = "This copies/verifies/moves data and replaces the source directory with a junction. Run only when no collector/postprocess is writing under source."
}

if ($PlanOnly -or -not $ConfirmedMove) {
    $plan | ConvertTo-Json -Depth 8
    if (-not $ConfirmedMove -and -not $PlanOnly) {
        throw "Refusing to move without -ConfirmedMove. Re-run with -PlanOnly to inspect or -ConfirmedMove to execute."
    }
    exit 0
}

$transcriptStarted = $false
try {
    Start-Transcript -Path $transcriptPath -Force | Out-Null
    $transcriptStarted = $true
} catch {
    Write-Host ("Transcript unavailable: {0}" -f $_.Exception.Message)
}

try {
    Write-Host "Moving trading_mvp exports to external disk"
    Write-Host "Source: $sourcePath"
    Write-Host "Destination: $destFull"
    Write-Host "Raw durable target: $rawDurableTarget"
    Write-Host "Robocopy log: $robocopyLog"

    New-Item -ItemType Directory -Force -Path $destFull | Out-Null

    $copyCode = Invoke-RobocopyChecked -From $sourcePath -To $destFull -ExtraArgs @("/E", "/XJ") -LogPath $robocopyLog
    $destSummary = Get-TreeSummary -Path $destFull -ExcludeTopLevel @("raw-durable")
    Assert-SummaryMatches -Before $sourceSummary -After $destSummary -Label "non-junction exports"

    if ($rawDurableTarget) {
        if (-not (Test-Path -LiteralPath $rawDurableTarget)) {
            throw "raw-durable target does not exist: $rawDurableTarget"
        }
        $rawDest = Join-Path $destFull "raw-durable"
        $rawCopyCode = Invoke-RobocopyChecked -From $rawDurableTarget -To $rawDest -ExtraArgs @("/E") -LogPath $robocopyLog
        $rawDestSummary = Get-TreeSummary -Path $rawDest
        Assert-SummaryMatches -Before $rawSummary -After $rawDestSummary -Label "raw-durable"
    } else {
        $rawCopyCode = $null
    }

    Write-Host "Verification passed. Removing local source and replacing with junction."
    if (Test-Path -LiteralPath $rawDurablePath) {
        Remove-Item -LiteralPath $rawDurablePath -Force
    }
    Remove-Item -LiteralPath $sourcePath -Recurse -Force
    New-Item -ItemType Junction -Path $sourcePath -Target $destFull | Out-Null

    if ($rawDurableTarget -and (Test-Path -LiteralPath $rawDurableTarget)) {
        $rawSourceAfterCopy = Get-TreeSummary -Path $rawDurableTarget
        if (
            $rawDestSummary -and
            [int64]$rawSourceAfterCopy.files -eq [int64]$rawDestSummary.files -and
            [int64]$rawSourceAfterCopy.bytes -eq [int64]$rawDestSummary.bytes
        ) {
            Assert-WithinExpectedRoot -Path $rawDurableTarget -ExpectedPrefix "D:\ZolotyayLopata-data" -Name "Raw durable original target"
            Remove-Item -LiteralPath $rawDurableTarget -Recurse -Force
            Write-Host "Removed verified raw durable original target: $rawDurableTarget"
        } else {
            Write-Host "Raw durable original target verification changed after migration, leaving it in place: $rawDurableTarget"
        }
    }

    $result = [ordered]@{
        ok = $true
        source = $sourcePath
        source_link_type = (Get-Item -LiteralPath $sourcePath -Force).LinkType
        source_target = (Get-Item -LiteralPath $sourcePath -Force).Target
        destination = $destFull
        non_junction_files = $destSummary.files
        non_junction_bytes = $destSummary.bytes
        raw_durable_files = if ($rawDestSummary) { $rawDestSummary.files } else { $null }
        raw_durable_bytes = if ($rawDestSummary) { $rawDestSummary.bytes } else { $null }
        robocopy_exit_code = $copyCode
        raw_robocopy_exit_code = $rawCopyCode
        transcript = $transcriptPath
        robocopy_log = $robocopyLog
    }
    $result | ConvertTo-Json -Depth 8
} finally {
    if ($transcriptStarted) {
        Stop-Transcript | Out-Null
    }
}

if (-not $NoPause) {
    Read-Host "Press Enter to close this migration window"
}

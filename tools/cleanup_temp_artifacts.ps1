<#
.SYNOPSIS
    Periodic cleanup script for disposable temporary directories, test caches, and temp files.

.DESCRIPTION
    Scans the repository root and subdirectories for disposable temporary artifacts:
    - tmp* random folders from tempfile/unittests
    - .tmp*, .test-tmp, .codex-test-tmp, .audit-tmp
    - .pytest_cache, .ruff_cache
    - __pycache__ directories
    Preserves all core code, tools, docs, and exports.
#>

[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [switch]$DryRun,
    [switch]$IncludePycache
)

$ErrorActionPreference = "Continue"
$projectRoot = Split-Path -Parent $PSScriptRoot

Write-Host "==========================================" -ForegroundColor Cyan
Write-Host " ZolotyayLopata Temp Cleanup Utility" -ForegroundColor Cyan
Write-Host " Root: $projectRoot" -ForegroundColor Cyan
Write-Host " Mode: $(if ($DryRun) { 'DRY RUN (preview only)' } else { 'LIVE CLEANUP' })" -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan

$patterns = @(
    "^tmp[0-9a-zA-Z_]+$",
    "^\.tmp",
    "^\.codex-test-",
    "^\.codex-tmp-",
    "^\.test-tmp",
    "^\.audit-tmp",
    "^\.pytest_cache$",
    "^\.ruff_cache$"
)

$removedCount = 0
$freedBytes = 0

# 1. Scan Root directories
$candidates = Get-ChildItem -Path $projectRoot -Directory -Force | Where-Object {
    $dirName = $_.Name
    foreach ($p in $patterns) {
        if ($dirName -match $p) { return $true }
    }
    return $false
}

# 2. Scan trading_mvp subdirectories
$subCandidates = Get-ChildItem -Path (Join-Path $projectRoot "trading_mvp") -Directory -Force -ErrorAction SilentlyContinue | Where-Object {
    $dirName = $_.Name
    foreach ($p in $patterns) {
        if ($dirName -match $p) { return $true }
    }
    return $false
}

$allDirs = @($candidates) + @($subCandidates)

foreach ($dir in $allDirs) {
    if (Test-Path $dir.FullName) {
        $files = Get-ChildItem -Path $dir.FullName -Recurse -File -Force -ErrorAction SilentlyContinue
        $size = ($files | Measure-Object -Property Length -Sum).Sum
        if ($null -eq $size) { $size = 0 }
        $freedBytes += $size

        Write-Host "  -> $(if ($DryRun) { '[PREVIEW]' } else { '[REMOVING]' }) $($dir.FullName) ($($files.Count) files, $([math]::Round($size/1KB, 1)) KB)" -ForegroundColor Yellow
        if (-not $DryRun) {
            Remove-Item -Path $dir.FullName -Recurse -Force -ErrorAction SilentlyContinue
            $removedCount++
        }
    }
}

# 3. Optional Pycache cleanup
if ($IncludePycache) {
    Write-Host "`nScanning for __pycache__ folders..." -ForegroundColor Cyan
    $pycaches = Get-ChildItem -Path $projectRoot -Directory -Recurse -Filter "__pycache__" -Force -ErrorAction SilentlyContinue
    foreach ($py in $pycaches) {
        Write-Host "  -> $(if ($DryRun) { '[PREVIEW]' } else { '[REMOVING]' }) $($py.FullName)" -ForegroundColor Gray
        if (-not $DryRun) {
            Remove-Item -Path $py.FullName -Recurse -Force -ErrorAction SilentlyContinue
            $removedCount++
        }
    }
}

Write-Host "------------------------------------------" -ForegroundColor Cyan
Write-Host " Cleanup completed!" -ForegroundColor Green
Write-Host " Total directories processed: $($allDirs.Count)" -ForegroundColor Green
Write-Host " Total size cleared: $([math]::Round($freedBytes/1KB, 1)) KB" -ForegroundColor Green
Write-Host "==========================================" -ForegroundColor Cyan

param(
    [ValidateSet("next", "ensure", "claim", "complete", "fail")]
    [string]$Action = "next",
    [string]$TaskId = "",
    [string]$ArtifactPath = "",
    [string]$ErrorMessage = "",
    [string]$Owner = "Codex",
    [string]$BacklogPath = ""
)

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$module = Join-Path $repoRoot "trading_mvp\src\autopilot_research_backlog.py"
if (-not $BacklogPath) {
    $BacklogPath = Join-Path $repoRoot "docs\agent-log\trading-mvp-autopilot-research-backlog.json"
}
$python = "C:\Program Files\Python313\python.exe"
if (-not (Test-Path -LiteralPath $python)) {
    throw "Python runtime is unavailable: $python"
}

$arguments = @($module, $Action, "--backlog", $BacklogPath)
if ($TaskId) { $arguments += @("--task-id", $TaskId) }
if ($Owner) { $arguments += @("--owner", $Owner) }
if ($ArtifactPath) { $arguments += @("--artifact", $ArtifactPath) }
if ($ErrorMessage) { $arguments += @("--error", $ErrorMessage) }
& $python @arguments
if ($LASTEXITCODE -ne 0) {
    throw "Research backlog action failed with exit code $LASTEXITCODE."
}

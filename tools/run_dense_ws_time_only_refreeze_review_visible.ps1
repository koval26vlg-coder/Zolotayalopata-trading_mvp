[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
[Console]::InputEncoding = [System.Text.UTF8Encoding]::new($false)
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)

$workflowId = "2026-08-03-022032-241689-trading-mvp-dense-ws-time-only-refreeze-v2-independent-review"
$workflowRoot = "D:\AionUi-Paperclip\docs\agent-workflows"
$runner = "D:\AionUi-Paperclip\tools\run-agent-workflow.ps1"
$transcriptPath = Join-Path $PSScriptRoot "..\docs\agent-log\regressions\dense-ws-time-only-refreeze-swarm-review-visible-20260803.log"

Start-Transcript -LiteralPath $transcriptPath -Append | Out-Null
try {
    Write-Host "Dense WS time-only refreeze independent review"
    Write-Host "Workflow: $workflowId"
    Write-Host "No collector, market data, returns, PnL, or OOS actions are authorized."
    & $runner `
        -Root $workflowRoot `
        -WorkflowId $workflowId `
        -TimeoutSeconds 390 `
        -MaxSteps 5
}
catch {
    Write-Error $_
    throw
}
finally {
    Stop-Transcript | Out-Null
}

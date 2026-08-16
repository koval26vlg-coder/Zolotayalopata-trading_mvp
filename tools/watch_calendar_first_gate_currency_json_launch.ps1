$ErrorActionPreference = "Stop"
$launch = Join-Path (Split-Path $PSScriptRoot -Parent) "docs\agent-log\run-gates\slow_liquidity_calendar_first_gate_currency_json_20260816.launch.json"
while ($true) {
    if (Test-Path -LiteralPath $launch) {
        $j = Get-Content -Raw -LiteralPath $launch | ConvertFrom-Json
        $status = [string]$j.status
        if ($status -eq "COMPLETE") {
            Write-Output "DONE"
            exit 0
        }
        if ($status -eq "STOPPED_INCOMPLETE") {
            Write-Output "FAILED"
            exit 1
        }
    }
    Start-Sleep -Seconds 15
}

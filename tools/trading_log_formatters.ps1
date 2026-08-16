# Trading Terminal Output & Log Formatters
# Extracted for modular reuse and clean display across trading_mvp runners

function Format-TradingRunHeader {
    param(
        [string]$ActionName,
        [string]$Mode = "paper",
        [string]$ExtraInfo = ""
    )

    Write-Host "==========================================" -ForegroundColor Cyan
    Write-Host " Trading MVP Engine Action: $ActionName" -ForegroundColor Cyan
    Write-Host " Mode: $Mode | Timestamp: $((Get-Date).ToString('yyyy-MM-dd HH:mm:ss'))" -ForegroundColor Cyan
    if ($ExtraInfo) {
        Write-Host " Info: $ExtraInfo" -ForegroundColor Gray
    }
    Write-Host "==========================================" -ForegroundColor Cyan
}

function Format-TradingQualitySummary {
    param(
        [string]$QualityJsonPath
    )

    if (-not (Test-Path -LiteralPath $QualityJsonPath)) {
        Write-Warning "Quality JSON report not found at $QualityJsonPath"
        return
    }

    try {
        $q = Get-Content -Raw -LiteralPath $QualityJsonPath | ConvertFrom-Json
        Write-Host "`n--- Data Quality Summary ---" -ForegroundColor Yellow
        Write-Host " Decision : $($q.decision)" -ForegroundColor $(if ($q.accepted) { "Green" } else { "Red" })
        Write-Host " Accepted : $($q.accepted)" -ForegroundColor $(if ($q.accepted) { "Green" } else { "Red" })
        if ($q.metrics) {
            Write-Host " Total Rows : $($q.metrics.line_count)" -ForegroundColor Gray
            Write-Host " OK Bases   : $($q.metrics.ok_bases)" -ForegroundColor Gray
            Write-Host " Exchanges  : $($q.metrics.ok_exchanges)" -ForegroundColor Gray
        }
        Write-Host "----------------------------`n" -ForegroundColor Yellow
    } catch {
        Write-Warning "Could not parse quality report: $($_.Exception.Message)"
    }
}

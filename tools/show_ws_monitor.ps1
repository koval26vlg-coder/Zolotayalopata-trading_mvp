$GatePath = "C:\Users\koval\Documents\ZolotyayLopata\docs\agent-log\active-run-gate.json"
$RawDir = "C:\Users\koval\Documents\ZolotyayLopata\exports\trading-mvp\raw"

if (Test-Path -LiteralPath $GatePath) {
    $g = Get-Content -Raw -LiteralPath $GatePath | ConvertFrom-Json
    Write-Host "Status:           $($g.status)" -ForegroundColor Green
    Write-Host "Run ID:           $($g.run_id)" -ForegroundColor White
    Write-Host "Process PIDs:     $($g.process_ids -join ', ')" -ForegroundColor White
}
if (Test-Path -LiteralPath $RawDir) {
    $files = @(Get-ChildItem -LiteralPath $RawDir -File -ErrorAction SilentlyContinue)
    $bytes = 0
    foreach ($f in $files) { $bytes += $f.Length }
    $gb = [Math]::Round($bytes / 1GB, 2)
    $last = ($files | Sort-Object LastWriteTime -Descending | Select-Object -First 1).LastWriteTime
    Write-Host "Raw Data Volume:  $gb GB ($($files.Count) files)" -ForegroundColor Yellow
    Write-Host "Last Data Write:  $($last.ToString('yyyy-MM-dd HH:mm:ss'))" -ForegroundColor Cyan
}

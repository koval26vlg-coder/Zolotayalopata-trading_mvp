param()
$ErrorActionPreference = "Stop"
$ProjectRoot = "C:\Users\koval\Documents\ZolotyayLopata"
$LogsDir = Join-Path $ProjectRoot "docs\agent-log"
$BackupDir = Join-Path $ProjectRoot "docs\agent-log\_backups"

if (-not (Test-Path -LiteralPath $BackupDir)) {
    New-Item -ItemType Directory -Path $BackupDir | Out-Null
}

$timestamp = (Get-Date).ToString("yyyyMMdd_HHmmss")
$zipPath = Join-Path $BackupDir "agent_log_backup_$timestamp.zip"

Write-Host "Backing up agent logs to $zipPath ..."
# We must exclude the _backups directory itself to avoid recursion issues
$items = Get-ChildItem -Path $LogsDir | Where-Object { $_.Name -ne "_backups" }
Compress-Archive -Path $items.FullName -DestinationPath $zipPath -Update -ErrorAction Stop

# Keep only the latest 10 backups
$backups = Get-ChildItem -Path $BackupDir -Filter "*.zip" | Sort-Object LastWriteTime -Descending
if ($backups.Count -gt 10) {
    for ($i = 10; $i -lt $backups.Count; $i++) {
        Remove-Item -LiteralPath $backups[$i].FullName -Force
    }
}
Write-Host "Backup completed successfully."

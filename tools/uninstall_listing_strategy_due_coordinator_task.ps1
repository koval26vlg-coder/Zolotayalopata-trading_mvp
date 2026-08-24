param(
    [string]$TaskName = "ZolotyayLopata Listing Strategy Due Coordinator",
    [switch]$Json
)

$ErrorActionPreference = "Stop"
$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($existing) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    $status = "UNINSTALLED"
} else {
    $status = "NOT_INSTALLED"
}

[ordered]@{
    status = $status
    task_name = $TaskName
    artifacts_preserved = $true
} | ConvertTo-Json -Depth 10

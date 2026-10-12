$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..\..\..')).Path
$launcher = Join-Path $root 'tools\start_premarket_depth_coordinator_visible.ps1'
$text = Get-Content -LiteralPath $launcher -Raw
$source = [regex]::Match($text, "(?s)Add-Type -TypeDefinition @'\r?\n(.*?)\r?\n'@").Groups[1].Value
if (-not $source) { throw 'Cannot find the exact launcher Job Object implementation' }
Add-Type -TypeDefinition $source
$ast = [Management.Automation.Language.Parser]::ParseFile($launcher, [ref]$null, [ref]$null)
$function = $ast.Find({param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq 'New-OwnerJob'}, $true)
. ([scriptblock]::Create($function.Extent.Text))
$visible = [PremarketDepthJob]::IsWindowVisible([PremarketDepthJob]::GetConsoleWindow())
if (-not $visible) { throw 'Synthetic test requires a visible console' }
$job = New-OwnerJob
$child = $null
try {
    # Harmless sleeping fixture: no market module, claim, files, or network.
    $child = Start-Process -FilePath (Get-Command pwsh).Source -ArgumentList @('-NoProfile', '-Command', 'Start-Sleep -Seconds 60') -NoNewWindow -PassThru
    if (-not [PremarketDepthJob]::AssignProcessToJobObject($job, $child.Handle)) { throw 'AssignProcessToJobObject failed' }
    $closed = [PremarketDepthJob]::CloseHandle($job)
    $job = [IntPtr]::Zero
    if (-not $closed -or -not $child.WaitForExit(5000)) { throw 'Orphan process survived owner close' }
    [ordered]@{status='PASS';visible_console=$visible;job_kill_on_close_verified=$true;
        fixture_pid=$child.Id;network_requests=0;production_writer_claim_created=$false;
        observed_utc=[DateTime]::UtcNow.ToString('o')} | ConvertTo-Json |
        Set-Content -LiteralPath (Join-Path $PSScriptRoot 'native-owner-result.json') -Encoding utf8NoBOM
    Write-Host 'NATIVE_OWNER_PASS: harmless fixture terminated on owner close'
} finally {
    if ($child -and -not $child.HasExited) { Stop-Process -InputObject $child -Force }
    if ($job -ne [IntPtr]::Zero) { [PremarketDepthJob]::CloseHandle($job) | Out-Null }
}

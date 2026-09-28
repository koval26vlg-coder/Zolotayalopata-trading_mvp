$ErrorActionPreference = "Stop"

function Assert-True([bool]$Condition, [string]$Message) {
    if (-not $Condition) { throw $Message }
}

$installerSource = Get-Content -LiteralPath (Join-Path $PSScriptRoot "install_listing_strategy_due_coordinator_task.ps1") -Raw
$refreshSource = Get-Content -LiteralPath (Join-Path $PSScriptRoot "refresh_listing_strategy_due_coordinator.ps1") -Raw
$tokens = $null
$errors = $null
$installerAst = [Management.Automation.Language.Parser]::ParseInput($installerSource, [ref]$tokens, [ref]$errors)
Assert-True ($errors.Count -eq 0) "installer syntax error"
$refreshAst = [Management.Automation.Language.Parser]::ParseInput($refreshSource, [ref]$tokens, [ref]$errors)
Assert-True ($errors.Count -eq 0) "refresh syntax error"
Assert-True ($installerAst.ParamBlock.Parameters.Name.VariablePath.UserPath -ccontains "InstallDisabled") "installer has no explicit InstallDisabled mode"
Assert-True ($refreshAst.ParamBlock.Parameters.Name.VariablePath.UserPath -ccontains "InstallDisabled") "refresh does not accept InstallDisabled"

# Execute the actual production registration tail, replacing only external task and
# binding APIs. A mistaken enable-then-disable implementation fails at registration.
$start = $installerSource.IndexOf('$action = New-ScheduledTaskAction', [StringComparison]::Ordinal)
Assert-True ($start -ge 0) "registration tail missing"
$registrationTail = [scriptblock]::Create($installerSource.Substring($start))
function Invoke-RegistrationFixture([bool]$Disabled, [bool]$ReturnEnabled = $false) {
    & {
        $InstallDisabled = $Disabled
        $script:registrationFixture = @{calls=0;settings=$null;disable_calls=0;enable_calls=0}
        $TaskName = "OFFLINE_FIXTURE_ONLY"
        $pwsh = "fixture-pwsh.exe"
        $actionArguments = "fixture-action"
        $repoRoot = "fixture-root"
        $WorkerExitTimeoutSec = 600
        $legacyRecords = @()
        $coordinatorPreflight = @{execution_performed=$false}
        function New-ScheduledTaskAction { param($Execute,$Argument,$WorkingDirectory) return @{} }
        function New-ScheduledTaskTrigger { param([switch]$Once,$At,$RepetitionInterval,$RepetitionDuration) return @{} }
        function New-ScheduledTaskSettingsSet {
            param([switch]$Hidden,$MultipleInstances,$ExecutionTimeLimit,[switch]$StartWhenAvailable,
                [switch]$AllowStartIfOnBatteries,[switch]$DontStopIfGoingOnBatteries,[switch]$Disable)
            $script:registrationFixture.settings = [pscustomobject]@{Enabled=(-not [bool]$Disable)}
            return $script:registrationFixture.settings
        }
        function New-ScheduledTaskPrincipal { param($UserId,$LogonType,$RunLevel) return @{} }
        function Assert-ControlPlaneBinding { return @{installer="fixture";coordinator="fixture";validator="fixture"} }
        function Assert-PublicationBinding { return @{registry="fixture";receipt="fixture"} }
        function Assert-LegacyAutomationSnapshot { }
        function Register-ScheduledTask {
            param($TaskName,$Action,$Trigger,$Settings,$Principal,[switch]$Force)
            if ($InstallDisabled -and $Settings.Enabled) { throw "DISABLED_INSTALL_REGISTERED_ENABLED_TASK" }
            $script:registrationFixture.calls++
        }
        function Get-ScheduledTask {
            param($TaskName,$ErrorAction)
            $enabled = $ReturnEnabled -or $script:registrationFixture.settings.Enabled
            return [pscustomobject]@{TaskPath="fixture";State=$(if ($enabled) {"Ready"} else {"Disabled"});Settings=[pscustomobject]@{Enabled=$enabled}}
        }
        function Disable-ScheduledTask { $script:registrationFixture.disable_calls++; throw "POST_REGISTRATION_DISABLE_FORBIDDEN" }
        function Enable-ScheduledTask { $script:registrationFixture.enable_calls++; throw "ENABLE_FORBIDDEN" }
        function Start-ScheduledTask { throw "START_FORBIDDEN" }
        $caught = $null
        $payload = $null
        try { $payload = (& $registrationTail | Out-String) | ConvertFrom-Json }
        catch { $caught = $_.Exception.Message }
        [pscustomobject]@{payload=$payload;error=$caught;calls=$script:registrationFixture.calls;
            enabled_at_registration=$script:registrationFixture.settings.Enabled}
    }
}

$disabled = Invoke-RegistrationFixture $true
Assert-True ($null -eq $disabled.error) "disabled registration fixture failed: $($disabled.error)"
Assert-True ($disabled.calls -eq 1 -and $disabled.enabled_at_registration -eq $false) "disabled install must be disabled before the single registration"
Assert-True ($disabled.payload.status -ceq "INSTALLED_DISABLED" -and $disabled.payload.scheduler_enabled -eq $false -and $disabled.payload.task_state -ceq "Disabled") "disabled install receipt does not prove disabled readback"
Assert-True ($disabled.payload.execution_performed -eq $false) "disabled installation must not report execution"
$normal = Invoke-RegistrationFixture $false
Assert-True ($null -eq $normal.error -and $normal.calls -eq 1 -and $normal.enabled_at_registration -eq $true -and $normal.payload.status -ceq "INSTALLED") "default enabled registration behavior regressed"
$badReadback = Invoke-RegistrationFixture $true $true
Assert-True ($badReadback.error -match "INSTALLED_TASK_NOT_DISABLED" -and $null -eq $badReadback.payload) "incorrect task readback was reported as successful disabled installation"

# Refresh's splatted argument table is executable code, not a string assertion.
$installArgsNode = $refreshAst.Find({param($node) $node -is [Management.Automation.Language.AssignmentStatementAst] -and $node.Left.Extent.Text -ceq '$installArguments'}, $true)
Assert-True ($null -ne $installArgsNode) "refresh installer argument table missing"
function Get-RawSha256([string]$Path) { return "fixture-sha" }
foreach ($requestedDisabled in @($true, $false)) {
    $InstallDisabled = $requestedDisabled
    $registry=$receipt=$installer=$coordinator=$validator=$commit="fixture"
    . ([scriptblock]::Create($installArgsNode.Extent.Text))
    Assert-True ($installArguments.ContainsKey("InstallDisabled") -and [bool]$installArguments.InstallDisabled -eq $requestedDisabled) "refresh loses requested disabled state"
}
$refreshReportNode = $refreshAst.Find({param($node) $node -is [Management.Automation.Language.AssignmentStatementAst] -and $node.Left.Extent.Text -ceq '$report'}, $true)
foreach ($requestedDisabled in @($true, $false)) {
    $InstallDisabled=$requestedDisabled
    . ([scriptblock]::Create($refreshReportNode.Extent.Text))
    Assert-True ($report.Contains("scheduler_enabled") -and $report.scheduler_enabled -eq (-not $requestedDisabled)) "refresh dry run omits intended scheduler state"
}
[ordered]@{status="PASS";tests=9;registration_attempted=$false;fixtures="production_tail_with_task_api_stubs"} | ConvertTo-Json -Compress

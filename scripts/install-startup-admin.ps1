param(
    [string]$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path,
    [string]$TaskName = "TURZX SideScreen",
    [string]$Port = "COM7",
    [int]$IntervalMs = 500,
    [switch]$DoNotDisableOldTasks
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$isAdmin = ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).
    IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    throw "Please run as Administrator, or use scripts\install-startup-admin.cmd for a UAC prompt."
}

$Root = (Resolve-Path $Root).Path
$script = Join-Path $Root "tools\turzx_side_screen\StartSideScreenWatchdog.ps1"
if (!(Test-Path -LiteralPath $script)) {
    throw "Missing watchdog script: $script"
}

$checker = Join-Path $Root "scripts\check-runtime.ps1"
if (Test-Path -LiteralPath $checker) {
    powershell -NoProfile -ExecutionPolicy Bypass -File $checker -Root $Root
    if ($LASTEXITCODE -ne 0) {
        throw "Runtime check failed. Startup task was not installed."
    }
}

$workingDir = Split-Path -Parent $script
$action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument ('-NoProfile -ExecutionPolicy Bypass -File "{0}" -Root "{1}" -Port {2} -IntervalMs {3}' -f $script, $Root, $Port, $IntervalMs) `
    -WorkingDirectory $workingDir

$trigger = New-ScheduledTaskTrigger -AtLogOn
$principal = New-ScheduledTaskPrincipal `
    -UserId ("{0}\{1}" -f $env:USERDOMAIN, $env:USERNAME) `
    -LogonType Interactive `
    -RunLevel Highest

$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -MultipleInstances IgnoreNew `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit (New-TimeSpan -Hours 0)

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Principal $principal `
    -Settings $settings `
    -Description ("Start TURZX SideScreen from {0}" -f $Root) `
    -Force | Out-Null

if (-not $DoNotDisableOldTasks) {
    foreach ($oldTask in @("TURZX WeatherFix", "TURZX_88inch_AdminStart")) {
        $existing = Get-ScheduledTask -TaskName $oldTask -ErrorAction SilentlyContinue
        if ($existing) {
            Disable-ScheduledTask -TaskName $oldTask -ErrorAction SilentlyContinue | Out-Null
            Write-Host "Disabled old startup task: $oldTask"
        }
    }
}

Get-ScheduledTask | Where-Object { $_.TaskName -in @($TaskName, "TURZX WeatherFix", "TURZX_88inch_AdminStart") } |
    Select-Object TaskName, State, @{Name="RunLevel";Expression={$_.Principal.RunLevel}},
        @{Name="Action";Expression={($_.Actions | ForEach-Object { $_.Execute + " " + $_.Arguments }) -join " | "}} |
    Format-List

Write-Host "Installed highest-privilege startup task: $TaskName"
Write-Host "Root: $Root"

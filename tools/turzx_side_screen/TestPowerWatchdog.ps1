param(
    [string]$Root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$side = Join-Path $Root "tools\turzx_side_screen"
$watchdog = Join-Path $side "StartSideScreenWatchdog.ps1"
$watchdogLauncher = Join-Path $side "StartSideScreenWatchdog-Hidden.vbs"
$stack = Join-Path $side "StartSideScreenStack.ps1"
$stop = Join-Path $side "StopSideScreenStack.ps1"
$blank = Join-Path $side "SendBlankFrame.ps1"
$installer = Join-Path $Root "scripts\install-startup-admin.ps1"
$installerCmd = Join-Path $Root "scripts\install-startup-admin.cmd"
$start = Join-Path $Root "scripts\start.ps1"

foreach ($path in @($watchdog, $watchdogLauncher, $stop, $blank)) {
    if (!(Test-Path -LiteralPath $path)) {
        throw "Missing power management script: $path"
    }
}

$watchdogText = Get-Content -Raw -LiteralPath $watchdog
foreach ($pattern in @(
    "Win32_PowerManagementEvent",
    "Win32_ComputerShutdownEvent",
    "TURZXSideScreenShutdown",
    "Stop-OtherWatchdogs",
    "cleared paused flag at watchdog start",
    "EventType = 4",
    "EventType = 7",
    "EventType = 18",
    "MaxConsecutiveFailures",
    "SendBlankFrame.ps1",
    "StopSideScreenStack.ps1",
    "StartSideScreenStack.ps1",
    "-Worker"
)) {
    if ($watchdogText -notmatch [regex]::Escape($pattern)) {
        throw "Watchdog missing expected pattern: $pattern"
    }
}

foreach ($pattern in @(
    'Send-Blank -Reason "shutdown"',
    'Send-Blank -Reason "watchdog-exit"'
)) {
    if ($watchdogText -notmatch [regex]::Escape($pattern)) {
        throw "Watchdog must blank the panel during shutdown and watchdog exit; missing: $pattern"
    }
}

$stackText = Get-Content -Raw -LiteralPath $stack
foreach ($pattern in @("StartSideScreenWatchdog.ps1", '[switch]$Worker')) {
    if ($stackText -notmatch [regex]::Escape($pattern)) {
        throw "Stack entrypoint must delegate to watchdog unless called as worker; missing: $pattern"
    }
}

$installerText = Get-Content -Raw -LiteralPath $installer
foreach ($pattern in @("wscript.exe", "StartSideScreenWatchdog-Hidden.vbs")) {
    if ($installerText -notmatch [regex]::Escape($pattern)) {
        throw "Startup installer must point the scheduled task at hidden watchdog launcher; missing: $pattern"
    }
}

$watchdogLauncherText = Get-Content -Raw -LiteralPath $watchdogLauncher
foreach ($pattern in @("StartSideScreenWatchdog.ps1", "shell.Run(command, 0, True)")) {
    if ($watchdogLauncherText -notmatch [regex]::Escape($pattern)) {
        throw "Hidden watchdog launcher missing expected pattern: $pattern"
    }
}

$installerCmdText = Get-Content -Raw -LiteralPath $installerCmd
foreach ($pattern in @("Start-Process", "-Verb RunAs", "install-startup-admin.ps1", "-Root")) {
    if ($installerCmdText -notmatch [regex]::Escape($pattern)) {
        throw "Admin startup cmd wrapper missing expected pattern: $pattern"
    }
}
if ($installerCmdText -match [regex]::Escape("-NoExit")) {
    throw "Admin startup cmd wrapper must not leave an elevated PowerShell window open."
}

$startText = Get-Content -Raw -LiteralPath $start
foreach ($pattern in @("schtasks.exe", "TURZX SideScreen", "StartSideScreenWatchdog.ps1", "restart-on-start.flag")) {
    if ($startText -notmatch [regex]::Escape($pattern)) {
        throw "Desktop start path missing expected pattern: $pattern"
    }
}

$stopText = Get-Content -Raw -LiteralPath $stop
if ($stopText -notmatch [regex]::Escape("SkipStackEntrypoint")) {
    throw "Stop script must support SkipStackEntrypoint for elevated self-cleanup."
}

foreach ($pattern in @("restart-on-start.flag", "StopSideScreenStack.ps1", "SkipStackEntrypoint")) {
    if ($stackText -notmatch [regex]::Escape($pattern)) {
        throw "Stack entrypoint missing elevated cleanup pattern: $pattern"
    }
}

if ($stopText -notmatch [regex]::Escape("taskkill.exe")) {
    throw "Stop script must use taskkill.exe as a hard fallback for crashed elevated stream processes."
}

if ($stopText -notmatch [regex]::Escape("ParentProcessId")) {
    throw "Stop script must kill parent PowerShell processes for crashed stream children."
}

powershell -NoProfile -ExecutionPolicy Bypass -File $blank -Root $Root -DryRun | Out-Host
$blankPng = Join-Path $side "out\blank-screen.png"
if (!(Test-Path -LiteralPath $blankPng)) {
    throw "Blank PNG was not created: $blankPng"
}

$item = Get-Item -LiteralPath $blankPng
if ($item.Length -le 1000) {
    throw "Blank PNG is unexpectedly small: $($item.Length)"
}

Write-Host "Power watchdog checks completed."

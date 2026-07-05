param(
    [string]$Root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$side = Join-Path $Root "tools\turzx_side_screen"
$watchdog = Join-Path $side "StartSideScreenWatchdog.ps1"
$stack = Join-Path $side "StartSideScreenStack.ps1"
$stop = Join-Path $side "StopSideScreenStack.ps1"
$blank = Join-Path $side "SendBlankFrame.ps1"
$installer = Join-Path $Root "scripts\install-startup-admin.ps1"
$start = Join-Path $Root "scripts\start.ps1"

foreach ($path in @($watchdog, $stop, $blank)) {
    if (!(Test-Path -LiteralPath $path)) {
        throw "Missing power management script: $path"
    }
}

$watchdogText = Get-Content -Raw -LiteralPath $watchdog
foreach ($pattern in @(
    "Win32_PowerManagementEvent",
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

$stackText = Get-Content -Raw -LiteralPath $stack
foreach ($pattern in @("StartSideScreenWatchdog.ps1", '[switch]$Worker')) {
    if ($stackText -notmatch [regex]::Escape($pattern)) {
        throw "Stack entrypoint must delegate to watchdog unless called as worker; missing: $pattern"
    }
}

$installerText = Get-Content -Raw -LiteralPath $installer
if ($installerText -notmatch [regex]::Escape("StartSideScreenWatchdog.ps1")) {
    throw "Startup installer must point the scheduled task at StartSideScreenWatchdog.ps1."
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

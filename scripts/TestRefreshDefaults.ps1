param(
    [string]$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$Root = (Resolve-Path -LiteralPath $Root).Path

$defaultFiles = @(
    "scripts\start.ps1",
    "scripts\install-startup-admin.ps1",
    "scripts\create-desktop-shortcut.ps1",
    "scripts\repair-elevated.ps1",
    "tools\turzx_side_screen\StartSideScreenStack.ps1",
    "tools\turzx_side_screen\StartSideScreenWatchdog.ps1",
    "tools\turzx_side_screen\InstallStartupTask-Admin.ps1"
)

foreach ($relative in $defaultFiles) {
    $path = Join-Path $Root $relative
    $text = Get-Content -Raw -LiteralPath $path
    if ($text -notmatch [regex]::Escape('[int]$IntervalMs = 1000')) {
        throw "Main refresh default should be 1000ms in $relative"
    }
}

$explicitEntries = @(
    "start-side-screen.cmd",
    "scripts\repair-elevated.cmd",
    "README.md",
    "docs\startup.md",
    "docs\architecture.md"
)

foreach ($relative in $explicitEntries) {
    $path = Join-Path $Root $relative
    $text = Get-Content -Raw -LiteralPath $path
    if ($text -match [regex]::Escape("-IntervalMs 500") -or
        $text -match [regex]::Escape("0.5s updates") -or
        $text -match [regex]::Escape('Default refresh: `500ms`')) {
        throw "Public entry or docs still advertise 500ms refresh: $relative"
    }
}

Write-Host "Refresh default checks completed."

param(
    [string]$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$shortcutScript = Join-Path $Root "scripts\create-desktop-shortcut.ps1"
if (!(Test-Path -LiteralPath $shortcutScript)) {
    throw "Missing shortcut script: $shortcutScript"
}

$shortcutText = Get-Content -Raw -LiteralPath $shortcutScript
foreach ($pattern in @(
    '[switch]$DryRun',
    'GetFolderPath("Desktop")',
    'GetFolderPath("Programs")',
    'TURZX SideScreen.lnk',
    'CreateShortcut'
)) {
    if ($shortcutText -notmatch [regex]::Escape($pattern)) {
        throw "Shortcut script missing expected pattern: $pattern"
    }
}

$output = powershell -NoProfile -ExecutionPolicy Bypass -File $shortcutScript -Root $Root -DryRun | Out-String
if ($LASTEXITCODE -ne 0) {
    throw "Shortcut dry-run failed."
}

foreach ($pattern in @("Desktop shortcut:", "Start menu shortcut:")) {
    if ($output -notmatch [regex]::Escape($pattern)) {
        throw "Shortcut dry-run missing expected output: $pattern"
    }
}

Write-Host "Shortcut script checks completed."

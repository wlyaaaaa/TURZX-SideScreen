param(
    [string]$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path,
    [string]$ShortcutName = "TURZX SideScreen Start.lnk",
    [string]$Port = "COM7",
    [int]$IntervalMs = 500
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$Root = (Resolve-Path -LiteralPath $Root).Path
$startScript = Join-Path $Root "scripts\start.ps1"
if (!(Test-Path -LiteralPath $startScript)) {
    throw "Missing start script: $startScript"
}

$desktop = [Environment]::GetFolderPath("Desktop")
if ([string]::IsNullOrWhiteSpace($desktop)) {
    throw "Desktop path not found."
}

$shortcutPath = Join-Path $desktop $ShortcutName
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = Join-Path $env:WINDIR "System32\WindowsPowerShell\v1.0\powershell.exe"
$shortcut.Arguments = ('-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "{0}" -Root "{1}" -Port {2} -IntervalMs {3}' -f $startScript, $Root, $Port, $IntervalMs)
$shortcut.WorkingDirectory = $Root
$shortcut.IconLocation = Join-Path $env:WINDIR "System32\shell32.dll,25"
$shortcut.Description = "Start or restart the TURZX side screen watchdog."
$shortcut.Save()

Write-Host ("Desktop shortcut: {0}" -f $shortcutPath)

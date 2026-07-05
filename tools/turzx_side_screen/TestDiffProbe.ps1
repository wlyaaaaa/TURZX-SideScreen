Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path

powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $scriptDir "StartDiffProbe.ps1") -DryRun -Frames 2 -IntervalMs 10 | Out-Host

$preview = Join-Path $scriptDir "out\diff-probe\diff-last.png"
if (!(Test-Path -LiteralPath $preview)) {
    throw "Missing diff probe preview: $preview"
}

$item = Get-Item -LiteralPath $preview
if ($item.Length -le 0) {
    throw "Diff probe preview is empty: $preview"
}

Write-Host ("OK {0} bytes -> {1}" -f $item.Length, $item.FullName)

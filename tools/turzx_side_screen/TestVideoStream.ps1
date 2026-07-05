Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path

powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $scriptDir "StartVideoStream.ps1") -Sample -DryRun -Diff -Frames 2 -IntervalMs 10 | Out-Host

$preview = Join-Path $scriptDir "out\stream\stream-last.png"
if (!(Test-Path -LiteralPath $preview)) {
    throw "Missing stream preview: $preview"
}

$item = Get-Item -LiteralPath $preview
if ($item.Length -le 0) {
    throw "Stream preview is empty: $preview"
}

Write-Host ("OK {0} bytes -> {1}" -f $item.Length, $item.FullName)

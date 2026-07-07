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

$heartbeat = Join-Path $scriptDir "out\stream\stream-heartbeat.json"
if (!(Test-Path -LiteralPath $heartbeat)) {
    throw "Missing stream heartbeat: $heartbeat"
}

$heartbeatJson = Get-Content -Raw -LiteralPath $heartbeat | ConvertFrom-Json
if ($heartbeatJson.status -ne "ok") {
    throw "Stream heartbeat status was not ok: $($heartbeatJson.status)"
}
if ([int]$heartbeatJson.frame -lt 2) {
    throw "Stream heartbeat did not reach the dry-run frame count: $($heartbeatJson.frame)"
}
if ([int]$heartbeatJson.failed -ne 0) {
    throw "Stream heartbeat reported failures: $($heartbeatJson.failed)"
}

Write-Host ("OK {0} bytes -> {1}" -f $item.Length, $item.FullName)

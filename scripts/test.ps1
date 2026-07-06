param(
    [string]$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path,
    [switch]$SkipStreamWhenRunning
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$side = Join-Path $Root "tools\turzx_side_screen"
$runningStream = Get-CimInstance Win32_Process |
    Where-Object { $_.Name -like "TURZX.SideScreen.Stream*" -and $_.CommandLine -like "*$Root*" } |
    Select-Object -First 1

python (Join-Path $side "test_metrics_agent.py")
if ($LASTEXITCODE -ne 0) { throw "test_metrics_agent.py failed" }

powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $side "TestRenderer.ps1")
if ($LASTEXITCODE -ne 0) { throw "TestRenderer.ps1 failed" }

powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $side "TestHttpPipeline.ps1")
if ($LASTEXITCODE -ne 0) { throw "TestHttpPipeline.ps1 failed" }

powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $side "TestPowerWatchdog.ps1") -Root $Root
if ($LASTEXITCODE -ne 0) { throw "TestPowerWatchdog.ps1 failed" }

powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $Root "scripts\TestShortcutScripts.ps1") -Root $Root
if ($LASTEXITCODE -ne 0) { throw "TestShortcutScripts.ps1 failed" }

powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $Root "scripts\TestRefreshDefaults.ps1") -Root $Root
if ($LASTEXITCODE -ne 0) { throw "TestRefreshDefaults.ps1 failed" }

powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $side "TestStreamCadence.ps1")
if ($LASTEXITCODE -ne 0) { throw "TestStreamCadence.ps1 failed" }

powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $Root "scripts\test-public-release.ps1")
if ($LASTEXITCODE -ne 0) { throw "test-public-release.ps1 failed" }

if ($runningStream -and $SkipStreamWhenRunning) {
    Write-Host "SKIP TestVideoStream.ps1 because live stream is running: PID=$($runningStream.ProcessId)"
} elseif ($runningStream) {
    Write-Host "SKIP TestVideoStream.ps1 because live stream locks TURZX.SideScreen.Stream.exe. Stop stream or pass -SkipStreamWhenRunning."
} else {
    powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $side "TestVideoStream.ps1")
    if ($LASTEXITCODE -ne 0) { throw "TestVideoStream.ps1 failed" }
}

Write-Host "Core checks completed."

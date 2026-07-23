param(
    [string]$Root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path,
    [string]$Port = "COM7",
    [int]$IntervalMs = 1000,
    [int]$FullResyncEveryFrames = 300,
    [switch]$Worker
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$outDir = Join-Path $scriptDir "out"
$logPath = Join-Path $outDir "side-screen-stack.log"
New-Item -ItemType Directory -Force -Path $outDir | Out-Null

function Write-StackLog {
    param([string]$Message)
    $line = "{0} {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $Message
    Add-Content -LiteralPath $logPath -Value $line -Encoding UTF8
}

if (-not $Worker) {
    $watchdog = Join-Path $scriptDir "StartSideScreenWatchdog.ps1"
    $stopScript = Join-Path $scriptDir "StopSideScreenStack.ps1"
    $restartFlag = Join-Path $outDir "restart-on-start.flag"
    $stopFlag = Join-Path $outDir "stop-on-start.flag"
    if (!(Test-Path -LiteralPath $watchdog)) {
        throw "Missing watchdog script: $watchdog"
    }

    if (Test-Path -LiteralPath $stopFlag) {
        Remove-Item -LiteralPath $stopFlag -Force -ErrorAction SilentlyContinue
        Write-StackLog "stop-on-start flag detected; stopping stack and exiting"
        powershell -NoProfile -ExecutionPolicy Bypass -File $stopScript -Root $Root -IncludeWatchdog -SkipStackEntrypoint -Quiet
        exit 0
    }

    if (Test-Path -LiteralPath $restartFlag) {
        Remove-Item -LiteralPath $restartFlag -Force -ErrorAction SilentlyContinue
        Write-StackLog "restart-on-start flag detected; stopping stale elevated stack first"
        powershell -NoProfile -ExecutionPolicy Bypass -File $stopScript -Root $Root -IncludeWatchdog -SkipStackEntrypoint -Quiet
        Start-Sleep -Seconds 2
    }

    Write-StackLog ("delegating to watchdog root={0} port={1} interval={2}" -f $Root, $Port, $IntervalMs)
    Start-Process -FilePath "powershell.exe" `
        -ArgumentList @(
            "-NoProfile",
            "-ExecutionPolicy", "Bypass",
            "-File", $watchdog,
            "-Root", $Root,
            "-Port", $Port,
            "-IntervalMs", [string]$IntervalMs
            "-FullResyncEveryFrames", [string]$FullResyncEveryFrames
        ) `
        -WorkingDirectory $scriptDir `
        -WindowStyle Hidden | Out-Null
    exit 0
}

function Find-Python {
    $cmd = Get-Command python -ErrorAction SilentlyContinue
    if ($cmd -and (Test-Path -LiteralPath $cmd.Source)) {
        return $cmd.Source
    }

    $candidates = @(
        (Join-Path $env:LOCALAPPDATA "Programs\Python\Python311\python.exe"),
        (Join-Path $env:LOCALAPPDATA "Microsoft\WindowsApps\python.exe")
    )

    foreach ($candidate in $candidates) {
        if (Test-Path -LiteralPath $candidate) {
            return $candidate
        }
    }

    throw "python.exe not found"
}

function Stop-ProcessByCommandLine {
    param(
        [string]$NamePattern,
        [string]$CommandPattern
    )

    Get-CimInstance Win32_Process |
        Where-Object { $_.Name -like $NamePattern -and $_.CommandLine -like $CommandPattern } |
        ForEach-Object {
            Write-StackLog ("stopping PID={0} CMD={1}" -f $_.ProcessId, $_.CommandLine)
            Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
        }
}

Write-StackLog ("starting stack root={0} port={1} interval={2}" -f $Root, $Port, $IntervalMs)

# Keep the custom side-screen stack authoritative.
Get-Process "TURZX", "TURZX.weatherfix", "TURZX.weatherfix.metrics" -ErrorAction SilentlyContinue |
    Stop-Process -Force -ErrorAction SilentlyContinue

Stop-ProcessByCommandLine -NamePattern "python*" -CommandPattern "*turzx_side_screen\metrics_agent.py*"
Stop-ProcessByCommandLine -NamePattern "python*" -CommandPattern "*turzx_side_screen\top_processes_helper.py*"
Stop-ProcessByCommandLine -NamePattern "python*" -CommandPattern "*turzx_weather_shim\turzx_weather_shim.py*"
Stop-ProcessByCommandLine -NamePattern "TURZX.SideScreen.Stream.exe" -CommandPattern "*turzx_side_screen*"

$python = Find-Python
$weatherShim = Join-Path $Root "tools\turzx_weather_shim\turzx_weather_shim.py"
$weatherDir = Split-Path -Parent $weatherShim
Start-Process -FilePath $python `
    -ArgumentList @($weatherShim, "--host", "127.0.0.1", "--port", "18080") `
    -WorkingDirectory $weatherDir `
    -WindowStyle Hidden
Write-StackLog "weather shim launched"

Start-Process -FilePath $python `
    -ArgumentList @((Join-Path $scriptDir "top_processes_helper.py"), "--cache-path", (Join-Path $outDir "top-processes.json"), "--interval-seconds", "3", "--limit", "5") `
    -WorkingDirectory $scriptDir `
    -WindowStyle Hidden
Write-StackLog "top processes helper launched"

Start-Sleep -Milliseconds 900

$streamScript = Join-Path $scriptDir "StartVideoStream.ps1"
& $streamScript -Root $Root -Port $Port -IntervalMs $IntervalMs -Frames 0 -FullResyncEveryFrames $FullResyncEveryFrames -Diff

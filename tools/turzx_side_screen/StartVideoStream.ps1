param(
    [string]$Root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path,
    [string]$Port = "COM7",
    [int]$IntervalMs = 3000,
    [int]$Frames = 0,
    [int]$MaxConsecutiveSendFailures = 5,
    [int]$FullResyncEveryFrames = 300,
    [switch]$Sample,
    [switch]$DryRun,
    [switch]$Diff,
    [switch]$AltHelper
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$outDir = Join-Path $scriptDir "out"
$exePath = Join-Path $outDir "TURZX.SideScreen.Stream.exe"
$previewDir = Join-Path $outDir "stream"
$metricsUrl = "http://127.0.0.1:18765/snapshot"

New-Item -ItemType Directory -Force -Path $outDir | Out-Null
New-Item -ItemType Directory -Force -Path $previewDir | Out-Null

function Test-MetricsEndpointReady {
    try {
        $probe = Invoke-WebRequest -UseBasicParsing -Uri $metricsUrl -TimeoutSec 2
        return $probe.StatusCode -eq 200 -and -not [string]::IsNullOrWhiteSpace($probe.Content)
    }
    catch {
        return $false
    }
}

function Wait-MetricsEndpointReady {
    param([int]$TimeoutSeconds = 10)

    $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    do {
        if (Test-MetricsEndpointReady) {
            return
        }
        Start-Sleep -Milliseconds 250
    } while ([DateTime]::UtcNow -lt $deadline)

    throw "metrics endpoint did not become ready within $TimeoutSeconds seconds"
}

$cscCommand = Get-Command csc -ErrorAction SilentlyContinue
$cscPath = $null
if ($null -ne $cscCommand) {
    $cscPath = $cscCommand.Source
}
if ([string]::IsNullOrWhiteSpace($cscPath)) {
    $frameworkCsc = Join-Path $env:WINDIR "Microsoft.NET\Framework64\v4.0.30319\csc.exe"
    if (Test-Path $frameworkCsc) {
        $cscPath = $frameworkCsc
    }
}
if ([string]::IsNullOrWhiteSpace($cscPath)) {
    throw "csc.exe not found."
}

if (Get-Process "TURZX.SideScreen.Stream*" -ErrorAction SilentlyContinue) {
    $exePath = Join-Path $outDir ("TURZX.SideScreen.Stream.{0}.exe" -f $PID)
}

$sources = @(
    (Join-Path $scriptDir "SnapshotModels.cs"),
    (Join-Path $scriptDir "TURZX.SideScreen.Renderer.cs"),
    (Join-Path $scriptDir "TURZX.SideScreen.TurzxHelperSender.cs"),
    (Join-Path $scriptDir "TURZX.SideScreen.Stream.cs")
)

& $cscPath /nologo /codepage:65001 /utf8output /target:exe /out:$exePath /r:System.dll /r:System.Core.dll /r:System.Drawing.dll /r:System.Runtime.Serialization.dll $sources
if ($LASTEXITCODE -ne 0) {
    throw "csc failed with exit code $LASTEXITCODE"
}

$agentProcess = $null
if (!$Sample -and !$DryRun) {
    $agent = Join-Path $scriptDir "metrics_agent.py"
    $existingAgent = Get-CimInstance Win32_Process |
        Where-Object { $_.Name -like "python*" -and $_.CommandLine -like "*$agent*" } |
        Select-Object -First 1

    if (!(Test-MetricsEndpointReady) -and !$existingAgent) {
        $agentProcess = Start-Process -FilePath python -ArgumentList @($agent, "--host", "127.0.0.1", "--port", "18765") -WindowStyle Hidden -PassThru
    }

    Wait-MetricsEndpointReady
}

try {
    $argsList = @("--root", $Root, "--port", $Port, "--interval-ms", [string]$IntervalMs, "--frames", [string]$Frames, "--max-consecutive-send-failures", [string]$MaxConsecutiveSendFailures, "--full-resync-every-frames", [string]$FullResyncEveryFrames, "--preview-dir", $previewDir)
    if ($Sample) { $argsList += "--sample" }
    if ($DryRun) { $argsList += "--dry-run" }
    if ($Diff) { $argsList += "--diff" }
    if ($AltHelper) { $argsList += "--alt-helper" }
    & $exePath @argsList
    if ($LASTEXITCODE -ne 0) {
        throw "stream failed with exit code $LASTEXITCODE"
    }
}
finally {
    if ($agentProcess -and !$agentProcess.HasExited) {
        Stop-Process -Id $agentProcess.Id -Force
    }
}

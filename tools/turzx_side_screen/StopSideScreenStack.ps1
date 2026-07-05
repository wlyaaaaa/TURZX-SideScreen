param(
    [string]$Root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path,
    [switch]$IncludeWatchdog,
    [switch]$SkipStackEntrypoint,
    [switch]$Quiet
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$Root = (Resolve-Path -LiteralPath $Root).Path
$side = Join-Path $Root "tools\turzx_side_screen"
$weather = Join-Path $Root "tools\turzx_weather_shim"
$outDir = Join-Path $side "out"
$logPath = Join-Path $outDir "side-screen-stop.log"
New-Item -ItemType Directory -Force -Path $outDir | Out-Null

function Write-StopLog {
    param([string]$Message)
    $line = "{0} {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $Message
    Add-Content -LiteralPath $logPath -Value $line -Encoding UTF8
    if (-not $Quiet) {
        Write-Host $line
    }
}

function Stop-MatchingProcess {
    param(
        [scriptblock]$Predicate,
        [string]$Reason
    )

    Get-CimInstance Win32_Process |
        Where-Object {
            $_.ProcessId -ne $PID -and (& $Predicate $_)
        } |
        ForEach-Object {
            Write-StopLog ("stopping PID={0} reason={1} CMD={2}" -f $_.ProcessId, $Reason, $_.CommandLine)
            Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
        }
}

$sidePattern = "*" + $side + "*"
$weatherPattern = "*" + $weather + "*"

Stop-MatchingProcess -Reason "metrics-agent" -Predicate {
    param($p)
    $p.Name -like "python*" -and $p.CommandLine -like "*turzx_side_screen\metrics_agent.py*" -and $p.CommandLine -like $sidePattern
}

Stop-MatchingProcess -Reason "top-processes-helper" -Predicate {
    param($p)
    $p.Name -like "python*" -and $p.CommandLine -like "*turzx_side_screen\top_processes_helper.py*" -and $p.CommandLine -like $sidePattern
}

Stop-MatchingProcess -Reason "weather-shim" -Predicate {
    param($p)
    $p.Name -like "python*" -and $p.CommandLine -like "*turzx_weather_shim\turzx_weather_shim.py*" -and $p.CommandLine -like $weatherPattern
}

Stop-MatchingProcess -Reason "stream-exe" -Predicate {
    param($p)
    $p.Name -like "TURZX.SideScreen.Stream*" -and $p.CommandLine -like $sidePattern
}

$streamParents = @(Get-CimInstance Win32_Process |
    Where-Object { $_.Name -like "TURZX.SideScreen.Stream*" } |
    Select-Object -ExpandProperty ParentProcessId -Unique |
    Where-Object { $_ -and $_ -ne $PID })
foreach ($parentPid in $streamParents) {
    try {
        Write-StopLog ("stopping stream parent PID={0}" -f $parentPid)
        Stop-Process -Id $parentPid -Force -ErrorAction SilentlyContinue
        $parentKillOutput = & taskkill.exe /PID $parentPid /F /T 2>&1
        foreach ($line in $parentKillOutput) {
            Write-StopLog ("taskkill stream parent: {0}" -f $line)
        }
    }
    catch {
        Write-StopLog ("stream parent kill failed PID={0}: {1}" -f $parentPid, $_.Exception.Message)
    }
}

try {
    $taskkillOutput = & taskkill.exe /IM "TURZX.SideScreen.Stream.exe" /F /T 2>&1
    foreach ($line in $taskkillOutput) {
        Write-StopLog ("taskkill stream: {0}" -f $line)
    }
}
catch {
    Write-StopLog ("taskkill stream failed: {0}" -f $_.Exception.Message)
}

if (-not $SkipStackEntrypoint) {
    Stop-MatchingProcess -Reason "stack-script" -Predicate {
        param($p)
        ($p.Name -like "powershell*" -or $p.Name -like "pwsh*") -and
            $p.CommandLine -like "*StartSideScreenStack.ps1*" -and
            $p.CommandLine -like $sidePattern
    }
}

if ($IncludeWatchdog) {
    Stop-MatchingProcess -Reason "watchdog-script" -Predicate {
        param($p)
        ($p.Name -like "powershell*" -or $p.Name -like "pwsh*") -and
            $p.CommandLine -like "*StartSideScreenWatchdog.ps1*" -and
            $p.CommandLine -like $sidePattern
    }
}

foreach ($pidFile in @("video-stream.pid", "side-screen-stack-child.pid")) {
    $path = Join-Path $outDir $pidFile
    if (Test-Path -LiteralPath $path) {
        Remove-Item -LiteralPath $path -Force -ErrorAction SilentlyContinue
    }
}

Write-StopLog "stop complete"

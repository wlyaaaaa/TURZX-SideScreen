param(
    [string]$Root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path,
    [string]$Port = "COM7",
    [int]$IntervalMs = 500,
    [int]$ResumeDelaySeconds = 8,
    [int]$PollSeconds = 2,
    [int]$MaxConsecutiveFailures = 3,
    [switch]$NoPowerEvents
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$Root = (Resolve-Path -LiteralPath $Root).Path
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$outDir = Join-Path $scriptDir "out"
$logPath = Join-Path $outDir "side-screen-watchdog.log"
$stdoutPath = Join-Path $outDir "side-screen-stack.stdout.log"
$stderrPath = Join-Path $outDir "side-screen-stack.stderr.log"
$childPidPath = Join-Path $outDir "side-screen-stack-child.pid"
$watchdogPidPath = Join-Path $outDir "side-screen-watchdog.pid"
$pausedPath = Join-Path $outDir "side-screen-watchdog.paused"
$stackScript = Join-Path $scriptDir "StartSideScreenStack.ps1"
$stopScript = Join-Path $scriptDir "StopSideScreenStack.ps1"
$blankScript = Join-Path $scriptDir "SendBlankFrame.ps1"
$sourceId = "TURZXSideScreenPower"

New-Item -ItemType Directory -Force -Path $outDir | Out-Null
Set-Content -LiteralPath $watchdogPidPath -Value $PID -Encoding ASCII

function Write-WatchdogLog {
    param([string]$Message)
    $line = "{0} {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $Message
    Add-Content -LiteralPath $logPath -Value $line -Encoding UTF8
    Write-Host $line
}

function Stop-Stack {
    param([string]$Reason)
    Write-WatchdogLog ("stop stack reason={0}" -f $Reason)
    powershell -NoProfile -ExecutionPolicy Bypass -File $stopScript -Root $Root -Quiet | Out-Null
}

function Start-Stack {
    param([string]$Reason)
    Stop-Stack -Reason ("pre-start/{0}" -f $Reason)
    Write-WatchdogLog ("start stack reason={0} root={1} port={2} interval={3}" -f $Reason, $Root, $Port, $IntervalMs)
    $arguments = @(
        "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-File", $stackScript,
        "-Root", $Root,
        "-Port", $Port,
        "-IntervalMs", [string]$IntervalMs,
        "-Worker"
    )
    $process = Start-Process -FilePath "powershell.exe" -ArgumentList $arguments -WindowStyle Hidden -RedirectStandardOutput $stdoutPath -RedirectStandardError $stderrPath -PassThru
    Set-Content -LiteralPath $childPidPath -Value $process.Id -Encoding ASCII
    Write-WatchdogLog ("stack child pid={0}" -f $process.Id)
    return $process
}

function Send-Blank {
    param([string]$Reason)
    Write-WatchdogLog ("send blank reason={0}" -f $Reason)
    try {
        powershell -NoProfile -ExecutionPolicy Bypass -File $blankScript -Root $Root -Port $Port -TimeoutMs 15000 | Out-Null
    }
    catch {
        Write-WatchdogLog ("blank failed: {0}" -f $_.Exception.Message)
    }
}

Get-EventSubscriber -SourceIdentifier $sourceId -ErrorAction SilentlyContinue |
    Unregister-Event -ErrorAction SilentlyContinue
Get-Event -SourceIdentifier $sourceId -ErrorAction SilentlyContinue |
    Remove-Event -ErrorAction SilentlyContinue

$subscription = $null
if (-not $NoPowerEvents) {
    $powerQuery = "SELECT * FROM Win32_PowerManagementEvent WHERE EventType = 4 OR EventType = 7 OR EventType = 18"
    $subscription = Register-WmiEvent -Query $powerQuery -SourceIdentifier $sourceId
    Write-WatchdogLog "registered Win32_PowerManagementEvent watcher: EventType = 4 suspend, EventType = 7 resume, EventType = 18 automatic resume"
}

$child = $null
$consecutiveFailures = 0
try {
    $child = Start-Stack -Reason "watchdog-start"
    while ($true) {
        $event = $null
        if (-not $NoPowerEvents) {
            $event = Wait-Event -SourceIdentifier $sourceId -Timeout $PollSeconds
        }
        else {
            Start-Sleep -Seconds $PollSeconds
        }

        if ($event) {
            try {
                $eventType = [int]$event.SourceEventArgs.NewEvent.EventType
                Write-WatchdogLog ("power event type={0}" -f $eventType)
                if ($eventType -eq 4) {
                    Stop-Stack -Reason "suspend"
                    Send-Blank -Reason "suspend"
                }
                elseif ($eventType -eq 7 -or $eventType -eq 18) {
                    $consecutiveFailures = 0
                    Remove-Item -LiteralPath $pausedPath -Force -ErrorAction SilentlyContinue
                    Stop-Stack -Reason "resume"
                    Start-Sleep -Seconds $ResumeDelaySeconds
                    $child = Start-Stack -Reason ("resume-event-{0}" -f $eventType)
                }
            }
            finally {
                Remove-Event -EventIdentifier $event.EventIdentifier -ErrorAction SilentlyContinue
            }
        }

        if ($child -and $child.HasExited) {
            $consecutiveFailures++
            Write-WatchdogLog ("stack child exited code={0}; consecutiveFailures={1}" -f $child.ExitCode, $consecutiveFailures)
            if ($consecutiveFailures -ge $MaxConsecutiveFailures) {
                Set-Content -LiteralPath $pausedPath -Value (Get-Date -Format "o") -Encoding ASCII
                Write-WatchdogLog ("max consecutive failures reached ({0}); watchdog paused" -f $MaxConsecutiveFailures)
                break
            }
            Start-Sleep -Seconds 3
            $child = Start-Stack -Reason "child-exit"
        }
    }
}
finally {
    if ($subscription) {
        Unregister-Event -SourceIdentifier $sourceId -ErrorAction SilentlyContinue
    }
    Stop-Stack -Reason "watchdog-exit"
    Remove-Item -LiteralPath $watchdogPidPath -Force -ErrorAction SilentlyContinue
}

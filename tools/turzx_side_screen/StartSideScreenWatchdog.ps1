param(
    [string]$Root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path,
    [string]$Port = "COM7",
    [int]$IntervalMs = 1000,
    [int]$ResumeDelaySeconds = 8,
    [int]$QuickBlankTimeoutMs = 2500,
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
$powerSourceId = "TURZXSideScreenPower"
$shutdownSourceId = "TURZXSideScreenShutdown"

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
    param(
        [string]$Reason,
        [int]$TimeoutMs = 15000
    )
    Write-WatchdogLog ("send blank reason={0} timeoutMs={1}" -f $Reason, $TimeoutMs)
    try {
        powershell -NoProfile -ExecutionPolicy Bypass -File $blankScript -Root $Root -Port $Port -TimeoutMs $TimeoutMs | Out-Null
    }
    catch {
        Write-WatchdogLog ("blank failed: {0}" -f $_.Exception.Message)
    }
}

function Stop-OtherWatchdogs {
    param([string]$Reason)

    $rootPattern = "*" + $Root + "*"
    $stopped = 0
    Get-CimInstance Win32_Process |
        Where-Object {
            $_.ProcessId -ne $PID -and
            ($_.Name -like "powershell*" -or $_.Name -like "pwsh*") -and
            $_.CommandLine -like "*-File*StartSideScreenWatchdog.ps1*" -and
            $_.CommandLine -like "*StartSideScreenWatchdog.ps1*" -and
            $_.CommandLine -like $rootPattern
        } |
        ForEach-Object {
            $stopped++
            Write-WatchdogLog ("stopping old watchdog PID={0} reason={1}" -f $_.ProcessId, $Reason)
            Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
        }

    if ($stopped -gt 0) {
        Start-Sleep -Milliseconds 1500
    }
}

$watchdogMutexName = "Global\TURZX.SideScreen.Watchdog"
$watchdogMutexCreated = $false
$watchdogMutex = $null
try {
    $watchdogMutex = New-Object System.Threading.Mutex($true, $watchdogMutexName, [ref]$watchdogMutexCreated)
}
catch {
    Write-WatchdogLog ("failed to create watchdog mutex: {0}" -f $_.Exception.Message)
    exit 1
}

if (-not $watchdogMutexCreated) {
    Write-WatchdogLog "duplicate watchdog detected; keeping existing instance"
    $watchdogMutex.Dispose()
    exit 0
}

foreach ($eventSourceId in @($powerSourceId, $shutdownSourceId)) {
    Get-EventSubscriber -SourceIdentifier $eventSourceId -ErrorAction SilentlyContinue |
        Unregister-Event -ErrorAction SilentlyContinue
    Get-Event -SourceIdentifier $eventSourceId -ErrorAction SilentlyContinue |
        Remove-Event -ErrorAction SilentlyContinue
}

Stop-OtherWatchdogs -Reason "watchdog-start"
Remove-Item -LiteralPath $pausedPath -Force -ErrorAction SilentlyContinue
Write-WatchdogLog "cleared paused flag at watchdog start"

$powerSubscription = $null
$shutdownSubscription = $null
if (-not $NoPowerEvents) {
    $powerQuery = "SELECT * FROM Win32_PowerManagementEvent WHERE EventType = 4 OR EventType = 7 OR EventType = 18"
    $powerSubscription = Register-WmiEvent -Query $powerQuery -SourceIdentifier $powerSourceId
    Write-WatchdogLog "registered Win32_PowerManagementEvent watcher: EventType = 4 suspend, EventType = 7 resume, EventType = 18 automatic resume"
    $shutdownSubscription = Register-WmiEvent -Query "SELECT * FROM Win32_ComputerShutdownEvent" -SourceIdentifier $shutdownSourceId
    Write-WatchdogLog "registered Win32_ComputerShutdownEvent watcher for shutdown/restart blanking"
}

$child = $null
$consecutiveFailures = 0
try {
    $child = Start-Stack -Reason "watchdog-start"
    while ($true) {
        $event = $null
        if (-not $NoPowerEvents) {
            $event = Wait-Event -Timeout $PollSeconds
        }
        else {
            Start-Sleep -Seconds $PollSeconds
        }

        if ($event) {
            try {
                if ($event.SourceIdentifier -eq $powerSourceId) {
                    $eventType = [int]$event.SourceEventArgs.NewEvent.EventType
                    Write-WatchdogLog ("power event type={0}" -f $eventType)
                    if ($eventType -eq 4) {
                        Send-Blank -Reason "suspend" -TimeoutMs $QuickBlankTimeoutMs
                        Stop-Stack -Reason "suspend"
                    }
                    elseif ($eventType -eq 7 -or $eventType -eq 18) {
                        $consecutiveFailures = 0
                        Remove-Item -LiteralPath $pausedPath -Force -ErrorAction SilentlyContinue
                        Stop-Stack -Reason "resume"
                        Start-Sleep -Seconds $ResumeDelaySeconds
                        $child = Start-Stack -Reason ("resume-event-{0}" -f $eventType)
                    }
                }
                elseif ($event.SourceIdentifier -eq $shutdownSourceId) {
                    Write-WatchdogLog "computer shutdown/restart event detected"
                    Send-Blank -Reason "shutdown" -TimeoutMs $QuickBlankTimeoutMs
                    Stop-Stack -Reason "shutdown"
                    break
                }
                else {
                    Write-WatchdogLog ("ignored event source={0}" -f $event.SourceIdentifier)
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
    foreach ($eventSourceId in @($powerSourceId, $shutdownSourceId)) {
        Get-EventSubscriber -SourceIdentifier $eventSourceId -ErrorAction SilentlyContinue |
            Unregister-Event -ErrorAction SilentlyContinue
        Get-Event -SourceIdentifier $eventSourceId -ErrorAction SilentlyContinue |
            Remove-Event -ErrorAction SilentlyContinue
    }
    Stop-Stack -Reason "watchdog-exit"
    Send-Blank -Reason "watchdog-exit" -TimeoutMs $QuickBlankTimeoutMs
    Remove-Item -LiteralPath $watchdogPidPath -Force -ErrorAction SilentlyContinue
    if ($watchdogMutex) {
        $watchdogMutex.ReleaseMutex()
        $watchdogMutex.Dispose()
    }
}

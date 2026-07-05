Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$pidPath = Join-Path $scriptDir "out\video-stream.pid"

if (!(Test-Path -LiteralPath $pidPath)) {
    Write-Host "No video-stream.pid found."
    exit 0
}

$pidValue = Get-Content -LiteralPath $pidPath | Select-Object -First 1
if ([string]::IsNullOrWhiteSpace($pidValue)) {
    Remove-Item -LiteralPath $pidPath -Force
    Write-Host "Empty PID file removed."
    exit 0
}

$process = Get-Process -Id ([int]$pidValue) -ErrorAction SilentlyContinue
if ($process) {
    Stop-Process -Id $process.Id -Force
    Write-Host ("Stopped TURZX video stream PID {0}" -f $process.Id)
} else {
    Write-Host ("No running process for PID {0}" -f $pidValue)
}

$streamExe = Join-Path $scriptDir "out\TURZX.SideScreen.Stream.exe"
Get-CimInstance Win32_Process |
    Where-Object { $_.ExecutablePath -eq $streamExe } |
    ForEach-Object {
        Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
        Write-Host ("Stopped TURZX stream child PID {0}" -f $_.ProcessId)
    }

Remove-Item -LiteralPath $pidPath -Force

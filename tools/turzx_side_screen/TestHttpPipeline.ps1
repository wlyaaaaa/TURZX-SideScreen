Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$agent = Join-Path $root "metrics_agent.py"
$exe = Join-Path $root "out\TURZX.SideScreen.exe"
$out = Join-Path $root "out\side-screen-http-preview.png"

powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $root "TestSideScreenApp.ps1") | Out-Host

$process = $null
try {
    $process = Start-Process -FilePath python -ArgumentList @($agent, "--host", "127.0.0.1", "--port", "18765") -WindowStyle Hidden -PassThru
    Start-Sleep -Milliseconds 900

    & $exe --metrics-url "http://127.0.0.1:18765/snapshot" --timeout-ms 5000 --output $out
    if ($LASTEXITCODE -ne 0) {
        throw "SideScreen exe failed with exit code $LASTEXITCODE"
    }

    $preview = Get-Item -LiteralPath $out
    if ($preview.Length -le 0) {
        throw "HTTP preview file is empty: $out"
    }

    Write-Host ("OK {0} bytes -> {1}" -f $preview.Length, $preview.FullName)
}
finally {
    if ($process -and !$process.HasExited) {
        Stop-Process -Id $process.Id -Force
    }
}

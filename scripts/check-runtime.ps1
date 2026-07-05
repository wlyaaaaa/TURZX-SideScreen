param(
    [string]$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path,
    [switch]$AsJson
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Find-Csc {
    $command = Get-Command csc -ErrorAction SilentlyContinue
    if ($null -ne $command) {
        return $command.Source
    }

    $frameworkCsc = Join-Path $env:WINDIR "Microsoft.NET\Framework64\v4.0.30319\csc.exe"
    if (Test-Path -LiteralPath $frameworkCsc) {
        return $frameworkCsc
    }
    return $null
}

function Find-Python {
    $command = Get-Command python -ErrorAction SilentlyContinue
    if ($null -ne $command) {
        return $command.Source
    }
    return $null
}

$Root = (Resolve-Path $Root -ErrorAction SilentlyContinue).Path
if ([string]::IsNullOrWhiteSpace($Root)) {
    $Root = (Get-Location).Path
}

$missing = New-Object System.Collections.Generic.List[string]
$found = [ordered]@{}

$python = Find-Python
if ([string]::IsNullOrWhiteSpace($python)) {
    $missing.Add("python")
} else {
    $found.python = $python
}

$csc = Find-Csc
if ([string]::IsNullOrWhiteSpace($csc)) {
    $missing.Add("csc.exe")
} else {
    $found.csc = $csc
}

$rjcp = Join-Path $Root "RJCP.SerialPortStream.dll"
if (!(Test-Path -LiteralPath $rjcp)) {
    $missing.Add("RJCP.SerialPortStream.dll")
} else {
    $found.rjcp = $rjcp
}

$patched = Join-Path $Root "TURZX.weatherfix.metrics.exe"
$stock = Join-Path $Root "TURZX.exe"
if (!(Test-Path -LiteralPath $patched) -and !(Test-Path -LiteralPath $stock)) {
    $missing.Add("TURZX.exe or TURZX.weatherfix.metrics.exe")
} else {
    $found.turzx = if (Test-Path -LiteralPath $patched) { $patched } else { $stock }
}

$stack = Join-Path $Root "tools\turzx_side_screen\StartSideScreenStack.ps1"
if (!(Test-Path -LiteralPath $stack)) {
    $missing.Add("tools\\turzx_side_screen\\StartSideScreenStack.ps1")
} else {
    $found.stack = $stack
}

$payload = [ordered]@{
    ready = ($missing.Count -eq 0)
    root = $Root
    missing = @($missing)
    found = $found
}

if ($AsJson) {
    $payload | ConvertTo-Json -Depth 5 -Compress
} else {
    if ($payload.ready) {
        Write-Host "Runtime ready: $Root"
        $found.GetEnumerator() | ForEach-Object { Write-Host ("OK {0}: {1}" -f $_.Key, $_.Value) }
    } else {
        Write-Host "Runtime is missing required dependencies under: $Root"
        $missing | ForEach-Object { Write-Host ("MISSING " + $_) }
        Write-Host ""
        Write-Host "Install/copy the stock TURZX runtime files next to this repository root:"
        Write-Host "- RJCP.SerialPortStream.dll"
        Write-Host "- TURZX.exe or TURZX.weatherfix.metrics.exe"
    }
}

exit ($(if ($missing.Count -eq 0) { 0 } else { 1 }))

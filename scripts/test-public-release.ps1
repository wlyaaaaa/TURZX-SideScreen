Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$checker = Join-Path $root "scripts\check-runtime.ps1"
if (!(Test-Path -LiteralPath $checker)) {
    throw "Missing runtime checker: $checker"
}

$tempRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("turzx_public_release_" + [Guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Force -Path $tempRoot | Out-Null

try {
    $missingOutput = & powershell -NoProfile -ExecutionPolicy Bypass -File $checker -Root $tempRoot -AsJson 2>$null
    if ($LASTEXITCODE -eq 0) {
        throw "Runtime checker should fail when vendor runtime files are missing."
    }

    $missing = $missingOutput | ConvertFrom-Json
    if (-not ($missing.missing -contains "RJCP.SerialPortStream.dll")) {
        throw "Missing output did not mention RJCP.SerialPortStream.dll"
    }
    if (-not ($missing.missing -contains "TURZX.exe or TURZX.weatherfix.metrics.exe")) {
        throw "Missing output did not mention TURZX runtime executable"
    }

    New-Item -ItemType File -Force -Path (Join-Path $tempRoot "RJCP.SerialPortStream.dll") | Out-Null
    New-Item -ItemType File -Force -Path (Join-Path $tempRoot "TURZX.weatherfix.metrics.exe") | Out-Null
    $stackDir = Join-Path $tempRoot "tools\turzx_side_screen"
    New-Item -ItemType Directory -Force -Path $stackDir | Out-Null
    New-Item -ItemType File -Force -Path (Join-Path $stackDir "StartSideScreenStack.ps1") | Out-Null

    $okOutput = & powershell -NoProfile -ExecutionPolicy Bypass -File $checker -Root $tempRoot -AsJson
    if ($LASTEXITCODE -ne 0) {
        throw "Runtime checker should pass with required vendor runtime files present."
    }

    $ok = $okOutput | ConvertFrom-Json
    if ($ok.ready -ne $true) {
        throw "Runtime checker JSON did not report ready=true"
    }
}
finally {
    if (Test-Path -LiteralPath $tempRoot) {
        Remove-Item -LiteralPath $tempRoot -Recurse -Force
    }
}

Write-Host "Public release runtime checks verified."

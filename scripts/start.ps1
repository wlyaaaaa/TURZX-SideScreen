param(
    [string]$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path,
    [string]$Port = "COM7",
    [int]$IntervalMs = 500
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$stack = Join-Path $Root "tools\turzx_side_screen\StartSideScreenStack.ps1"
if (!(Test-Path -LiteralPath $stack)) {
    throw "Missing stack script: $stack"
}

$checker = Join-Path $Root "scripts\check-runtime.ps1"
if (Test-Path -LiteralPath $checker) {
    powershell -NoProfile -ExecutionPolicy Bypass -File $checker -Root $Root
    if ($LASTEXITCODE -ne 0) {
        throw "Runtime check failed. See missing dependency list above."
    }
}

powershell -NoProfile -ExecutionPolicy Bypass -File $stack -Root $Root -Port $Port -IntervalMs $IntervalMs

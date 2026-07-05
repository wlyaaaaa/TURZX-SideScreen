Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$outDir = Join-Path $scriptDir "out"
$exePath = Join-Path $outDir "TURZX.SideScreen.exe"
$previewPath = Join-Path $outDir "side-screen-app-preview.png"

New-Item -ItemType Directory -Force -Path $outDir | Out-Null

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
    throw "csc.exe not found. Install .NET Framework Developer Pack or Visual Studio Build Tools."
}

$sources = @(
    (Join-Path $scriptDir "SnapshotModels.cs"),
    (Join-Path $scriptDir "TURZX.SideScreen.Renderer.cs"),
    (Join-Path $scriptDir "TURZX.SideScreen.Protocol.cs"),
    (Join-Path $scriptDir "TURZX.SideScreen.cs")
)

& $cscPath /nologo /codepage:65001 /utf8output /target:exe /out:$exePath /r:System.dll /r:System.Core.dll /r:System.Drawing.dll /r:System.Runtime.Serialization.dll $sources
if ($LASTEXITCODE -ne 0) {
    throw "csc failed with exit code $LASTEXITCODE"
}

& $exePath --sample --output $previewPath
if ($LASTEXITCODE -ne 0) {
    throw "Sample render failed with exit code $LASTEXITCODE"
}

$preview = Get-Item $previewPath
if ($preview.Length -le 0) {
    throw "Preview file is empty: $previewPath"
}

& $exePath --help | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw "Help command failed with exit code $LASTEXITCODE"
}

Write-Host ("OK {0} bytes -> {1}" -f $preview.Length, $preview.FullName)

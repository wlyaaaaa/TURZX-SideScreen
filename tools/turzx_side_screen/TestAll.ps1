$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$tests = @(
    "TestFinalDesign.ps1",
    "test_metrics_agent.py",
    "TestRenderer.ps1",
    "TestProtocolEncoding.ps1",
    "TestSideScreenApp.ps1",
    "TestHttpPipeline.ps1",
    "TestVideoStream.ps1",
    "TestDiffProbe.ps1"
)

foreach ($test in $tests) {
    $path = Join-Path $root $test
    if (!(Test-Path -LiteralPath $path)) {
        "SKIP missing $test"
        continue
    }

    if ($test.EndsWith(".py")) {
        "RUN python $test"
        python $path
        if ($LASTEXITCODE -ne 0) {
            throw "$test failed with exit code $LASTEXITCODE"
        }
    } else {
        "RUN powershell $test"
        powershell -NoProfile -ExecutionPolicy Bypass -File $path
        if ($LASTEXITCODE -ne 0) {
            throw "$test failed with exit code $LASTEXITCODE"
        }
    }
}

"All available side-screen checks completed."

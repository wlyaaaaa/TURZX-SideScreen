Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$outDir = Join-Path $scriptDir "out\tests"
New-Item -ItemType Directory -Force -Path $outDir | Out-Null

$programPath = Join-Path $outDir ("TestStreamCadenceProgram.{0}.cs" -f $PID)
$exePath = Join-Path $outDir ("TestStreamCadenceProgram.{0}.exe" -f $PID)

$program = @'
using System;
using TURZX.SideScreen;

public static class TestStreamCadenceProgram
{
    public static int Main()
    {
        try
        {
            Run();
            Console.WriteLine("OK stream cadence policy");
            return 0;
        }
        catch (Exception ex)
        {
            Console.Error.WriteLine("FAIL " + ex.GetType().Name + ": " + ex.Message);
            return 1;
        }
    }

    private static void Run()
    {
        Equal("sleep keeps one-second start cadence", 980, SideScreenStreamApp.ComputeSleepMillisecondsForTest(1000, 1000, 1020, 1000));
        Equal("sleep clamps overruns", 0, SideScreenStreamApp.ComputeSleepMillisecondsForTest(1000, 1000, 2050, 1000));
        Equal("zero interval does not sleep", 0, SideScreenStreamApp.ComputeSleepMillisecondsForTest(1000, 0, 1001, 1000));

        Snapshot snapshot = new Snapshot
        {
            Time = new TimeSnapshot
            {
                Date = "1999-01-01",
                Weekday = "周五",
                Time = "00:00:00",
                UpdateIntervalSeconds = 0.5
            },
            Health = new HealthSnapshot { RefreshIntervalSeconds = 0.5 }
        };
        SideScreenStreamApp.ApplyStreamIntervalForTest(snapshot, 1000);
        EqualDouble("stream interval overrides health refresh", 1.0, snapshot.Health.RefreshIntervalSeconds.Value);
        EqualDouble("stream interval overrides time refresh", 1.0, ((TimeSnapshot)snapshot.Time).UpdateIntervalSeconds.Value);

        TimeSnapshot header = SideScreenRenderer.ResolveHeaderTimeForTest(
            (TimeSnapshot)snapshot.Time,
            new DateTime(2026, 7, 6, 11, 18, 42));
        Equal("header clock uses render time", "11:18:42", header.Time);
        Equal("header date uses render date", "2026-07-06", header.Date);
        Equal("header weekday uses render weekday", "\u5468\u4e00", header.Weekday);
        EqualDouble("header keeps actual refresh interval", 1.0, header.UpdateIntervalSeconds.Value);

        string fallbackStatus;
        Snapshot reused = SideScreenStreamApp.SelectSnapshotAfterFetchFailureForTest(
            new Snapshot { Sequence = 42 },
            new TimeoutException("slow snapshot"),
            out fallbackStatus);
        Equal("fetch timeout reuses previous snapshot", 42L, reused.Sequence.Value);
        StartsWith("fallback status marks stale data", "stale:TimeoutException", fallbackStatus);

        Snapshot empty = SideScreenStreamApp.SelectSnapshotAfterFetchFailureForTest(
            null,
            new TimeoutException("slow snapshot"),
            out fallbackStatus);
        Equal("missing cache returns empty snapshot sequence", 0L, empty.Sequence.Value);
        StartsWith("missing cache status marks empty data", "empty:TimeoutException", fallbackStatus);

        Equal("device error is classified as send failure", true,
            SideScreenStreamApp.IsLikelyDeviceSendFailureForTest(
                new InvalidOperationException("SendReg false:204 Device Error")));
        Equal("generic render error is not classified as device send failure", false,
            SideScreenStreamApp.IsLikelyDeviceSendFailureForTest(
                new InvalidOperationException("Font render failed")));
        Equal("consecutive send failures below threshold continue", false,
            SideScreenStreamApp.ShouldAbortAfterConsecutiveSendFailuresForTest(2, 3));
        Equal("consecutive send failures at threshold abort", true,
            SideScreenStreamApp.ShouldAbortAfterConsecutiveSendFailuresForTest(3, 3));
        Equal("disabled send failure threshold never aborts", false,
            SideScreenStreamApp.ShouldAbortAfterConsecutiveSendFailuresForTest(99, 0));
        string described = SideScreenStreamApp.DescribeExceptionForTest(
            new System.Reflection.TargetInvocationException(
                new InvalidOperationException("inner device detail")));
        Contains("target invocation description names wrapper", "TargetInvocationException:", described);
        Contains("target invocation description unwraps inner exception", "InvalidOperationException: inner device detail", described);
    }

    private static void Equal(string name, object expected, object actual)
    {
        if (!object.Equals(expected, actual))
        {
            throw new Exception(name + ": expected " + expected + ", got " + actual);
        }
    }

    private static void EqualDouble(string name, double expected, double actual)
    {
        if (Math.Abs(expected - actual) > 0.0001)
        {
            throw new Exception(name + ": expected " + expected + ", got " + actual);
        }
    }

    private static void StartsWith(string name, string expectedPrefix, string actual)
    {
        if (actual == null || !actual.StartsWith(expectedPrefix, StringComparison.Ordinal))
        {
            throw new Exception(name + ": expected prefix " + expectedPrefix + ", got " + actual);
        }
    }

    private static void Contains(string name, string expectedText, string actual)
    {
        if (actual == null || actual.IndexOf(expectedText, StringComparison.Ordinal) < 0)
        {
            throw new Exception(name + ": expected text " + expectedText + ", got " + actual);
        }
    }
}
'@

Set-Content -LiteralPath $programPath -Value $program -Encoding UTF8

$cscCommand = Get-Command csc -ErrorAction SilentlyContinue
$cscPath = $null
if ($null -ne $cscCommand) {
    $cscPath = $cscCommand.Source
}
if ([string]::IsNullOrWhiteSpace($cscPath)) {
    $frameworkCsc = Join-Path $env:WINDIR "Microsoft.NET\Framework64\v4.0.30319\csc.exe"
    if (Test-Path -LiteralPath $frameworkCsc) {
        $cscPath = $frameworkCsc
    }
}
if ([string]::IsNullOrWhiteSpace($cscPath)) {
    throw "csc.exe not found."
}

$sources = @(
    $programPath,
    (Join-Path $scriptDir "SnapshotModels.cs"),
    (Join-Path $scriptDir "TURZX.SideScreen.Renderer.cs"),
    (Join-Path $scriptDir "TURZX.SideScreen.TurzxHelperSender.cs"),
    (Join-Path $scriptDir "TURZX.SideScreen.Stream.cs")
)

& $cscPath /nologo /codepage:65001 /utf8output /target:exe /main:TestStreamCadenceProgram /out:$exePath /r:System.dll /r:System.Core.dll /r:System.Drawing.dll /r:System.Runtime.Serialization.dll $sources
if ($LASTEXITCODE -ne 0) {
    throw "csc failed with exit code $LASTEXITCODE"
}

& $exePath
if ($LASTEXITCODE -ne 0) {
    throw "stream cadence test failed with exit code $LASTEXITCODE"
}

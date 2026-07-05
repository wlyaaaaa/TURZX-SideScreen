Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$outDir = Join-Path $scriptDir "out"
$previewPath = Join-Path $outDir "renderer-preview.png"

New-Item -ItemType Directory -Force -Path $outDir | Out-Null

$tempRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("turzx_renderer_" + [Guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Force -Path $tempRoot | Out-Null
$exePath = Join-Path $tempRoot "RenderPreview.exe"
$programPath = Join-Path $tempRoot "RenderPreview.cs"

$program = @'
using System;
using System.Drawing;
using System.Drawing.Imaging;
using System.Reflection;
using TURZX.SideScreen;

internal static class RenderPreview
{
    private static int Main(string[] args)
    {
        if (args.Length != 1)
        {
            Console.Error.WriteLine("Usage: RenderPreview.exe <output.png>");
            return 2;
        }

        Snapshot snapshot = BuildSnapshot();
        using (Bitmap bitmap = SideScreenRenderer.Render(snapshot))
        {
            if (bitmap.Width != 480 || bitmap.Height != 1920)
            {
                Console.Error.WriteLine("Unexpected bitmap size: {0}x{1}", bitmap.Width, bitmap.Height);
                return 3;
            }

            bitmap.Save(args[0], ImageFormat.Png);
        }

        using (Bitmap agentBitmap = SideScreenRenderer.Render(BuildAgentStyleSnapshot()))
        {
            if (agentBitmap.Width != 480 || agentBitmap.Height != 1920)
            {
                Console.Error.WriteLine("Unexpected agent bitmap size: {0}x{1}", agentBitmap.Width, agentBitmap.Height);
                return 4;
            }
        }

        MethodInfo weatherDetailMethod = typeof(SideScreenRenderer).GetMethod("WeatherDetailLine", BindingFlags.NonPublic | BindingFlags.Static);
        if (weatherDetailMethod == null)
        {
            Console.Error.WriteLine("WeatherDetailLine method not found.");
            return 5;
        }

        string missingAqiLine = (string)weatherDetailMethod.Invoke(null, new object[] { new WeatherSnapshot { HumidityPercent = 41 } });
        if (missingAqiLine != "AQI -- · 湿度 41%")
        {
            Console.Error.WriteLine("Unexpected missing-AQI weather line: " + missingAqiLine);
            return 6;
        }

        string presentAqiLine = (string)weatherDetailMethod.Invoke(null, new object[] { new WeatherSnapshot { Aqi = 75, HumidityPercent = 41 } });
        if (presentAqiLine != "AQI 75 · 湿度 41%")
        {
            Console.Error.WriteLine("Unexpected present-AQI weather line: " + presentAqiLine);
            return 7;
        }

        Console.WriteLine("Preview written: " + args[0]);
        return 0;
    }

    private static Snapshot BuildSnapshot()
    {
        Snapshot snapshot = new Snapshot();

        snapshot.Time = new TimeSnapshot
        {
            Date = "2026-07-05",
            Weekday = "周日",
            Time = "17:02:35",
            UpdateIntervalSeconds = 0.5
        };
        snapshot.Weather = new WeatherSnapshot
        {
            City = "北京",
            TemperatureCelsius = 31,
            Condition = "晴",
            Aqi = 38,
            HumidityPercent = 41
        };
        snapshot.Alert = new AlertSnapshot
        {
            Level = "ok",
            Message = "系统正常"
        };
        snapshot.ForegroundApp = new ForegroundAppSnapshot
        {
            Name = "game.exe",
            Title = "TURZX Hardware Overlay Preview"
        };
        snapshot.Cpu = new CpuSnapshot
        {
            Model = "AMD Ryzen 9 9950X3D",
            UsagePercent = 32,
            TemperatureCelsius = 63,
            PowerWatts = 145,
            ClockGhz = 5.56,
            CoreVoltage = 1.27,
            LoadHistoryPercent = new double[] { 18, 28, 31, 29, 34, 51, 59, 47, 16, 12, 46, 76, 58 }
        };
        snapshot.Gpu = new GpuSnapshot
        {
            Model = "NVIDIA GeForce RTX 5090 D",
            UsagePercent = 17,
            TemperatureCelsius = 54,
            PowerWatts = 154,
            CoreClockGhz = 2.84,
            CoreVoltage = 1.00,
            MemoryClockGhz = 16.4,
            VramUsedGb = 4.5,
            VramTotalGb = 32.0,
            LoadHistoryPercent = new double[] { 10, 9, 16, 31, 25, 4, 1, 20, 41, 36, 6, 0, 22 }
        };
        snapshot.Fps = new FpsSnapshot
        {
            Current = 144,
            Average = 141,
            Low1Percent = 118,
            FrameTimeMs = 6.9,
            Source = "PresentMon / RTSS API"
        };
        snapshot.Memory = new MemorySnapshot
        {
            RamUsagePercent = 34,
            RamUsedGb = 22.0,
            RamTotalGb = 64.0,
            VramUsagePercent = 14,
            VramUsedGb = 4.5,
            VramTotalGb = 32.0
        };
        snapshot.Network = new NetworkSnapshot
        {
            DownloadBytesPerSecond = 10 * 1024,
            UploadBytesPerSecond = 22 * 1024,
            PingMs = 18,
            JitterMs = 2,
            PacketLossPercent = 0
        };
        snapshot.Disks = new DiskSnapshot[]
        {
            new DiskSnapshot { Drive = "C:", Label = "Win11", UsagePercent = 44, FreeText = "120 GB 可用" },
            new DiskSnapshot { Drive = "D:", Label = "game", UsagePercent = 70, FreeText = "320 GB 可用" },
            new DiskSnapshot { Drive = "E:", Label = "software", UsagePercent = 35, FreeText = "450 GB 可用" },
            new DiskSnapshot { Drive = "F:", Label = "RECOVER", UsagePercent = 0, FreeText = "15 GB 可用" },
            new DiskSnapshot { Drive = "G:", Label = "data", UsagePercent = 64, FreeText = "1.2 TB 可用" },
            new DiskSnapshot { Drive = "H:", Label = "1871", UsagePercent = 17, FreeText = "871 GB 可用" },
            new DiskSnapshot { Drive = "Z:", Label = "RAMDISK-EXTREMELY-LONG-VOLUME-LABEL", UsagePercent = 3, FreeText = "23 GB 可用" }
        };
        snapshot.TopProcesses = new ProcessSnapshot[]
        {
            new ProcessSnapshot
            {
                Name = "VeryLongGameName-Shipping.exe",
                Description = "Unreal Renderer Foreground Capture With Extra Long Title",
                CpuPercent = 18,
                GpuPercent = 62,
                MemoryGb = 3.1
            },
            new ProcessSnapshot { Name = "chrome.exe", CpuPercent = 6, GpuPercent = 3, MemoryGb = 3.1 },
            new ProcessSnapshot { Name = "python.exe", Description = "metrics_agent", CpuPercent = 2, GpuPercent = 0, MemoryGb = 0.4 }
        };
        snapshot.Health = new HealthSnapshot
        {
            Status = "诊断服务在线",
            Detail = "模块正常运转中",
            DpcLatencyUs = 430,
            HardPageFaultsPerSecond = 0,
            RefreshIntervalSeconds = 0.5
        };
        snapshot.Trust = new TrustSnapshot
        {
            Score = 96,
            Level = "ok",
            Summary = "可信度 96/100",
            WorstComponent = "fps",
            WorstLabel = "FPS",
            MissingCount = 0,
            FallbackCount = 0,
            StaleCount = 0,
            LogPath = "out/data-trust.jsonl",
            Items = new TrustItemSnapshot[]
            {
                new TrustItemSnapshot { Component = "cpu", Label = "CPU", Score = 100, Status = "ok", Source = "windows_api+lhm" },
                new TrustItemSnapshot { Component = "gpu", Label = "GPU", Score = 96, Status = "ok", Source = "nvml+lhm" },
                new TrustItemSnapshot { Component = "fps", Label = "FPS", Score = 92, Status = "ok", Source = "presentmon" }
            }
        };

        return snapshot;
    }

    private static Snapshot BuildAgentStyleSnapshot()
    {
        Snapshot snapshot = new Snapshot();
        snapshot.SchemaVersion = 1;
        snapshot.TimestampUnixMs = 1783267355000;
        snapshot.Sequence = 42;
        snapshot.Time = "2026-07-05T09:02:35Z";
        snapshot.Weather = new WeatherSnapshot
        {
            Summary = "unknown",
            TemperatureC = 29,
            Source = "fallback"
        };
        snapshot.Alert = new AlertSnapshot
        {
            Level = "ok",
            Message = null,
            Items = new string[0]
        };
        snapshot.ForegroundApp = new ForegroundAppSnapshot
        {
            Title = "Foreground window",
            ProcessId = 1234,
            ProcessName = "foreground-long-process-name.exe",
            ExePath = "C:\\Program Files\\TURZX\\foreground-long-process-name.exe",
            Source = "win32"
        };
        snapshot.Cpu = new CpuSnapshot
        {
            UsagePercent = 12.5,
            LogicalCount = 32,
            ClockMhz = 5560,
            Status = "idle",
            Source = "fallback"
        };
        snapshot.Gpu = new GpuSnapshot
        {
            Name = "NVIDIA GeForce RTX Agent Sample",
            UsagePercent = 47.2,
            TemperatureC = 61,
            CoreClockMhz = 2840,
            MemoryClockMhz = 16400,
            Status = "active",
            Source = "fallback"
        };
        snapshot.Fps = new FpsSnapshot
        {
            Current = 0,
            Average = null,
            Status = "idle",
            Source = "fallback"
        };
        snapshot.Memory = new MemorySnapshot
        {
            UsedPercent = 34.1,
            UsedGb = 22.0,
            AvailableGb = 42.0,
            TotalGb = 64.0,
            Source = "win32"
        };
        snapshot.Disks = new DiskSnapshot[]
        {
            new DiskSnapshot { Drive = "C:\\", Label = "WindowsWithAVeryVeryLongVolumeName", UsedPercent = 50.0, FreeGb = 10.0, TotalGb = 20.0, DriveType = "fixed" }
        };
        snapshot.Network = new NetworkSnapshot
        {
            RxBytesPerSecond = 1536,
            TxBytesPerSecond = 4096,
            Addresses = new string[] { "127.0.0.1" },
            Source = "stdlib"
        };
        snapshot.TopProcesses = new ProcessSnapshot[]
        {
            new ProcessSnapshot { Name = "ExtremelyLongProcessNameThatMustWrapBeforeItHitsTheRightEdge.exe", Pid = 99, CpuPercent = null, GpuPercent = null, MemoryMb = 2048.0 }
        };
        snapshot.Health = new HealthSnapshot
        {
            Status = "ok",
            GeneratedAt = "2026-07-05T09:02:35Z",
            Errors = new HealthErrorSnapshot[0]
        };
        snapshot.Trust = new TrustSnapshot
        {
            Score = 72,
            Level = "warn",
            Summary = "可信度 72/100",
            WorstComponent = "weather",
            WorstLabel = "天气",
            MissingCount = 3,
            FallbackCount = 2,
            Items = new TrustItemSnapshot[]
            {
                new TrustItemSnapshot { Component = "weather", Label = "天气", Score = 45, Status = "warn", Source = "fallback" },
                new TrustItemSnapshot { Component = "fps", Label = "FPS", Score = 70, Status = "warn", Source = "fallback" }
            }
        };
        return snapshot;
    }
}
'@

try {
    Set-Content -Path $programPath -Value $program -Encoding UTF8

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
        $programPath
    )

    & $cscPath /nologo /codepage:65001 /utf8output /target:exe /out:$exePath /r:System.dll /r:System.Core.dll /r:System.Drawing.dll /r:System.Runtime.Serialization.dll $sources
    if ($LASTEXITCODE -ne 0) {
        throw "csc failed with exit code $LASTEXITCODE"
    }

    & $exePath $previewPath
    if ($LASTEXITCODE -ne 0) {
        throw "RenderPreview failed with exit code $LASTEXITCODE"
    }

    $preview = Get-Item $previewPath
    if ($preview.Length -le 0) {
        throw "Preview file is empty: $previewPath"
    }

    Add-Type -AssemblyName System.Drawing
    $bitmap = [System.Drawing.Bitmap]::FromFile($previewPath)
    try {
        $cpuBox = $bitmap.GetPixel(322, 1558)
        $ramBox = $bitmap.GetPixel(398, 1558)
        if (!($cpuBox.B -gt 220 -and $cpuBox.R -lt 235)) {
            throw "Expected app CPU metric box on the right side, got RGB($($cpuBox.R),$($cpuBox.G),$($cpuBox.B))"
        }
        if (!($ramBox.G -gt 230 -and $ramBox.R -lt 235)) {
            throw "Expected app RAM metric box on the right side, got RGB($($ramBox.R),$($ramBox.G),$($ramBox.B))"
        }
    }
    finally {
        $bitmap.Dispose()
    }

    Write-Host ("OK {0} bytes -> {1}" -f $preview.Length, $preview.FullName)
}
finally {
    if (Test-Path $tempRoot) {
        Remove-Item -LiteralPath $tempRoot -Recurse -Force
    }
}

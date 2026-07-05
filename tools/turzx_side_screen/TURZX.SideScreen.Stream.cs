using System;
using System.Diagnostics;
using System.Drawing;
using System.Drawing.Imaging;
using System.IO;
using System.Net;
using System.Runtime.Serialization.Json;
using System.Threading;

namespace TURZX.SideScreen
{
    public static class SideScreenStreamApp
    {
        private const string DefaultMetricsUrl = "http://127.0.0.1:18765/snapshot";

        public static int Main(string[] args)
        {
            StreamOptions options;
            try
            {
                options = StreamOptions.Parse(args);
                if (options.ShowHelp)
                {
                    PrintUsage();
                    return 0;
                }
            }
            catch (Exception ex)
            {
                Console.Error.WriteLine(ex.Message);
                PrintUsage();
                return 2;
            }

            int frame = 0;
            int sent = 0;
            int failed = 0;
            Stopwatch total = Stopwatch.StartNew();
            TurzxHelperSender.DiffSession diffSession = null;
            byte[] previousFrameData = null;
            long diffSequence = 0;

            Console.WriteLine("TURZX stream starting: frames=" + (options.FrameCount == 0 ? "infinite" : options.FrameCount.ToString()) +
                ", intervalMs=" + options.IntervalMs +
                ", dryRun=" + options.DryRun +
                ", diff=" + options.UseDiff +
                ", altHelper=" + options.AltHelper +
                ", port=" + options.Port);

            try
            {
                if (options.UseDiff && !options.DryRun)
                {
                    diffSession = new TurzxHelperSender.DiffSession(options.Root, options.Port, options.DevCode);
                }

                while (options.FrameCount == 0 || frame < options.FrameCount)
                {
                    frame++;
                    Stopwatch frameWatch = Stopwatch.StartNew();
                    try
                    {
                        Snapshot snapshot = options.UseSample ? SampleSnapshot(frame) : FetchSnapshot(options);
                        using (Bitmap bitmap = SideScreenRenderer.Render(snapshot))
                        {
                            if (!string.IsNullOrWhiteSpace(options.PreviewDir))
                            {
                                Directory.CreateDirectory(options.PreviewDir);
                                string preview = Path.Combine(options.PreviewDir, "stream-last.png");
                                bitmap.Save(preview, ImageFormat.Png);
                            }

                            if (options.DryRun)
                            {
                                sent++;
                                Console.WriteLine("frame " + frame + " rendered in " + frameWatch.ElapsedMilliseconds + "ms");
                            }
                            else if (options.UseDiff)
                            {
                                Stopwatch sendWatch = Stopwatch.StartNew();
                                byte[] currentFrameData = diffSession.Convert(bitmap);
                                if (previousFrameData == null)
                                {
                                    diffSession.SendFull(currentFrameData);
                                    sendWatch.Stop();
                                    sent++;
                                    Console.WriteLine("frame " + frame + " FULL sent in " + sendWatch.ElapsedMilliseconds + "ms: frameBytes=" + currentFrameData.Length);
                                }
                                else
                                {
                                    long sequence = diffSequence++;
                                    int result = diffSession.SendDiff(previousFrameData, currentFrameData, sequence, false, false, options.AltHelper);
                                    sendWatch.Stop();
                                    sent++;
                                    Console.WriteLine("frame " + frame + " DIFF sent in " + sendWatch.ElapsedMilliseconds + "ms: seq=" + sequence + ", result=" + result);
                                }

                                previousFrameData = currentFrameData;
                            }
                            else
                            {
                                string message;
                                Stopwatch sendWatch = Stopwatch.StartNew();
                                bool ok = TurzxHelperSender.SendBitmap(options.Root, options.Port, bitmap, options.DevCode, options.SendTimeoutMs, out message);
                                sendWatch.Stop();
                                if (!ok)
                                {
                                    failed++;
                                    Console.WriteLine("frame " + frame + " send failed after " + sendWatch.ElapsedMilliseconds + "ms: " + message);
                                }
                                else
                                {
                                    sent++;
                                    Console.WriteLine("frame " + frame + " sent in " + sendWatch.ElapsedMilliseconds + "ms: " + message);
                                }
                            }
                        }
                    }
                    catch (Exception ex)
                    {
                        failed++;
                        Console.WriteLine("frame " + frame + " exception: " + ex.GetType().Name + ": " + ex.Message);
                    }

                    frameWatch.Stop();
                    int sleepMs = options.IntervalMs - (int)Math.Min(int.MaxValue, frameWatch.ElapsedMilliseconds);
                    if (sleepMs > 0 && (options.FrameCount == 0 || frame < options.FrameCount))
                    {
                        Thread.Sleep(sleepMs);
                    }
                }
            }
            finally
            {
                if (diffSession != null)
                {
                    diffSession.Dispose();
                }
            }

            Console.WriteLine("TURZX stream stopped: renderedOrSent=" + sent + ", failed=" + failed + ", elapsedMs=" + total.ElapsedMilliseconds);
            return failed == 0 ? 0 : 1;
        }

        private static Snapshot FetchSnapshot(StreamOptions options)
        {
            HttpWebRequest request = (HttpWebRequest)WebRequest.Create(options.MetricsUrl);
            request.Method = "GET";
            request.Timeout = options.HttpTimeoutMs;
            request.ReadWriteTimeout = options.HttpTimeoutMs;
            using (WebResponse response = request.GetResponse())
            using (Stream stream = response.GetResponseStream())
            {
                DataContractJsonSerializer serializer = new DataContractJsonSerializer(typeof(Snapshot));
                Snapshot snapshot = serializer.ReadObject(stream) as Snapshot;
                if (snapshot == null)
                {
                    throw new InvalidDataException("Snapshot JSON did not deserialize.");
                }

                if (snapshot.SchemaVersion.HasValue && snapshot.SchemaVersion.Value != 1)
                {
                    throw new InvalidDataException("Unsupported schema_version: " + snapshot.SchemaVersion.Value);
                }

                return snapshot;
            }
        }

        private static Snapshot SampleSnapshot(int frame)
        {
            double cpu = 24 + ((frame * 17) % 50);
            double gpu = 12 + ((frame * 13) % 44);
            return new Snapshot
            {
                SchemaVersion = 1,
                Sequence = frame,
                Time = new TimeSnapshot
                {
                    Date = DateTime.Now.ToString("yyyy-MM-dd"),
                    Weekday = ChineseWeekday(DateTime.Now),
                    Time = DateTime.Now.ToString("HH:mm:ss"),
                    UpdateIntervalSeconds = 0.5
                },
                Weather = new WeatherSnapshot
                {
                    City = "北京",
                    TemperatureCelsius = 31,
                    Condition = "晴",
                    Aqi = 38,
                    HumidityPercent = 41
                },
                Alert = new AlertSnapshot { Message = "系统正常", Level = "ok" },
                ForegroundApp = new ForegroundAppSnapshot { Name = "game.exe" },
                Cpu = new CpuSnapshot
                {
                    Model = "AMD Ryzen 9 9950X3D",
                    UsagePercent = cpu,
                    TemperatureCelsius = 63,
                    PowerWatts = 145,
                    ClockGhz = 5.56,
                    CoreVoltage = 1.27,
                    LoadHistoryPercent = new double[] { 18, 28, 31, 29, cpu, 51, 59, 47, 16, 12, 46, 76, 58 }
                },
                Gpu = new GpuSnapshot
                {
                    Model = "NVIDIA GeForce RTX 5090 D",
                    UsagePercent = gpu,
                    TemperatureCelsius = 54,
                    PowerWatts = 154,
                    CoreClockGhz = 2.84,
                    CoreVoltage = 1.00,
                    MemoryClockGhz = 16.4,
                    LoadHistoryPercent = new double[] { 10, 9, 16, 31, gpu, 4, 1, 20, 41, 36, 6, 0, 22 }
                },
                Fps = new FpsSnapshot { Current = 144, Average = 141, Low1Percent = 118, FrameTimeMs = 6.9, Source = "PresentMon / RTSS API" },
                Memory = new MemorySnapshot { RamUsagePercent = 34, RamUsedGb = 22, RamTotalGb = 64, VramUsagePercent = 14 },
                Network = new NetworkSnapshot { DownloadBytesPerSecond = 10240, UploadBytesPerSecond = 22528, PingMs = 18, JitterMs = 2, PacketLossPercent = 0 },
                Disks = new DiskSnapshot[]
                {
                    new DiskSnapshot { Drive = "C:", Label = "Win11", UsagePercent = 44, FreeText = "343 GB 可用" },
                    new DiskSnapshot { Drive = "D:", Label = "game", UsagePercent = 70, FreeText = "1.1 TB 可用" },
                    new DiskSnapshot { Drive = "E:", Label = "software", UsagePercent = 35, FreeText = "2 TB 可用" }
                },
                TopProcesses = new ProcessSnapshot[]
                {
                    new ProcessSnapshot { Name = "VeryLongGameName-Shipping.exe", CpuPercent = 18, GpuPercent = 62, MemoryGb = 3.1 },
                    new ProcessSnapshot { Name = "chrome.exe", CpuPercent = 6, GpuPercent = 3, MemoryGb = 3.1 },
                    new ProcessSnapshot { Name = "python.exe", Description = "metrics_agent", CpuPercent = 2, GpuPercent = 0, MemoryGb = 0.4 }
                },
                Health = new HealthSnapshot { Status = "诊断服务在线", Detail = "模块正常运转中", DpcLatencyUs = 430, HardPageFaultsPerSecond = 0, RefreshIntervalSeconds = 0.5 },
                Trust = new TrustSnapshot
                {
                    Score = 96,
                    Level = "ok",
                    Summary = "可信度 96/100",
                    WorstComponent = "fps",
                    WorstLabel = "FPS",
                    MissingCount = 0,
                    FallbackCount = 0,
                    Items = new TrustItemSnapshot[]
                    {
                        new TrustItemSnapshot { Component = "cpu", Label = "CPU", Score = 100, Status = "ok", Source = "windows_api+lhm" },
                        new TrustItemSnapshot { Component = "gpu", Label = "GPU", Score = 96, Status = "ok", Source = "nvml+lhm" },
                        new TrustItemSnapshot { Component = "fps", Label = "FPS", Score = 92, Status = "ok", Source = "presentmon" }
                    }
                }
            };
        }

        private static string ChineseWeekday(DateTime value)
        {
            string[] names = { "周日", "周一", "周二", "周三", "周四", "周五", "周六" };
            return names[(int)value.DayOfWeek];
        }

        private static void PrintUsage()
        {
            Console.WriteLine("TURZX.SideScreen.Stream.exe [--sample] [--dry-run] [--diff] [--alt-helper] [--frames N] [--interval-ms 1000] [--metrics-url URL] [--root TURZX_ROOT] [--port COM7]");
            Console.WriteLine("frames=0 means infinite. --diff sends one full baseline frame, then command-204 differential frames.");
        }

        private sealed class StreamOptions
        {
            public bool ShowHelp;
            public bool UseSample;
            public bool DryRun;
            public bool UseDiff;
            public bool AltHelper;
            public int FrameCount = 0;
            public int IntervalMs = 3000;
            public int HttpTimeoutMs = 5000;
            public int SendTimeoutMs = 240000;
            public string MetricsUrl = DefaultMetricsUrl;
            public string Root = Path.GetFullPath(Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "..", ".."));
            public string Port = "COM7";
            public string DevCode = TurzxHelperSender.DefaultDevCode;
            public string PreviewDir;

            public static StreamOptions Parse(string[] args)
            {
                StreamOptions options = new StreamOptions();
                for (int i = 0; i < args.Length; i++)
                {
                    string arg = args[i];
                    if (arg == "--help" || arg == "-h") options.ShowHelp = true;
                    else if (arg == "--sample") options.UseSample = true;
                    else if (arg == "--dry-run") options.DryRun = true;
                    else if (arg == "--diff") options.UseDiff = true;
                    else if (arg == "--alt-helper") options.AltHelper = true;
                    else if (arg == "--frames") options.FrameCount = int.Parse(Next(args, ref i, arg));
                    else if (arg == "--interval-ms") options.IntervalMs = int.Parse(Next(args, ref i, arg));
                    else if (arg == "--timeout-ms") options.HttpTimeoutMs = int.Parse(Next(args, ref i, arg));
                    else if (arg == "--send-timeout-ms") options.SendTimeoutMs = int.Parse(Next(args, ref i, arg));
                    else if (arg == "--metrics-url") options.MetricsUrl = Next(args, ref i, arg);
                    else if (arg == "--root") options.Root = Next(args, ref i, arg);
                    else if (arg == "--port") options.Port = Next(args, ref i, arg);
                    else if (arg == "--dev-code") options.DevCode = Next(args, ref i, arg);
                    else if (arg == "--preview-dir") options.PreviewDir = Next(args, ref i, arg);
                    else throw new ArgumentException("Unknown argument: " + arg);
                }

                if (options.FrameCount < 0) throw new ArgumentOutOfRangeException("frames");
                if (options.IntervalMs < 0) throw new ArgumentOutOfRangeException("interval-ms");
                return options;
            }

            private static string Next(string[] args, ref int index, string arg)
            {
                if (index + 1 >= args.Length) throw new ArgumentException(arg + " requires a value.");
                index++;
                return args[index];
            }
        }
    }
}

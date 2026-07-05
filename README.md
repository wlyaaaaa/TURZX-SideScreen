# TURZX SideScreen

Self-hosted realtime dashboard for 480x1920 TURZX USB side screens.

This project replaces the stock TURZX monitoring page with a custom local stack:

- Python metrics agents for CPU, GPU, FPS, weather, disks, network, foreground app, and process ranking.
- C# / GDI+ renderer for a dense 480x1920 dashboard.
- COM7 differential frame streaming for smoother 0.5s updates.
- Data trust scoring and JSONL diagnostics.
- Windows Scheduled Task startup support with highest privilege.

## Current Status

This is an early Windows-first project extracted from a working local setup. The protocol and UI are practical, not polished SDK abstractions yet.

Known assumptions:

- Display size: `480x1920`.
- Serial port: `COM7` by default.
- Runtime OS: Windows.
- Python 3.11+ recommended.
- .NET Framework compiler `csc.exe` is required for the renderer/stream binaries.
- Hardware metrics work best with NVIDIA NVML, LibreHardwareMonitor, RTSS/PresentMon, and the optional `E:\TimeAudit` telemetry stack.
- Optional TimeAudit FPS source is enabled with `TIMEAUDIT_DSN`; no database password is stored in this repository.

## Quick Start

First check local runtime dependencies:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\check-runtime.ps1
```

The public repository does not include stock TURZX binaries. Put these files next to the repository root before starting the COM stream:

- `RJCP.SerialPortStream.dll`
- `TURZX.exe` or `TURZX.weatherfix.metrics.exe`

Run directly:

```text
start-side-screen.cmd
```

Or from PowerShell:

```powershell
cd E:\TURZX-SideScreen
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start.ps1 -Port COM7 -IntervalMs 500
```

Install startup task:

```text
install-startup.cmd
```

Or from elevated PowerShell:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\install-startup-admin.ps1 -Port COM7 -IntervalMs 500
```

Uninstall startup task:

```text
uninstall-startup.cmd
```

Or from elevated PowerShell:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\uninstall-startup-admin.ps1
```

## Useful Commands

Run tests and render previews:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\test.ps1
```

Build a release zip:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\build-release.ps1
```

Check startup state:

```powershell
Get-ScheduledTask | Where-Object { $_.TaskName -like '*TURZX*' } |
  Select-Object TaskName,State,@{Name='RunLevel';Expression={$_.Principal.RunLevel}}
```

## Runtime Logs

Generated files stay out of git:

- `tools\turzx_side_screen\out\stream\stream-last.png`
- `tools\turzx_side_screen\out\data-trust.jsonl`
- `tools\turzx_side_screen\out\side-screen-stack.log`
- `tools\turzx_side_screen\out\top-processes.json`

## Repository Layout

```text
scripts/                       public install/start/test/release wrappers
docs/                          public documentation
tools/turzx_side_screen/       metrics agent, renderer, streamer, tests
tools/turzx_weather_shim/      weather shim used by local weather requests
```

The original TURZX vendor binaries and local runtime folders are intentionally excluded from git.

## License

Repository source code is MIT licensed. Third-party/vendor binaries and TURZX stock application files are not part of the public source license and should not be committed.

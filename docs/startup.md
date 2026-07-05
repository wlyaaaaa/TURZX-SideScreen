# Startup Task

The recommended startup path is a Windows Scheduled Task:

- Task name: `TURZX SideScreen`
- Run level: `Highest`
- Trigger: user logon
- Action: `StartSideScreenStack.ps1`
- Default port: `COM7`
- Default refresh: `500ms`

This is not a `SYSTEM` account task. It runs as the current interactive user with `Highest` run level, which is usually safer for COM ports, user-profile Python installs, RTSS/Afterburner, and other desktop telemetry tools.

Install:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\install-startup-admin.ps1
```

The installer runs `scripts\check-runtime.ps1` first. It will not install the startup task if the local stock TURZX runtime files are missing.

Uninstall:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\uninstall-startup-admin.ps1
```

Check current state:

```powershell
Get-ScheduledTask | Where-Object { $_.TaskName -in @('TURZX SideScreen','TURZX WeatherFix','TURZX_88inch_AdminStart') } |
  Select-Object TaskName,State,@{Name='RunLevel';Expression={$_.Principal.RunLevel}}
```

The installer disables these old stock startup tasks if present:

- `TURZX WeatherFix`
- `TURZX_88inch_AdminStart`

It does not delete them, so rollback is still possible.

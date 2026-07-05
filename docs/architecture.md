# Architecture

TURZX SideScreen is intentionally split into small local processes:

1. `turzx_weather_shim.py`
   - Provides short weather text for the dashboard.
   - Keeps weather API behavior isolated from screen rendering.

2. `metrics_agent.py`
   - Serves `GET http://127.0.0.1:18765/snapshot`.
   - Collects hardware, network, disk, weather, FPS, foreground app, and health data.
   - Adds `trust` scoring to every snapshot.
   - Writes data trust diagnostics to `out\data-trust.jsonl`.

3. `top_processes_helper.py`
   - Samples process CPU/RAM independently every 3 seconds.
   - Writes `out\top-processes.json`.
   - Prevents heavy process sampling from blocking the 0.5s main snapshot loop.

4. `TURZX.SideScreen.Stream.exe`
   - Fetches snapshots.
   - Renders 480x1920 bitmaps with `System.Drawing`.
   - Sends one full frame, then TURZX differential frames over COM7.

5. `StartSideScreenStack.ps1`
   - Starts/stops the full stack.
   - Used by both manual launch and the Windows startup task.

## Data Freshness

- Main screen refresh target: `500ms`.
- Top process ranking refresh: `3s`.
- Weather refresh: cached and much slower.
- Data trust log write: throttled to avoid high-frequency disk writes.

## Public Repository Boundary

The public repo should include source code, docs, and scripts only.

Do not commit:

- Original TURZX vendor binaries.
- Local logs and generated previews.
- Device configs copied from a specific machine.
- Weather/API credentials.
- Large binary assets from the original package.

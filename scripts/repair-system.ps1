param(
    [string]$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path,
    [string]$TaskName = "TURZX SideScreen"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Continue"

$Root = (Resolve-Path -LiteralPath $Root).Path
$side = Join-Path $Root "tools\turzx_side_screen"
$outDir = Join-Path $side "out"
$logPath = Join-Path $outDir "repair-system.log"
New-Item -ItemType Directory -Force -Path $outDir | Out-Null

function Write-SystemRepairLog {
    param([string]$Message)
    $line = "{0} {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $Message
    Add-Content -LiteralPath $logPath -Value $line -Encoding UTF8
}

function Invoke-SystemLogged {
    param(
        [string]$Label,
        [scriptblock]$Script
    )

    Write-SystemRepairLog ("BEGIN {0}" -f $Label)
    try {
        & $Script 2>&1 | ForEach-Object { Write-SystemRepairLog ("{0}: {1}" -f $Label, $_) }
    }
    catch {
        Write-SystemRepairLog ("{0} EXCEPTION: {1}" -f $Label, $_.Exception.Message)
    }
    Write-SystemRepairLog ("END {0}" -f $Label)
}

Write-SystemRepairLog ("system repair start identity={0}" -f [Security.Principal.WindowsIdentity]::GetCurrent().Name)

$nativeSource = @'
using System;
using System.Runtime.InteropServices;

public static class NativeKill {
    [StructLayout(LayoutKind.Sequential)]
    public struct LUID { public uint LowPart; public int HighPart; }

    [StructLayout(LayoutKind.Sequential)]
    public struct TOKEN_PRIVILEGES {
        public uint PrivilegeCount;
        public LUID Luid;
        public uint Attributes;
    }

    [DllImport("kernel32.dll")]
    public static extern IntPtr GetCurrentProcess();

    [DllImport("advapi32.dll", SetLastError=true)]
    public static extern bool OpenProcessToken(IntPtr ProcessHandle, UInt32 DesiredAccess, out IntPtr TokenHandle);

    [DllImport("advapi32.dll", SetLastError=true, CharSet=CharSet.Unicode)]
    public static extern bool LookupPrivilegeValue(string lpSystemName, string lpName, out LUID lpLuid);

    [DllImport("advapi32.dll", SetLastError=true)]
    public static extern bool AdjustTokenPrivileges(IntPtr TokenHandle, bool DisableAllPrivileges, ref TOKEN_PRIVILEGES NewState, UInt32 BufferLength, IntPtr PreviousState, IntPtr ReturnLength);

    [DllImport("kernel32.dll", SetLastError=true)]
    public static extern IntPtr OpenProcess(UInt32 dwDesiredAccess, bool bInheritHandle, UInt32 dwProcessId);

    [DllImport("kernel32.dll", SetLastError=true)]
    public static extern bool TerminateProcess(IntPtr hProcess, UInt32 uExitCode);

    [DllImport("kernel32.dll")]
    public static extern bool CloseHandle(IntPtr hObject);

    public static string EnableDebugPrivilege() {
        IntPtr token;
        if (!OpenProcessToken(GetCurrentProcess(), 0x20 | 0x8, out token)) return "OpenProcessToken failed " + Marshal.GetLastWin32Error();
        try {
            LUID luid;
            if (!LookupPrivilegeValue(null, "SeDebugPrivilege", out luid)) return "LookupPrivilegeValue failed " + Marshal.GetLastWin32Error();
            TOKEN_PRIVILEGES tp = new TOKEN_PRIVILEGES();
            tp.PrivilegeCount = 1;
            tp.Luid = luid;
            tp.Attributes = 0x2;
            if (!AdjustTokenPrivileges(token, false, ref tp, 0, IntPtr.Zero, IntPtr.Zero)) return "AdjustTokenPrivileges failed " + Marshal.GetLastWin32Error();
            return "SeDebugPrivilege enabled";
        }
        finally { CloseHandle(token); }
    }

    public static string Kill(uint pid) {
        IntPtr handle = OpenProcess(0x0001, false, pid);
        if (handle == IntPtr.Zero) return "OpenProcess failed " + Marshal.GetLastWin32Error();
        try {
            if (!TerminateProcess(handle, 1)) return "TerminateProcess failed " + Marshal.GetLastWin32Error();
            return "TerminateProcess OK";
        }
        finally { CloseHandle(handle); }
    }
}
'@

try {
    Add-Type -TypeDefinition $nativeSource -Language CSharp
    Write-SystemRepairLog ([NativeKill]::EnableDebugPrivilege())
}
catch {
    Write-SystemRepairLog ("native kill helper load failed: {0}" -f $_.Exception.Message)
}

Invoke-SystemLogged "end side screen task" {
    schtasks.exe /End /TN $TaskName
}

Invoke-SystemLogged "kill stream by image" {
    taskkill.exe /IM TURZX.SideScreen.Stream.exe /F /T
}

$streamProcesses = @(Get-CimInstance Win32_Process | Where-Object { $_.Name -like "TURZX.SideScreen.Stream*" })
foreach ($proc in $streamProcesses) {
    Invoke-SystemLogged ("native terminate stream pid " + $proc.ProcessId) {
        [NativeKill]::Kill([uint32]$proc.ProcessId)
    }
    Invoke-SystemLogged ("kill stream pid " + $proc.ProcessId) {
        taskkill.exe /PID $proc.ProcessId /F /T
    }
    Invoke-SystemLogged ("wmi terminate stream pid " + $proc.ProcessId) {
        $target = Get-CimInstance Win32_Process -Filter ("ProcessId={0}" -f $proc.ProcessId) -ErrorAction SilentlyContinue
        if ($target) {
            Invoke-CimMethod -InputObject $target -MethodName Terminate | Format-List | Out-String
        }
    }
}

Start-Sleep -Seconds 2
$remaining = @(Get-CimInstance Win32_Process | Where-Object { $_.Name -like "TURZX.SideScreen.Stream*" })
Write-SystemRepairLog ("remaining stream count={0}" -f $remaining.Count)
foreach ($proc in $remaining) {
    Write-SystemRepairLog ("remaining PID={0} Parent={1} Name={2} CommandLine={3}" -f $proc.ProcessId, $proc.ParentProcessId, $proc.Name, $proc.CommandLine)
}

Write-SystemRepairLog "system repair complete"

param(
    [string]$TaskName = "TURZX SideScreen",
    [string]$ResumeTaskName = "TURZX SideScreen Resume"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$isAdmin = ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).
    IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    throw "Please run as Administrator."
}

foreach ($name in @($TaskName, $ResumeTaskName)) {
    $existing = Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
    if ($existing) {
        Unregister-ScheduledTask -TaskName $name -Confirm:$false
        Write-Host "Removed startup task: $name"
    } else {
        Write-Host "Startup task not found: $name"
    }
}

Get-ScheduledTask | Where-Object { $_.TaskName -like "*TURZX*" -or $_.TaskName -like "*SideScreen*" } |
    Select-Object TaskName, State, @{Name="RunLevel";Expression={$_.Principal.RunLevel}} |
    Format-Table -AutoSize

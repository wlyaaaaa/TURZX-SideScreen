param(
    [string]$TaskName = "TURZX SideScreen"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$isAdmin = ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).
    IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    throw "Please run as Administrator."
}

$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($existing) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "Removed startup task: $TaskName"
} else {
    Write-Host "Startup task not found: $TaskName"
}

Get-ScheduledTask | Where-Object { $_.TaskName -like "*TURZX*" -or $_.TaskName -like "*SideScreen*" } |
    Select-Object TaskName, State, @{Name="RunLevel";Expression={$_.Principal.RunLevel}} |
    Format-Table -AutoSize

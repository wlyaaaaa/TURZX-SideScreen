$ErrorActionPreference = "Stop"

$tasks = @("TURZX_88inch_AdminStart", "TempMonitor_8")
foreach ($taskName in $tasks) {
    $task = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
    if ($task) {
        Disable-ScheduledTask -TaskName $taskName | Out-Null
    }
}

Set-StrictMode -Version Latest

function Get-TurzxShutdownEventDecision {
    [CmdletBinding()]
    param(
        [AllowNull()]
        [object]$EventType,

        [Parameter(Mandatory)]
        [DateTime]$WatchdogStartedUtc,

        [DateTime]$NowUtc = [DateTime]::UtcNow,

        [ValidateRange(0, 3600)]
        [int]$StartupGraceSeconds = 180
    )

    $parsedType = 0
    if ($null -eq $EventType -or -not [int]::TryParse([string]$EventType, [ref]$parsedType)) {
        return [pscustomobject]@{
            Action = "Ignore"
            Reason = "missing-or-invalid-type"
            Type = $null
            AgeSeconds = [Math]::Max(0, ($NowUtc.ToUniversalTime() - $WatchdogStartedUtc.ToUniversalTime()).TotalSeconds)
        }
    }

    $ageSeconds = [Math]::Max(0, ($NowUtc.ToUniversalTime() - $WatchdogStartedUtc.ToUniversalTime()).TotalSeconds)
    if ($parsedType -eq 0) {
        return [pscustomobject]@{
            Action = "Ignore"
            Reason = "logoff"
            Type = $parsedType
            AgeSeconds = $ageSeconds
        }
    }

    if ($parsedType -ne 1) {
        return [pscustomobject]@{
            Action = "Ignore"
            Reason = "unsupported-type"
            Type = $parsedType
            AgeSeconds = $ageSeconds
        }
    }

    if ($ageSeconds -lt $StartupGraceSeconds) {
        return [pscustomobject]@{
            Action = "Ignore"
            Reason = "startup-grace"
            Type = $parsedType
            AgeSeconds = $ageSeconds
        }
    }

    return [pscustomobject]@{
        Action = "Shutdown"
        Reason = "confirmed"
        Type = $parsedType
        AgeSeconds = $ageSeconds
    }
}

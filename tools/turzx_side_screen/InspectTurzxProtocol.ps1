param(
    [string]$Root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path,
    [string[]]$Assemblies = @("TURZX.weatherfix.metrics.exe", "TURZX.exe"),
    [switch]$NoCecil
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding $false

$rootPath = (Resolve-Path -LiteralPath $Root).Path

Write-Host "TURZX protocol static inspection"
Write-Host ("Root: {0}" -f $rootPath)
Write-Host "Safety: reflection/metadata only; this script does not create driver instances, open serial ports, or write COM ports."
Write-Host ""

function Get-FileSummary {
    param([string]$Path)

    if (!(Test-Path -LiteralPath $Path)) {
        return "missing"
    }

    $item = Get-Item -LiteralPath $Path
    $hash = Get-FileHash -LiteralPath $Path -Algorithm SHA256
    return ("bytes={0} sha256={1} lastWrite={2:yyyy-MM-dd HH:mm:ss}" -f $item.Length, $hash.Hash, $item.LastWriteTime)
}

function Invoke-ReflectionWorker {
    param(
        [string]$RootPath,
        [string]$AssemblyPath
    )

    $worker = @'
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding $false

$rootPath = $env:TURZX_INSPECT_ROOT
$assemblyPath = $env:TURZX_INSPECT_ASSEMBLY
$knownTypes = @(
    ([string][char]0x8DB5),
    ([string][char]0x99DF),
    ([string][char]0x91C3),
    ([string][char]0x967E),
    ([string][char]0xB6EE)
)
$interestingConstants = @(200, 202, 204, 249, 250, 24900, 61289, 65000)
$flags = [Reflection.BindingFlags]"Public,NonPublic,Instance,Static,DeclaredOnly"

[AppDomain]::CurrentDomain.add_AssemblyResolve({
    param($sender, $eventArgs)

    $name = (New-Object System.Reflection.AssemblyName($eventArgs.Name)).Name
    foreach ($extension in @(".dll", ".exe")) {
        $candidate = Join-Path $rootPath ($name + $extension)
        if (Test-Path -LiteralPath $candidate) {
            return [Reflection.Assembly]::LoadFrom($candidate)
        }
    }

    return $null
})

function Format-TypeName {
    param([Type]$Type)

    if ($null -eq $Type) {
        return "<null>"
    }

    return $Type.FullName
}

function Format-MethodSignature {
    param([Reflection.MethodBase]$Method)

    $returnType = "<ctor>"
    $methodInfo = $Method -as [Reflection.MethodInfo]
    if ($null -ne $methodInfo) {
        $returnType = Format-TypeName $methodInfo.ReturnType
    }

    $parameters = ($Method.GetParameters() | ForEach-Object {
        (Format-TypeName $_.ParameterType) + " " + $_.Name
    }) -join ", "

    return ("{0} {1}({2})" -f $returnType, $Method.Name, $parameters)
}

function Test-LdcI4 {
    param(
        [byte[]]$Bytes,
        [int]$Value
    )

    if ($null -eq $Bytes -or $Bytes.Length -eq 0) {
        return $false
    }

    $le = [BitConverter]::GetBytes($Value)
    for ($i = 0; $i -le $Bytes.Length - 5; $i++) {
        if ($Bytes[$i] -eq 0x20 -and
            $Bytes[$i + 1] -eq $le[0] -and
            $Bytes[$i + 2] -eq $le[1] -and
            $Bytes[$i + 3] -eq $le[2] -and
            $Bytes[$i + 4] -eq $le[3]) {
            return $true
        }
    }

    if ($Value -ge -128 -and $Value -le 127) {
        $sbyteValue = [byte]([sbyte]$Value)
        for ($i = 0; $i -le $Bytes.Length - 2; $i++) {
            if ($Bytes[$i] -eq 0x1F -and $Bytes[$i + 1] -eq $sbyteValue) {
                return $true
            }
        }
    }

    if ($Value -ge 0 -and $Value -le 8) {
        $opcode = 0x16 + $Value
        return $Bytes -contains [byte]$opcode
    }

    if ($Value -eq -1) {
        return $Bytes -contains [byte]0x15
    }

    return $false
}

function Get-BodyBytes {
    param([Reflection.MethodBase]$Method)

    try {
        $body = $Method.GetMethodBody()
        if ($null -eq $body) {
            return $null
        }

        return $body.GetILAsByteArray()
    }
    catch {
        return $null
    }
}

$assembly = [Reflection.Assembly]::LoadFrom($assemblyPath)
$types = $assembly.GetTypes()

Write-Output ("REFLECTION assembly={0}" -f (Split-Path -Leaf $assemblyPath))
Write-Output ("  FullName: {0}" -f $assembly.FullName)
Write-Output ("  TypeCount: {0}" -f $types.Count)

foreach ($typeName in $knownTypes) {
    $type = $assembly.GetType($typeName, $false)
    Write-Output ("  TYPE {0}: {1}" -f $typeName, [bool]$type)
    if ($null -eq $type) {
        continue
    }

    foreach ($field in $type.GetFields($flags)) {
        Write-Output ("    field {0} {1}" -f (Format-TypeName $field.FieldType), $field.Name)
    }

    foreach ($ctor in $type.GetConstructors($flags)) {
        Write-Output ("    ctor {0}" -f (Format-MethodSignature $ctor))
    }

    foreach ($method in ($type.GetMethods($flags) | Sort-Object Name)) {
        $signature = Format-MethodSignature $method
        if ($signature -match "Byte\[\]|Bitmap|SerialPortStream|System\.IO\.Stream|System\.String|System\.Int32,System\.Boolean") {
            Write-Output ("    method {0}" -f $signature)
        }
    }
}

Write-Output "  Reflection IL constant hits:"
$hitCount = 0
foreach ($type in $types) {
    foreach ($method in $type.GetMethods($flags)) {
        $bytes = Get-BodyBytes $method
        if ($null -eq $bytes) {
            continue
        }

        foreach ($value in $interestingConstants) {
            if (Test-LdcI4 -Bytes $bytes -Value $value) {
                $hitCount++
                Write-Output ("    value={0} type={1} method={2} params={3} return={4}" -f `
                    $value, $type.FullName, $method.Name, $method.GetParameters().Count, (Format-TypeName $method.ReturnType))
            }
        }
    }
}

if ($hitCount -eq 0) {
    Write-Output "    (none)"
}
'@

    $encoded = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($worker))
    $oldRoot = $env:TURZX_INSPECT_ROOT
    $oldAssembly = $env:TURZX_INSPECT_ASSEMBLY

    try {
        $env:TURZX_INSPECT_ROOT = $RootPath
        $env:TURZX_INSPECT_ASSEMBLY = $AssemblyPath
        & powershell -NoProfile -ExecutionPolicy Bypass -EncodedCommand $encoded
        if ($LASTEXITCODE -ne 0) {
            throw "Reflection worker failed for $AssemblyPath with exit code $LASTEXITCODE"
        }
    }
    finally {
        if ($null -eq $oldRoot) {
            Remove-Item Env:\TURZX_INSPECT_ROOT -ErrorAction SilentlyContinue
        }
        else {
            $env:TURZX_INSPECT_ROOT = $oldRoot
        }

        if ($null -eq $oldAssembly) {
            Remove-Item Env:\TURZX_INSPECT_ASSEMBLY -ErrorAction SilentlyContinue
        }
        else {
            $env:TURZX_INSPECT_ASSEMBLY = $oldAssembly
        }
    }
}

function Resolve-CecilPath {
    param([string]$RootPath)

    $candidates = @(
        (Join-Path $RootPath "tools\turzx_metrics_patcher_run\Mono.Cecil.dll"),
        (Join-Path $RootPath "tools\turzx_metrics_patcher\bin\Release\net8.0\Mono.Cecil.dll")
    )

    foreach ($candidate in $candidates) {
        if (Test-Path -LiteralPath $candidate) {
            return $candidate
        }
    }

    return $null
}

function Get-CecilAllTypes {
    param($Types)

    foreach ($type in $Types) {
        $type
        if ($type.HasNestedTypes) {
            Get-CecilAllTypes -Types $type.NestedTypes
        }
    }
}

function Get-CecilLdcI4 {
    param($Instruction)

    $code = $Instruction.OpCode.Code.ToString()
    if (!$code.StartsWith("Ldc_I4")) {
        return $null
    }

    if ($null -ne $Instruction.Operand) {
        return [int]$Instruction.Operand
    }

    switch ($code) {
        "Ldc_I4_M1" { return -1 }
        "Ldc_I4_0" { return 0 }
        "Ldc_I4_1" { return 1 }
        "Ldc_I4_2" { return 2 }
        "Ldc_I4_3" { return 3 }
        "Ldc_I4_4" { return 4 }
        "Ldc_I4_5" { return 5 }
        "Ldc_I4_6" { return 6 }
        "Ldc_I4_7" { return 7 }
        "Ldc_I4_8" { return 8 }
        default { return $null }
    }
}

function Write-CecilConstantHits {
    param(
        $Module,
        [int[]]$InterestingConstants
    )

    $hits = New-Object "System.Collections.Generic.HashSet[string]"
    foreach ($type in (Get-CecilAllTypes -Types $Module.Types)) {
        foreach ($method in $type.Methods) {
            if (!$method.HasBody) {
                continue
            }

            foreach ($instruction in $method.Body.Instructions) {
                $value = Get-CecilLdcI4 -Instruction $instruction
                if ($null -ne $value -and $InterestingConstants -contains $value) {
                    [void]$hits.Add(("{0}|{1}|{2}|params={3}" -f $value, $type.FullName, $method.Name, $method.Parameters.Count))
                }
            }
        }
    }

    if ($hits.Count -eq 0) {
        Write-Host "    (none)"
        return
    }

    $hits | Sort-Object | ForEach-Object {
        Write-Host ("    {0}" -f $_)
    }
}

function Write-CecilWindow {
    param(
        $Module,
        [string]$TypeName,
        [string]$MethodName,
        [int]$ParameterCount,
        [int[]]$Values
    )

    $type = (Get-CecilAllTypes -Types $Module.Types | Where-Object { $_.FullName -eq $TypeName } | Select-Object -First 1)
    if ($null -eq $type) {
        return
    }

    foreach ($method in ($type.Methods | Where-Object { $_.Name -eq $MethodName -and $_.Parameters.Count -eq $ParameterCount })) {
        if (!$method.HasBody) {
            continue
        }

        $instructions = $method.Body.Instructions
        for ($i = 0; $i -lt $instructions.Count; $i++) {
            $value = Get-CecilLdcI4 -Instruction $instructions[$i]
            if ($null -eq $value -or !($Values -contains $value)) {
                continue
            }

            Write-Host ("    WINDOW value={0} method={1}" -f $value, $method.FullName)
            $start = [Math]::Max(0, $i - 4)
            $end = [Math]::Min($instructions.Count - 1, $i + 8)
            for ($j = $start; $j -le $end; $j++) {
                Write-Host ("      {0:X4}: {1} {2}" -f $instructions[$j].Offset, $instructions[$j].OpCode, $instructions[$j].Operand)
            }
        }
    }
}

$assemblyPaths = @()
foreach ($assemblyName in $Assemblies) {
    $path = Join-Path $rootPath $assemblyName
    Write-Host ("FILE {0}: {1}" -f $assemblyName, (Get-FileSummary -Path $path))
    if (Test-Path -LiteralPath $path) {
        $assemblyPaths += $path
    }
}

Write-Host ""
Write-Host "=== Reflection summaries, isolated per assembly ==="
foreach ($assemblyPath in $assemblyPaths) {
    Invoke-ReflectionWorker -RootPath $rootPath -AssemblyPath $assemblyPath
    Write-Host ""
}

if (!$NoCecil) {
    $cecilPath = Resolve-CecilPath -RootPath $rootPath
    if ([string]::IsNullOrWhiteSpace($cecilPath)) {
        Write-Host "=== Cecil static IL scan skipped: Mono.Cecil.dll not found ==="
    }
    else {
        Write-Host "=== Cecil static IL scan ==="
        Write-Host ("Mono.Cecil: {0}" -f $cecilPath)
        Add-Type -Path $cecilPath

        foreach ($assemblyPath in $assemblyPaths) {
            $module = [Mono.Cecil.ModuleDefinition]::ReadModule($assemblyPath)
            Write-Host ("CECIL assembly={0}" -f (Split-Path -Leaf $assemblyPath))
            Write-Host ("  MVID: {0}" -f $module.Mvid)
            Write-Host ("  RawTypeCount: {0}" -f $module.Types.Count)

            $frameType = [string][char]0x8DB5
            $driverType = [string][char]0x99DF
            $serialType = [string][char]0x91C3
            $usbType = [string][char]0x967E
            $baseDriverType = [string][char]0xB6EE
            $sendMethod = [string][char]0x8A54
            $diffMethod = [string][char]0x88FA

            foreach ($typeName in @($frameType, $driverType, $serialType, $usbType, $baseDriverType)) {
                $type = (Get-CecilAllTypes -Types $module.Types | Where-Object { $_.FullName -eq $typeName } | Select-Object -First 1)
                Write-Host ("  TYPE {0}: {1}" -f $typeName, [bool]$type)
            }

            Write-Host "  Cecil constant hits:"
            Write-CecilConstantHits -Module $module -InterestingConstants @(200, 202, 204, 249, 250, 24900, 61289, 65000)

            Write-Host "  Key command windows:"
            Write-CecilWindow -Module $module -TypeName $driverType -MethodName $sendMethod -ParameterCount 3 -Values @(200, 202)
            Write-CecilWindow -Module $module -TypeName $driverType -MethodName $diffMethod -ParameterCount 4 -Values @(204, 61289, 65000)
            Write-CecilWindow -Module $module -TypeName $serialType -MethodName $sendMethod -ParameterCount 4 -Values @(250, 61289)
            Write-CecilWindow -Module $module -TypeName $serialType -MethodName $sendMethod -ParameterCount 2 -Values @(24900)
            Write-Host ""
        }
    }
}

Write-Host "Done. No serial or COM operation was performed."

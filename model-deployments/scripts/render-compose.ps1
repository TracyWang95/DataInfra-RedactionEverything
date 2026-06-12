param(
    [string]$Preset = "balanced-local",
    [string]$Chip = "nvidia-cuda",
    [string]$Output = ".\model-deployments\docker-compose.generated.yml"
)

$ErrorActionPreference = "Stop"

$manifestPath = Join-Path $PSScriptRoot "..\manifest.json"
$manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json

$presetConfig = $manifest.presets | Where-Object { $_.id -eq $Preset } | Select-Object -First 1
if (-not $presetConfig) {
    throw "Unknown preset '$Preset'."
}

$chipProfile = $manifest.chip_profiles | Where-Object { $_.id -eq $Chip } | Select-Object -First 1
if (-not $chipProfile) {
    throw "Unknown chip profile '$Chip'."
}

function Get-TaskConfig {
    param([string]$TaskId)
    return $manifest.tasks | Where-Object { $_.id -eq $TaskId } | Select-Object -First 1
}

function Get-ActiveModelId {
    param([object]$PresetConfig, [string]$TaskId)
    $property = $PresetConfig.active_by_task.PSObject.Properties |
        Where-Object { $_.Name -eq $TaskId } |
        Select-Object -First 1
    if (-not $property) {
        throw "Preset '$($PresetConfig.id)' does not define task '$TaskId'."
    }
    return [string]$property.Value
}

function Get-ModelConfig {
    param([object]$TaskConfig, [string]$ModelId)
    $model = $TaskConfig.models | Where-Object { $_.id -eq $ModelId } | Select-Object -First 1
    if (-not $model) {
        throw "Task '$($TaskConfig.id)' does not contain model '$ModelId'."
    }
    return $model
}

function Add-EnvironmentLines {
    param([System.Collections.Generic.List[string]]$Lines, [object]$Environment)
    if (-not $Environment) {
        return
    }
    $properties = $Environment.PSObject.Properties
    if ($properties.Count -eq 0) {
        return
    }
    $Lines.Add("    environment:")
    foreach ($property in $properties) {
        $Lines.Add("      $($property.Name): `"$($property.Value)`"")
    }
}

function Add-StringList {
    param(
        [System.Collections.Generic.List[string]]$Lines,
        [string]$Name,
        [object[]]$Values
    )
    if (-not $Values -or $Values.Count -eq 0) {
        return
    }
    $Lines.Add("    ${Name}:")
    foreach ($value in $Values) {
        $escaped = [string]$value
        $Lines.Add("      - `"$escaped`"")
    }
}

function Add-DeviceReservation {
    param([System.Collections.Generic.List[string]]$Lines, [object]$ChipProfile)
    if (-not $ChipProfile.compose_device) {
        return
    }
    $device = $ChipProfile.compose_device
    $capabilities = ($device.capabilities | ForEach-Object { [string]$_ }) -join ", "
    $Lines.Add("    deploy:")
    $Lines.Add("      resources:")
    $Lines.Add("        reservations:")
    $Lines.Add("          devices:")
    $Lines.Add("            - driver: $($device.driver)")
    $Lines.Add("              count: $($device.count)")
    $Lines.Add("              capabilities: [$capabilities]")
}

$taskOrder = @("text_ner", "ocr", "visual_feature")
$lines = [System.Collections.Generic.List[string]]::new()
$lines.Add("# Generated from model-deployments/manifest.json")
$lines.Add("# Preset: $Preset")
$lines.Add("# Chip: $Chip")
$lines.Add("services:")

foreach ($taskId in $taskOrder) {
    $taskConfig = Get-TaskConfig -TaskId $taskId
    $modelId = Get-ActiveModelId -PresetConfig $presetConfig -TaskId $taskId
    $model = Get-ModelConfig -TaskConfig $taskConfig -ModelId $modelId

    if ($model.external -eq $true) {
        $lines.Add("  # $taskId uses external model '$modelId' at $($model.base_url).")
        continue
    }

    if ($model.supported_chips -notcontains $Chip) {
        throw "Model '$modelId' does not declare support for chip profile '$Chip'."
    }

    $serviceName = [string]$model.service_name
    $lines.Add("  ${serviceName}:")

    if ($model.build_context) {
        $lines.Add("    build:")
        $lines.Add("      context: $($model.build_context)")
        $lines.Add("      dockerfile: $($model.dockerfile)")
    } else {
        $image = '${' + $model.image_env + ':-' + $model.default_image + '}'
        $lines.Add("    image: `"$image`"")
    }

    $lines.Add("    ports:")
    $lines.Add("      - `"`${$($model.host_port_env):-$($model.default_host_port)}:$($model.internal_port)`"")

    Add-EnvironmentLines -Lines $lines -Environment $model.environment
    Add-StringList -Lines $lines -Name "volumes" -Values $model.volumes
    Add-StringList -Lines $lines -Name "command" -Values $model.command
    Add-DeviceReservation -Lines $lines -ChipProfile $chipProfile
    $lines.Add("    networks:")
    $lines.Add("      - redaction-models")
    $lines.Add("    restart: unless-stopped")
    $lines.Add("")
}

$lines.Add("networks:")
$lines.Add("  redaction-models:")
$lines.Add("    driver: bridge")

$outputPath = Resolve-Path -LiteralPath (Split-Path -Parent $Output) -ErrorAction SilentlyContinue
if (-not $outputPath) {
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $Output) | Out-Null
}

Set-Content -LiteralPath $Output -Value ($lines -join [Environment]::NewLine) -Encoding UTF8
Write-Host "Generated $Output from preset '$Preset' and chip '$Chip'."

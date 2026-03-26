# HaS Image (YOLO11) - port 8081
$ErrorActionPreference = "Stop"
$ScriptDir = $PSScriptRoot
$ProjectRoot = Split-Path -Parent $ScriptDir
$BackendRoot = Join-Path $ProjectRoot "backend"
$EnvName = if ($env:LEGAL_REDACTION_CONDA_ENV) { $env:LEGAL_REDACTION_CONDA_ENV } else { "legal-redaction" }

function Get-CondaRoot {
    if ($env:CONDA_ROOT -and (Test-Path (Join-Path $env:CONDA_ROOT "Scripts\conda.exe"))) { return $env:CONDA_ROOT }
    foreach ($c in @("conda-root", "C:\ProgramData\miniconda3", "C:\ProgramData\anaconda3", "$env:USERPROFILE\anaconda3", "$env:USERPROFILE\miniconda3")) {
        if (Test-Path (Join-Path $c "Scripts\conda.exe")) { return $c }
    }
    $cmd = Get-Command conda -ErrorAction SilentlyContinue
    if ($cmd -and $cmd.Source -match 'conda\.exe$') { return (Split-Path (Split-Path $cmd.Source)) }
    return $null
}

$CondaRoot = Get-CondaRoot
$CondaExe = if ($CondaRoot) { Join-Path $CondaRoot "Scripts\conda.exe" } else { $null }
if (-not $CondaExe -or -not (Test-Path -LiteralPath $CondaExe)) {
    Write-Host "conda.exe not found; use start_has_image.bat or set CONDA_ROOT" -ForegroundColor Red
    exit 1
}

if (-not $env:HAS_IMAGE_WEIGHTS) {
    $env:HAS_IMAGE_WEIGHTS = "has_models/sensitive_seg_best.pt"
}

Write-Host "HaS Image: conda run -n $EnvName python has_image_server.py" -ForegroundColor Cyan
Write-Host "HaS Image: HAS_IMAGE_WEIGHTS=$($env:HAS_IMAGE_WEIGHTS)" -ForegroundColor DarkGray

$args = @("run", "-n", $EnvName, "--no-capture-output", "python", "has_image_server.py")
$p = Start-Process -FilePath $CondaExe -ArgumentList $args -WorkingDirectory $BackendRoot -WindowStyle Minimized -PassThru

Write-Host "HaS Image: started PID=$($p.Id) port 8081" -ForegroundColor Green
exit 0

# FastAPI main backend — port 8000 (conda run, same pattern as HaS Image / OCR)
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
    Write-Host "conda.exe not found; set CONDA_ROOT or use start_backend.bat" -ForegroundColor Red
    exit 1
}

Write-Host "Backend: conda run -n $EnvName python -m uvicorn app.main:app --host 0.0.0.0 --port 8000" -ForegroundColor Cyan
$p = Start-Process -FilePath $CondaExe `
    -ArgumentList @("run", "-n", $EnvName, "--no-capture-output", "python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000") `
    -WorkingDirectory $BackendRoot `
    -WindowStyle Minimized -PassThru

Write-Host "Backend: started PID=$($p.Id) port 8000" -ForegroundColor Green
exit 0

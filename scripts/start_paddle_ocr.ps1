# PaddleOCR-VL - port 8082
$ErrorActionPreference = "Stop"
$ScriptDir = $PSScriptRoot
$ProjectRoot = Split-Path -Parent $ScriptDir
$BackendRoot = Join-Path $ProjectRoot "backend"

$EnvName = if ($env:LEGAL_REDACTION_CONDA_ENV) { $env:LEGAL_REDACTION_CONDA_ENV } else { "oda" }
$CondaRoot = if ($env:CONDA_ROOT) { $env:CONDA_ROOT } else { "conda-root" }
$EnvRoot = Join-Path $CondaRoot "envs\$EnvName"
$EnvPython = Join-Path $EnvRoot "python.exe"
if (-not (Test-Path -LiteralPath $EnvPython)) {
    Write-Host "Python not found: $EnvPython" -ForegroundColor Red
    exit 1
}
$ocrPort = if ($env:OCR_PORT) { $env:OCR_PORT } else { "8082" }

$nvBase = Join-Path $EnvRoot "Lib\site-packages"
$nvDirs = @("nvidia\cudnn\bin","nvidia\cublas\bin","nvidia\cuda_runtime\bin","nvidia\curand\bin","nvidia\cusolver\bin","nvidia\cusparse\bin","nvidia\nvjitlink\bin")
$extraPath = ($nvDirs | ForEach-Object { Join-Path $nvBase $_ } | Where-Object { Test-Path $_ }) -join ";"

$inner = "set ""PATH=$extraPath;%PATH%"" && set ""PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK=True"" && set ""OCR_PORT=$ocrPort"" && ""$EnvPython"" -u ocr_server.py"

Write-Host "PaddleOCR-VL: env=$EnvName port=$ocrPort" -ForegroundColor Cyan
$p = Start-Process -FilePath "cmd.exe" -ArgumentList "/c $inner" -WorkingDirectory $BackendRoot -WindowStyle Minimized -PassThru
Write-Host "PaddleOCR-VL: started PID=$($p.Id)" -ForegroundColor Green
exit 0

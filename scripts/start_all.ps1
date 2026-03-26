# Legal Redaction - Start All Services
# OCR(8082) + HaS(8080) + HaS Image YOLO(8081) + Backend(8000) + Frontend(3000)

$ScriptDir = $PSScriptRoot
$ProjectRoot = Split-Path -Parent $ScriptDir

# 先停止本机已占用的相关端口（避免旧进程残留）
$StopScript = Join-Path $ScriptDir "stop_all.ps1"
if (Test-Path $StopScript) {
    Write-Host "Stopping existing services..." -ForegroundColor Yellow
    & $StopScript
}

function Stop-PortProcess {
    param([int]$Port)
    $line = netstat -ano | Select-String ":$Port\s+.*LISTENING"
    if ($line) {
        $parts = $line -split '\s+'
        $procId = $parts[-1]
        if ($procId -match '^\d+$') {
            Write-Host "Stop process on port $Port (PID $procId)" -ForegroundColor Yellow
            Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
            Start-Sleep -Seconds 2
        }
    }
}

Write-Host ""
Write-Host "Legal Redaction - Starting all services" -ForegroundColor Cyan
Write-Host ""

# Clear ports
Write-Host "Clearing ports..." -ForegroundColor Yellow
Stop-PortProcess 8080
Stop-PortProcess 8081
Stop-PortProcess 8000
Stop-PortProcess 8082
Stop-PortProcess 3000
Write-Host ""

# Start HaS (8080) - NER model（优先 PowerShell 启动脚本，自动解析 llama-server 并写 logs/）
Write-Host "Start HaS NER (8080)..." -ForegroundColor Green
$hasPs1 = Join-Path $ScriptDir "start_has.ps1"
if (Test-Path $hasPs1) {
    & powershell -NoProfile -ExecutionPolicy Bypass -File $hasPs1
} else {
    Start-Process -FilePath (Join-Path $ScriptDir "start_has.bat") -WindowStyle Minimized -WorkingDirectory $ProjectRoot
}

# Start HaS Image (8081) — 优先 PS1（conda run），与 Paddle 一致
Write-Host "Start HaS Image (8081)..." -ForegroundColor Green
$hiPs1 = Join-Path $ScriptDir "start_has_image.ps1"
if (Test-Path $hiPs1) {
    & powershell -NoProfile -ExecutionPolicy Bypass -File $hiPs1
} else {
    Start-Process -FilePath (Join-Path $ScriptDir "start_has_image.bat") -WindowStyle Minimized -WorkingDirectory $ProjectRoot
}

# Start PaddleOCR-VL (8082) — 优先 PS1（写 logs/），否则 bat
Write-Host "Start PaddleOCR-VL (8082)..." -ForegroundColor Green
$paddlePs1 = Join-Path $ScriptDir "start_paddle_ocr.ps1"
if (Test-Path $paddlePs1) {
    & powershell -NoProfile -ExecutionPolicy Bypass -File $paddlePs1
} else {
    Start-Process -FilePath (Join-Path $ScriptDir "start_paddle_ocr.bat") -WindowStyle Minimized -WorkingDirectory $ProjectRoot
}

# Start Backend（优先 PS1：conda run，与 HaS Image/OCR 一致）
Write-Host "Start Backend (8000)..." -ForegroundColor Green
$bePs1 = Join-Path $ScriptDir "start_backend.ps1"
if (Test-Path $bePs1) {
    & powershell -NoProfile -ExecutionPolicy Bypass -File $bePs1
} else {
    Start-Process -FilePath (Join-Path $ScriptDir "start_backend.bat") -WindowStyle Minimized -WorkingDirectory $ProjectRoot
}

# Wait
Write-Host "Waiting for backend (uvicorn + conda may need 15–30s)..." -ForegroundColor Gray
Start-Sleep -Seconds 20

# Start Frontend
Write-Host "Start Frontend (3000)..." -ForegroundColor Green
Start-Process -FilePath (Join-Path $ScriptDir "start_frontend.bat") -WindowStyle Normal -WorkingDirectory $ProjectRoot

Write-Host ""
Write-Host "Done! Frontend: http://localhost:3000" -ForegroundColor Green
Write-Host "API docs: http://localhost:8000/docs" -ForegroundColor White
Write-Host ""

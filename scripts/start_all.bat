@echo off
setlocal
chcp 65001 >nul
REM ====================================================================
REM  DataInfra-RedactionEverything — 一键启动所有服务
REM  HaS NER(8080) + HaS Image(8081) + PaddleOCR(8082) + Backend(8000) + Frontend(3000)
REM ====================================================================

set "SCRIPT_DIR=%~dp0"
set "PROJECT_ROOT=%SCRIPT_DIR%.."

echo.
echo  DataInfra-RedactionEverything — Starting all services
echo  =====================================================
echo.

REM --- 清理残留端口 ---
echo [1/6] Clearing ports...
for %%P in (8080 8081 8082 8000 3000) do (
    for /f "tokens=5" %%A in ('netstat -ano ^| findstr ":%%P " ^| findstr "LISTENING"') do (
        echo   Killing PID %%A on port %%P
        taskkill /PID %%A /F >nul 2>&1
    )
)
timeout /t 2 /nobreak >nul

REM --- 探测 Conda ---
call "%SCRIPT_DIR%ensure_conda_root.bat"
if errorlevel 1 (
    echo ERROR: conda not found. Set CONDA_ROOT or install Miniconda.
    pause
    exit /b 1
)
echo   CONDA_ROOT = %CONDA_ROOT%
echo.

REM --- 1. HaS NER (8080) ---
echo [2/6] Starting HaS NER (8080)...
start "HaS-NER-8080" /min cmd /c ""%SCRIPT_DIR%start_has.bat""

REM --- 2. HaS Image YOLO (8081) ---
echo [3/6] Starting HaS Image YOLO (8081)...
start "HaS-Image-8081" /min cmd /c ""%SCRIPT_DIR%start_has_image.bat""

REM --- 3. PaddleOCR (8082) ---
echo [4/6] Starting PaddleOCR-VL (8082)...
start "PaddleOCR-8082" /min cmd /c ""%SCRIPT_DIR%start_paddle_ocr.bat""

REM --- 4. Backend (8000) ---
echo [5/6] Starting Backend (8000)...
start "Backend-8000" /min cmd /c ""%SCRIPT_DIR%start_backend.bat""

REM --- 等待后端启动 ---
echo.
echo   Waiting for services to start (20s)...
timeout /t 20 /nobreak >nul

REM --- 5. Frontend (3000) ---
echo [6/6] Starting Frontend (3000)...
start "Frontend-3000" cmd /c ""%SCRIPT_DIR%start_frontend.bat""

echo.
echo  =====================================================
echo  All services started!
echo  Frontend:  http://localhost:3000
echo  Backend:   http://localhost:8000
echo  API docs:  http://localhost:8000/docs
echo  =====================================================
echo.
pause

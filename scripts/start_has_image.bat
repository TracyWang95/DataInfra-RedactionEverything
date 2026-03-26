@echo off
setlocal
chcp 65001 >nul
REM HaS Image (YOLO11) — 端口 8081，与 Paddle 一样先 activate legal-redaction
if not defined CONDA_ROOT set "CONDA_ROOT=conda-root"
call "%CONDA_ROOT%\Scripts\activate.bat" legal-redaction
if errorlevel 1 goto :activate_fail
goto :activate_ok
:activate_fail
echo ERROR: conda activate failed: legal-redaction
pause
exit /b 1
:activate_ok
if not defined HAS_IMAGE_WEIGHTS set "HAS_IMAGE_WEIGHTS=has_models/sensitive_seg_best.pt"
cd /d "%~dp0..\backend"
if not exist "has_image_server.py" (
    echo ERROR: has_image_server.py not found in "%CD%"
    pause
    exit /b 1
)
python has_image_server.py
pause

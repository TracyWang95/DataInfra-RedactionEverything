@echo off
setlocal
chcp 65001 >nul
REM 主后端 FastAPI — 使用 conda 环境 legal-redaction
if not defined CONDA_ROOT set "CONDA_ROOT=conda-root"
call "%CONDA_ROOT%\Scripts\activate.bat" legal-redaction
if errorlevel 1 goto :activate_fail
goto :activate_ok
:activate_fail
echo ERROR: conda activate failed: legal-redaction
pause
exit /b 1
:activate_ok
cd /d "%~dp0..\backend"
if not exist "app\main.py" (
    echo ERROR: backend not found in "%CD%"
    pause
    exit /b 1
)
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
pause

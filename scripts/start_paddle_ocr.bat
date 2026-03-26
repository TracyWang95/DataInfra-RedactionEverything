@echo off
setlocal
chcp 65001 >nul
REM PaddleOCR-VL - port 8082 (uses conda env oda by default)
if not defined CONDA_ROOT set "CONDA_ROOT=conda-root"
if not defined LEGAL_REDACTION_CONDA_ENV set "LEGAL_REDACTION_CONDA_ENV=oda"
set "ENV_ROOT=%CONDA_ROOT%\envs\%LEGAL_REDACTION_CONDA_ENV%"
set "ENV_PYTHON=%ENV_ROOT%\python.exe"
set "PATH=%ENV_ROOT%\Lib\site-packages\nvidia\cudnn\bin;%ENV_ROOT%\Lib\site-packages\nvidia\cublas\bin;%ENV_ROOT%\Lib\site-packages\nvidia\cuda_runtime\bin;%ENV_ROOT%\Lib\site-packages\nvidia\curand\bin;%ENV_ROOT%\Lib\site-packages\nvidia\cusolver\bin;%ENV_ROOT%\Lib\site-packages\nvidia\cusparse\bin;%ENV_ROOT%\Lib\site-packages\nvidia\nvjitlink\bin;%PATH%"
set "PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK=True"
cd /d "%~dp0..\backend"
if not exist "ocr_server.py" (
    echo ERROR: ocr_server.py not found in "%CD%"
    pause
    exit /b 1
)
if not exist "%ENV_PYTHON%" (
    echo ERROR: Python not found: %ENV_PYTHON%
    pause
    exit /b 1
)
"%ENV_PYTHON%" -u ocr_server.py
pause

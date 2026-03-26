@echo off
setlocal
chcp 65001 >nul
REM HaS NER (llama-server) — 端口 8080
REM 默认：HaS_Text_0209 Q4_K_M（https://huggingface.co/xuanwulab/HaS_Text_0209_0.6B_Q4）
REM 覆盖：set HAS_NER_GGUF=D:\path\to\file.gguf
if not defined CONDA_ROOT set "CONDA_ROOT=conda-root"
if not defined HAS_NER_HF_REPO set "HAS_NER_HF_REPO=xuanwulab/HaS_Text_0209_0.6B_Q4"
if not defined HAS_NER_NGL set "HAS_NER_NGL=99"

set "HAS_MODEL="
if defined HAS_NER_GGUF (
    if exist "%HAS_NER_GGUF%" set "HAS_MODEL=%HAS_NER_GGUF%"
)
if not defined HAS_MODEL if exist "has_models/HaS_Text_0209_0.6B_Q4_K_M.gguf" set "HAS_MODEL=has_models/HaS_Text_0209_0.6B_Q4_K_M.gguf"
if not defined HAS_MODEL if exist "has_models/has_4.0_0.6B_q4.gguf" set "HAS_MODEL=has_models/has_4.0_0.6B_q4.gguf"

set "LLAMA_CONDA=%CONDA_ROOT%\envs\legal-redaction\Library\bin\llama-server.exe"
if not exist "%LLAMA_CONDA%" set "LLAMA_CONDA=%CONDA_ROOT%\envs\legal-redaction\Scripts\llama-server.exe"

if exist "%LLAMA_CONDA%" (
    call "%CONDA_ROOT%\Scripts\activate.bat" legal-redaction
    if errorlevel 1 (
        echo ERROR conda activate failed legal-redaction
        pause
        exit /b 1
    )
    if defined HAS_MODEL (
        echo HaS NER: conda + local %HAS_MODEL%
        "%LLAMA_CONDA%" -m "%HAS_MODEL%" --port 8080 -ngl %HAS_NER_NGL% --host 0.0.0.0 -c 8192 -np 1
    ) else (
        echo HaS NER: conda + -hf %HAS_NER_HF_REPO%
        "%LLAMA_CONDA%" -hf %HAS_NER_HF_REPO% --port 8080 -ngl %HAS_NER_NGL% --host 0.0.0.0 -c 8192 -np 1
    )
    goto :done
)

set "LLAMA_SERVER="
for /d %%D in ("%LOCALAPPDATA%\Microsoft\WinGet\Packages\ggml.llamacpp*") do (
    if exist "%%D\llama-server.exe" (
        set "LLAMA_SERVER=%%D\llama-server.exe"
        goto :found_llama
    )
)
:found_llama
if not defined LLAMA_SERVER (
    echo Error: llama-server not found. Install ggml.llamacpp ^(winget^) or copy llama-server.exe to conda env legal-redaction\Library\bin
    pause
    exit /b 1
)
if defined HAS_MODEL (
    "%LLAMA_SERVER%" -m "%HAS_MODEL%" --port 8080 -ngl %HAS_NER_NGL% --host 0.0.0.0 -c 8192 -np 1
) else (
    "%LLAMA_SERVER%" -hf %HAS_NER_HF_REPO% --port 8080 -ngl %HAS_NER_NGL% --host 0.0.0.0 -c 8192 -np 1
)

:done
pause

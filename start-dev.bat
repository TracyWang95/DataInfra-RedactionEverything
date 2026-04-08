@echo off
chcp 65001 >nul
title DataInfra-RedactionEverything Dev Services

echo ============================================
echo   DataInfra-RedactionEverything Dev Launcher
echo ============================================
echo.

echo [1/5] Backend (FastAPI :8000)
start "Backend :8000" cmd /k "cd /d D:\DataInfra-RedactionEverything\backend && set DEBUG=true && set AUTH_ENABLED=false && set DATA_DIR=./data && set UPLOAD_DIR=./uploads && set OUTPUT_DIR=./outputs && python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload"

echo [2/5] Frontend (Vite :3000)
start "Frontend :3000" cmd /k "cd /d D:\DataInfra-RedactionEverything\frontend && npm run dev -- --port 3000 --strictPort"

echo [3/5] PaddleOCR-VL (conda:oda :8082)
start "OCR :8082" cmd /k "cd /d D:\DataInfra-RedactionEverything\backend && conda activate oda && python scripts/ocr_server.py"

echo [4/5] HaS-Image YOLO (conda:legal-redaction :8081)
start "Vision :8081" cmd /k "cd /d D:\DataInfra-RedactionEverything\backend && set PYTHONPATH=. && conda activate legal-redaction && python scripts/has_image_server.py"

echo [5/5] HaS-Text NER (llama-server :8080)
start "NER :8080" cmd /k ""%LOCALAPPDATA%\Microsoft\WinGet\Packages\ggml.llamacpp_Microsoft.Winget.Source_8wekyb3d8bbwe\llama-server" --host 0.0.0.0 --port 8080 -m D:\has_models\HaS_Text_0209_0.6B_Q4_K_M.gguf -ngl 99"

echo.
echo ============================================
echo   Backend:    http://localhost:8000
echo   Frontend:   http://localhost:3000
echo   OCR:        http://localhost:8082  (conda:oda)
echo   Vision:     http://localhost:8081  (conda:legal-redaction)
echo   NER:        http://localhost:8080  (llama-server)
echo ============================================
echo.
echo   Health: curl http://localhost:8000/health/services
echo   Stop:   run stop-dev.bat
echo.
pause

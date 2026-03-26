@echo off
setlocal
cd /d "%~dp0..\frontend"
if not exist "package.json" (
    echo ERROR: frontend not found in "%CD%"
    pause
    exit /b 1
)
call npx vite --port 3000
pause

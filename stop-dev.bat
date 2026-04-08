@echo off
chcp 65001 >nul
echo Stopping all dev services...

powershell -Command "Get-Process python*,node* -ErrorAction SilentlyContinue | Stop-Process -Force"

:: Kill llama-server separately
powershell -Command "Get-Process llama-server -ErrorAction SilentlyContinue | Stop-Process -Force"

echo All services stopped.
pause

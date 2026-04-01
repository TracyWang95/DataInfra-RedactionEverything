@echo off
setlocal
chcp 65001 >nul
REM ====================================================================
REM  DataInfra-RedactionEverything — 停止所有服务
REM ====================================================================

echo.
echo  Stopping all services...
echo.

for %%P in (8080 8081 8082 8000 3000) do (
    for /f "tokens=5" %%A in ('netstat -ano ^| findstr ":%%P " ^| findstr "LISTENING"') do (
        echo   Port %%P : killing PID %%A
        taskkill /PID %%A /F >nul 2>&1
    )
)

echo.
echo  Done.
echo.
pause

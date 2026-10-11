@echo off
rem Start the agentic-tool web config editor and open it in a browser.
rem Run from anywhere: scripts\run_web.bat [flags]
setlocal
cd /d "%~dp0.."

if exist ".venv\Scripts\python.exe" (
    .venv\Scripts\python.exe web\server.py %*
    goto :end
)

where py >nul 2>nul
if %errorlevel% equ 0 (
    py web\server.py %*
) else (
    python web\server.py %*
    if errorlevel 9009 (
        echo Error: python not found on PATH. 1>&2
        exit /b 1
    )
)
:end
endlocal

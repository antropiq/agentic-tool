@echo off
rem Start the Console MCP connector server (default http://127.0.0.1:9999/mcp).
rem Run from anywhere: scripts\run_console_mcp.bat [flags]
setlocal
cd /d "%~dp0.."

if exist ".venv\Scripts\python.exe" (
    .venv\Scripts\python.exe -m mcp_connectors.console_mcp %*
    goto :end
)

where py >nul 2>nul
if %errorlevel% equ 0 (
    py -m mcp_connectors.console_mcp %*
) else (
    python -m mcp_connectors.console_mcp %*
    if errorlevel 9009 (
        echo Error: python not found on PATH. 1>&2
        exit /b 1
    )
)
:end
endlocal

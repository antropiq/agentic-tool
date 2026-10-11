@echo off
rem Start the Playwright MCP connector server (default http://127.0.0.1:8934/mcp).
rem Run from anywhere: scripts\run_playwright_mcp.bat [flags]
setlocal
cd /d "%~dp0.."

if exist ".venv\Scripts\python.exe" (
    .venv\Scripts\python.exe -m mcp_connectors.playwright_mcp %*
    goto :end
)

where py >nul 2>nul
if %errorlevel% equ 0 (
    py -m mcp_connectors.playwright_mcp %*
) else (
    python -m mcp_connectors.playwright_mcp %*
    if errorlevel 9009 (
        echo Error: python not found on PATH. 1>&2
        exit /b 1
    )
)
:end
endlocal

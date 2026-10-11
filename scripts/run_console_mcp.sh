#!/usr/bin/env sh
# Start the Console MCP connector server (default http://127.0.0.1:9999/mcp).
# Run from anywhere: ./scripts/run_console_mcp.sh [flags]
cd "$(dirname "$0")/.." || exit 1

if [ -x ".venv/bin/python" ]; then
    exec .venv/bin/python -m mcp_connectors.console_mcp "$@"
elif command -v python3 >/dev/null 2>&1; then
    exec python3 -m mcp_connectors.console_mcp "$@"
elif command -v python >/dev/null 2>&1; then
    exec python -m mcp_connectors.console_mcp "$@"
else
    echo "Error: python3 (or python) not found on PATH." >&2
    exit 1
fi

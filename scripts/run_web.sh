#!/usr/bin/env sh
# Start the agentic-tool web config editor and open it in a browser.
# Run from anywhere: ./scripts/run_web.sh [flags]
cd "$(dirname "$0")/.." || exit 1

if [ -x ".venv/bin/python" ]; then
    exec .venv/bin/python web/server.py "$@"
elif command -v python3 >/dev/null 2>&1; then
    exec python3 web/server.py "$@"
elif command -v python >/dev/null 2>&1; then
    exec python web/server.py "$@"
else
    echo "Error: python3 (or python) not found on PATH." >&2
    exit 1
fi

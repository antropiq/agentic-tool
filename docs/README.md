# agentic-tool — User Documentation

**agentic-tool** is a Python CLI tool that reads a JSON task-description file,
connects to an OpenAI-compatible LLM endpoint with MCP (Model Context Protocol)
tools, and executes the described tasks sequentially. Each task gets its own
LLM session with a selected subset of MCP tools.

The project also ships a zero-dependency **web config editor** for creating,
validating, and running those JSON config files from the browser, plus two
bundled **MCP connector servers** (console command execution and browser
automation via Playwright).

## Documentation

| Document | Contents |
|----------|----------|
| [Getting Started](getting-started.md) | Installation, first run, worked example with `examples/simple.json` |
| [Web Config Editor Guide](web-editor.md) | Step-by-step UI walkthrough with screenshots (New / Open / Save, MCP checks, Execute tab) |
| [Configuration Reference](configuration.md) | Full JSON config schema, field by field |
| [MCP Connectors](mcp-connectors.md) | The bundled `console_mcp` and `playwright_mcp` servers and their tools |

## The idea in one paragraph

You describe a *run* in a single JSON file: which LLM endpoint to talk to, which
MCP servers are available, and an ordered list of tasks. Each task has a natural
language `prompt` and a `tools` array naming the MCP servers it is allowed to
use. `agentic-tool.py` then, per task: connects to those MCP servers, converts
their tool definitions to OpenAI function-calling format, sends the prompt to
the LLM, executes any `tool_calls` the model returns, feeds the results back,
and loops until the model produces its final answer. Streamed output is printed
live to the console.

```
┌──────────────┐     ┌──────────────────┐     ┌─────────────────┐
│  agentic-    │────▶│  Task Runner      │────▶│  OpenAI Compat  │
│  tool.py     │     │  (sequential)     │     │  LLM Endpoint   │
└──────────────┘     └────────┬─────────┘     └─────────────────┘
                              │                    ▲
              ┌───────────────┼───────────────┐    │
              ▼               ▼               ▼    │ (tool calls)
        ┌───────────┐  ┌───────────┐  ┌───────────┐│
        │ MCP Server│  │ MCP Server│  │ MCP Server││
        └───────────┘  └───────────┘  └───────────┘
```

## Quick start

```bash
# 1. Setup (first time)
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium          # only needed for the browser connector

# 2. Start a bundled MCP connector (in its own terminal)
./scripts/run_console_mcp.sh         # http://127.0.0.1:9999/mcp

# 3a. Run a config from the CLI
python agentic-tool.py --file examples/simple.json

# 3b. …or edit/run configs in the browser (http://127.0.0.1:8765)
./scripts/run_web.sh
```

Windows equivalents: `scripts\run_console_mcp.bat`, `scripts\run_web.bat`.

## Requirements

- Python 3.10+
- An OpenAI-compatible LLM endpoint (local/self-hosted endpoints work without
  an API key)
- One or more running MCP servers reachable over Streamable HTTP

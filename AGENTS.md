# agentic-tool — Project Overview

## What It Is

A Python CLI tool that reads a JSON task-description file, connects to an OpenAI-compatible LLM endpoint with MCP (Model Context Protocol) tools, and executes tasks sequentially. Each task gets its own LLM session with a selected subset of MCP tools.

The repo also contains a **web sub-project** (`web/`): a zero-dependency browser editor for the JSON config files, with live validation, JSON preview, a New / Open / Save workflow (open copies a file to a temp folder, save writes to a chosen folder via the server or downloads it), and live MCP server checks.

## Quick Start

```bash
# Setup (first time)
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Run the CLI
python agentic-tool.py --file <config.json>

# Launch the web config editor (opens http://127.0.0.1:8765)
./scripts/run_web.sh        # Linux/macOS  (Windows: scripts\run_web.bat)
# options: --port <n>, --no-browser

# Standalone MCP connector servers (bundled; launcher scripts use the project venv)
./scripts/run_console_mcp.sh --port 9999      # http://127.0.0.1:9999/mcp  (Windows: scripts\run_console_mcp.bat)
./scripts/run_playwright_mcp.sh --port 8934   # http://127.0.0.1:8934/mcp  (Windows: scripts\run_playwright_mcp.bat)
# or directly: .venv/bin/python -m mcp_connectors.console_mcp / .playwright_mcp
# playwright browser tools need: playwright install chromium
```

## Config File Schema

```jsonc
{
  "name": "string",           // project/session name
  "version": "string",        // config version
  "llm": {
    "openAiCompatibleServerUrl": "http://...",  // OpenAI-compatible base URL (with /v1 suffix)
    "model": "string",         // model identifier
    "api-key": "string",       // optional bearer token for the endpoint (defaults to "not-needed")
    "systemMessage": "string", // optional system prompt
    "stream": true,            // optional, default true
    "maxToolResultLength": 120000,  // optional, truncates large tool outputs
    "sampling": {                   // optional; omitted fields are not sent
      "temperature": 0.7, "top_p": 0.95, "top_k": 40, "min_p": 0.05,
      "repeat_penalty": 1.1, "presence_penalty": 0.0,
      "reasoning_effort": "low"     // none|low|medium|high|xhigh
    },
    "mcpTools": [              // available MCP servers
      { "name": "string", "endpoint": "http://.../mcp" }
    ]
  },
  "tasks": [                   // executed sequentially, in order
    {
      "name": "string",        // task label (shown in console)
      "prompt": "string",      // full prompt sent to the LLM
      "tools": ["string"]      // subset of mcpTools names this task may use
    }
  ]
}
```

Every string value in the config is expanded at load time via `config.expand_env`
(`AppConfig` before-validator): `${VAR}` and `${VAR:-default}` from
`os.environ`; undefined vars without default stay literal; `$$` escapes `$`;
bare `$VAR` is never expanded. The web editor (stdlib-only) never expands —
it stores raw `${VAR}` text.

## Architecture

```
┌──────────────┐     ┌──────────────────┐     ┌─────────────────┐
│  agentic-    │────▶│  Task Runner      │────▶│  OpenAI Compat  │
│  tool.py     │     │  (sequential)     │     │  LLM Endpoint   │
└──────────────┘     └────────┬─────────┘     └─────────────────┘
                              │                    ▲
              ┌───────────────┼───────────────┐    │
              ▼               ▼               ▼    │
        ┌───────────┐  ┌───────────┐  ┌───────────┐│
        │ MCP Server│  │ MCP Server│  │ MCP Server││ (tool calls)
        │  (SSE/HTTP)│  │  (SSE/HTTP)│  │  (SSE/HTTP)│
        └───────────┘  └───────────┘  └───────────┘
```

**Flow per task:**
1. Resolve which MCP servers the task needs (from `task.tools`)
2. Connect to those MCP servers, discover their tools via `list_tools()`
3. Convert MCP tool definitions → OpenAI function-calling format
4. Send `prompt` + tools to LLM
5. If LLM returns `tool_calls`, execute each via the corresponding MCP client, send results back
6. Repeat step 4-5 until LLM returns a plain text response
7. Print output, move to next task

## Dependencies

| Package | Purpose |
|---------|---------|
| `openai` | OpenAI-compatible API client (chat completions with function calling) |
| `mcp` | Official MCP Python SDK — SSE/HTTP transport, tool discovery & invocation |
| `starlette` / `uvicorn` | HTTP server stack used by the bundled `mcp_connectors` servers |
| `playwright` | Browser automation for the bundled `mcp_connectors.playwright_mcp` server |

## Key Implementation Details

All task logic lives in `runner.py`; `agentic-tool.py` is only the CLI entry point.

### runner.py — exported helpers

| Function | Purpose |
|----------|---------|
| `run_task()` | Orchestrates one task (entry point from CLI) |
| `connect_mcp_servers()` | Connects MCP servers, discovers tools via `list_tools()` |
| `run_llm_loop()` | LLM chat loop with tool-calling until final response |
| `execute_tool_call()` | Routes a single tool call to the correct MCP client |
| `extract_tool_result_text()` | Extracts and truncates text from MCP results |
| `tools_to_openai_format()` | Converts MCP Tool objects → OpenAI function-calling format |

### MCP Transport
MCP server endpoints use Streamable HTTP. Pass the URL string directly to `Client`:
```python
from mcp import Client

async with Client("http://localhost:8934/mcp") as client:
    tools = await client.list_tools()
```

### Tool Routing
A single task can use multiple MCP servers. Tool calls from the LLM must be routed to the correct MCP client based on which server defined that tool. Maintain a `tool_name → (mcp_client, tool_def)` mapping.

### No API Key
The target LLM endpoints are local/self-hosted — no `api_key` is required. Pass `api_key="not-needed"` or similar placeholder to the OpenAI client.

### Console Output Format
```
Task 1/5: starting task 01_internationale
llm_output: <streaming or final text>
llm_output: <more text>
Tool call: browser_navigate → http://...
Tool result: (truncated)
llm_output: <final response>
Task 1/5: done

...

All 5 tasks are done, quitting the app.
```

## Web Config Editor (`web/`)

A browser-based editor for the JSON config files. **Standard library only** — no npm, no build step, no project dependencies.

### Running

```bash
./scripts/run_web.sh             # Linux/macOS (Windows: scripts\run_web.bat)
python3 web/server.py --port 9000 --no-browser
```

Serves at `http://127.0.0.1:8765` by default (loopback only). Relative config paths resolve against the project root.

### Architecture

- `web/server.py` — `ThreadingHTTPServer` serving the static UI plus a small JSON API:

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/` , static files | GET | Serves `index.html`, `app.js`, `style.css` (path-traversal guarded to `web/`) |
| `/api/browse?dir=...` | GET | Lists directories and `.json` files for the Open modal (defaults to the project root) |
| `/api/open` | POST | Reads a `.json` config, validates it, copies it into the temp edit folder (`$TMPDIR/agentic-tool-editor`), returns `name`, `tmpPath`, `data` |
| `/api/check` | POST | Probes an MCP endpoint: `initialize` → `notifications/initialized` → `tools/list` over raw JSON-RPC (handles both plain JSON and SSE replies); returns `serverInfo`, `toolCount`, tool list, or a friendly error |
| `/api/save` | POST | Writes the edited config (`dir`, `name`, `data`) as a `.json` file into the chosen directory (name sanitized, `.json` enforced); returns `name`, `path` |
| `/api/run/start` | POST | Ensures the config's MCP servers are reachable first (bundled connectors that are down are auto-started and re-stopped when the run ends; any other unreachable MCP server aborts the start), then launches `<venv python> agentic-tool.py --file <path>` (cwd = project root) and captures merged stdout/stderr into a ring buffer; rejects if a run is already in progress |
| `/api/run/stop` | POST | Terminates the running `agentic-tool.py` process (kill after 5s) |
| `/api/run/status?offset=N` | GET | `running`, `exitCode`, `path`, output `lines` appended since `offset` (with `reset: true` when the buffer wrapped past `offset`), and `pending` (the not-yet-newline-terminated tail, so streaming deltas render live); the child runs with `-u`/`PYTHONUNBUFFERED=1` and the pump reads raw chunks, so output appears as in a console; the client polls this every second while the Execute tab is open |
| `/api/connectors` | GET | Lists the bundled MCP connectors (`mcp_connectors` modules) with `status` (`running`/`stopped`/`external` port-busy), pid, endpoint, and recent log tail |
| `/api/connectors/start`, `/api/connectors/stop` | POST | Starts/stops a connector (`id`) as a child process (`<venv python> -m mcp_connectors.<id> --port <default>`); children are terminated when the editor server exits |

- `web/app.js` — vanilla JS SPA with Settings/Tasks/Execute tabs, live validation, JSON preview, per-MCP-server "Check" buttons with a result modal, and task→tool checkbox assignment. Follows a New / Open / Save workflow: Open uses the `/api/browse` + `/api/open` modal (original file never modified, edits happen on the temp copy); Save shows a filename field plus the same folder browser and writes via `/api/save` ("Save here") or downloads the config through the browser ("Download").
 The toolbar's "MCP Connectors" button opens a modal listing the bundled connectors with start (▶) / stop (■) controls and a "+" that adds the connector as an `mcpTools` entry (disabled when already present).
 The toolbar also has a separator plus ▶ Play / ■ Stop buttons that are only enabled while the Execute tab is selected: Play requires a loaded config (temp copy or saved path), zero validation errors, no unsaved changes, and no run in progress; Stop requires a run in progress. The Execute tab shows the run's live stdout/stderr in a readonly textarea (1s polling of `/api/run/status`).
- `scripts/run_web.sh` / `scripts/run_web.bat` — thin launchers that cd to the project root, prefer `.venv/bin/python` (or `.venv\Scripts\python.exe`), fall back to `python3`/`py`/`python`, and forward flags. `scripts/run_console_mcp.*` and `scripts/run_playwright_mcp.*` do the same for `python -m mcp_connectors.console_mcp` / `playwright_mcp`.

### MCP Check Implementation Note

The editor's `/api/check` does **not** use the `mcp` package — it hand-rolls Streamable HTTP JSON-RPC with `urllib` (with a cookie jar and `Mcp-Session-Id` / `MCP-Protocol-Version` headers) so the editor stays dependency-free.

## Project Structure

```
agentic-tool/
├── agentic-tool.py      # CLI entry point (argparse, config loading + validation, task loop)
├── runner.py            # Task execution (MCP connect, LLM loop, tool routing)
├── config.py            # Pydantic models for the JSON config (AppConfig, LlmConfig, TaskConfig, McpToolConfig)
├── requirements.txt     # openai, mcp, pydantic, starlette, uvicorn, playwright
├── README.md            # user-facing documentation
├── scripts/             # Launcher scripts (.sh/.bat): run_web, run_console_mcp, run_playwright_mcp
├── examples/            # Example config files (simple.json) + run instructions
├── mcp_connectors/      # Standalone MCP connector servers (run via python -m)
│   ├── console_mcp.py   # Console command execution server (MCPServer/FastMCP-style, default port 9999)
│   └── playwright_mcp.py# Browser automation server (lowlevel Server, Streamable HTTP only, default port 8934)
├── web/                 # Browser config editor (stdlib server + vanilla JS UI)
│   ├── server.py        # HTTP server + static files + /api/browse,/api/open,/api/check,/api/save,/api/run/*
│   ├── index.html       # UI markup (Settings/Tasks/Execute tabs, modals)
│   ├── app.js           # Editor state, validation, JSON preview, MCP checks
│   └── style.css        # UI styles
├── .venv/               # Python virtualenv
└── AGENTS.md            # this file
```

## Gotchas

- **MCP servers must be running before execution** — the tool will fail if an MCP endpoint is unreachable. Connect lazily per-task and handle connection failures gracefully.
- **Tool definitions can change at runtime** — always call `list_tools()` fresh on each task, don't cache across tasks.
- **Large tool responses** — MCP tool outputs (e.g. full page HTML/text) can exceed LLM context limits. Truncate tool results if needed (configurable threshold).
- **Streamable HTTP only** — pass the MCP endpoint URL directly to `Client(url)`. Do not use `StreamableHTTPTransport` or SSE transports; they are not async context managers and will fail.
- **Web editor is loopback-only and dependency-free** — `web/server.py` binds to `127.0.0.1`, guards static file paths against traversal out of `web/`, and must keep working with stdlib only (don't import `openai`/`mcp`/`pydantic` there). `/api/save` intentionally writes config files to any local directory (server-side file writes are possible by design — never expose the server beyond loopback).

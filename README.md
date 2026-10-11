# agentic-tool

A Python CLI tool that reads a JSON task-description file, connects to an
OpenAI-compatible LLM endpoint with MCP (Model Context Protocol) tools, and
executes tasks sequentially. Each task gets its own LLM session with a
selected subset of MCP tools.

## How It Works

For each task in the config file, the tool:

1. Connects to the MCP servers listed in the task's `tools` array and discovers
   their tools via `list_tools()`.
2. Converts the MCP tool definitions to OpenAI function-calling format.
3. Sends the task `prompt` plus the available tools to the LLM.
4. When the LLM returns `tool_calls`, each call is routed to the MCP server
   that defined the tool, and the results are sent back to the LLM.
5. Repeats the loop until the LLM signals completion (or the iteration cap is
   reached), then moves on to the next task.

Streamed responses are printed live to the console. MCP servers are connected
per task and always re-discovered fresh, so tool definitions can change between
tasks.

## Requirements

- Python 3.10+
- An OpenAI-compatible LLM endpoint (local/self-hosted endpoints work without
  an API key)
- One or more running MCP servers reachable over Streamable HTTP

## Installation

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

### Playwright browser binaries

The bundled `playwright_mcp` connector needs real browser binaries in addition
to the Python package. After `pip install`, download Chromium once:

```bash
playwright install chromium
```

Without this step the server still starts and lists its tools, but every
browser tool call fails with a "browser executable not found" error. (Pass
`--with-deps` instead if system libraries are also missing, e.g. on a fresh
Linux install: `playwright install --with-deps chromium`.)

## Running

```bash
python agentic-tool.py --file <config.json>
```

Make sure the MCP servers referenced in the config are running before starting
the tool — unreachable endpoints cause the task to fail.

### Web config editor

A zero-dependency browser editor for config files lives in the `web/` folder.
Start it and it opens a page at `http://127.0.0.1:8765` (pass `--port` or
`--no-browser` to change this):

```bash
./scripts/run_web.sh        # Linux/macOS
scripts\run_web.bat         # Windows
```

The editor uses a New / Open / Save workflow: **Open** shows a file
browser modal, and the picked file is copied into a temp folder
(`/tmp/agentic-tool-editor`) for editing — the original is never modified.
**Save** shows a filename field plus a folder browser: **Save
here** writes the file into the chosen folder via the local server, or
**Download** fetches it through the browser. It includes live JSON preview and validation, and uses
only the Python standard library — no npm/build step required.

### Example config

```jsonc
{
  "name": "my-run",
  "version": "1.0",
  "llm": {
    "openAiCompatibleServerUrl": "http://localhost:8080/v1",
    "model": "my-model",
    "api-key": "not-needed",            // optional, defaults to "not-needed"
    "systemMessage": "You are a research assistant.",  // optional
    "stream": true,                       // optional, default true
    "maxToolResultLength": 120000,        // optional, truncates large tool outputs
    "mcpTools": [
      { "name": "browser", "endpoint": "http://localhost:8934/mcp" },
      { "name": "console", "endpoint": "http://localhost:8935/mcp" }
    ]
  },
  "tasks": [
    {
      "name": "01_internationale",
      "prompt": "Research the origin of the song and summarize it.",
      "tools": ["browser"]               // subset of mcpTools names this task may use
    }
  ]
}
```

### Environment variables in config files

Any string value in the config supports `${VAR}` interpolation, expanded from
the process environment when the config is loaded (prompts, endpoints, URLs —
everything). `${VAR:-fallback}` uses `fallback` when `VAR` is not set; an
undefined variable without a default is left as-is; `$$` is a literal `$`
(so `$${VAR}` stays literal). Bare `$VAR` is never expanded.

```jsonc
"prompt": "List files located at ${HOME}/dev/agentic-tool"
```

The web editor stores the raw `${VAR}` text; expansion happens at load/run time.

### Console output

```
Task 1/5: starting task 01_internationale
llm_output: <streaming or final text>
Tool call: browser_navigate → http://...
Tool result: (truncated)
llm_output: <final response>
Task 1/5: done

...

All 5 tasks are done, quitting the app.
```

## Bundled MCP connectors

This project ships two standalone MCP connector servers in the `mcp_connectors/`
folder. Both speak Streamable HTTP and are started with the launcher scripts in
the `scripts/` folder (they use the project venv when present). Each must be
running (in its own terminal) before you execute tasks that reference it.

### Running them

```bash
# Console command execution server — http://127.0.0.1:9999/mcp
./scripts/run_console_mcp.sh        # Windows: scripts\run_console_mcp.bat
# options: --port <n>, --host <addr>, --debug

# Browser automation server — http://127.0.0.1:8934/mcp
./scripts/run_playwright_mcp.sh     # Windows: scripts\run_playwright_mcp.bat
# options: --port <n>, --host <addr>
```

Equivalently, as Python modules with the project venv:

```bash
.venv/bin/python -m mcp_connectors.console_mcp
.venv/bin/python -m mcp_connectors.playwright_mcp
```

| Server | Default endpoint | Tools exposed |
|--------|------------------|---------------|
| `mcp_connectors.console_mcp` | `http://127.0.0.1:9999/mcp` | `execute_command`, `list_allowed_commands`, `check_command_allowed`, `safe_file_read`, `safe_file_write` |
| `mcp_connectors.playwright_mcp` | `http://127.0.0.1:8934/mcp` | `browser_navigate`, `browser_screenshot`, `browser_click`, `browser_type`, `browser_get_text`, `browser_evaluate`, `browser_select_option`, `browser_press_key`, `browser_scroll_down`, `browser_scroll_up`, `browser_go_back`, `browser_go_forward`, `browser_close` |

Notes:

- `console_mcp` only executes commands on a security whitelist and blocks
  dangerous ones (`rm`, `dd`, `shutdown`, …); it binds to `127.0.0.1` by default.
- `playwright_mcp` binds to `127.0.0.1` by default — pass `--host 0.0.0.0`
  to let other machines on your network reach it.
- `playwright_mcp` requires the Chromium binaries (see
  [Installation](#installation)).

### Using them in tasks

Declare each running connector as an entry in `llm.mcpTools` (the `name` is
yours to pick, the `endpoint` must match the running server), then reference
those names in each task's `tools` array:

```jsonc
{
  "name": "my-run",
  "version": "1.0",
  "llm": {
    "openAiCompatibleServerUrl": "http://localhost:8080/v1",
    "model": "my-model",
    "mcpTools": [
      { "name": "console",  "endpoint": "http://127.0.0.1:9999/mcp" },
      { "name": "browser",  "endpoint": "http://127.0.0.1:8934/mcp" }
    ]
  },
  "tasks": [
    {
      "name": "scrape-and-log",
      "prompt": "Open https://example.com, save the page text to /tmp/page.txt, then list that file.",
      "tools": ["browser", "console"]   // this task may use both connectors
    },
    {
      "name": "disk-usage",
      "prompt": "Show which directories under /var use the most space.",
      "tools": ["console"]              // browser is not available to this task
    }
  ]
}
```

A task can only call tools from the servers listed in its `tools` array; the
same connector can be shared by any number of tasks. You can verify a running
connector with the **Check** button in the web config editor, or simply by
pointing `endpoint` at it — unreachable endpoints make the task fail.

## Project Structure

```
agentic-tool/
├── agentic-tool.py    # CLI entry point (argparse, config loading + validation, task loop)
├── runner.py          # Task execution (MCP connect, LLM loop, tool routing)
├── config.py          # Pydantic models for the JSON config
├── requirements.txt   # openai, mcp, pydantic, starlette, uvicorn, playwright
├── scripts/           # Launcher scripts (run_web, run_console_mcp, run_playwright_mcp — .sh/.bat)
├── examples/          # Example config files (simple.json) + how to run them
├── mcp_connectors/    # Standalone MCP connector servers (console_mcp, playwright_mcp)
└── web/               # Browser-based config editor (stdlib server + vanilla JS UI)
```

## License

Copyright (c) 2026 vgr. All rights not expressly granted are reserved.

This software is provided free of charge for **non-commercial use only**.
You may use, modify, and redistribute it (in whole or in part) for
non-commercial purposes, provided that every copy or derivative work
includes the license text and clearly credits the project origin
("agentic-tool" and its public repository URL) — including when it is
included within another open-source stack.

Commercial use of all or part of this software requires a separate written
commercial license. See [LICENSE.md](LICENSE.md) for the full terms.

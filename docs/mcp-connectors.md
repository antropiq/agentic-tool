# Bundled MCP Connectors

The project ships two standalone MCP connector servers in `mcp_connectors/`.
Both speak Streamable HTTP, bind to `127.0.0.1` by default, and must be running
before any task that references them. The web editor can start/stop them for
you (MCP Connectors modal, and auto-start on Play) — see the
[Web Config Editor Guide](web-editor.md).

## Running them

```bash
# Console command execution server — http://127.0.0.1:9999/mcp
./scripts/run_console_mcp.sh         # Windows: scripts\run_console_mcp.bat
# options: --port <n>, --host <addr>, --debug

# Browser automation server — http://127.0.0.1:8934/mcp
./scripts/run_playwright_mcp.sh      # Windows: scripts\run_playwright_mcp.bat
# options: --port <n>, --host <addr>
```

Equivalently, as Python modules with the project venv:

```bash
.venv/bin/python -m mcp_connectors.console_mcp
.venv/bin/python -m mcp_connectors.playwright_mcp
```

The launcher scripts cd to the project root and prefer the `.venv` Python.

## Using a connector in a config

Declare each running connector in `llm.mcpTools` (you pick the `name`; the
`endpoint` must match the running server), then reference those names in each
task's `tools` array:

```jsonc
"llm": {
  "mcpTools": [
    { "name": "console", "endpoint": "http://127.0.0.1:9999/mcp" },
    { "name": "browser", "endpoint": "http://127.0.0.1:8934/mcp" }
  ]
},
"tasks": [
  { "name": "scrape-and-log",
    "prompt": "Open https://example.com, save the page text to /tmp/page.txt, then list that file.",
    "tools": ["browser", "console"] },
  { "name": "disk-usage",
    "prompt": "Show which directories under /var use the most space.",
    "tools": ["console"] }
]
```

Verify a running connector with the editor's **Check** button (it performs a
real `initialize` → `tools/list` handshake and lists the tools — see
[MCP check screenshot](web-editor.md#4-check-an-mcp-server)).

---

## `console_mcp` — console command execution

**Default endpoint:** `http://127.0.0.1:9999/mcp`

| Tool | Purpose |
|------|---------|
| `execute_command` | Run a shell command, subject to the security policy below |
| `list_allowed_commands` | Print the command whitelist |
| `check_command_allowed` | Test one command against the policy without running it |
| `safe_file_read` | Read a file (default cap 1000 lines) |
| `safe_file_write` | Write text to a file |

### Security model

`execute_command` validates every command before running it:

1. **Whitelist** — only these base commands are allowed:
   `ls dir cat echo pwd whoami date time find grep sed wc head tail sort uniq
   cut mkdir touch cp mv rm chmod chown ps top df du free uptime hostname curl
   wget ping nslookup dig python python3 node npm pip git vim nano less more man
   env printenv id groups who w`
2. **Always blocked** (even though some are on the whitelist):
   `rm rmdir chmod chown mkfs dd shutdown reboot poweroff`
3. **Dangerous shell patterns rejected**: `|` `;` `&` `>` `<` `$(` `` ` `` `||`
   `&&` — no pipes, chaining, or redirection.

The practical effect (visible in the
[getting-started run log](getting-started.md#4-run-it-from-the-cli)): the model
learns mid-task that `ls > file` is rejected and switches to
`safe_file_write`. Pass `--host 0.0.0.0` to expose the server beyond loopback
(not recommended).

## `playwright_mcp` — browser automation

**Default endpoint:** `http://127.0.0.1:8934/mcp` (Streamable HTTP only)

| Tool | Purpose |
|------|---------|
| `browser_navigate` | Go to a URL |
| `browser_screenshot` | Capture the current page |
| `browser_click` | Click an element by CSS selector |
| `browser_type` | Type text into an input (optional submit) |
| `browser_get_text` | Read text content of an element or the page |
| `browser_evaluate` | Run JavaScript in the page and return the result |
| `browser_select_option` | Choose a `<select>` option |
| `browser_press_key` | Send a keyboard key |
| `browser_scroll_down` / `browser_scroll_up` | Scroll by one viewport |
| `browser_go_back` / `browser_go_forward` | History navigation |
| `browser_close` | Close the browser and end the session |

### Requirements

Real Chromium binaries are needed in addition to the Python package:

```bash
playwright install chromium
# fresh Linux installs may also need system libraries:
playwright install --with-deps chromium
```

Without them the server starts and lists its tools, but every browser tool call
fails with "browser executable not found".

### Notes

- Binds to `127.0.0.1` by default — pass `--host 0.0.0.0` to let other machines
  on your network reach it.
- Tool definitions are re-discovered fresh per task, so a connector restart is
  picked up on the next task automatically.

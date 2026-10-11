# Getting Started

This guide takes you from a fresh checkout to a completed run using the example
config `examples/simple.json`. Screenshots of the web editor steps are in the
[Web Config Editor Guide](web-editor.md).

## 1. Install

```bash
cd agentic-tool
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

If you plan to use the bundled **browser automation** connector, download the
Chromium binaries once:

```bash
playwright install chromium          # add --with-deps on a fresh Linux install
```

Without this step the server still starts and lists its tools, but every
browser tool call fails with a "browser executable not found" error.

## 2. Start an MCP connector

Tasks can only use MCP servers that are **already running**. Start the console
connector in its own terminal:

```bash
./scripts/run_console_mcp.sh         # Windows: scripts\run_console_mcp.bat
# → http://127.0.0.1:9999/mcp
```

See [MCP Connectors](mcp-connectors.md) for the full list of bundled servers.

## 3. Understand the example config

`examples/simple.json` is a complete, minimal run definition:

```json
{
  "name": "my-run",
  "version": "1.0",
  "llm": {
    "openAiCompatibleServerUrl": "http://192.168.1.2:8080/v1",
    "model": "qwen3.8-flash-next-unsloth-ud-iq4_xs",
    "api-key": "not-needed",
    "systemMessage": "You are a helpfull assistant.",
    "stream": true,
    "maxToolResultLength": 120000,
    "mcpTools": [
      { "name": "console_mcp", "endpoint": "http://127.0.0.1:9999/mcp" }
    ]
  },
  "tasks": [
    {
      "name": "01_list_files",
      "prompt": "Using the console tools list files located at /home/vgr/dev/agentic-tool and put them in a file named agentic-tool-content-folder.txt within my $HOME directory.",
      "tools": ["console_mcp"]
    }
  ]
}
```

Reading it top to bottom:

- `llm.openAiCompatibleServerUrl` / `llm.model` — the OpenAI-compatible endpoint
  and model to chat with (adjust these to match *your* server).
- `llm.mcpTools` — the pool of available MCP servers. Here there is one, named
  `console_mcp`, pointing at the connector started in step 2.
- `tasks[]` — executed sequentially, in order. The single task asks the model
  to list a directory and save the listing to a file, and may only use tools
  from the `console_mcp` server (its `tools` array).

See [Configuration Reference](configuration.md) for every field.

## 4. Run it from the CLI

```bash
python agentic-tool.py --file examples/simple.json
```

Console output from a real run of this exact config (the model adapts to the
console connector's safety filters on its own):

```
Task 1/1: starting task 01_list_files
  LLM iteration 1/200
  Tool call: execute_command with args {"command": "ls -la /home/vgr/dev/agentic-tool"}
  Tool call: execute_command with args {"command": "echo $HOME"}
  LLM iteration 2/200
I found the directory contents. Now I'll save the listing to a file in your home directory.
  Tool call: execute_command with args {"command": "ls /home/vgr/dev/agentic-tool > ..."}
  LLM iteration 3/200
  ...
  Tool call: safe_file_write with args {"filepath": "/home/vgr/agentic-tool-content-folder.txt", ...}
  LLM iteration 6/200
  Tool call: safe_file_read with args {"filepath": "/home/vgr/agentic-tool-content-folder.txt"}
  LLM iteration 7/200
Done! I listed the contents of `/home/vgr/dev/agentic-tool` and saved them to ...
{"task_result": "completed"}
  Task 1/1: done

All 1 tasks are done, quitting the app.
```

What happened, step by step, per task:

1. The tool connected to the MCP servers in `task.tools` and discovered their
   tools via `list_tools()` (always re-discovered fresh, never cached).
2. Tool definitions were converted to OpenAI function-calling format.
3. The task `prompt` plus tools were sent to the LLM.
4. Every `tool_call` the model returned was routed to the MCP server that
   defines it; results were sent back.
5. The loop repeated until the model returned its final text answer, then the
   next task started (here there is only one).

## 5. Or use the web editor instead

```bash
./scripts/run_web.sh                 # opens http://127.0.0.1:8765
```

From the browser you can **Open** `examples/simple.json`, verify the MCP server
with **Check**, tweak prompts on the **Tasks** tab, and press **▶ Play** on the
**Execute** tab to run it with live console output — all without leaving the
page. The complete walkthrough with screenshots:
[Web Config Editor Guide](web-editor.md).

## Troubleshooting

| Symptom | Cause / fix |
|---------|-------------|
| Task fails immediately, MCP connection error | The MCP server in `tools` isn't running — start it (`scripts/run_console_mcp.*`), or use the editor's **MCP Connectors** modal / **Check** button |
| `browser executable not found` on a browser tool call | Run `playwright install chromium` |
| LLM connection errors | Verify `openAiCompatibleServerUrl` (must include the `/v1` suffix) and that the endpoint is up |
| Very large tool outputs missing from context | Outputs above `maxToolResultLength` characters are truncated by design; raise the value if needed |

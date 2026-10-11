# Examples

Example config files for the agentic-tool CLI. Run all commands from the
**project root** (the folder containing `agentic-tool.py`).

## simple.json

A minimal single-task config: it connects to an OpenAI-compatible LLM endpoint
and uses the bundled `console_mcp` connector to list the files of a folder and
write them to `~/agentic-tool-content-folder.txt`.

### 1. Set up the environment (first time only)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Point the config at your LLM endpoint

Open `examples/simple.json` and adjust the `llm` section:

- `openAiCompatibleServerUrl` — base URL of your OpenAI-compatible endpoint
  (with the `/v1` suffix); the example uses `http://192.168.1.2:8080/v1`.
- `model` — the model identifier served by that endpoint.
- `api-key` — keep `"not-needed"` for local/self-hosted endpoints.

Also check the task `prompt` — it references `/home/vgr/dev/agentic-tool`;
change it to a folder that exists on your machine.

### 3. Start the console MCP connector

The task uses the `console_mcp` server, which must be running **before** the
tool executes (in its own terminal):

```bash
./scripts/run_console_mcp.sh        # Linux/macOS
scripts\run_console_mcp.bat         # Windows
```

It serves at `http://127.0.0.1:9999/mcp` (options: `--port <n>`,
`--host <addr>`, `--debug`).

### 4. Run the example

```bash
python agentic-tool.py --file examples/simple.json
```

The tool connects to the LLM, executes the task (with the `console_mcp`
tools), prints the output, and quits when all tasks are done.

### Expected output

```
Task 1/1: starting task 01_list_files
llm_output: ...
Tool call: execute_command → ls -la /home/vgr/dev/agentic-tool
...
Task 1/1: done

All 1 tasks are done, quitting the app.
```

You should then find `agentic-tool-content-folder.txt` in your home directory.

### Troubleshooting

- **"MCP endpoint unreachable"** — the connector isn't running or uses a
  different port; start it (step 3) or match the `endpoint` in the config.
- **Connection error to the LLM** — verify `openAiCompatibleServerUrl` and
  `model` in the config and that the endpoint is up.
- **Allowed commands** — `console_mcp` only runs whitelisted commands
  (`ls`, `cat`, `ps`, …) and blocks dangerous ones (`rm`, `dd`, …).

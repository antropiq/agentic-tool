# Configuration Reference

A config file is a single JSON document validated by the Pydantic models in
`config.py`. Unknown keys are ignored. The web editor enforces the same schema
with live validation (see the [Web Config Editor Guide](web-editor.md)).

## Top level — `AppConfig`

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | string | no | Project/session name |
| `version` | string | no | Config version |
| `llm` | object | **yes** | LLM + MCP connection settings ([LlmConfig](#llm--llmconfig)) |
| `tasks` | array | no | Tasks executed sequentially, in order ([TaskConfig](#tasks--taskconfig)) |

## `llm` — `LlmConfig`

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `openAiCompatibleServerUrl` | string | **required** | OpenAI-compatible base URL, **including the `/v1` suffix** (e.g. `http://localhost:8080/v1`) |
| `model` | string | **required** | Model identifier served by the endpoint |
| `api-key` | string | `"not-needed"` | Bearer token for the endpoint. Local/self-hosted endpoints don't need one — the placeholder default is used |
| `systemMessage` | string \| null | `null` | Optional system prompt; `null`/absent uses the built-in default |
| `stream` | boolean | `true` | Stream the LLM response to the console as it arrives |
| `maxToolResultLength` | integer | `120000` | Tool outputs longer than this many characters are truncated before being sent back to the LLM (protects the context window) |
| `mcpTools` | array | `[]` | Available MCP servers ([McpToolConfig](#mcptools--mcptoolconfig)) |

## `llm.mcpTools[]` — `McpToolConfig`

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | string | **yes** | Your label for this server; tasks reference it in their `tools` array |
| `endpoint` | string | **yes** | Streamable HTTP MCP endpoint, e.g. `http://127.0.0.1:9999/mcp`. The server must already be running |

## `tasks[]` — `TaskConfig`

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `name` | string | **required** | Task label shown in the console (`Task 1/5: starting task <name>`) |
| `prompt` | string | **required** | The full prompt sent to the LLM for this task |
| `tools` | array of strings | `[]` | Subset of `llm.mcpTools[].name` values this task may use. A task can only call tools from these servers |

## Execution semantics

- Tasks run **sequentially, in order**; one task's conversation never leaks
  into the next.
- Per task: connect to its MCP servers → `list_tools()` fresh (never cached
  across tasks) → convert to OpenAI function-calling format → prompt the LLM →
  execute returned `tool_calls` (routed by `tool_name → (client, tool_def)`) →
  repeat until a plain-text answer or the iteration cap.
- Unreachable MCP endpoints cause the task to fail — start servers first, or
  verify them with the editor's **Check** button.

## Full annotated example

Based on `examples/simple.json`:

```jsonc
{
  "name": "my-run",
  "version": "1.0",
  "llm": {
    "openAiCompatibleServerUrl": "http://192.168.1.2:8080/v1", // /v1 suffix required
    "model": "qwen3.8-flash-next-unsloth-ud-iq4_xs",
    "api-key": "not-needed",              // optional; omit for local endpoints
    "systemMessage": "You are a helpfull assistant.",  // optional
    "stream": true,                       // optional, default true
    "maxToolResultLength": 120000,        // optional, default 120000
    "mcpTools": [
      { "name": "console_mcp", "endpoint": "http://127.0.0.1:9999/mcp" },
      { "name": "browser",     "endpoint": "http://127.0.0.1:8934/mcp" }
    ]
  },
  "tasks": [
    {
      "name": "01_list_files",
      "prompt": "Using the console tools list files located at /home/vgr/dev/agentic-tool and put them in a file named agentic-tool-content-folder.txt within my $HOME directory.",
      "tools": ["console_mcp"]            // only console tools here
    },
    {
      "name": "02_scrape",
      "prompt": "Open https://example.com and summarize the page.",
      "tools": ["browser", "console_mcp"] // this task may use both
    }
  ]
}
```

## Running a config

```bash
python agentic-tool.py --file <config.json>
```

Or load it in the web editor and press **▶ Play** on the Execute tab.
Expected console output format:

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

"""Task runner — connect MCP servers, execute LLM tool-calling loops."""

import json
from contextlib import AsyncExitStack
from types import SimpleNamespace

from mcp import Client
from openai import AsyncOpenAI

from config import LlmConfig, McpToolConfig, TaskConfig

DEFAULT_SYSTEM_MESSAGE = (
    "You are an autonomous research assistant. "
    "You have access to browser automation and console tools. "
    "Think step by step. Use tools methodically. "
    "Do not hallucinate content — only use information gathered from the tools you call."
)

# Appended to every system message (default or user-provided) so the tool can
# reliably detect when the LLM considers its work finished.
COMPLETION_SENTINEL_DIRECTIVE = (
    "\n\nIMPORTANT: When your work is fully complete, send a final message containing "
    'ONLY this JSON and nothing else: {"task_result": "completed"}'
    "\nWarning: this is not a Tool call but a regular message to be sended back to the user."
)

# The exact string the LLM must output to signal task completion.
COMPLETION_SENTINEL = '{"task_result": "completed"}'

MAX_ITERATION = 200


def _delta_content_to_text(content) -> str:
    """Coerce a streaming content delta to plain raw text.

    Most OpenAI-compatible servers send ``str`` deltas, but some send an
    array of content parts (e.g. ``[{"type": "text", "text": "..."}]``).
    Printing those objects would log a repr instead of readable text.
    """
    if not content:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for part in content:
            if isinstance(part, str):
                parts.append(part)
            elif isinstance(part, dict) and isinstance(part.get("text"), str):
                parts.append(part["text"])
            elif getattr(part, "text", None) is not None and isinstance(part.text, str):
                parts.append(part.text)
        return "".join(parts)
    return ""


async def stream_chat_completion(llm_client, live_print: bool = False, **kwargs):
    """Call chat.completions with stream=True and reassemble a
    ChatCompletion-shaped object from the chunks, so the rest of the loop
    works unchanged. Streaming keeps bytes flowing to the proxy
    (llama-swap), avoiding its 600s idle timeout on long generations.

    If live_print is True, each text fragment is printed as it arrives.
    """
    content_parts: list[str] = []
    tool_calls: dict[int, dict] = {}
    finish_reason = None

    async for chunk in await llm_client.chat.completions.create(stream=True, **kwargs):
        if not chunk.choices:
            continue
        delta = chunk.choices[0].delta
        if chunk.choices[0].finish_reason:
            finish_reason = chunk.choices[0].finish_reason

        delta_text = _delta_content_to_text(delta.content)
        if delta_text:
            content_parts.append(delta_text)
            if live_print:
                print(delta_text, end="")

        if delta.tool_calls:
            for tc_delta in delta.tool_calls:
                idx = tc_delta.index or 0
                entry = tool_calls.setdefault(idx, {"id": None, "name": None, "arguments": ""})
                if tc_delta.id:
                    entry["id"] = tc_delta.id
                if tc_delta.function:
                    # name can theoretically also be split across chunks
                    entry["name"] = (entry["name"] or "") + (tc_delta.function.name or "")
                    if tc_delta.function.arguments:
                        entry["arguments"] += tc_delta.function.arguments

    # End the live-printed line (the caller's batched prints also end with \n)
    if live_print and content_parts:
        print()

    message = SimpleNamespace(
        content="".join(content_parts) or None,
        tool_calls=[
            SimpleNamespace(
                id=entry["id"],
                type="function",
                function=SimpleNamespace(name=entry["name"], arguments=entry["arguments"]),
            )
            for _, entry in sorted(tool_calls.items())
        ],
    )
    return SimpleNamespace(choices=[SimpleNamespace(message=message, finish_reason=finish_reason)])


def _is_completion_sentinel(text: str) -> bool:
    """Check whether the LLM's response contains the completion sentinel.

    The LLM may embed the sentinel anywhere in its reply, surrounded by
    natural-language text. We try to parse every JSON fragment found and
    accept if any matches {"task_result": "completed"}.
    """
    # Quick check: exact match (most common after the reminder prompt)
    if text.strip() == COMPLETION_SENTINEL:
        return True

    # Broader check: look for a JSON object containing the sentinel key anywhere
    # in the text. This handles cases like:
    #   "Le document est complet.\n\n{\"task_result\": \"completed\"}"
    #   "Je signal que c'est terminé: {\"task_result\": \"completed\"}, fin."
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict) and parsed.get("task_result") == "completed":
            return True
    except (json.JSONDecodeError, ValueError):
        pass

    # Last resort: substring search for the key-value pair, tolerant of
    # whitespace variations (spaces around colon, different quote styles).
    import re
    pattern = r'"task_result"\s*:\s*"completed"'
    return bool(re.search(pattern, text))


def tools_to_openai_format(tools: list) -> list[dict]:
    """Convert MCP Tool objects to OpenAI function-calling format."""
    return [
        {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description or "",
                "parameters": tool.input_schema or {"type": "object", "properties": {}},
            },
        }
        for tool in tools
    ]


def extract_tool_result_text(result, max_length: int = 120_000) -> str:
    """Extract plain text from an MCP CallToolResult, truncating if needed."""
    # Check for explicit error flag from the MCP server
    if getattr(result, "is_error", False):
        error_texts = []
        for item in result.content:
            if hasattr(item, "text"):
                error_texts.append(item.text)
            elif isinstance(item, dict) and "text" in item:
                error_texts.append(item["text"])
        return ("\n".join(error_texts)
                if error_texts
                else "[Tool execution failed — no error details provided.]")

    # Separate text content from non-text content types
    text_parts = []
    non_text_types = []
    for item in result.content:
        if hasattr(item, "text"):
            text_parts.append(item.text)
        elif isinstance(item, dict) and "text" in item:
            text_parts.append(item["text"])
        else:
            content_type = (
                getattr(item, "type", None)
                or (item.get("type") if isinstance(item, dict) else None)
                or type(item).__name__
            )
            non_text_types.append(content_type)

    # Build response based on what we found
    if text_parts:
        text = "\n".join(text_parts)
        if non_text_types:
            types_summary = ", ".join(sorted(set(non_text_types)))
            text += f"\n[Note: tool also returned non-text content of types: {types_summary}]"
    elif non_text_types:
        types_summary = ", ".join(sorted(set(non_text_types)))
        text = f"[Tool returned no text output. Content types received: {types_summary}]"
    else:
        text = "[Tool returned empty response.]"

    if len(text) > max_length:
        text = text[:max_length] + "\n... [truncated]"
    return text


async def connect_mcp_servers(
    stack: AsyncExitStack,
    requested_tools: list[str],
    mcp_servers: dict[str, McpToolConfig],
) -> tuple[dict[str, Client], list, dict[str, str]]:
    """Connect to MCP servers and discover available tools.

    Returns (clients, all_mcp_tools, tool_to_server).
    """
    clients: dict[str, Client] = {}
    all_mcp_tools: list = []
    tool_to_server: dict[str, str] = {}

    for server_name in requested_tools:
        if server_name not in mcp_servers:
            print(f"  Warning: MCP server '{server_name}' not found in config, skipping.")
            continue

        server_info = mcp_servers[server_name]
        client = Client(server_info.endpoint)
        await stack.enter_async_context(client)
        clients[server_name] = client

        try:
            tools_result = await client.list_tools()
            for tool in tools_result.tools:
                all_mcp_tools.append(tool)
                tool_to_server[tool.name] = server_name
        except Exception as e:
            print(f"  Warning: failed to list tools from {server_name}: {e}")

    return clients, all_mcp_tools, tool_to_server


async def execute_tool_call(
    tool_name: str,
    tool_args: dict,
    clients: dict[str, Client],
    tool_to_server: dict[str, str],
    max_tool_result_length: int = 120_000,
) -> str:
    """Route and execute a single MCP tool call, returning the text result."""
    server_name = tool_to_server.get(tool_name)
    if not server_name or server_name not in clients:
        return f"Error: tool '{tool_name}' not found"

    try:
        result = await clients[server_name].call_tool(tool_name, tool_args)
        return extract_tool_result_text(result, max_length=max_tool_result_length)
    except Exception as e:
        return f"Error calling {tool_name}: {e}"


async def run_llm_loop(
    llm_client: AsyncOpenAI,
    model: str,
    prompt: str,
    openai_tools: list[dict],
    clients: dict[str, Client],
    tool_to_server: dict[str, str],
    task_num: int,
    total: int,
    max_tool_result_length: int = 120_000,
    system_message: str | None = DEFAULT_SYSTEM_MESSAGE,
    stream: bool = True,
) -> None:
    """Run the LLM chat loop with tool-calling until a final response."""
    messages: list[dict] = []
    if system_message is not None:
        messages.append({"role": "system", "content": system_message + COMPLETION_SENTINEL_DIRECTIVE})
    else:
        messages.append({"role": "system", "content": DEFAULT_SYSTEM_MESSAGE + COMPLETION_SENTINEL_DIRECTIVE})
    messages.append({"role": "user", "content": prompt})
    max_iterations = MAX_ITERATION
    is_done: bool = False

    for iteration in range(max_iterations):
        kwargs: dict = {
            "model": model,
            "messages": messages,
        }
        if openai_tools:
            kwargs["tools"] = openai_tools

        print(f"  LLM iteration {iteration + 1}/{max_iterations}")

        if stream:
            # Streaming keeps bytes flowing so the llama-swap 600s idle
            # timeout never fires. Text fragments are printed live.
            response = await stream_chat_completion(llm_client, live_print=True, **kwargs)
            text_printed_live = True
        else:
            response = await llm_client.chat.completions.create(**kwargs)
            text_printed_live = False
        choice = response.choices[0]

        if choice.message.tool_calls:
            # Append the assistant's message WITH tool_calls to history.
            # This is required by the OpenAI protocol so the LLM can correlate
            # subsequent tool results with the calls it made.
            messages.append({
                "role": "assistant",
                "content": choice.message.content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        },
                    }
                    for tc in choice.message.tool_calls
                ],
            })

            # Print assistant text alongside tool calls (some models include both).
            # When streaming was used, the text was already printed live.
            assistant_text = _delta_content_to_text(choice.message.content)
            if assistant_text and not text_printed_live:
                for line in assistant_text.splitlines(keepends=True):
                    if line:
                        print(f"{line}", end="")

            for tc in choice.message.tool_calls:
                tool_name = tc.function.name

                # Parse arguments — catch malformed JSON and return a clear error
                # so the LLM can self-correct on the next iteration.
                try:
                    tool_args = (
                        json.loads(tc.function.arguments)
                        if tc.function.arguments
                        else {}
                    )
                except json.JSONDecodeError as e:
                    print(f"  Tool call: {tool_name} — INVALID JSON in arguments")
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": (
                            f"Error: the arguments for '{tool_name}' are not valid JSON. "
                            f"Fix the syntax and retry. Details: {e}"
                        ),
                    })
                    continue

                # Log readable raw text, never a Python object repr.
                try:
                    args_preview = json.dumps(tool_args, ensure_ascii=False)
                except (TypeError, ValueError):
                    args_preview = str(tool_args)
                if len(args_preview) > 200:
                    args_preview = args_preview[:200] + "\n... [truncated]"
                print(f"  Tool call: {tool_name} with args {args_preview}")

                result_text = await execute_tool_call(
                    tool_name, tool_args, clients, tool_to_server,
                    max_tool_result_length=max_tool_result_length,
                )

                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result_text,
                })

                # you did this ?!
                if _is_completion_sentinel(args_preview):
                    is_done = True
                    break

            if not is_done:
                continue

        # No more tool calls — check if the LLM signaled completion.
        assistant_text = _delta_content_to_text(choice.message.content)

        if _is_completion_sentinel(assistant_text):
            is_done = True

        if is_done:
            print(f"  Task {task_num}/{total}: done")
            messages.append({"role": "assistant", "content": assistant_text})
            break

        # The LLM responded with text but did NOT send the completion sentinel.
        # It may have finished early or is still thinking. Loop back and remind it.
        print(f"  Warning: LLM responded without tool calls and without completion signal — looping back.")
        messages.append({"role": "assistant", "content": assistant_text})
        messages.append({
            "role": "user",
            "content": (
                "You did not signal task completion. If your work is truly finished, "
                f"respond with a JSON message ONLY with this exact following content: {COMPLETION_SENTINEL}\n"
                "If there is still work to do, call the appropriate tools now."
            ),
        })
        continue
    else:
        print(f"  Warning: reached max LLM iterations ({max_iterations})")
        print(f"Task {task_num}/{total}: done (max iterations)")


async def run_task(
    task: TaskConfig,
    llm_config: LlmConfig,
    mcp_servers: dict[str, McpToolConfig],
    task_num: int,
    total: int,
) -> None:
    """Execute a single task: connect MCP servers, run LLM loop with tool calling."""
    task_name = task.name
    prompt = task.prompt
    requested_tools = task.tools

    print(f"Task {task_num}/{total}: starting task {task_name}")

    async with AsyncExitStack() as stack:
        clients, all_mcp_tools, tool_to_server = await connect_mcp_servers(
            stack, requested_tools, mcp_servers
        )

        if not all_mcp_tools:
            print("  No MCP tools available for this task.")

        openai_tools = tools_to_openai_format(all_mcp_tools)

        llm_client = AsyncOpenAI(
            base_url=llm_config.openAiCompatibleServerUrl,
            api_key=llm_config.api_key,
        )

        max_tool_result_length = llm_config.maxToolResultLength
        system_message = llm_config.systemMessage
        stream = llm_config.stream

        await run_llm_loop(
            llm_client,
            llm_config.model,
            prompt,
            openai_tools,
            clients,
            tool_to_server,
            task_num,
            total,
            max_tool_result_length=max_tool_result_length,
            system_message=system_message,
            stream=stream,
        )

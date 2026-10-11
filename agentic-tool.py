#!/usr/bin/env python3
"""agentic-tool — Run sequential LLM tasks with MCP tool support."""

import argparse
import asyncio
import sys
from pathlib import Path

from pydantic import ValidationError

from config import AppConfig
from runner import run_task


def load_config(path: str) -> AppConfig:
    """Load and validate the JSON config file."""
    p = Path(path)
    if not p.exists():
        print(f"Error: config file not found: {path}", file=sys.stderr)
        sys.exit(1)
    try:
        return AppConfig.model_validate_json(p.read_text())
    except ValidationError as e:
        print(f"Error: invalid config file {path}:\n{e}", file=sys.stderr)
        sys.exit(1)


async def main() -> None:
    parser = argparse.ArgumentParser(description="Run LLM tasks with MCP tool support")
    parser.add_argument("--file", required=True, help="Path to JSON task description file")
    args = parser.parse_args()

    config = load_config(args.file)

    llm_config = config.llm
    mcp_servers = {s.name: s for s in llm_config.mcpTools}
    tasks = config.tasks

    if not tasks:
        print("No tasks found in config.", file=sys.stderr)
        sys.exit(1)

    total = len(tasks)
    for i, task in enumerate(tasks, 1):
        await run_task(task, llm_config, mcp_servers, i, total)

    print(f"\nAll {total} tasks are done, quitting the app.")


if __name__ == "__main__":
    asyncio.run(main())

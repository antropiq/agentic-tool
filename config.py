"""Pydantic models matching the JSON configuration file schema."""

import os
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

_ENV_PATTERN = re.compile(r"\$(\$|\{([A-Za-z_]\w*)(?::-([^}]*))?\})")


def _expand_match(match: re.Match) -> str:
    if match.group(1) == "$":
        return "$"
    name, default = match.group(2), match.group(3)
    value = os.environ.get(name)
    if value is not None:
        return value
    return default if default is not None else match.group(0)


def expand_env(value):
    """Recursively expand ${VAR} / ${VAR:-default} in every string of a JSON value.

    Undefined variables without a default are left untouched. ``$$`` is an
    escape for a literal ``$`` (so ``$${VAR}`` stays literal).
    """
    if isinstance(value, str):
        return _ENV_PATTERN.sub(_expand_match, value)
    if isinstance(value, dict):
        return {k: expand_env(v) for k, v in value.items()}
    if isinstance(value, list):
        return [expand_env(v) for v in value]
    return value


class McpToolConfig(BaseModel):
    """An MCP server available to tasks."""

    model_config = ConfigDict(extra="ignore")

    name: str
    endpoint: str


class SamplingConfig(BaseModel):
    """Optional sampling parameters forwarded to the LLM call when set."""

    model_config = ConfigDict(extra="ignore")

    temperature: float | None = None
    top_p: float | None = None
    top_k: int | None = None
    min_p: float | None = None
    repeat_penalty: float | None = None
    presence_penalty: float | None = None
    reasoning_effort: Literal["none", "low", "medium", "high", "xhigh"] | None = None

    def to_kwargs(self) -> dict:
        """Non-None sampling parameters as chat.completions kwargs.

        OpenAI-compatible params are passed directly; the non-standard ones
        (top_k, min_p, repeat_penalty) go through extra_body, which llama.cpp-
        style servers accept in the request JSON.
        """
        params = self.model_dump(exclude_none=True)
        extra_body = {k: params.pop(k) for k in ("top_k", "min_p", "repeat_penalty") if k in params}
        if extra_body:
            params["extra_body"] = extra_body
        return params


class LlmConfig(BaseModel):
    """LLM inference engine connection settings."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    openAiCompatibleServerUrl: str
    model: str
    api_key: str = Field(default="not-needed", alias="api-key")
    systemMessage: str | None = None
    mcpTools: list[McpToolConfig] = Field(default_factory=list)
    maxToolResultLength: int = 120_000
    stream: bool = True
    sampling: SamplingConfig | None = None


class TaskConfig(BaseModel):
    """A single task executed sequentially."""

    model_config = ConfigDict(extra="ignore")

    name: str
    prompt: str
    tools: list[str] = Field(default_factory=list)


class AppConfig(BaseModel):
    """Top-level configuration file."""

    model_config = ConfigDict(extra="ignore")

    name: str | None = None
    version: str | None = None
    llm: LlmConfig
    tasks: list[TaskConfig] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def expand_environment_variables(cls, data):
        return expand_env(data)

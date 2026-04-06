from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


McpStatus = Literal["stopped", "running", "disabled", "error"]


@dataclass(slots=True)
class McpServerConfig:
    name: str
    type: str = "stdio"
    command: str | None = None
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    url: str | None = None
    enabled: bool = True
    timeout_seconds: float = 30.0
    source: str = ""


@dataclass(slots=True)
class McpServerState:
    name: str
    type: str
    status: McpStatus
    source: str = ""
    command: list[str] = field(default_factory=list)
    error: str | None = None
    tools: int = 0
    resources: int = 0
    prompts: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "type": self.type,
            "status": self.status,
            "source": self.source,
            "command": self.command,
            "error": self.error,
            "tools": self.tools,
            "resources": self.resources,
            "prompts": self.prompts,
        }


@dataclass(slots=True)
class McpToolInfo:
    server: str
    name: str
    description: str
    input_schema: dict[str, Any]

    @property
    def tool_id(self) -> str:
        return f"mcp__{_safe_name(self.server)}__{_safe_name(self.name)}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.tool_id,
            "server": self.server,
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
        }


def _safe_name(value: str) -> str:
    safe = "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in value.strip())
    safe = "_".join(part for part in safe.split("_") if part)
    return safe or "unnamed"

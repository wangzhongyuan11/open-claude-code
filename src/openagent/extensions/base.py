from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from openagent.domain.tools import ToolContext
from openagent.permission.models import PermissionRequest


@dataclass(slots=True)
class PermissionDecision:
    allowed: bool
    action: str = "allow"
    reason: str = ""
    request: PermissionRequest | None = None


@dataclass(slots=True)
class ExtensionContext:
    tool_name: str
    arguments: dict[str, Any]
    tool_context: ToolContext
    metadata: dict[str, Any] = field(default_factory=dict)


class PermissionPolicy(Protocol):
    def check(self, context: ExtensionContext) -> PermissionDecision: ...


class MCPAdapter(Protocol):
    def list_tools(self) -> list[dict[str, Any]]: ...


class LSPAdapter(Protocol):
    def get_diagnostics(self, path: str) -> list[dict[str, Any]]: ...


class GitHubAdapter(Protocol):
    def create_issue(self, title: str, body: str) -> str: ...

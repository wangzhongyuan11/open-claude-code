from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


McpStatus = Literal[
    "stopped",
    "connected",
    "disabled",
    "failed",
    "needs_auth",
    "needs_client_registration",
]
McpTransport = Literal["stdio", "streamable_http", "sse"]


@dataclass(slots=True)
class McpOAuthConfig:
    enabled: bool = False
    client_id: str | None = None
    client_secret: str | None = None
    scope: list[str] = field(default_factory=list)

    @classmethod
    def from_value(cls, value: bool | dict[str, Any] | None) -> "McpOAuthConfig":
        if value is False or value is None:
            return cls(enabled=False)
        if value is True:
            return cls(enabled=True)
        if not isinstance(value, dict):
            return cls(enabled=True)
        scope = value.get("scope") or value.get("scopes") or []
        if isinstance(scope, str):
            scope = [item for item in scope.replace(",", " ").split() if item]
        return cls(
            enabled=True,
            client_id=str(value.get("clientId")) if value.get("clientId") else None,
            client_secret=str(value.get("clientSecret")) if value.get("clientSecret") else None,
            scope=[str(item) for item in scope],
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "clientId": self.client_id,
            "scope": list(self.scope),
        }


@dataclass(slots=True)
class McpServerConfig:
    name: str
    type: str = "stdio"
    command: str | None = None
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    url: str | None = None
    sse_url: str | None = None
    headers: dict[str, str] = field(default_factory=dict)
    oauth: McpOAuthConfig = field(default_factory=McpOAuthConfig)
    enabled: bool = True
    timeout_seconds: float = 30.0
    source: str = ""


@dataclass(slots=True)
class McpAuthRecord:
    server_name: str
    server_url: str
    access_token: str
    header_name: str = "Authorization"
    prefix: str = "Bearer "
    token_type: str | None = None
    refresh_token: str | None = None
    expires_at: str | None = None
    client_id: str | None = None
    client_secret: str | None = None
    state: str | None = None
    code_verifier: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "server_name": self.server_name,
            "server_url": self.server_url,
            "access_token": self.access_token,
            "header_name": self.header_name,
            "prefix": self.prefix,
            "token_type": self.token_type,
            "refresh_token": self.refresh_token,
            "expires_at": self.expires_at,
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "state": self.state,
            "code_verifier": self.code_verifier,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "McpAuthRecord":
        return cls(
            server_name=str(payload.get("server_name") or ""),
            server_url=str(payload.get("server_url") or ""),
            access_token=str(payload.get("access_token") or ""),
            header_name=str(payload.get("header_name") or "Authorization"),
            prefix=str(payload["prefix"]) if "prefix" in payload else "Bearer ",
            token_type=str(payload.get("token_type")) if payload.get("token_type") else None,
            refresh_token=str(payload.get("refresh_token")) if payload.get("refresh_token") else None,
            expires_at=str(payload.get("expires_at")) if payload.get("expires_at") else None,
            client_id=str(payload.get("client_id")) if payload.get("client_id") else None,
            client_secret=str(payload.get("client_secret")) if payload.get("client_secret") else None,
            state=str(payload.get("state")) if payload.get("state") else None,
            code_verifier=str(payload.get("code_verifier")) if payload.get("code_verifier") else None,
        )


@dataclass(slots=True)
class McpServerState:
    name: str
    type: str
    status: McpStatus
    source: str = ""
    command: list[str] = field(default_factory=list)
    url: str | None = None
    transport: McpTransport | None = None
    auth_status: str | None = None
    fallback_used: bool = False
    error: str | None = None
    tools: int = 0
    resources: int = 0
    prompts: int = 0
    attempts: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "type": self.type,
            "status": self.status,
            "source": self.source,
            "command": self.command,
            "url": self.url,
            "transport": self.transport,
            "auth_status": self.auth_status,
            "fallback_used": self.fallback_used,
            "error": self.error,
            "tools": self.tools,
            "resources": self.resources,
            "prompts": self.prompts,
            "attempts": list(self.attempts),
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

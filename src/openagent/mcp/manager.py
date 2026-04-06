from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from openagent.domain.events import Event
from openagent.events.bus import EventBus
from openagent.mcp.client import McpClientError, StdioMcpClient
from openagent.mcp.models import McpServerConfig, McpServerState, McpToolInfo


class McpManager:
    def __init__(
        self,
        workspace: Path,
        *,
        config_paths: list[str] | None = None,
        event_bus: EventBus | None = None,
    ) -> None:
        self.workspace = workspace.resolve()
        self.event_bus = event_bus
        self.config_paths = [Path(item) for item in (config_paths or []) if item]
        self.configs = self._load_configs()
        self.clients: dict[str, StdioMcpClient] = {}
        self.status: dict[str, McpServerState] = {}
        self.tool_defs: dict[str, McpToolInfo] = {}
        self.resources: dict[str, list[dict[str, Any]]] = {}
        self.prompts: dict[str, list[dict[str, Any]]] = {}
        for name, config in self.configs.items():
            if config.enabled:
                self.status[name] = McpServerState(
                    name=name,
                    type=config.type,
                    status="stopped",
                    source=config.source,
                    command=[config.command or "", *config.args],
                )
            else:
                self.status[name] = McpServerState(
                    name=name,
                    type=config.type,
                    status="disabled",
                    source=config.source,
                    command=[config.command or "", *config.args],
                )

    def close(self) -> None:
        for client in list(self.clients.values()):
            client.close()
        self.clients.clear()

    def connect_all(self) -> None:
        for name in sorted(self.configs):
            if self.configs[name].enabled:
                self.connect(name)

    def connect(self, name: str) -> McpServerState:
        config = self.configs.get(name)
        if config is None:
            raise KeyError(f"unknown MCP server: {name}")
        if not config.enabled:
            state = McpServerState(name=name, type=config.type, status="disabled", source=config.source)
            self.status[name] = state
            return state
        if config.type != "stdio":
            state = McpServerState(
                name=name,
                type=config.type,
                status="error",
                source=config.source,
                error=f"unsupported MCP transport: {config.type}",
            )
            self.status[name] = state
            return state
        old = self.clients.pop(name, None)
        if old:
            old.close()
        for tool_id, info in list(self.tool_defs.items()):
            if info.server == name:
                self.tool_defs.pop(tool_id, None)
        self.resources.pop(name, None)
        self.prompts.pop(name, None)
        client = StdioMcpClient(config, self.workspace)
        try:
            client.connect()
            tools = [
                McpToolInfo(
                    server=name,
                    name=str(item.get("name", "")),
                    description=str(item.get("description") or f"MCP tool {name}:{item.get('name', '')}"),
                    input_schema=_normalize_schema(item.get("inputSchema")),
                )
                for item in client.list_tools()
                if item.get("name")
            ]
            resources = _safe_list(lambda: client.list_resources())
            prompts = _safe_list(lambda: client.list_prompts())
            for info in tools:
                self.tool_defs[info.tool_id] = info
            self.resources[name] = resources
            self.prompts[name] = prompts
            self.clients[name] = client
            state = McpServerState(
                name=name,
                type=config.type,
                status="running",
                source=config.source,
                command=client.command_line,
                tools=len(tools),
                resources=len(resources),
                prompts=len(prompts),
            )
            self.status[name] = state
            self._emit("mcp.connected", state.to_dict())
            return state
        except Exception as exc:
            client.close()
            state = McpServerState(
                name=name,
                type=config.type,
                status="error",
                source=config.source,
                command=[config.command or "", *config.args],
                error=str(exc),
            )
            self.status[name] = state
            self._emit("mcp.failed", state.to_dict())
            return state

    def list_states(self) -> list[McpServerState]:
        return [self.status[name] for name in sorted(self.status)]

    def list_tools(self) -> list[McpToolInfo]:
        return [self.tool_defs[key] for key in sorted(self.tool_defs)]

    def list_resources(self) -> dict[str, list[dict[str, Any]]]:
        return {key: self.resources.get(key, []) for key in sorted(self.configs)}

    def list_prompts(self) -> dict[str, list[dict[str, Any]]]:
        return {key: self.prompts.get(key, []) for key in sorted(self.configs)}

    def call_tool(self, tool_id: str, arguments: dict[str, Any]) -> dict[str, Any]:
        info = self.tool_defs.get(tool_id)
        if info is None:
            raise KeyError(f"unknown MCP tool: {tool_id}")
        client = self.clients.get(info.server)
        if client is None or not client.running:
            self.connect(info.server)
            client = self.clients.get(info.server)
        if client is None:
            state = self.status.get(info.server)
            raise McpClientError(state.error if state and state.error else f"MCP server not running: {info.server}")
        return client.call_tool(info.name, arguments)

    def read_resource(self, server: str, uri: str) -> dict[str, Any]:
        client = self._client_for(server)
        return client.read_resource(uri)

    def get_prompt(self, server: str, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        client = self._client_for(server)
        return client.get_prompt(name, arguments)

    def _client_for(self, server: str) -> StdioMcpClient:
        if server not in self.configs:
            raise KeyError(f"unknown MCP server: {server}")
        client = self.clients.get(server)
        if client is None or not client.running:
            self.connect(server)
            client = self.clients.get(server)
        if client is None:
            state = self.status.get(server)
            raise McpClientError(state.error if state and state.error else f"MCP server not running: {server}")
        return client

    def _load_configs(self) -> dict[str, McpServerConfig]:
        configs: dict[str, McpServerConfig] = {}
        for path in self._candidate_paths():
            if not path.exists():
                continue
            data = json.loads(path.read_text(encoding="utf-8"))
            section = data.get("mcpServers") or data.get("mcp") or {}
            for name, item in section.items():
                config = _parse_config(name, item, path, self.workspace)
                configs[config.name] = config
        return configs

    def _candidate_paths(self) -> list[Path]:
        paths = [
            self.workspace / "openagent.mcp.json",
            self.workspace / ".opencode" / "mcp.json",
            *self.config_paths,
        ]
        env_path = os.getenv("OPENAGENT_MCP_CONFIG")
        if env_path:
            paths.extend(Path(item) for item in env_path.split(os.pathsep) if item)
        seen: list[Path] = []
        for path in paths:
            resolved = path.expanduser().resolve()
            if resolved not in seen:
                seen.append(resolved)
        return seen

    def _emit(self, event_type: str, payload: dict[str, Any]) -> None:
        if self.event_bus is not None:
            self.event_bus.emit(Event(type=event_type, payload=payload))


def _parse_config(name: str, item: Any, path: Path, workspace: Path) -> McpServerConfig:
    if not isinstance(item, dict):
        raise ValueError(f"invalid MCP server config for {name}: expected object")
    safe_name = _safe_server_name(name)
    enabled = bool(item.get("enabled", True))
    server_type = str(item.get("type") or ("stdio" if item.get("command") else "remote"))
    timeout = float(item.get("timeout") or item.get("timeout_seconds") or 30)
    env = {str(key): str(value) for key, value in dict(item.get("env") or item.get("environment") or {}).items()}
    command = item.get("command")
    args = item.get("args")
    if isinstance(command, list):
        argv = [str(_expand(value, workspace)) for value in command]
        command_name = argv[0] if argv else None
        command_args = argv[1:]
    else:
        command_name = str(_expand(command, workspace)) if command else None
        command_args = [str(_expand(value, workspace)) for value in (args or [])]
    return McpServerConfig(
        name=safe_name,
        type=server_type,
        command=command_name,
        args=command_args,
        env=env,
        url=str(item.get("url")) if item.get("url") else None,
        enabled=enabled,
        timeout_seconds=timeout,
        source=str(path),
    )


def _safe_server_name(value: str) -> str:
    safe = "".join(ch if ch.isalnum() or ch in {"_", "-"} else "_" for ch in value.strip())
    return safe or "server"


def _expand(value: Any, workspace: Path) -> Any:
    if not isinstance(value, str):
        return value
    return value.replace("{workspace}", str(workspace))


def _normalize_schema(schema: Any) -> dict[str, Any]:
    if not isinstance(schema, dict):
        return {"type": "object", "properties": {}}
    normalized = dict(schema)
    normalized["type"] = "object"
    normalized.setdefault("properties", {})
    return normalized


def _safe_list(fn) -> list[dict[str, Any]]:
    try:
        return [item for item in fn() if isinstance(item, dict)]
    except Exception:
        return []

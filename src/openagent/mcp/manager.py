from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from openagent.domain.events import Event
from openagent.events.bus import EventBus
from openagent.mcp.client import (
    BaseMcpClient,
    McpAuthRequiredError,
    McpClientError,
    McpNeedsClientRegistrationError,
    RemoteMcpClient,
    StdioMcpClient,
)
from openagent.mcp.models import (
    McpAuthRecord,
    McpOAuthConfig,
    McpServerConfig,
    McpServerState,
    McpToolInfo,
)


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
        self.state_root = self.workspace / ".openagent"
        self.state_root.mkdir(parents=True, exist_ok=True)
        self.auth_path = self.state_root / "mcp_auth.json"
        self.auth_records = self._load_auth_records()
        self.configs = self._load_configs()
        self.clients: dict[str, BaseMcpClient] = {}
        self.status: dict[str, McpServerState] = {}
        self.tool_defs: dict[str, McpToolInfo] = {}
        self.resources: dict[str, list[dict[str, Any]]] = {}
        self.prompts: dict[str, list[dict[str, Any]]] = {}
        self.tool_schemas: dict[str, dict[str, Any]] = {}
        for name, config in self.configs.items():
            self.status[name] = self._initial_state(config)

    def close(self) -> None:
        for client in list(self.clients.values()):
            client.close()
        self.clients.clear()

    def connect_all(self) -> None:
        for name in sorted(self.configs):
            if self.configs[name].enabled and not self._is_connected(name):
                self.connect(name)

    def connect(self, name: str) -> McpServerState:
        config = self._require_config(name)
        if self._is_connected(name):
            return self.status[name]
        if not config.enabled:
            state = self._initial_state(config)
            self.status[name] = state
            return state
        self.disconnect(name)
        client = self._build_client(config)
        try:
            client.connect()
            tools_payload = client.list_tools()
            tools = [
                McpToolInfo(
                    server=name,
                    name=str(item.get("name", "")),
                    description=str(item.get("description") or f"MCP tool {name}:{item.get('name', '')}"),
                    input_schema=_normalize_schema(item.get("inputSchema")),
                )
                for item in tools_payload
                if item.get("name")
            ]
            resources = _safe_list(lambda: client.list_resources())
            prompts = _safe_list(lambda: client.list_prompts())
            self._replace_server_capabilities(name, tools, resources, prompts)
            self.clients[name] = client
            fallback_used = len(client.transport_attempts) > 1 and any(
                item.get("status") == "failed" for item in client.transport_attempts[:-1]
            )
            state = McpServerState(
                name=name,
                type=config.type,
                status="connected",
                source=config.source,
                command=client.descriptor,
                url=config.url,
                transport=client.transport_name,
                auth_status="configured" if self._auth_for(config) is not None else ("required" if config.oauth.enabled else None),
                fallback_used=fallback_used,
                error=None,
                tools=len(tools),
                resources=len(resources),
                prompts=len(prompts),
                attempts=list(client.transport_attempts),
            )
            self.status[name] = state
            self._emit("mcp.connected", state.to_dict())
            return state
        except McpAuthRequiredError as exc:
            state = McpServerState(
                name=name,
                type=config.type,
                status="needs_auth",
                source=config.source,
                command=client.descriptor,
                url=config.url,
                transport=client.transport_name,
                auth_status="required",
                fallback_used=False,
                error=str(exc),
                attempts=list(client.transport_attempts),
            )
            self.status[name] = state
            self._emit("mcp.auth_required", state.to_dict())
            return state
        except McpNeedsClientRegistrationError as exc:
            state = McpServerState(
                name=name,
                type=config.type,
                status="needs_client_registration",
                source=config.source,
                command=client.descriptor,
                url=config.url,
                transport=client.transport_name,
                auth_status="registration_required",
                fallback_used=False,
                error=str(exc),
                attempts=list(client.transport_attempts),
            )
            self.status[name] = state
            self._emit("mcp.client_registration_required", state.to_dict())
            return state
        except Exception as exc:
            state = McpServerState(
                name=name,
                type=config.type,
                status="failed",
                source=config.source,
                command=client.descriptor,
                url=config.url,
                transport=client.transport_name,
                auth_status="configured" if self._auth_for(config) is not None else None,
                fallback_used=False,
                error=str(exc),
                attempts=list(client.transport_attempts),
            )
            self.status[name] = state
            self._emit("mcp.failed", state.to_dict())
            return state
        finally:
            if name not in self.clients:
                client.close()

    def disconnect(self, name: str) -> McpServerState:
        config = self._require_config(name)
        client = self.clients.pop(name, None)
        if client is not None:
            client.close()
        self._replace_server_capabilities(name, [], [], [])
        state = self._initial_state(config)
        self.status[name] = state
        self._emit("mcp.disconnected", state.to_dict())
        return state

    def reconnect(self, name: str) -> McpServerState:
        return self.connect(name)

    def ping(self, name: str) -> dict[str, Any]:
        state = self.connect(name)
        return {
            "server": name,
            "status": state.status,
            "transport": state.transport,
            "error": state.error,
            "fallback_used": state.fallback_used,
        }

    def inspect(self, name: str) -> dict[str, Any]:
        config = self._require_config(name)
        state = self.status.get(name) or self._initial_state(config)
        tools = [tool.to_dict() for tool in self.list_tools() if tool.server == name]
        resources = self.resources.get(name, [])
        prompts = self.prompts.get(name, [])
        auth = self._auth_for(config)
        return {
            "server": state.to_dict(),
            "config": {
                "name": config.name,
                "type": config.type,
                "source": config.source,
                "enabled": config.enabled,
                "url": config.url,
                "sse_url": config.sse_url,
                "timeout": config.timeout_seconds,
                "headers": sorted(config.headers.keys()),
                "oauth": config.oauth.to_dict(),
            },
            "auth": {
                "present": auth is not None,
                "header_name": auth.header_name if auth else None,
                "prefix": auth.prefix if auth else None,
                "server_url": auth.server_url if auth else None,
            },
            "tools": tools,
            "resources": resources,
            "prompts": prompts,
        }

    def trace(self) -> dict[str, Any]:
        return {
            "servers": [
                {
                    "name": state.name,
                    "status": state.status,
                    "transport": state.transport,
                    "fallback_used": state.fallback_used,
                    "attempts": state.attempts,
                    "error": state.error,
                }
                for state in self.list_states()
            ]
        }

    def set_auth(self, name: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        config = self._require_config(name)
        if not config.url:
            raise McpClientError(f"MCP server {name} is not a remote server")
        if payload is None:
            auth = self._auth_for(config)
            return {
                "server": name,
                "url": config.url,
                "oauth": config.oauth.to_dict(),
                "auth_present": auth is not None,
                "auth": auth.to_dict() if auth else None,
            }
        access_token = str(payload.get("access_token") or payload.get("token") or "").strip()
        if not access_token:
            raise McpClientError("auth payload requires access_token or token")
        record = McpAuthRecord(
            server_name=name,
            server_url=config.url,
            access_token=access_token,
            header_name=str(payload["header_name"] if "header_name" in payload else payload.get("header") or "Authorization"),
            prefix=str(payload["prefix"]) if "prefix" in payload else "Bearer ",
            token_type=str(payload.get("token_type")) if payload.get("token_type") else None,
            refresh_token=str(payload.get("refresh_token")) if payload.get("refresh_token") else None,
            expires_at=str(payload.get("expires_at")) if payload.get("expires_at") else None,
            client_id=str(payload.get("client_id") or payload.get("clientId")) if payload.get("client_id") or payload.get("clientId") else config.oauth.client_id,
            client_secret=str(payload.get("client_secret") or payload.get("clientSecret")) if payload.get("client_secret") or payload.get("clientSecret") else config.oauth.client_secret,
            state=str(payload.get("state")) if payload.get("state") else None,
            code_verifier=str(payload.get("code_verifier") or payload.get("codeVerifier")) if payload.get("code_verifier") or payload.get("codeVerifier") else None,
        )
        self.auth_records[self._auth_key(name, config.url)] = record
        self._save_auth_records()
        state = self.reconnect(name)
        return {
            "server": name,
            "status": state.status,
            "transport": state.transport,
            "auth_status": state.auth_status,
            "error": state.error,
        }

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
        client = self._client_for(info.server)
        return client.call_tool(info.name, arguments)

    def read_resource(self, server: str, uri: str) -> dict[str, Any]:
        client = self._client_for(server)
        return client.read_resource(uri)

    def get_prompt(self, server: str, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        client = self._client_for(server)
        return client.get_prompt(name, arguments)

    def _client_for(self, server: str) -> BaseMcpClient:
        if server not in self.configs:
            raise KeyError(f"unknown MCP server: {server}")
        client = self.clients.get(server)
        if client is None or not client.running:
            state = self.connect(server)
            if state.status != "connected":
                raise McpClientError(state.error or f"MCP server not connected: {server}")
            client = self.clients.get(server)
        if client is None:
            state = self.status.get(server)
            raise McpClientError(state.error if state and state.error else f"MCP server not connected: {server}")
        return client

    def _build_client(self, config: McpServerConfig) -> BaseMcpClient:
        if config.type == "stdio":
            return StdioMcpClient(config, self.workspace)
        if config.type == "remote":
            return RemoteMcpClient(
                config,
                self.workspace,
                auth_headers=self._auth_headers(config),
            )
        raise McpClientError(f"unsupported MCP transport: {config.type}")

    def _replace_server_capabilities(
        self,
        server: str,
        tools: list[McpToolInfo],
        resources: list[dict[str, Any]],
        prompts: list[dict[str, Any]],
    ) -> None:
        for tool_id, info in list(self.tool_defs.items()):
            if info.server == server:
                self.tool_defs.pop(tool_id, None)
                self.tool_schemas.pop(tool_id, None)
        for info in tools:
            self.tool_defs[info.tool_id] = info
            self.tool_schemas[info.tool_id] = info.input_schema
        self.resources[server] = resources
        self.prompts[server] = prompts

    def _initial_state(self, config: McpServerConfig) -> McpServerState:
        status = "disabled" if not config.enabled else "stopped"
        auth = self._auth_for(config)
        return McpServerState(
            name=config.name,
            type=config.type,
            status=status,
            source=config.source,
            command=[config.command or "", *config.args] if config.type == "stdio" else [],
            url=config.url,
            transport=None,
            auth_status="configured" if auth is not None else ("required" if config.oauth.enabled else None),
            fallback_used=False,
            error=None,
            attempts=[],
        )

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

    def _load_auth_records(self) -> dict[str, McpAuthRecord]:
        if not self.auth_path.exists():
            return {}
        try:
            payload = json.loads(self.auth_path.read_text(encoding="utf-8"))
        except Exception:
            return {}
        if not isinstance(payload, dict):
            return {}
        records: dict[str, McpAuthRecord] = {}
        for key, value in payload.items():
            if not isinstance(value, dict):
                continue
            try:
                records[str(key)] = McpAuthRecord.from_dict(value)
            except Exception:
                continue
        return records

    def _save_auth_records(self) -> None:
        payload = {key: value.to_dict() for key, value in self.auth_records.items()}
        self.auth_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def _auth_for(self, config: McpServerConfig) -> McpAuthRecord | None:
        if not config.url:
            return None
        record = self.auth_records.get(self._auth_key(config.name, config.url))
        if record is None or record.server_url != config.url:
            return None
        return record

    def _auth_headers(self, config: McpServerConfig) -> dict[str, str]:
        record = self._auth_for(config)
        if record is None:
            return {}
        return {record.header_name: f"{record.prefix}{record.access_token}"}

    @staticmethod
    def _auth_key(server_name: str, server_url: str) -> str:
        return f"{server_name}|{server_url}"

    def _require_config(self, name: str) -> McpServerConfig:
        try:
            return self.configs[name]
        except KeyError as exc:
            raise KeyError(f"unknown MCP server: {name}") from exc

    def _is_connected(self, name: str) -> bool:
        client = self.clients.get(name)
        state = self.status.get(name)
        return client is not None and client.running and state is not None and state.status == "connected"

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
    env = {str(key): str(_expand(value, workspace)) for key, value in dict(item.get("env") or item.get("environment") or {}).items()}
    headers = {
        str(key): str(_expand(value, workspace))
        for key, value in dict(item.get("headers") or {}).items()
    }
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
        url=str(_expand(item.get("url"), workspace)) if item.get("url") else None,
        sse_url=str(_expand(item.get("sse_url") or item.get("sseUrl"), workspace)) if item.get("sse_url") or item.get("sseUrl") else None,
        headers=headers,
        oauth=McpOAuthConfig.from_value(item.get("oauth")),
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
    return os.path.expandvars(value.replace("{workspace}", str(workspace)))


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

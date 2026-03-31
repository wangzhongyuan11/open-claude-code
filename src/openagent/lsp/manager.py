from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
import threading
from typing import Any

from openagent.events.bus import EventBus
from openagent.lsp.client import LspClient, uri_to_path
from openagent.lsp.server import DEFAULT_SERVERS, LspServerInfo


@dataclass(slots=True)
class WorkspaceSymbol:
    name: str
    kind: int
    path: str
    line: int
    character: int


class LspManager:
    def __init__(
        self,
        workspace: Path,
        *,
        event_bus: EventBus | None = None,
        servers: list[LspServerInfo] | None = None,
    ) -> None:
        self.workspace = workspace.resolve()
        self.event_bus = event_bus
        self.servers = list(servers or DEFAULT_SERVERS)
        self._clients: dict[tuple[str, str], LspClient] = {}
        self._lock = threading.RLock()

    def close(self) -> None:
        with self._lock:
            clients = list(self._clients.values())
            self._clients.clear()
        for client in clients:
            client.shutdown()

    def status(self) -> list[dict[str, Any]]:
        with self._lock:
            return [
                {
                    "id": client.server.id,
                    "root": str(client.root),
                    "command": client.server.resolve_command(),
                }
                for client in self._clients.values()
            ]

    def workspace_symbol(self, query: str) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for server in self._available_servers_in_workspace():
            client = self._client_for_server(server)
            if client is None:
                continue
            try:
                payload = client.request("workspace/symbol", {"query": query}) or []
            except Exception:
                continue
            for item in payload:
                location = item.get("location") or {}
                uri = location.get("uri")
                rng = location.get("range", {}).get("start", {})
                if not uri:
                    continue
                try:
                    path = uri_to_path(uri).resolve().relative_to(self.workspace).as_posix()
                except Exception:
                    continue
                results.append(
                    asdict(
                        WorkspaceSymbol(
                            name=item.get("name", ""),
                            kind=int(item.get("kind", 0)),
                            path=path,
                            line=int(rng.get("line", 0)) + 1,
                            character=int(rng.get("character", 0)) + 1,
                        )
                    )
                )
        return results

    def document_symbol(self, file_path: str) -> list[dict[str, Any]]:
        client, uri = self._client_and_uri(file_path)
        payload = client.request("textDocument/documentSymbol", {"textDocument": {"uri": uri}}) or []
        return [_normalize_document_symbol(item) for item in payload]

    def definition(self, file_path: str, line: int, character: int) -> list[dict[str, Any]]:
        client, uri = self._client_and_uri(file_path)
        payload = client.request(
            "textDocument/definition",
            {"textDocument": {"uri": uri}, "position": _position(line, character)},
        )
        return _normalize_locations(payload, self.workspace)

    def references(self, file_path: str, line: int, character: int) -> list[dict[str, Any]]:
        client, uri = self._client_and_uri(file_path)
        payload = client.request(
            "textDocument/references",
            {
                "textDocument": {"uri": uri},
                "position": _position(line, character),
                "context": {"includeDeclaration": True},
            },
        )
        return _normalize_locations(payload, self.workspace)

    def hover(self, file_path: str, line: int, character: int) -> list[dict[str, Any]]:
        client, uri = self._client_and_uri(file_path)
        payload = client.request(
            "textDocument/hover",
            {"textDocument": {"uri": uri}, "position": _position(line, character)},
        ) or {}
        contents = payload.get("contents")
        text = _hover_text(contents)
        return [{"path": file_path, "line": line, "character": character, "contents": text}] if text else []

    def _client_and_uri(self, file_path: str) -> tuple[LspClient, str]:
        path = (self.workspace / file_path).resolve() if not Path(file_path).is_absolute() else Path(file_path).resolve()
        if not path.exists():
            raise FileNotFoundError(f"file not found: {file_path}")
        server = next((item for item in self.servers if item.supports(path)), None)
        if server is None:
            raise FileNotFoundError(f"no LSP server configured for {path.suffix or path.name}")
        client = self._client_for_server(server)
        if client is None:
            raise FileNotFoundError(f"LSP server unavailable: {server.id}")
        uri = client.open_document(path)
        return client, uri

    def _available_servers_in_workspace(self) -> list[LspServerInfo]:
        available: list[LspServerInfo] = []
        for server in self.servers:
            command = server.resolve_command()
            if command is None:
                continue
            if any(next(self.workspace.rglob(f"*{ext}"), None) is not None for ext in server.extensions):
                available.append(server)
        return available

    def _client_for_server(self, server: LspServerInfo) -> LspClient | None:
        command = server.resolve_command()
        if command is None:
            return None
        root = server.root(self.workspace)
        if root is None:
            return None
        key = (server.id, str(root.resolve()))
        with self._lock:
            client = self._clients.get(key)
            if client is not None:
                return client
            client = LspClient(server, root)
            self._clients[key] = client
            return client


def _position(line: int, character: int) -> dict[str, int]:
    return {"line": max(0, line - 1), "character": max(0, character - 1)}


def _normalize_locations(payload: Any, workspace: Path) -> list[dict[str, Any]]:
    if not payload:
        return []
    items = payload if isinstance(payload, list) else [payload]
    results: list[dict[str, Any]] = []
    for item in items:
        uri = item.get("uri")
        rng = item.get("range", {}).get("start", {})
        if not uri:
            continue
        try:
            path = uri_to_path(uri).resolve().relative_to(workspace).as_posix()
        except Exception:
            path = uri
        results.append(
            {
                "path": path,
                "line": int(rng.get("line", 0)) + 1,
                "character": int(rng.get("character", 0)) + 1,
            }
        )
    return results


def _normalize_document_symbol(item: dict[str, Any]) -> dict[str, Any]:
    rng = item.get("selectionRange") or item.get("range") or {}
    start = rng.get("start", {})
    return {
        "name": item.get("name", ""),
        "detail": item.get("detail"),
        "kind": int(item.get("kind", 0)),
        "line": int(start.get("line", 0)) + 1,
        "character": int(start.get("character", 0)) + 1,
    }


def _hover_text(contents: Any) -> str:
    if isinstance(contents, str):
        return contents
    if isinstance(contents, dict):
        value = contents.get("value")
        return value if isinstance(value, str) else ""
    if isinstance(contents, list):
        parts = [_hover_text(item) for item in contents]
        return "\n".join(item for item in parts if item)
    return ""

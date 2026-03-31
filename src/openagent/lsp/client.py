from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import queue
import subprocess
import threading
from typing import Any
from urllib.parse import unquote, urlparse

from openagent.lsp.server import LspServerInfo


def path_to_uri(path: Path) -> str:
    return path.resolve().as_uri()


def uri_to_path(uri: str) -> Path:
    parsed = urlparse(uri)
    if parsed.scheme != "file":
        raise ValueError(f"unsupported uri scheme: {uri}")
    return Path(unquote(parsed.path))


@dataclass(slots=True)
class LspLocation:
    path: str
    line: int
    character: int


class LspClient:
    def __init__(self, server: LspServerInfo, root: Path) -> None:
        self.server = server
        self.root = root.resolve()
        self._next_id = 1
        self._pending: dict[int, queue.Queue[dict[str, Any]]] = {}
        self._pending_lock = threading.Lock()
        self._documents: dict[str, int] = {}
        self._stderr_lines: list[str] = []
        command = server.resolve_command()
        if command is None:
            raise FileNotFoundError(f"LSP server not found: {server.id}")
        self.process = subprocess.Popen(
            command,
            cwd=self.root,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=False,
        )
        if self.process.stdin is None or self.process.stdout is None or self.process.stderr is None:
            raise RuntimeError(f"failed to start LSP server: {server.id}")
        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._stderr_reader = threading.Thread(target=self._read_stderr_loop, daemon=True)
        self._reader.start()
        self._stderr_reader.start()
        self.initialize()

    def shutdown(self) -> None:
        try:
            self.request("shutdown", {})
        except Exception:
            pass
        try:
            self.notify("exit", {})
        except Exception:
            pass
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.process.kill()

    def initialize(self) -> None:
        self.request(
            "initialize",
            {
                "processId": None,
                "rootUri": path_to_uri(self.root),
                "capabilities": {
                    "workspace": {"symbol": {"dynamicRegistration": False}},
                    "textDocument": {
                        "definition": {"dynamicRegistration": False},
                        "references": {"dynamicRegistration": False},
                        "documentSymbol": {"dynamicRegistration": False},
                        "hover": {"dynamicRegistration": False},
                    },
                },
            },
        )
        self.notify("initialized", {})

    def open_document(self, path: Path) -> str:
        uri = path_to_uri(path)
        version = self._documents.get(uri, 0) + 1
        self._documents[uri] = version
        self.notify(
            "textDocument/didOpen",
            {
                "textDocument": {
                    "uri": uri,
                    "languageId": self.server.language_id_for(path),
                    "version": version,
                    "text": path.read_text(encoding="utf-8"),
                }
            },
        )
        return uri

    def request(self, method: str, params: dict[str, Any]) -> Any:
        request_id = self._reserve_id()
        payload = {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}
        waitq: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=1)
        with self._pending_lock:
            self._pending[request_id] = waitq
        self._send(payload)
        message = waitq.get(timeout=10)
        if "error" in message:
            raise RuntimeError(f"LSP request failed for {method}: {message['error']}")
        return message.get("result")

    def notify(self, method: str, params: dict[str, Any]) -> None:
        self._send({"jsonrpc": "2.0", "method": method, "params": params})

    def _reserve_id(self) -> int:
        request_id = self._next_id
        self._next_id += 1
        return request_id

    def _send(self, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        header = f"Content-Length: {len(body)}\r\n\r\n".encode("ascii")
        self.process.stdin.write(header + body)
        self.process.stdin.flush()

    def _read_loop(self) -> None:
        stream = self.process.stdout
        while True:
            headers = {}
            while True:
                line = stream.readline()
                if not line:
                    return
                if line == b"\r\n":
                    break
                text = line.decode("ascii", errors="replace").strip()
                if ":" in text:
                    key, value = text.split(":", 1)
                    headers[key.strip().lower()] = value.strip()
            try:
                length = int(headers.get("content-length", "0"))
            except ValueError:
                return
            body = stream.read(length)
            if not body:
                return
            message = json.loads(body.decode("utf-8", errors="replace"))
            request_id = message.get("id")
            if request_id is None:
                continue
            with self._pending_lock:
                waitq = self._pending.pop(int(request_id), None)
            if waitq is not None:
                waitq.put(message)

    def _read_stderr_loop(self) -> None:
        stream = self.process.stderr
        while True:
            line = stream.readline()
            if not line:
                return
            self._stderr_lines.append(line.decode("utf-8", errors="replace").rstrip())


from __future__ import annotations

import json
import os
import select
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from queue import Empty, Queue
from typing import Any

from openagent.mcp.models import McpServerConfig, McpTransport


class McpClientError(RuntimeError):
    pass


class McpAuthRequiredError(McpClientError):
    pass


class McpNeedsClientRegistrationError(McpClientError):
    pass


class BaseMcpClient:
    def __init__(self, config: McpServerConfig, workspace: Path) -> None:
        self.config = config
        self.workspace = workspace
        self._next_id = 1
        self.transport_name: McpTransport | None = None
        self.transport_attempts: list[dict[str, Any]] = []

    @property
    def running(self) -> bool:
        raise NotImplementedError

    @property
    def descriptor(self) -> list[str]:
        raise NotImplementedError

    def connect(self) -> None:
        raise NotImplementedError

    def close(self) -> None:
        raise NotImplementedError

    def list_tools(self) -> list[dict[str, Any]]:
        result = self._request("tools/list", {})
        return list(result.get("tools") or [])

    def list_resources(self) -> list[dict[str, Any]]:
        result = self._request("resources/list", {})
        return list(result.get("resources") or [])

    def list_prompts(self) -> list[dict[str, Any]]:
        result = self._request("prompts/list", {})
        return list(result.get("prompts") or [])

    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        return self._request("tools/call", {"name": name, "arguments": arguments or {}})

    def read_resource(self, uri: str) -> dict[str, Any]:
        return self._request("resources/read", {"uri": uri})

    def get_prompt(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        return self._request("prompts/get", {"name": name, "arguments": arguments or {}})

    def _request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError

    def _notify(self, method: str, params: dict[str, Any]) -> None:
        raise NotImplementedError

    def _initialize(self) -> None:
        self._request(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {"roots": {"listChanged": True}},
                "clientInfo": {"name": "openagent", "version": "0.1.0"},
            },
        )
        self._notify("notifications/initialized", {})

    def _new_request_id(self) -> int:
        request_id = self._next_id
        self._next_id += 1
        return request_id


class StdioMcpClient(BaseMcpClient):
    def __init__(self, config: McpServerConfig, workspace: Path) -> None:
        super().__init__(config, workspace)
        if not config.command:
            raise McpClientError(f"MCP server {config.name} missing command")
        self._process: subprocess.Popen[str] | None = None
        self._stderr: list[str] = []
        self._stderr_thread: threading.Thread | None = None
        self._stdio_framing = "content-length"

    @property
    def running(self) -> bool:
        return self._process is not None and self._process.poll() is None

    @property
    def descriptor(self) -> list[str]:
        return [self.config.command or "", *self.config.args]

    @property
    def stderr_tail(self) -> str:
        return "\n".join(self._stderr[-20:])

    def connect(self) -> None:
        if self.running:
            return
        errors: list[str] = []
        for framing in ("jsonl", "content-length"):
            self._stdio_framing = framing
            try:
                self._connect_with_framing()
                self.transport_name = "stdio"
                self.transport_attempts = [{"transport": "stdio", "status": "ok", "framing": framing}]
                return
            except Exception as exc:
                errors.append(f"{framing}: {exc}")
                self.close()
        raise McpClientError("; ".join(errors))

    def _connect_with_framing(self) -> None:
        env = os.environ.copy()
        env.update(self.config.env)
        self._process = subprocess.Popen(
            self.descriptor,
            cwd=str(self.workspace),
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=0,
        )
        self._stderr_thread = threading.Thread(target=self._read_stderr, daemon=True)
        self._stderr_thread.start()
        try:
            self._initialize()
        except Exception:
            self.close()
            raise

    def close(self) -> None:
        process = self._process
        self._process = None
        if process is None:
            return
        try:
            if process.stdin:
                process.stdin.close()
        except Exception:
            pass
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()

    def _request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        process = self._ensure_process()
        request_id = self._new_request_id()
        payload = {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}
        assert process.stdin is not None
        self._write_payload(process, payload)
        process.stdin.flush()
        deadline = time.time() + self.config.timeout_seconds
        while time.time() < deadline:
            if process.poll() is not None:
                raise McpClientError(
                    f"MCP server {self.config.name} exited with code {process.returncode}: {self.stderr_tail}"
                )
            message = self._read_payload(process, deadline)
            if message is None:
                continue
            if "id" not in message or message.get("id") != request_id:
                continue
            if message.get("error"):
                error = message["error"]
                raise McpClientError(error.get("message") if isinstance(error, dict) else str(error))
            result = message.get("result")
            return result if isinstance(result, dict) else {}
        raise McpClientError(f"MCP request timed out: {self.config.name}.{method}")

    def _notify(self, method: str, params: dict[str, Any]) -> None:
        process = self._ensure_process()
        assert process.stdin is not None
        payload = {"jsonrpc": "2.0", "method": method, "params": params}
        self._write_payload(process, payload)
        process.stdin.flush()

    def _ensure_process(self) -> subprocess.Popen[str]:
        if self._process is None or self._process.poll() is not None:
            raise McpClientError(f"MCP server {self.config.name} is not running")
        return self._process

    def _read_stderr(self) -> None:
        process = self._process
        if process is None or process.stderr is None:
            return
        for line in process.stderr:
            text = line.decode("utf-8", errors="replace") if isinstance(line, bytes) else line
            self._stderr.append(text.rstrip())

    def _write_payload(self, process: subprocess.Popen, payload: dict[str, Any]) -> None:
        assert process.stdin is not None
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        if self._stdio_framing == "content-length":
            process.stdin.write(f"Content-Length: {len(body)}\r\n\r\n".encode("ascii") + body)
        else:
            process.stdin.write(body + b"\n")

    def _read_payload(self, process: subprocess.Popen, deadline: float) -> dict[str, Any] | None:
        assert process.stdout is not None
        timeout = min(0.25, max(0.0, deadline - time.time()))
        ready, _, _ = select.select([process.stdout], [], [], timeout)
        if not ready:
            return None
        if self._stdio_framing == "content-length":
            return self._read_content_length_payload(process, deadline)
        line = process.stdout.readline()
        if not line:
            return None
        if isinstance(line, bytes):
            line = line.decode("utf-8")
        return json.loads(line)

    def _read_content_length_payload(self, process: subprocess.Popen, deadline: float) -> dict[str, Any] | None:
        assert process.stdout is not None
        headers: dict[str, str] = {}
        while time.time() < deadline:
            line = process.stdout.readline()
            if not line:
                return None
            if isinstance(line, bytes):
                line_text = line.decode("ascii", errors="replace")
            else:
                line_text = line
            line_text = line_text.rstrip("\r\n")
            if not line_text:
                break
            if ":" in line_text:
                key, value = line_text.split(":", 1)
                headers[key.strip().lower()] = value.strip()
        length_text = headers.get("content-length")
        if not length_text:
            raise McpClientError(f"MCP server {self.config.name} sent framed response without Content-Length")
        remaining = int(length_text)
        chunks: list[bytes] = []
        while remaining > 0 and time.time() < deadline:
            chunk = process.stdout.read(remaining)
            if not chunk:
                break
            if isinstance(chunk, str):
                chunk = chunk.encode("utf-8")
            chunks.append(chunk)
            remaining -= len(chunk)
        if remaining > 0:
            return None
        return json.loads(b"".join(chunks).decode("utf-8"))


class RemoteMcpClient(BaseMcpClient):
    def __init__(
        self,
        config: McpServerConfig,
        workspace: Path,
        *,
        auth_headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(config, workspace)
        if not config.url:
            raise McpClientError(f"MCP server {config.name} missing url")
        self.auth_headers = dict(auth_headers or {})
        self._connected = False
        self._sse_messages_url: str | None = None
        self._sse_response = None
        self._sse_thread: threading.Thread | None = None
        self._sse_closed = threading.Event()
        self._sse_ready = threading.Event()
        self._pending: dict[int, Queue[dict[str, Any]]] = {}
        self._sse_error: str | None = None
        self._session_id: str | None = None

    @property
    def running(self) -> bool:
        return self._connected

    @property
    def descriptor(self) -> list[str]:
        return [self.config.url or ""]

    def connect(self) -> None:
        self.close()
        attempts: list[dict[str, Any]] = []
        last_auth_exc: McpAuthRequiredError | None = None
        last_registration_exc: McpNeedsClientRegistrationError | None = None
        try:
            self._connect_streamable_http()
            self.transport_attempts = attempts + [{"transport": "streamable_http", "status": "ok"}]
            return
        except McpAuthRequiredError as exc:
            last_auth_exc = exc
            attempts.append({"transport": "streamable_http", "status": "failed", "error": str(exc)})
        except McpNeedsClientRegistrationError as exc:
            last_registration_exc = exc
            attempts.append({"transport": "streamable_http", "status": "failed", "error": str(exc)})
        except Exception as exc:
            attempts.append({"transport": "streamable_http", "status": "failed", "error": str(exc)})
        try:
            self._connect_sse()
            self.transport_attempts = attempts + [{"transport": "sse", "status": "ok"}]
            return
        except McpAuthRequiredError as exc:
            last_auth_exc = exc
            attempts.append({"transport": "sse", "status": "failed", "error": str(exc)})
        except McpNeedsClientRegistrationError as exc:
            last_registration_exc = exc
            attempts.append({"transport": "sse", "status": "failed", "error": str(exc)})
        except Exception as exc:
            attempts.append({"transport": "sse", "status": "failed", "error": str(exc)})
            self.transport_attempts = attempts
            if last_registration_exc is not None:
                raise last_registration_exc
            if last_auth_exc is not None:
                raise last_auth_exc
            raise McpClientError(" ; ".join(f"{item['transport']}: {item['error']}" for item in attempts)) from exc
        self.transport_attempts = attempts
        if last_registration_exc is not None:
            raise last_registration_exc
        if last_auth_exc is not None:
            raise last_auth_exc
        raise McpClientError(" ; ".join(f"{item['transport']}: {item['error']}" for item in attempts))

    def close(self) -> None:
        self._connected = False
        self.transport_name = None
        self._sse_closed.set()
        response = self._sse_response
        self._sse_response = None
        if response is not None:
            try:
                response.close()
            except Exception:
                pass
        self._sse_messages_url = None
        self._sse_error = None
        self._session_id = None
        self._sse_ready.clear()
        self._pending.clear()

    def _request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        if not self.running or self.transport_name is None:
            raise McpClientError(f"MCP server {self.config.name} is not connected")
        if self.transport_name == "streamable_http":
            return self._post_request(self.config.url or "", method, params)
        if self.transport_name == "sse":
            return self._sse_request(method, params)
        raise McpClientError(f"unsupported remote transport: {self.transport_name}")

    def _notify(self, method: str, params: dict[str, Any]) -> None:
        if not self.running or self.transport_name is None:
            raise McpClientError(f"MCP server {self.config.name} is not connected")
        if self.transport_name == "streamable_http":
            self._post_notification(self.config.url or "", method, params)
            return
        if self.transport_name == "sse":
            self._sse_notification(method, params)
            return
        raise McpClientError(f"unsupported remote transport: {self.transport_name}")

    def _connect_streamable_http(self) -> None:
        self.transport_name = "streamable_http"
        self._connected = True
        try:
            self._initialize()
        except Exception:
            self.close()
            raise

    def _connect_sse(self) -> None:
        sse_url = self.config.sse_url or _derive_sse_url(self.config.url or "")
        request = urllib.request.Request(
            sse_url,
            headers=self._headers({"Accept": "text/event-stream"}),
            method="GET",
        )
        try:
            self._sse_response = urllib.request.urlopen(request, timeout=self.config.timeout_seconds)
        except urllib.error.HTTPError as exc:
            raise _map_http_error(self.config.name, exc) from exc
        except urllib.error.URLError as exc:
            raise McpClientError(str(exc.reason or exc)) from exc
        self._sse_closed.clear()
        self._sse_ready.clear()
        self._sse_thread = threading.Thread(target=self._read_sse, daemon=True)
        self._sse_thread.start()
        if not self._sse_ready.wait(timeout=self.config.timeout_seconds):
            self.close()
            raise McpClientError(self._sse_error or f"MCP SSE endpoint did not publish an endpoint: {sse_url}")
        time.sleep(0.1)
        self.transport_name = "sse"
        self._connected = True
        try:
            self._initialize()
        except Exception:
            self.close()
            raise

    def _post_request(self, url: str, method: str, params: dict[str, Any]) -> dict[str, Any]:
        request_id = self._new_request_id()
        payload = {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}
        response = self._http_json(url, payload)
        if response.get("error"):
            error = response["error"]
            raise McpClientError(error.get("message") if isinstance(error, dict) else str(error))
        result = response.get("result")
        return result if isinstance(result, dict) else {}

    def _post_notification(self, url: str, method: str, params: dict[str, Any]) -> None:
        payload = {"jsonrpc": "2.0", "method": method, "params": params}
        self._http_json(url, payload, expect_result=False)

    def _sse_request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        if not self._sse_messages_url:
            raise McpClientError(f"MCP SSE messages endpoint missing for {self.config.name}")
        request_id = self._new_request_id()
        queue: Queue[dict[str, Any]] = Queue()
        self._pending[request_id] = queue
        try:
            payload = {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}
            self._http_json(self._sse_messages_url, payload, expect_result=False)
            response = queue.get(timeout=self.config.timeout_seconds)
        except Empty as exc:
            raise McpClientError(f"MCP request timed out: {self.config.name}.{method}") from exc
        finally:
            self._pending.pop(request_id, None)
        if response.get("error"):
            error = response["error"]
            raise McpClientError(error.get("message") if isinstance(error, dict) else str(error))
        result = response.get("result")
        return result if isinstance(result, dict) else {}

    def _sse_notification(self, method: str, params: dict[str, Any]) -> None:
        if not self._sse_messages_url:
            raise McpClientError(f"MCP SSE messages endpoint missing for {self.config.name}")
        payload = {"jsonrpc": "2.0", "method": method, "params": params}
        self._http_json(self._sse_messages_url, payload, expect_result=False)

    def _read_sse(self) -> None:
        response = self._sse_response
        if response is None:
            return
        event = "message"
        data_lines: list[str] = []
        try:
            for raw_line in response:
                if self._sse_closed.is_set():
                    return
                line = raw_line.decode("utf-8") if isinstance(raw_line, bytes) else raw_line
                line = line.rstrip("\n")
                if not line:
                    self._dispatch_sse_event(event, "\n".join(data_lines))
                    event = "message"
                    data_lines = []
                    continue
                if line.startswith("event:"):
                    event = line.split(":", 1)[1].strip() or "message"
                elif line.startswith("data:"):
                    data_lines.append(line.split(":", 1)[1].lstrip())
        except Exception as exc:
            self._sse_error = str(exc)
            self._sse_ready.set()

    def _dispatch_sse_event(self, event: str, data: str) -> None:
        if not data:
            return
        if event == "endpoint":
            self._sse_messages_url = _resolve_endpoint_url(self.config.url or "", data)
            self._sse_ready.set()
            return
        try:
            message = json.loads(data)
        except json.JSONDecodeError:
            self._sse_error = data
            self._sse_ready.set()
            return
        request_id = message.get("id")
        if request_id is None:
            return
        queue = self._pending.get(int(request_id))
        if queue is not None:
            queue.put(message)

    def _http_json(self, url: str, payload: dict[str, Any], *, expect_result: bool = True) -> dict[str, Any]:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=data,
            headers=self._headers({"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}),
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.config.timeout_seconds) as response:
                session_id = response.headers.get("mcp-session-id")
                if session_id:
                    self._session_id = session_id
                raw = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            raise _map_http_error(self.config.name, exc) from exc
        except urllib.error.URLError as exc:
            raise McpClientError(str(exc.reason or exc)) from exc
        if not raw.strip():
            return {}
        if raw.lstrip().startswith("event:") or "\ndata:" in raw:
            parsed_stream = _parse_event_stream_json(raw)
            if parsed_stream is not None:
                return parsed_stream
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            if not expect_result:
                return {}
            raise
        if not isinstance(parsed, dict):
            if expect_result:
                raise McpClientError(f"MCP server {self.config.name} returned a non-object response")
            return {}
        return parsed

    def _headers(self, extra: dict[str, str] | None = None) -> dict[str, str]:
        headers = dict(self.config.headers)
        headers.update(self.auth_headers)
        if self._session_id:
            headers["mcp-session-id"] = self._session_id
        if extra:
            headers.update(extra)
        return headers


def _derive_sse_url(base_url: str) -> str:
    if base_url.endswith("/mcp"):
        return base_url[:-4] + "/sse"
    return base_url.rstrip("/") + "/sse"


def _resolve_endpoint_url(base_url: str, payload: str) -> str:
    try:
        parsed = json.loads(payload)
        candidate = (
            parsed.get("messagesUrl")
            or parsed.get("messages_url")
            or parsed.get("url")
            or parsed.get("endpoint")
        )
        if isinstance(candidate, str) and candidate:
            payload = candidate
    except json.JSONDecodeError:
        pass
    return urllib.parse.urljoin(base_url, payload)


def _map_http_error(server_name: str, exc: urllib.error.HTTPError) -> McpClientError:
    if exc.code in {401, 403}:
        return McpAuthRequiredError(f"MCP server {server_name} requires authentication ({exc.code})")
    if exc.code == 428:
        return McpNeedsClientRegistrationError(
            f"MCP server {server_name} requires client registration ({exc.code})"
        )
    return McpClientError(f"HTTP {exc.code}: {exc.reason}")


def _parse_event_stream_json(raw: str) -> dict[str, Any] | None:
    data_lines: list[str] = []
    for line in raw.splitlines():
        if line.startswith("data:"):
            data_lines.append(line.split(":", 1)[1].lstrip())
    if not data_lines:
        return None
    payload = "\n".join(data_lines).strip()
    if not payload:
        return None
    parsed = json.loads(payload)
    return parsed if isinstance(parsed, dict) else None

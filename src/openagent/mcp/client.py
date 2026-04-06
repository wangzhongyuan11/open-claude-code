from __future__ import annotations

import json
import os
import select
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

from openagent.mcp.models import McpServerConfig


class McpClientError(RuntimeError):
    pass


class StdioMcpClient:
    def __init__(self, config: McpServerConfig, workspace: Path) -> None:
        if not config.command:
            raise McpClientError(f"MCP server {config.name} missing command")
        self.config = config
        self.workspace = workspace
        self._process: subprocess.Popen[str] | None = None
        self._next_id = 1
        self._stderr: list[str] = []
        self._stderr_thread: threading.Thread | None = None

    @property
    def running(self) -> bool:
        return self._process is not None and self._process.poll() is None

    @property
    def command_line(self) -> list[str]:
        return [self.config.command or "", *self.config.args]

    @property
    def stderr_tail(self) -> str:
        return "\n".join(self._stderr[-20:])

    def connect(self) -> None:
        if self.running:
            return
        env = os.environ.copy()
        env.update(self.config.env)
        self._process = subprocess.Popen(
            self.command_line,
            cwd=str(self.workspace),
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        self._stderr_thread = threading.Thread(target=self._read_stderr, daemon=True)
        self._stderr_thread.start()
        try:
            self._request(
                "initialize",
                {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"roots": {"listChanged": True}},
                    "clientInfo": {"name": "openagent", "version": "0.1.0"},
                },
            )
            self._notify("notifications/initialized", {})
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
        process = self._ensure_process()
        request_id = self._next_id
        self._next_id += 1
        payload = {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}
        assert process.stdin is not None
        process.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
        process.stdin.flush()
        deadline = time.time() + self.config.timeout_seconds
        while time.time() < deadline:
            if process.poll() is not None:
                raise McpClientError(
                    f"MCP server {self.config.name} exited with code {process.returncode}: {self.stderr_tail}"
                )
            assert process.stdout is not None
            ready, _, _ = select.select([process.stdout], [], [], min(0.25, max(0.0, deadline - time.time())))
            if not ready:
                continue
            line = process.stdout.readline()
            if not line:
                continue
            message = json.loads(line)
            if "id" not in message:
                continue
            if message.get("id") != request_id:
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
        process.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
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
            self._stderr.append(line.rstrip())

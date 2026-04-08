from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

from openagent.domain.tools import ToolContext
from openagent.mcp import McpGetPromptTool, McpManager, McpReadResourceTool, McpTool
from openagent.tools.registry import ToolRegistry


def _free_port() -> int:
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


def _write_stdio_config(workspace: Path) -> None:
    fixture = Path(__file__).parent / "fixtures" / "mcp" / "fake_mcp_server.py"
    (workspace / "openagent.mcp.json").write_text(
        json.dumps(
            {
                "mcpServers": {
                    "fake": {
                        "type": "stdio",
                        "command": sys.executable,
                        "args": [str(fixture)],
                        "enabled": True,
                        "timeout": 5,
                    }
                }
            }
        ),
        encoding="utf-8",
    )


def _start_remote_server(mode: str, port: int, token: str = "") -> subprocess.Popen[str]:
    fixture = Path(__file__).parent / "fixtures" / "mcp" / "fake_remote_mcp_server.py"
    env = dict(os.environ)
    env.update({"PYTHONUNBUFFERED": "1", "FAKE_REMOTE_MODE": mode, "FAKE_REMOTE_TOKEN": token})
    process = subprocess.Popen(
        [sys.executable, str(fixture), str(port)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        text=True,
        env=env,
    )
    deadline = time.time() + 5
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                return process
        except OSError:
            time.sleep(0.05)
    process.kill()
    raise RuntimeError(f"remote MCP fixture did not start on port {port}")


def _write_remote_config(workspace: Path, section: dict) -> None:
    (workspace / "openagent.mcp.json").write_text(
        json.dumps({"mcpServers": section}, ensure_ascii=False),
        encoding="utf-8",
    )


def test_mcp_manager_connects_and_lists_capabilities(tmp_path: Path):
    _write_stdio_config(tmp_path)
    manager = McpManager(tmp_path)
    try:
        state = manager.connect("fake")

        assert state.status == "connected"
        assert [tool.tool_id for tool in manager.list_tools()] == ["mcp__fake__echo"]
        assert manager.list_resources()["fake"][0]["uri"] == "fake://resource"
        assert manager.list_prompts()["fake"][0]["name"] == "fake-prompt"
    finally:
        manager.close()


def test_mcp_tool_invokes_through_registry(tmp_path: Path):
    _write_stdio_config(tmp_path)
    manager = McpManager(tmp_path)
    try:
        manager.connect_all()
        registry = ToolRegistry()
        registry.register(McpReadResourceTool(manager))
        registry.register(McpGetPromptTool(manager))
        for info in manager.list_tools():
            registry.register(McpTool(manager, info))

        result = registry.invoke(
            "mcp__fake__echo",
            {"message": "ok"},
            ToolContext(workspace=tmp_path, session_id="test", runtime_state={"yolo_mode": "true"}),
        )

        assert result.status == "succeeded"
        assert result.content == "echo:ok"
        assert result.metadata["tool_source"] == "mcp"
        assert result.metadata["server"] == "fake"

        resource = registry.invoke(
            "mcp_read_resource",
            {"server": "fake", "uri": "fake://resource"},
            ToolContext(workspace=tmp_path, session_id="test", runtime_state={"yolo_mode": "true"}),
        )
        assert resource.status == "succeeded"
        assert resource.content == "fake resource"

        prompt = registry.invoke(
            "mcp_get_prompt",
            {"server": "fake", "name": "fake-prompt"},
            ToolContext(workspace=tmp_path, session_id="test", runtime_state={"yolo_mode": "true"}),
        )
        assert prompt.status == "succeeded"
        assert "fake prompt" in prompt.content
    finally:
        manager.close()


def test_mcp_disabled_server_is_not_connected(tmp_path: Path):
    fixture = Path(__file__).parent / "fixtures" / "mcp" / "fake_mcp_server.py"
    (tmp_path / "openagent.mcp.json").write_text(
        json.dumps(
            {
                "mcpServers": {
                    "fake": {
                        "type": "stdio",
                        "command": sys.executable,
                        "args": [str(fixture)],
                        "enabled": False,
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    manager = McpManager(tmp_path)

    assert manager.list_states()[0].status == "disabled"
    assert manager.list_tools() == []


def test_remote_config_parse_and_streamable_connect(tmp_path: Path):
    port = _free_port()
    process = _start_remote_server("stream", port)
    _write_remote_config(
        tmp_path,
        {
            "remote-fake": {
                "type": "remote",
                "url": f"http://127.0.0.1:{port}/mcp",
                "headers": {"X-Test": "ok"},
                "enabled": True,
                "timeout": 5,
            }
        },
    )
    manager = McpManager(tmp_path)
    try:
        state = manager.connect("remote-fake")
        assert state.status == "connected"
        assert state.transport == "streamable_http"
        assert state.fallback_used is False
        assert [tool.tool_id for tool in manager.list_tools()] == ["mcp__remote_fake__echo"]
    finally:
        manager.close()
        process.kill()
        process.wait()


def test_remote_transport_falls_back_to_sse(tmp_path: Path):
    port = _free_port()
    process = _start_remote_server("sse_only", port)
    _write_remote_config(
        tmp_path,
        {
            "remote-sse": {
                "type": "remote",
                "url": f"http://127.0.0.1:{port}/mcp",
                "enabled": True,
                "timeout": 5,
            }
        },
    )
    manager = McpManager(tmp_path)
    try:
        state = manager.connect("remote-sse")
        assert state.status == "connected"
        assert state.transport == "sse"
        assert state.fallback_used is True
        assert state.attempts[0]["transport"] == "streamable_http"
        assert state.attempts[0]["status"] == "failed"
    finally:
        manager.close()
        process.kill()
        process.wait()


def test_remote_status_transitions_for_auth_and_registration(tmp_path: Path):
    auth_port = _free_port()
    auth_process = _start_remote_server("stream", auth_port, token="secret-token")
    reg_port = _free_port()
    reg_process = _start_remote_server("registration", reg_port)
    _write_remote_config(
        tmp_path,
        {
            "needs-auth": {
                "type": "remote",
                "url": f"http://127.0.0.1:{auth_port}/mcp",
                "oauth": {},
                "enabled": True,
                "timeout": 5,
            },
            "needs-registration": {
                "type": "remote",
                "url": f"http://127.0.0.1:{reg_port}/mcp",
                "enabled": True,
                "timeout": 5,
            },
        },
    )
    manager = McpManager(tmp_path)
    try:
        auth_state = manager.connect("needs-auth")
        reg_state = manager.connect("needs-registration")
        assert auth_state.status == "needs_auth"
        assert reg_state.status == "needs_client_registration"

        auth_result = manager.set_auth(
            "needs-auth",
            {"access_token": "secret-token", "header_name": "X-API-Key", "prefix": ""},
        )
        assert auth_result["status"] == "connected"
        assert manager.inspect("needs-auth")["auth"]["present"] is True
    finally:
        manager.close()
        auth_process.kill()
        auth_process.wait()
        reg_process.kill()
        reg_process.wait()


def test_registry_normalizes_mcp_tool_ids(tmp_path: Path):
    _write_config = _write_stdio_config
    _write_config(tmp_path)
    manager = McpManager(tmp_path)
    try:
        manager.connect_all()
        registry = ToolRegistry()
        registry.register_factory(
            "mcp__fake_server__echo",
            lambda: McpTool(
                manager,
                next(
                    info for info in manager.list_tools() if info.tool_id == "mcp__fake__echo"
                ),
            ),
            source="mcp",
        )
        alias = registry.invoke(
            "mcp__fake-server__echo",
            {"message": "ok"},
            ToolContext(workspace=tmp_path, session_id="test", runtime_state={"yolo_mode": "true"}),
        )
        assert alias.content == "echo:ok"
    finally:
        manager.close()

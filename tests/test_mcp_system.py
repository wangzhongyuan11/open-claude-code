from __future__ import annotations

import json
import sys
from pathlib import Path

from openagent.domain.tools import ToolContext
from openagent.mcp import McpGetPromptTool, McpManager, McpReadResourceTool, McpTool
from openagent.tools.registry import ToolRegistry


def _write_config(workspace: Path) -> None:
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


def test_mcp_manager_connects_and_lists_capabilities(tmp_path: Path):
    _write_config(tmp_path)
    manager = McpManager(tmp_path)
    try:
        state = manager.connect("fake")

        assert state.status == "running"
        assert [tool.tool_id for tool in manager.list_tools()] == ["mcp__fake__echo"]
        assert manager.list_resources()["fake"][0]["uri"] == "fake://resource"
        assert manager.list_prompts()["fake"][0]["name"] == "fake-prompt"
    finally:
        manager.close()


def test_mcp_tool_invokes_through_registry(tmp_path: Path):
    _write_config(tmp_path)
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

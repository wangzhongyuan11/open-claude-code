from __future__ import annotations

import json
from typing import Any

from openagent.domain.tools import ToolContext, ToolExecutionResult
from openagent.mcp.manager import McpManager
from openagent.mcp.models import McpToolInfo
from openagent.tools.base import BaseTool


class McpTool(BaseTool):
    source = "mcp"

    def __init__(self, manager: McpManager, info: McpToolInfo) -> None:
        self.manager = manager
        self.info = info
        self.tool_id = info.tool_id
        self.name = info.tool_id
        self.description = f"[MCP:{info.server}] {info.description}"
        self.input_schema = info.input_schema
        self.metadata = {"server": info.server, "mcp_tool": info.name}

    def invoke(self, arguments: dict[str, Any], context: ToolContext) -> ToolExecutionResult:
        result = self.manager.call_tool(self.info.tool_id, arguments)
        output = _format_mcp_result(result)
        is_error = bool(result.get("isError"))
        metadata = {
            "operation": "mcp_tool",
            "server": self.info.server,
            "mcp_tool": self.info.name,
            "raw": json.dumps(result, ensure_ascii=False)[:4000],
        }
        if is_error:
            return ToolExecutionResult.failure(
                output,
                error_type="mcp_tool_error",
                hint=f"MCP server {self.info.server} reported an error.",
                metadata=metadata,
            )
        return ToolExecutionResult.success(
            output,
            title=f"MCP {self.info.server}:{self.info.name}",
            metadata=metadata,
        )


class McpReadResourceTool(BaseTool):
    tool_id = "mcp_read_resource"
    name = "mcp_read_resource"
    description = "Read a resource from a configured MCP server by server name and resource URI."
    input_schema = {
        "type": "object",
        "properties": {
            "server": {"type": "string"},
            "uri": {"type": "string"},
        },
        "required": ["server", "uri"],
    }
    source = "mcp"

    def __init__(self, manager: McpManager) -> None:
        self.manager = manager

    def invoke(self, arguments: dict[str, Any], context: ToolContext) -> ToolExecutionResult:
        server = str(arguments["server"])
        uri = str(arguments["uri"])
        result = self.manager.read_resource(server, uri)
        return ToolExecutionResult.success(
            _format_mcp_resource(result),
            title=f"MCP resource {server}:{uri}",
            metadata={
                "operation": "mcp_resource",
                "server": server,
                "uri": uri,
                "raw": json.dumps(result, ensure_ascii=False)[:4000],
            },
        )


class McpGetPromptTool(BaseTool):
    tool_id = "mcp_get_prompt"
    name = "mcp_get_prompt"
    description = "Get a prompt template from a configured MCP server by server and prompt name."
    input_schema = {
        "type": "object",
        "properties": {
            "server": {"type": "string"},
            "name": {"type": "string"},
            "arguments": {"type": "object"},
        },
        "required": ["server", "name"],
    }
    source = "mcp"

    def __init__(self, manager: McpManager) -> None:
        self.manager = manager

    def invoke(self, arguments: dict[str, Any], context: ToolContext) -> ToolExecutionResult:
        server = str(arguments["server"])
        name = str(arguments["name"])
        result = self.manager.get_prompt(server, name, dict(arguments.get("arguments") or {}))
        return ToolExecutionResult.success(
            _format_mcp_prompt(result),
            title=f"MCP prompt {server}:{name}",
            metadata={
                "operation": "mcp_prompt",
                "server": server,
                "prompt": name,
                "raw": json.dumps(result, ensure_ascii=False)[:4000],
            },
        )


def _format_mcp_result(result: dict[str, Any]) -> str:
    content = result.get("content")
    if isinstance(content, list):
        chunks: list[str] = []
        for item in content:
            if not isinstance(item, dict):
                chunks.append(str(item))
                continue
            if item.get("type") == "text":
                chunks.append(str(item.get("text", "")))
            else:
                chunks.append(json.dumps(item, ensure_ascii=False))
        return "\n".join(chunk for chunk in chunks if chunk)
    if "structuredContent" in result:
        return json.dumps(result["structuredContent"], ensure_ascii=False, indent=2)
    return json.dumps(result, ensure_ascii=False, indent=2)


def _format_mcp_resource(result: dict[str, Any]) -> str:
    contents = result.get("contents")
    if isinstance(contents, list):
        chunks: list[str] = []
        for item in contents:
            if not isinstance(item, dict):
                chunks.append(str(item))
            elif "text" in item:
                chunks.append(str(item.get("text", "")))
            else:
                chunks.append(json.dumps(item, ensure_ascii=False))
        return "\n".join(chunk for chunk in chunks if chunk)
    return json.dumps(result, ensure_ascii=False, indent=2)


def _format_mcp_prompt(result: dict[str, Any]) -> str:
    messages = result.get("messages")
    if isinstance(messages, list):
        return "\n\n".join(json.dumps(item, ensure_ascii=False) for item in messages)
    return json.dumps(result, ensure_ascii=False, indent=2)

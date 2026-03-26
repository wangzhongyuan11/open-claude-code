from __future__ import annotations

from pathlib import Path

from openagent.domain.tools import ToolContext, ToolExecutionResult
from openagent.tools.base import BaseTool


def resolve_workspace_path(workspace: Path, raw_path: str) -> Path:
    path = (workspace / raw_path).resolve()
    if workspace.resolve() not in path.parents and path != workspace.resolve():
        raise ValueError(f"path escapes workspace: {raw_path}")
    return path


class ReadFileTool(BaseTool):
    name = "read_file"
    description = "Read a UTF-8 text file from the workspace."
    input_schema = {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
        },
        "required": ["path"],
    }

    def invoke(self, arguments: dict, context: ToolContext) -> ToolExecutionResult:
        path = resolve_workspace_path(context.workspace, arguments["path"])
        return ToolExecutionResult(content=path.read_text(encoding="utf-8"))


class WriteFileTool(BaseTool):
    name = "write_file"
    description = "Write UTF-8 text content to a file in the workspace."
    input_schema = {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "content": {"type": "string"},
        },
        "required": ["path", "content"],
    }

    def invoke(self, arguments: dict, context: ToolContext) -> ToolExecutionResult:
        path = resolve_workspace_path(context.workspace, arguments["path"])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(arguments["content"], encoding="utf-8")
        return ToolExecutionResult(content=f"wrote {len(arguments['content'])} bytes to {arguments['path']}")


class ListFilesTool(BaseTool):
    name = "list_files"
    description = "List workspace files recursively."
    input_schema = {
        "type": "object",
        "properties": {},
    }

    def invoke(self, arguments: dict, context: ToolContext) -> ToolExecutionResult:
        files = [
            str(path.relative_to(context.workspace))
            for path in sorted(context.workspace.rglob("*"))
            if path.is_file()
        ]
        return ToolExecutionResult(content="\n".join(files) if files else "(no files)")

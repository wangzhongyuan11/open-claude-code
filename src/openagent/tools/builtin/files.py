from __future__ import annotations

from pathlib import Path

from openagent.domain.tools import ToolContext, ToolExecutionResult
from openagent.tools.base import BaseTool

IGNORED_TOP_LEVEL_NAMES = {
    ".git",
    ".openagent",
    ".pytest_cache",
    "__pycache__",
}


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


class AppendFileTool(BaseTool):
    name = "append_file"
    description = "Append UTF-8 text content to a file in the workspace."
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
        with path.open("a", encoding="utf-8") as handle:
            handle.write(arguments["content"])
        return ToolExecutionResult(content=f"appended {len(arguments['content'])} bytes to {arguments['path']}")


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
            if path.is_file() and not _is_ignored(path, context.workspace)
        ]
        return ToolExecutionResult(content="\n".join(files) if files else "(no files)")


def _is_ignored(path: Path, workspace: Path) -> bool:
    relative_parts = path.relative_to(workspace).parts
    return any(part in IGNORED_TOP_LEVEL_NAMES for part in relative_parts)


class AppendFileTool(BaseTool):
    name = "append_file"
    description = "Append UTF-8 text to the end of a file in the workspace."
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
        path.write_text(path.read_text(encoding="utf-8") + arguments["content"], encoding="utf-8")
        return ToolExecutionResult(content=f"appended {len(arguments['content'])} bytes to {arguments['path']}")

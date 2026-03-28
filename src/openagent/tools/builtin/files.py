from __future__ import annotations

import hashlib
from pathlib import Path

from openagent.domain.tools import ToolContext, ToolExecutionResult, ToolOutputLimits
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
    output_limits = ToolOutputLimits(max_chars=16000, max_lines=500, direction="head")
    input_schema = {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
        },
        "required": ["path"],
    }

    def invoke(self, arguments: dict, context: ToolContext) -> ToolExecutionResult:
        path = resolve_workspace_path(context.workspace, arguments["path"])
        content = path.read_text(encoding="utf-8")
        return ToolExecutionResult.success(
            content,
            title=f"Read {arguments['path']}",
            metadata={
                "path": arguments["path"],
                "content": content,
                "snapshot_after_ref": _snapshot_ref(arguments["path"], content),
            },
        )


class ReadFileRangeTool(BaseTool):
    tool_id = "read_file_range"
    name = "read_file_range"
    description = "Read a specific line range from a UTF-8 text file."
    output_limits = ToolOutputLimits(max_chars=12000, max_lines=300, direction="head")
    input_schema = {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "start_line": {"type": "integer"},
            "end_line": {"type": "integer"},
        },
        "required": ["path", "start_line", "end_line"],
    }

    def invoke(self, arguments: dict, context: ToolContext) -> ToolExecutionResult:
        path = resolve_workspace_path(context.workspace, arguments["path"])
        start_line = max(1, int(arguments["start_line"]))
        end_line = max(start_line, int(arguments["end_line"]))
        if end_line < start_line:
            return ToolExecutionResult.failure(
                "invalid line range",
                error_type="invalid_range",
                hint="Use 1-based line numbers with end_line >= start_line.",
                metadata={"path": arguments["path"], "start_line": str(start_line), "end_line": str(end_line)},
            )
        lines = path.read_text(encoding="utf-8").splitlines()
        selected = lines[start_line - 1 : end_line]
        content = "\n".join(selected)
        return ToolExecutionResult.success(
            content,
            title=f"Read lines {start_line}-{end_line} from {arguments['path']}",
            metadata={
                "path": arguments["path"],
                "start_line": str(start_line),
                "end_line": str(end_line),
                "content": content,
                "snapshot_after_ref": _snapshot_ref(arguments["path"], "\n".join(lines)),
            },
        )


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
        before_exists = path.exists()
        before_content = path.read_text(encoding="utf-8") if before_exists else ""
        path.parent.mkdir(parents=True, exist_ok=True)
        after_content = arguments["content"]
        path.write_text(after_content, encoding="utf-8")
        return ToolExecutionResult.success(
            f"wrote {len(arguments['content'])} bytes to {arguments['path']}",
            title=f"Wrote {arguments['path']}",
            metadata={
                "path": arguments["path"],
                "operation": "write_file",
                "before_content": before_content,
                "after_content": after_content,
                "before_exists": before_exists,
                "snapshot_before_ref": _snapshot_ref(arguments["path"], before_content) if before_exists else None,
                "snapshot_after_ref": _snapshot_ref(arguments["path"], after_content),
            },
        )


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
        before_exists = path.exists()
        before_content = path.read_text(encoding="utf-8") if before_exists else ""
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(arguments["content"])
        after_content = path.read_text(encoding="utf-8")
        return ToolExecutionResult.success(
            f"appended {len(arguments['content'])} bytes to {arguments['path']}",
            title=f"Appended {arguments['path']}",
            metadata={
                "path": arguments["path"],
                "operation": "append_file",
                "before_content": before_content,
                "after_content": after_content,
                "before_exists": before_exists,
                "snapshot_before_ref": _snapshot_ref(arguments["path"], before_content) if before_exists else None,
                "snapshot_after_ref": _snapshot_ref(arguments["path"], after_content),
            },
        )


class ListFilesTool(BaseTool):
    name = "list_files"
    description = "List workspace files recursively."
    output_limits = ToolOutputLimits(max_chars=12000, max_lines=600, direction="head")
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
        return ToolExecutionResult.success(
            "\n".join(files) if files else "(no files)",
            title="Listed workspace files",
            metadata={"file_count": str(len(files))},
        )


class EnsureDirTool(BaseTool):
    tool_id = "ensure_dir"
    name = "ensure_dir"
    description = "Ensure that a directory exists inside the workspace."
    input_schema = {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
        },
        "required": ["path"],
    }

    def invoke(self, arguments: dict, context: ToolContext) -> ToolExecutionResult:
        path = resolve_workspace_path(context.workspace, arguments["path"])
        existed = path.exists()
        if existed and not path.is_dir():
            return ToolExecutionResult.failure(
                f"path exists but is not a directory: {arguments['path']}",
                error_type="not_a_directory",
                hint="Choose a path that is either missing or already a directory.",
                metadata={"path": arguments["path"], "operation": "ensure_dir"},
            )
        path.mkdir(parents=True, exist_ok=True)
        return ToolExecutionResult.success(
            f"directory ready: {arguments['path']}",
            title=f"Ensured directory {arguments['path']}",
            metadata={
                "path": arguments["path"],
                "operation": "ensure_dir",
                "dir_exists": "true",
                "already_existed": str(existed).lower(),
                "snapshot_after_ref": f"snapshot:{arguments['path']}:dir",
            },
        )


def _is_ignored(path: Path, workspace: Path) -> bool:
    relative_parts = path.relative_to(workspace).parts
    return any(part in IGNORED_TOP_LEVEL_NAMES for part in relative_parts)


def _snapshot_ref(path: str, content: str) -> str:
    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()[:12]
    return f"snapshot:{path}:{digest}"

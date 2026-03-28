from __future__ import annotations

import hashlib

from openagent.domain.tools import ToolContext, ToolExecutionResult
from openagent.tools.base import BaseTool
from openagent.tools.builtin.files import resolve_workspace_path


class EditFileTool(BaseTool):
    name = "edit_file"
    description = "Replace the first occurrence of exact text in a file."
    input_schema = {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "old_text": {"type": "string"},
            "new_text": {"type": "string"},
        },
        "required": ["path", "old_text", "new_text"],
    }

    def invoke(self, arguments: dict, context: ToolContext) -> ToolExecutionResult:
        path = resolve_workspace_path(context.workspace, arguments["path"])
        content = path.read_text(encoding="utf-8")
        old_text = arguments["old_text"]
        if old_text not in content:
            return ToolExecutionResult.failure(
                "target text not found",
                error_type="target_not_found",
                retryable=False,
                hint="Read the file again and use the exact current text for old_text.",
                metadata={"path": arguments["path"], "operation": "edit_file"},
            )
        updated = content.replace(old_text, arguments["new_text"], 1)
        path.write_text(updated, encoding="utf-8")
        return ToolExecutionResult.success(
            f"edited {arguments['path']}",
            title=f"Edited {arguments['path']}",
            metadata={
                "path": arguments["path"],
                "operation": "edit_file",
                "before_content": content,
                "after_content": updated,
                "snapshot_before_ref": _snapshot_ref(arguments["path"], content),
                "snapshot_after_ref": _snapshot_ref(arguments["path"], updated),
            },
        )


def _snapshot_ref(path: str, content: str) -> str:
    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()[:12]
    return f"snapshot:{path}:{digest}"


class MultiEditTool(BaseTool):
    tool_id = "multiedit"
    name = "multiedit"
    description = "Apply multiple exact text replacements to a single file in order."
    input_schema = {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "edits": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "old_text": {"type": "string"},
                        "new_text": {"type": "string"},
                    },
                    "required": ["old_text", "new_text"],
                },
            },
        },
        "required": ["path", "edits"],
    }

    def invoke(self, arguments: dict, context: ToolContext) -> ToolExecutionResult:
        path = resolve_workspace_path(context.workspace, arguments["path"])
        edits = arguments["edits"]
        content = path.read_text(encoding="utf-8")
        updated = content
        applied = 0
        for edit in edits:
            old_text = edit["old_text"]
            new_text = edit["new_text"]
            if old_text not in updated:
                return ToolExecutionResult.failure(
                    f"target text not found for edit #{applied + 1}",
                    error_type="target_not_found",
                    retryable=False,
                    hint="Read the file again and make sure every old_text exactly matches the current file content.",
                    metadata={"path": arguments["path"], "operation": "multiedit", "applied_count": str(applied)},
                )
            updated = updated.replace(old_text, new_text, 1)
            applied += 1
        path.write_text(updated, encoding="utf-8")
        return ToolExecutionResult.success(
            f"applied {applied} edits to {arguments['path']}",
            title=f"Multi-edited {arguments['path']}",
            metadata={
                "path": arguments["path"],
                "operation": "multiedit",
                "before_content": content,
                "after_content": updated,
                "applied_count": str(applied),
                "snapshot_before_ref": _snapshot_ref(arguments["path"], content),
                "snapshot_after_ref": _snapshot_ref(arguments["path"], updated),
            },
        )

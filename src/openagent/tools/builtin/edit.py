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

    def mutates_workspace(self) -> bool:
        return True

    def snapshot_paths(self, arguments: dict, context: ToolContext) -> list[str]:
        return [arguments["path"]]


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

    def mutates_workspace(self) -> bool:
        return True

    def snapshot_paths(self, arguments: dict, context: ToolContext) -> list[str]:
        return [arguments["path"]]


class ReplaceAllTool(BaseTool):
    tool_id = "replace_all"
    name = "replace_all"
    description = "Replace all occurrences of exact text in a file."
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
                hint="Read the file again and make sure old_text exactly matches the current file content.",
                metadata={"path": arguments["path"], "operation": "replace_all"},
            )
        updated = content.replace(old_text, arguments["new_text"])
        replacements = content.count(old_text)
        path.write_text(updated, encoding="utf-8")
        return ToolExecutionResult.success(
            f"replaced {replacements} occurrence(s) in {arguments['path']}",
            title=f"Replaced text in {arguments['path']}",
            metadata={
                "path": arguments["path"],
                "operation": "replace_all",
                "before_content": content,
                "after_content": updated,
                "replaced_count": str(replacements),
                "snapshot_before_ref": _snapshot_ref(arguments["path"], content),
                "snapshot_after_ref": _snapshot_ref(arguments["path"], updated),
            },
        )

    def mutates_workspace(self) -> bool:
        return True

    def snapshot_paths(self, arguments: dict, context: ToolContext) -> list[str]:
        return [arguments["path"]]


class InsertTextTool(BaseTool):
    tool_id = "insert_text"
    name = "insert_text"
    description = "Insert text before or after an exact anchor string in a file."
    input_schema = {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "anchor_text": {"type": "string"},
            "new_text": {"type": "string"},
            "position": {"type": "string"},
        },
        "required": ["path", "anchor_text", "new_text", "position"],
    }

    def invoke(self, arguments: dict, context: ToolContext) -> ToolExecutionResult:
        path = resolve_workspace_path(context.workspace, arguments["path"])
        content = path.read_text(encoding="utf-8")
        anchor = arguments["anchor_text"]
        position = arguments["position"]
        if position not in {"before", "after"}:
            return ToolExecutionResult.failure(
                "position must be 'before' or 'after'",
                error_type="invalid_arguments",
                hint="Use position='before' or position='after'.",
                metadata={"path": arguments["path"], "operation": "insert_text"},
            )
        index = content.find(anchor)
        if index < 0:
            return ToolExecutionResult.failure(
                "anchor text not found",
                error_type="target_not_found",
                hint="Read the file again and choose an exact anchor_text present in the current content.",
                metadata={"path": arguments["path"], "operation": "insert_text"},
            )
        insertion = arguments["new_text"]
        insert_at = index if position == "before" else index + len(anchor)
        updated = content[:insert_at] + insertion + content[insert_at:]
        path.write_text(updated, encoding="utf-8")
        return ToolExecutionResult.success(
            f"inserted text {position} anchor in {arguments['path']}",
            title=f"Inserted text into {arguments['path']}",
            metadata={
                "path": arguments["path"],
                "operation": "insert_text",
                "position": position,
                "anchor_text": anchor,
                "before_content": content,
                "after_content": updated,
                "snapshot_before_ref": _snapshot_ref(arguments["path"], content),
                "snapshot_after_ref": _snapshot_ref(arguments["path"], updated),
            },
        )

    def mutates_workspace(self) -> bool:
        return True

    def snapshot_paths(self, arguments: dict, context: ToolContext) -> list[str]:
        return [arguments["path"]]

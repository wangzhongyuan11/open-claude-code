from __future__ import annotations

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
            return ToolExecutionResult(content="target text not found", is_error=True)
        updated = content.replace(old_text, arguments["new_text"], 1)
        path.write_text(updated, encoding="utf-8")
        return ToolExecutionResult(content=f"edited {arguments['path']}")

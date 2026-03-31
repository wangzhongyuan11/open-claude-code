from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from openagent.agent.subagent import SubagentManager, format_subagent_report, normalize_subagent_name
from openagent.domain.session import SessionTodo
from openagent.domain.tools import ToolContext, ToolExecutionResult
from openagent.session.todo import render_todos
from openagent.tools.base import BaseTool
from openagent.tools.builtin.edit import EditFileTool
from openagent.tools.builtin.files import ReadFileRangeTool, ReadFileTool, WriteFileTool
from openagent.tools.builtin.patch import ApplyPatchTool


class ReadTool(BaseTool):
    tool_id = "read"
    name = "read"
    description = "Read a file, optionally constrained to a line range."
    input_schema = {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "start_line": {"type": "integer"},
            "end_line": {"type": "integer"},
        },
        "required": ["path"],
    }

    def invoke(self, arguments: dict, context: ToolContext) -> ToolExecutionResult:
        if "start_line" in arguments and "end_line" in arguments:
            return ReadFileRangeTool().invoke(arguments, context)
        return ReadFileTool().invoke(arguments, context)


class WriteTool(BaseTool):
    tool_id = "write"
    name = "write"
    description = "Write UTF-8 text content to a file."
    input_schema = WriteFileTool.input_schema

    def invoke(self, arguments: dict, context: ToolContext) -> ToolExecutionResult:
        return WriteFileTool().invoke(arguments, context)

    def mutates_workspace(self) -> bool:
        return True

    def snapshot_paths(self, arguments: dict, context: ToolContext) -> list[str]:
        return WriteFileTool().snapshot_paths(arguments, context)


class EditTool(BaseTool):
    tool_id = "edit"
    name = "edit"
    description = "Edit a file via exact text replacement."
    input_schema = EditFileTool.input_schema

    def invoke(self, arguments: dict, context: ToolContext) -> ToolExecutionResult:
        return EditFileTool().invoke(arguments, context)

    def mutates_workspace(self) -> bool:
        return True

    def snapshot_paths(self, arguments: dict, context: ToolContext) -> list[str]:
        return EditFileTool().snapshot_paths(arguments, context)


class PatchTool(BaseTool):
    tool_id = "patch"
    name = "patch"
    description = "Apply a unified diff patch to a single file."
    input_schema = ApplyPatchTool.input_schema

    def invoke(self, arguments: dict, context: ToolContext) -> ToolExecutionResult:
        return ApplyPatchTool().invoke(arguments, context)

    def mutates_workspace(self) -> bool:
        return True

    def snapshot_paths(self, arguments: dict, context: ToolContext) -> list[str]:
        return ApplyPatchTool().snapshot_paths(arguments, context)


class TaskTool(BaseTool):
    tool_id = "task"
    name = "task"
    description = "Delegate a focused subtask to a subagent."
    input_schema = {
        "type": "object",
        "properties": {
            "description": {"type": "string"},
            "prompt": {"type": "string"},
            "subagent_type": {"type": "string"},
            "task_id": {"type": "string"},
            "command": {"type": "string"},
        },
        "required": ["description", "prompt", "subagent_type"],
    }

    def __init__(self, subagent_manager: SubagentManager):
        self.subagent_manager = subagent_manager

    def invoke(self, arguments: dict, context: ToolContext) -> ToolExecutionResult:
        try:
            result = self.subagent_manager.run(
                arguments["prompt"],
                agent_name=normalize_subagent_name(arguments.get("subagent_type", "general")),
                task_id=arguments.get("task_id"),
            )
        except TypeError:
            result = self.subagent_manager.run(arguments["prompt"])
        report = format_subagent_report(result)
        title = arguments.get("description") or "delegated task"
        task_id = arguments.get("task_id") or f"subagent:{hash(arguments['prompt']) & 0xFFFF_FFFF:x}"
        output = "\n".join(
            [
                f"task_id: {task_id}",
                "",
                "<task_result>",
                report,
                "</task_result>",
            ]
        )
        agent_name = getattr(result, "agent_name", None) or normalize_subagent_name(arguments.get("subagent_type", "general"))
        return ToolExecutionResult.success(
            output,
            title=title,
            metadata={
                "task_id": task_id,
                "subagent_type": arguments.get("subagent_type"),
                "agent": agent_name,
                "touched_paths": getattr(result, "touched_paths", []),
                "verified_paths": getattr(result, "verified_paths", []),
            },
        )


class TodoWriteTool(BaseTool):
    tool_id = "todowrite"
    name = "todowrite"
    description = "Replace the current session todo list with the provided items."
    input_schema = {
        "type": "object",
        "properties": {
            "todos": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "content": {"type": "string"},
                        "status": {"type": "string"},
                        "priority": {"type": "string"},
                    },
                    "required": ["content"],
                },
            }
        },
        "required": ["todos"],
    }

    def invoke(self, arguments: dict, context: ToolContext) -> ToolExecutionResult:
        setter = context.runtime_state.get("set_todos")
        getter = context.runtime_state.get("get_todos")
        if not callable(setter) or not callable(getter):
            return ToolExecutionResult.failure(
                "todowrite is unavailable because the runtime did not provide todo callbacks.",
                error_type="unsupported_runtime",
                hint="Use the interactive /todo commands or run this tool in a runtime that exposes todo callbacks.",
            )
        todos = [
            SessionTodo(
                content=item["content"],
                status=_normalize_todo_status(item.get("status", "pending")),
                priority=item.get("priority", "medium"),
            )
            for item in arguments["todos"]
        ]
        setter(todos)
        current = getter()
        return ToolExecutionResult.success(
            json.dumps([asdict(todo) for todo in current], ensure_ascii=False, indent=2),
            title=f"{sum(1 for todo in current if todo.status != 'completed')} todos",
            metadata={"todo_count": str(len(current))},
        )


class TodoReadTool(BaseTool):
    tool_id = "todoread"
    name = "todoread"
    description = "Read the current persisted session todo list."
    input_schema = {"type": "object", "properties": {}}

    def invoke(self, arguments: dict, context: ToolContext) -> ToolExecutionResult:
        getter = context.runtime_state.get("get_todos")
        session = context.runtime_state.get("session")
        if callable(getter):
            todos = getter()
            output = json.dumps([asdict(todo) for todo in todos], ensure_ascii=False, indent=2)
            title = f"{sum(1 for todo in todos if todo.status != 'completed')} todos"
        elif session is not None:
            output = render_todos(session)
            title = "Todos"
        else:
            return ToolExecutionResult.failure(
                "todoread is unavailable because the runtime did not provide todo state.",
                error_type="unsupported_runtime",
                hint="Use the interactive /todos command or run this tool in a runtime that exposes todo callbacks.",
            )
        return ToolExecutionResult.success(output, title=title, metadata={"has_todos": "true"})


def _normalize_todo_status(status: str) -> str:
    normalized = (status or "pending").strip().lower()
    if normalized in {"completed", "complete", "done", "finished"}:
        return "completed"
    if normalized in {"in_progress", "in-progress", "doing", "working"}:
        return "pending"
    if normalized in {"pending", "todo", "open"}:
        return "pending"
    return "pending"

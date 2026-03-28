from __future__ import annotations

import json
from dataclasses import asdict

from openagent.domain.tools import ToolContext, ToolExecutionResult
from openagent.session.background import BackgroundTaskManager
from openagent.tools.base import BaseTool


class BackgroundTaskTool(BaseTool):
    tool_id = "background_task"
    name = "background_task"
    description = "Start, inspect, or list long-running background shell tasks without blocking the main conversation loop."
    input_schema = {
        "type": "object",
        "properties": {
            "action": {"type": "string"},
            "command": {"type": "string"},
            "task_id": {"type": "string"},
            "title": {"type": "string"},
            "cwd": {"type": "string"},
            "timeout_seconds": {"type": "integer"},
        },
        "required": ["action"],
    }

    def __init__(self, manager: BackgroundTaskManager):
        self.manager = manager

    def invoke(self, arguments: dict, context: ToolContext) -> ToolExecutionResult:
        action = arguments["action"]
        session_id = context.session_id
        if not session_id:
            return ToolExecutionResult.failure(
                "background_task requires a session-aware runtime.",
                error_type="unsupported_runtime",
                hint="Run this tool inside the normal session runtime.",
                metadata={"operation": "background_task"},
            )
        if action == "start":
            command = arguments.get("command")
            if not command:
                return ToolExecutionResult.failure(
                    "background_task start requires command.",
                    error_type="invalid_arguments",
                    metadata={"operation": "background_task", "action": action},
                )
            record = self.manager.start_task(
                session_id=session_id,
                command=command,
                title=arguments.get("title"),
                cwd=arguments.get("cwd"),
                timeout_seconds=arguments.get("timeout_seconds"),
            )
            return ToolExecutionResult.success(
                json.dumps(
                    {
                        "task_id": record.id,
                        "status": record.status,
                        "title": record.title,
                        "command": record.command,
                        "cwd": record.cwd,
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                title=f"Started background task {record.id}",
                metadata={
                    "operation": "background_task",
                    "action": "start",
                    "task_id": record.id,
                    "path": record.cwd,
                    "status": record.status,
                },
            )
        if action == "get":
            task_id = arguments.get("task_id")
            if not task_id:
                return ToolExecutionResult.failure(
                    "background_task get requires task_id.",
                    error_type="invalid_arguments",
                    metadata={"operation": "background_task", "action": action},
                )
            record = self.manager.get_task(session_id, task_id)
            if record is None:
                return ToolExecutionResult.failure(
                    f"background task not found: {task_id}",
                    error_type="task_not_found",
                    metadata={"operation": "background_task", "action": action, "task_id": task_id},
                )
            return ToolExecutionResult.success(
                json.dumps(asdict(record), ensure_ascii=False, indent=2),
                title=f"Background task {record.id}",
                metadata={
                    "operation": "background_task",
                    "action": "get",
                    "task_id": record.id,
                    "status": record.status,
                    "exit_code": "" if record.exit_code is None else str(record.exit_code),
                },
            )
        if action == "list":
            records = self.manager.list_tasks(session_id)
            return ToolExecutionResult.success(
                json.dumps([asdict(record) for record in records], ensure_ascii=False, indent=2),
                title=f"{len(records)} background task(s)",
                metadata={"operation": "background_task", "action": "list", "task_count": str(len(records))},
            )
        return ToolExecutionResult.failure(
            f"unsupported background_task action: {action}",
            error_type="invalid_arguments",
            hint="Use action=start|get|list.",
            metadata={"operation": "background_task", "action": action},
        )

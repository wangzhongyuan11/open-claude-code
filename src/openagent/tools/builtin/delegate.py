from __future__ import annotations

from openagent.agent.subagent import SubagentManager, format_subagent_report
from openagent.domain.tools import ToolContext, ToolExecutionResult
from openagent.tools.base import BaseTool


class DelegateTool(BaseTool):
    name = "delegate"
    description = (
        "Run a focused subagent with an isolated context and return a structured completion report. "
        "Treat the delegate result as authoritative; do not re-open verified files unless the user explicitly asks."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "prompt": {"type": "string"},
        },
        "required": ["prompt"],
    }

    def __init__(self, subagent_manager: SubagentManager):
        self.subagent_manager = subagent_manager

    def invoke(self, arguments: dict, context: ToolContext) -> ToolExecutionResult:
        result = self.subagent_manager.run(arguments["prompt"])
        return ToolExecutionResult.success(
            format_subagent_report(result),
            title="Delegated subtask",
            metadata={
                "message_count": len(result.history),
                "touched_paths": result.touched_paths,
                "verified_paths": result.verified_paths,
            },
        )

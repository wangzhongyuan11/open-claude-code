from __future__ import annotations

from openagent.agent.subagent import SubagentManager
from openagent.domain.tools import ToolContext, ToolExecutionResult
from openagent.tools.base import BaseTool


class DelegateTool(BaseTool):
    name = "delegate"
    description = "Run a focused subagent with an isolated context and return its summary."
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
        return ToolExecutionResult(
            content=result.summary or "(subagent returned no summary)",
            metadata={"message_count": len(result.history)},
        )

from __future__ import annotations

import subprocess

from openagent.domain.tools import ToolContext, ToolExecutionResult
from openagent.tools.base import BaseTool


class BashTool(BaseTool):
    name = "bash"
    description = "Run a shell command inside the workspace."
    input_schema = {
        "type": "object",
        "properties": {
            "command": {"type": "string"},
        },
        "required": ["command"],
    }

    def __init__(self, timeout_seconds: int = 30, max_output_chars: int = 12000):
        self.timeout_seconds = timeout_seconds
        self.max_output_chars = max_output_chars

    def invoke(self, arguments: dict, context: ToolContext) -> ToolExecutionResult:
        try:
            completed = subprocess.run(
                arguments["command"],
                shell=True,
                cwd=context.workspace,
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
            )
        except subprocess.TimeoutExpired:
            return ToolExecutionResult(content=f"command timed out after {self.timeout_seconds}s", is_error=True)

        output = (completed.stdout + completed.stderr).strip()
        if not output:
            output = "(no output)"
        if len(output) > self.max_output_chars:
            output = output[: self.max_output_chars] + "\n...[truncated]"
        if completed.returncode != 0:
            return ToolExecutionResult(
                content=f"exit_code={completed.returncode}\n{output}",
                is_error=True,
            )
        return ToolExecutionResult(content=output)

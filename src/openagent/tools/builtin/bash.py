from __future__ import annotations

import subprocess

from openagent.domain.tools import ToolContext, ToolExecutionResult, ToolOutputLimits
from openagent.tools.base import BaseTool


class BashTool(BaseTool):
    name = "bash"
    description = (
        "Run a shell command inside the workspace. "
        "Use this for shell-native tasks; do not use it for ordinary file reads or simple file edits when dedicated file tools are sufficient."
    )
    output_limits = ToolOutputLimits(max_chars=12000, max_lines=300, direction="head")
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
            return ToolExecutionResult.failure(
                f"command timed out after {self.timeout_seconds}s",
                error_type="timeout",
                retryable=True,
                hint="Use a narrower command or increase the timeout if the task genuinely needs a longer run.",
                metadata={"command": arguments["command"]},
                status="timed_out",
            )

        output = (completed.stdout + completed.stderr).strip()
        if not output:
            output = "(no output)"
        if completed.returncode != 0:
            return ToolExecutionResult.failure(
                f"exit_code={completed.returncode}\n{output}",
                error_type="nonzero_exit",
                retryable=False,
                hint="Inspect stderr/output and rerun with a narrower or corrected shell command.",
                metadata={"command": arguments["command"], "exit_code": str(completed.returncode)},
            )
        return ToolExecutionResult.success(
            output,
            title="Executed shell command",
            metadata={"command": arguments["command"], "exit_code": "0"},
        )

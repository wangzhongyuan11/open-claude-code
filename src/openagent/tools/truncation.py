from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from openagent.domain.tools import ToolArtifact, ToolExecutionResult, ToolOutputLimits


def apply_output_truncation(
    result: ToolExecutionResult,
    *,
    tool_id: str,
    workspace: Path,
    limits: ToolOutputLimits,
) -> ToolExecutionResult:
    text = result.content or ""
    if not text:
        return result
    lines = text.splitlines()
    if len(lines) <= limits.max_lines and len(text) <= limits.max_chars:
        return result

    output_dir = (workspace / ".openagent" / "tool_outputs").resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    output_path = output_dir / f"{timestamp}_{tool_id}.txt"
    output_path.write_text(text, encoding="utf-8")

    preview = _truncate_preview(text, limits)
    notice = (
        f"{preview}\n\n...[tool output truncated]...\n\n"
        f"Full output saved to: {output_path}"
    )
    result.content = notice
    result.truncated = True
    result.metadata = {
        **result.metadata,
        "truncated": "true",
        "output_path": str(output_path),
        "output_preview_chars": str(len(preview)),
    }
    result.artifacts.append(
        ToolArtifact(
            kind="tool-output",
            path=str(output_path),
            description="Full tool output saved because the inline result was truncated.",
        )
    )
    return result


def _truncate_preview(text: str, limits: ToolOutputLimits) -> str:
    lines = text.splitlines()
    if limits.direction == "tail":
        preview_lines = lines[-limits.max_lines :]
    else:
        preview_lines = lines[: limits.max_lines]
    preview = "\n".join(preview_lines)
    if len(preview) > limits.max_chars:
        if limits.direction == "tail":
            preview = preview[-limits.max_chars :]
        else:
            preview = preview[: limits.max_chars]
    return preview

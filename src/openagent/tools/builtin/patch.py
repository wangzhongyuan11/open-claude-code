from __future__ import annotations

import re
import subprocess
import tempfile
from pathlib import Path

from openagent.domain.tools import ToolContext, ToolExecutionResult
from openagent.tools.base import BaseTool
from openagent.tools.builtin.files import resolve_workspace_path


class ApplyPatchTool(BaseTool):
    tool_id = "apply_patch"
    name = "apply_patch"
    description = "Apply a unified diff patch to a single workspace file."
    input_schema = {
        "type": "object",
        "properties": {
            "patch": {"type": "string"},
        },
        "required": ["patch"],
    }

    def invoke(self, arguments: dict, context: ToolContext) -> ToolExecutionResult:
        patch_text = arguments["patch"]
        target_path = _extract_single_target_path(patch_text)
        if target_path is None:
            return ToolExecutionResult.failure(
                "apply_patch currently requires a single-file unified diff with a valid +++ target path.",
                error_type="invalid_patch",
                hint="Provide a single-file unified diff with ---/+++ headers.",
                metadata={"operation": "apply_patch"},
            )

        resolved = resolve_workspace_path(context.workspace, target_path)
        before_exists = resolved.exists()
        before_content = resolved.read_text(encoding="utf-8") if before_exists else ""
        resolved.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False, suffix=".patch") as handle:
            handle.write(patch_text)
            patch_file = Path(handle.name)
        try:
            completed = subprocess.run(
                ["patch", "--batch", "--forward", "-p1", "-i", str(patch_file)],
                cwd=context.workspace,
                capture_output=True,
                text=True,
                timeout=30,
            )
        finally:
            patch_file.unlink(missing_ok=True)

        output = (completed.stdout + completed.stderr).strip() or "(no output)"
        if completed.returncode != 0:
            return ToolExecutionResult.failure(
                f"patch failed\n{output}",
                error_type="patch_failed",
                hint="Re-read the target file and generate a patch against the current exact content.",
                metadata={"path": target_path, "operation": "apply_patch", "exit_code": str(completed.returncode)},
            )
        after_content = resolved.read_text(encoding="utf-8")
        return ToolExecutionResult.success(
            output,
            title=f"Applied patch to {target_path}",
            metadata={
                "path": target_path,
                "operation": "apply_patch",
                "before_content": before_content,
                "after_content": after_content,
                "before_exists": before_exists,
                "snapshot_before_ref": None,
                "snapshot_after_ref": None,
            },
        )

    def mutates_workspace(self) -> bool:
        return True

    def snapshot_paths(self, arguments: dict, context: ToolContext) -> list[str]:
        target_path = _extract_single_target_path(arguments["patch"])
        return [target_path] if target_path else []


def _extract_single_target_path(patch_text: str) -> str | None:
    targets = re.findall(r"(?m)^\+\+\+\s+(?:b/)?(.+)$", patch_text)
    targets = [target.strip() for target in targets if target.strip() != "/dev/null"]
    unique = list(dict.fromkeys(targets))
    if len(unique) != 1:
        return None
    return unique[0]

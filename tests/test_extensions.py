from pathlib import Path

from openagent.domain.tools import ToolContext
from openagent.extensions.base import ExtensionContext, PermissionDecision, PermissionPolicy
from openagent.tools.builtin.files import WriteFileTool
from openagent.tools.registry import ToolRegistry


class DenyWritePolicy(PermissionPolicy):
    def check(self, context: ExtensionContext) -> PermissionDecision:
        if context.tool_name == "write_file":
            return PermissionDecision(allowed=False, reason="write blocked")
        return PermissionDecision(allowed=True)


def test_permission_policy_can_block_tool_invocation(tmp_path: Path):
    registry = ToolRegistry(permission_policy=DenyWritePolicy())
    registry.register(WriteFileTool())

    result = registry.invoke(
        "write_file",
        {"path": "a.txt", "content": "blocked"},
        ToolContext(workspace=tmp_path),
    )

    assert result.is_error is True
    assert result.content == "write blocked"
    assert not (tmp_path / "a.txt").exists()

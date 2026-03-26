from __future__ import annotations

from openagent.domain.tools import ToolContext, ToolExecutionResult, ToolSpec
from openagent.extensions.base import ExtensionContext, PermissionPolicy
from openagent.extensions.defaults import AllowAllPolicy
from openagent.tools.base import BaseTool


class ToolRegistry:
    def __init__(self, permission_policy: PermissionPolicy | None = None) -> None:
        self._tools: dict[str, BaseTool] = {}
        self._permission_policy = permission_policy or AllowAllPolicy()

    def register(self, tool: BaseTool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"tool already registered: {tool.name}")
        self._tools[tool.name] = tool

    def get(self, name: str) -> BaseTool:
        try:
            return self._tools[name]
        except KeyError as exc:
            raise KeyError(f"unknown tool: {name}") from exc

    def specs(self) -> list[ToolSpec]:
        return [tool.spec() for tool in self._tools.values()]

    def invoke(self, name: str, arguments: dict, context: ToolContext) -> ToolExecutionResult:
        decision = self._permission_policy.check(
            ExtensionContext(
                tool_name=name,
                arguments=arguments,
                tool_context=context,
            )
        )
        if not decision.allowed:
            return ToolExecutionResult(content=decision.reason or "permission denied", is_error=True)
        tool = self.get(name)
        return tool.invoke(arguments, context)

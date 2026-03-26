from __future__ import annotations

from abc import ABC, abstractmethod

from openagent.domain.tools import ToolContext, ToolExecutionResult, ToolSpec


class BaseTool(ABC):
    name: str
    description: str
    input_schema: dict

    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.name,
            description=self.description,
            input_schema=self.input_schema,
        )

    @abstractmethod
    def invoke(self, arguments: dict, context: ToolContext) -> ToolExecutionResult:
        raise NotImplementedError

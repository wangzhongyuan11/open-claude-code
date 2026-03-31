from __future__ import annotations

from abc import ABC, abstractmethod

from openagent.domain.tools import ToolContext, ToolExecutionResult, ToolOutputLimits, ToolSpec


class BaseTool(ABC):
    tool_id: str | None = None
    name: str
    description: str
    input_schema: dict
    source: str = "builtin"
    metadata: dict = {}
    output_limits = ToolOutputLimits()

    @property
    def id(self) -> str:
        return self.tool_id or self.name

    def spec(self) -> ToolSpec:
        return ToolSpec(
            id=self.id,
            name=self.name,
            description=self.description,
            input_schema=self.input_schema,
            source=self.source,
            metadata=dict(self.metadata),
        )

    def init(self, context: ToolContext) -> None:
        return None

    def validate_arguments(self, arguments: dict) -> None:
        schema = self.input_schema or {}
        required = schema.get("required", [])
        properties = schema.get("properties", {})
        if not isinstance(arguments, dict):
            raise ValueError("tool arguments must be an object")
        for key in required:
            if key not in arguments:
                raise ValueError(f"missing required argument: {key}")
        for key, value in arguments.items():
            expected = properties.get(key, {}).get("type")
            if expected == "string" and not isinstance(value, str):
                raise ValueError(f"argument '{key}' must be a string")
            if expected == "integer" and not isinstance(value, int):
                raise ValueError(f"argument '{key}' must be an integer")
            if expected == "number" and not isinstance(value, (int, float)):
                raise ValueError(f"argument '{key}' must be a number")
            if expected == "boolean" and not isinstance(value, bool):
                raise ValueError(f"argument '{key}' must be a boolean")
            if expected == "array" and not isinstance(value, list):
                raise ValueError(f"argument '{key}' must be an array")
            if expected == "object" and not isinstance(value, dict):
                raise ValueError(f"argument '{key}' must be an object")

    def get_output_limits(self) -> ToolOutputLimits:
        return self.output_limits

    def mutates_workspace(self) -> bool:
        return False

    def snapshot_paths(self, arguments: dict, context: ToolContext) -> list[str]:
        return []

    @abstractmethod
    def invoke(self, arguments: dict, context: ToolContext) -> ToolExecutionResult:
        raise NotImplementedError

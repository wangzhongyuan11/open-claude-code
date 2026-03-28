from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

if False:  # pragma: no cover
    from openagent.events.bus import EventBus


ToolStatus = str


@dataclass(slots=True)
class ToolSpec:
    name: str
    description: str
    input_schema: dict[str, Any]
    id: str = ""
    source: str = "builtin"
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.id:
            self.id = self.name


@dataclass(slots=True)
class ToolArtifact:
    kind: str
    path: str | None = None
    description: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ToolError:
    type: str
    message: str
    retryable: bool = False
    hint: str | None = None
    traceback: str | None = None


@dataclass(slots=True)
class ToolOutputLimits:
    max_chars: int = 12000
    max_lines: int = 400
    direction: str = "head"


@dataclass(slots=True)
class ToolContext:
    workspace: Path
    session_id: str | None = None
    message_id: str | None = None
    tool_call_id: str | None = None
    agent_name: str | None = None
    event_bus: "EventBus | None" = None
    runtime_state: dict[str, Any] = field(default_factory=dict)
    permission: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def child(
        self,
        *,
        message_id: str | None = None,
        tool_call_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> "ToolContext":
        merged_metadata = dict(self.metadata)
        if metadata:
            merged_metadata.update(metadata)
        return ToolContext(
            workspace=self.workspace,
            session_id=self.session_id,
            message_id=message_id or self.message_id,
            tool_call_id=tool_call_id or self.tool_call_id,
            agent_name=self.agent_name,
            event_bus=self.event_bus,
            runtime_state=dict(self.runtime_state),
            permission=dict(self.permission),
            metadata=merged_metadata,
        )


@dataclass(slots=True)
class ToolExecutionResult:
    title: str = ""
    content: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    error: ToolError | None = None
    artifacts: list[ToolArtifact] = field(default_factory=list)
    truncated: bool = False
    status: ToolStatus = "succeeded"

    @property
    def is_error(self) -> bool:
        return self.status in {"failed", "cancelled", "timed_out"}

    @property
    def output(self) -> str:
        return self.content

    @classmethod
    def success(
        cls,
        content: str,
        *,
        title: str = "",
        metadata: dict[str, Any] | None = None,
        artifacts: list[ToolArtifact] | None = None,
    ) -> "ToolExecutionResult":
        return cls(
            title=title,
            content=content,
            metadata=metadata or {},
            artifacts=artifacts or [],
            status="succeeded",
        )

    @classmethod
    def failure(
        cls,
        content: str,
        *,
        error_type: str = "tool_error",
        retryable: bool = False,
        hint: str | None = None,
        metadata: dict[str, Any] | None = None,
        traceback: str | None = None,
        status: ToolStatus = "failed",
    ) -> "ToolExecutionResult":
        return cls(
            title="Tool failed",
            content=content,
            metadata=metadata or {},
            error=ToolError(
                type=error_type,
                message=content,
                retryable=retryable,
                hint=hint,
                traceback=traceback,
            ),
            status=status,
        )

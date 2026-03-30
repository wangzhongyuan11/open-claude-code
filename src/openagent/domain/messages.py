from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import uuid4


Role = Literal["system", "user", "assistant", "tool"]
PartType = Literal[
    "text",
    "tool",
    "reasoning",
    "file",
    "snapshot",
    "patch",
    "step-start",
    "step-finish",
    "agent",
    "compaction",
    "subtask",
    "retry",
    "background-task",
    "permission",
]
FinishReason = Literal["tool-calls", "stop", "length", "content-filter", "other"]


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def new_id() -> str:
    return uuid4().hex[:12]


@dataclass(slots=True)
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass(slots=True)
class ModelRef:
    provider_id: str
    model_id: str
    variant: str | None = None


@dataclass(slots=True)
class TokenUsage:
    input: int = 0
    output: int = 0
    reasoning: int = 0
    cache_read: int = 0
    cache_write: int = 0


@dataclass(slots=True)
class MessageError:
    code: str
    message: str
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class Part:
    type: PartType | str
    content: Any
    id: str = field(default_factory=new_id)
    state: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=utc_now_iso)


@dataclass(slots=True)
class Message:
    role: Role
    content: str = ""
    id: str = field(default_factory=new_id)
    session_id: str | None = None
    parent_id: str | None = None
    agent: str | None = None
    model: ModelRef | None = None
    tokens: TokenUsage = field(default_factory=TokenUsage)
    cost: float = 0.0
    finish: FinishReason | str | None = None
    error: MessageError | None = None
    created_at: str = field(default_factory=utc_now_iso)
    completed_at: str | None = None
    tool_call_id: str | None = None
    name: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)
    parts: list[Part] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.parts:
            self.parts = self._build_default_parts()
        if not self.content:
            self.content = self._derive_content_from_parts()
        if self.finish is None and self.tool_calls:
            self.finish = "tool-calls"
        if self.completed_at is None and self.role == "assistant" and not self.tool_calls:
            self.completed_at = self.created_at

    def add_part(self, part: Part) -> None:
        self.parts.append(part)
        self.content = self._derive_content_from_parts()

    def text_parts(self) -> list[Part]:
        return [part for part in self.parts if part.type in {"text", "reasoning", "patch", "file"}]

    def _build_default_parts(self) -> list[Part]:
        parts: list[Part] = []
        if self.content:
            part_type = "tool" if self.role == "tool" else "text"
            part_content: Any = self.content
            part_state: dict[str, Any] = {}
            if self.role == "tool":
                part_content = {
                    "tool_call_id": self.tool_call_id,
                    "name": self.name,
                    "output": self.content,
                }
                part_state = {"status": "completed"}
            parts.append(Part(type=part_type, content=part_content, state=part_state, created_at=self.created_at))
        if self.role == "assistant":
            for tool_call in self.tool_calls:
                parts.append(
                    Part(
                        type="tool",
                        content={
                            "id": tool_call.id,
                            "name": tool_call.name,
                            "arguments": tool_call.arguments,
                        },
                        state={"status": "requested"},
                        created_at=self.created_at,
                    )
                )
        return parts

    def _derive_content_from_parts(self) -> str:
        if self.role == "tool":
            file_chunks = _extract_file_chunks(self.parts)
            if file_chunks:
                return "\n".join(chunk for chunk in file_chunks if chunk).strip()
        chunks: list[str] = []
        for part in self.parts:
            if part.type in {"text", "reasoning", "patch"} and isinstance(part.content, str):
                chunks.append(part.content)
                continue
            if part.type == "file":
                if isinstance(part.content, str):
                    chunks.append(part.content)
                elif isinstance(part.content, dict):
                    text = part.content.get("content")
                    if isinstance(text, str):
                        chunks.append(text)
                continue
            if part.type == "tool" and self.role == "tool" and isinstance(part.content, dict):
                output = part.content.get("output")
                if isinstance(output, str):
                    chunks.append(output)
        return "\n".join(chunk for chunk in chunks if chunk).strip()


@dataclass(slots=True)
class AgentResponse:
    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    finish: FinishReason | str | None = None
    model: ModelRef | None = None
    tokens: TokenUsage = field(default_factory=TokenUsage)
    cost: float = 0.0
    error: MessageError | None = None
    raw: Any | None = None

    @property
    def requests_tools(self) -> bool:
        return self.finish == "tool-calls" or bool(self.tool_calls)


def _extract_file_chunks(parts: list[Part]) -> list[str]:
    chunks: list[str] = []
    for part in parts:
        if part.type != "file":
            continue
        if isinstance(part.content, str):
            chunks.append(part.content)
            continue
        if isinstance(part.content, dict):
            text = part.content.get("content")
            if isinstance(text, str):
                chunks.append(text)
    return chunks

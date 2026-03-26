from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from openagent.domain.messages import Message


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


@dataclass(slots=True)
class SessionSummary:
    text: str
    compacted_message_count: int
    updated_at: str = field(default_factory=utc_now_iso)


@dataclass(slots=True)
class SessionStatus:
    state: str = "idle"
    retry_count: int = 0
    last_error: str | None = None
    recovery_hint: str | None = None
    last_user_message: str | None = None
    last_turn_started_at: str | None = None
    last_turn_completed_at: str | None = None
    degraded: bool = False


@dataclass(slots=True)
class SessionTodo:
    content: str
    status: str = "pending"
    priority: str = "medium"


@dataclass(slots=True)
class Session:
    id: str
    workspace: str
    schema_version: int = 2
    created_at: str = field(default_factory=utc_now_iso)
    updated_at: str = field(default_factory=utc_now_iso)
    messages: list[Message] = field(default_factory=list)
    metadata: dict[str, str] = field(default_factory=dict)
    summary: SessionSummary | None = None
    status: SessionStatus = field(default_factory=SessionStatus)
    todos: list[SessionTodo] = field(default_factory=list)

    def touch(self) -> None:
        self.updated_at = utc_now_iso()

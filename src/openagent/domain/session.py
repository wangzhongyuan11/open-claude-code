from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from openagent.domain.messages import Message


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


@dataclass(slots=True)
class Session:
    id: str
    workspace: str
    created_at: str = field(default_factory=utc_now_iso)
    updated_at: str = field(default_factory=utc_now_iso)
    messages: list[Message] = field(default_factory=list)
    metadata: dict[str, str] = field(default_factory=dict)

    def touch(self) -> None:
        self.updated_at = utc_now_iso()

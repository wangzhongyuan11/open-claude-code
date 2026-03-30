from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import uuid4


PermissionAction = Literal["allow", "deny", "ask"]
PermissionReply = Literal["once", "always", "reject"]


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


@dataclass(slots=True)
class PermissionRule:
    permission: str
    pattern: str = "*"
    action: PermissionAction = "ask"
    agent: str = "*"
    source: str = "default"
    created_at: str = field(default_factory=_utc_now_iso)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "PermissionRule":
        return cls(
            permission=str(payload.get("permission", "*")),
            pattern=str(payload.get("pattern", "*")),
            action=str(payload.get("action", "ask")),  # type: ignore[arg-type]
            agent=str(payload.get("agent", "*")),
            source=str(payload.get("source", "default")),
            created_at=str(payload.get("created_at", _utc_now_iso())),
        )


@dataclass(slots=True)
class PermissionRequest:
    session_id: str
    agent_name: str
    tool_name: str
    permission: str
    pattern: str
    metadata: dict[str, Any] = field(default_factory=dict)
    message_id: str | None = None
    tool_call_id: str | None = None
    id: str = field(default_factory=lambda: uuid4().hex[:12])
    created_at: str = field(default_factory=_utc_now_iso)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


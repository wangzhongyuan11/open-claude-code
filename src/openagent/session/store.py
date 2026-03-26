from __future__ import annotations

import json
import uuid
from pathlib import Path

from openagent.domain.messages import Message, ToolCall
from openagent.domain.session import Session


class SessionStore:
    def __init__(self, root_dir: Path) -> None:
        self.root_dir = root_dir.resolve()
        self.root_dir.mkdir(parents=True, exist_ok=True)

    def create(self, workspace: Path, session_id: str | None = None) -> Session:
        session = Session(
            id=session_id or self._new_id(),
            workspace=str(workspace.resolve()),
        )
        self.save(session)
        return session

    def load(self, session_id: str) -> Session:
        path = self._session_file(session_id)
        if not path.exists():
            raise FileNotFoundError(f"session not found: {session_id}")
        payload = json.loads(path.read_text(encoding="utf-8"))
        return self._deserialize(payload)

    def save(self, session: Session) -> None:
        session_dir = self.root_dir / session.id
        session_dir.mkdir(parents=True, exist_ok=True)
        path = self._session_file(session.id)
        path.write_text(
            json.dumps(self._serialize(session), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def list_sessions(self) -> list[Session]:
        sessions: list[Session] = []
        for path in sorted(self.root_dir.glob("*/session.json")):
            payload = json.loads(path.read_text(encoding="utf-8"))
            sessions.append(self._deserialize(payload))
        return sessions

    def _session_file(self, session_id: str) -> Path:
        return self.root_dir / session_id / "session.json"

    @staticmethod
    def _new_id() -> str:
        return uuid.uuid4().hex[:12]

    @staticmethod
    def _serialize(session: Session) -> dict:
        return {
            "id": session.id,
            "workspace": session.workspace,
            "created_at": session.created_at,
            "updated_at": session.updated_at,
            "metadata": session.metadata,
            "messages": [
                {
                    "role": message.role,
                    "content": message.content,
                    "tool_call_id": message.tool_call_id,
                    "name": message.name,
                    "tool_calls": [
                        {
                            "id": tool_call.id,
                            "name": tool_call.name,
                            "arguments": tool_call.arguments,
                        }
                        for tool_call in message.tool_calls
                    ],
                }
                for message in session.messages
            ],
        }

    @staticmethod
    def _deserialize(payload: dict) -> Session:
        return Session(
            id=payload["id"],
            workspace=payload["workspace"],
            created_at=payload["created_at"],
            updated_at=payload["updated_at"],
            metadata=payload.get("metadata", {}),
            messages=[
                Message(
                    role=item["role"],
                    content=item["content"],
                    tool_call_id=item.get("tool_call_id"),
                    name=item.get("name"),
                    tool_calls=[
                        ToolCall(
                            id=tool_call["id"],
                            name=tool_call["name"],
                            arguments=tool_call["arguments"],
                        )
                        for tool_call in item.get("tool_calls", [])
                    ],
                )
                for item in payload.get("messages", [])
            ],
        )
